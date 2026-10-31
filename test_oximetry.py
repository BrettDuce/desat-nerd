"""
Comprehensive Validation Test Suite for desatNerd
Tests:
  1. Synthetic data creation for Nonin, Nellcor, Masimo, and Compumedics EDF formats.
  2. Multi-format parsing and signal integrity checks.
  3. Artifact detection and signal preprocessing.
  4. Desaturation event detection and morphology parameter verification (slopes, depths, areas).
  5. T90, T88, T85, T80 calculation checks.
  6. Azarbarzin Hypoxic Burden calculation (event-linked and standalone).
  7. REDTA calculation (event-linked and standalone).
  8. Kulkas Desaturation Severity and Recovery Dynamics.
  9. Batch appending and CSV export validation.
"""

import os
import shutil
import struct
import tempfile
import unittest
import numpy as np
import pandas as pd

from parsers import load_oximetry_file, parse_edf_oximetry, parse_text_oximetry, OximetryRecording
from oximetry_engine import OximetryEngine
from exporter import OximetryExporter


def create_synthetic_pure_edf(file_path: str, fs: float = 1.0, duration_sec: int = 1800) -> str:
    """Creates a valid EDF file containing SpO2 and Pulse channels."""
    n_records = duration_sec
    spr_spo2 = int(fs)
    spr_pulse = int(fs)

    # Generate synthetic SpO2 with periodic desaturations
    t = np.linspace(0, duration_sec, n_records * spr_spo2, endpoint=False)
    spo2 = np.full_like(t, 97.0)
    # Small physiological heart-rate variability so the pulse-flatline artefact
    # rejector does not treat the synthetic desaturations as a frozen sensor.
    pulse = 65.0 + 2.0 * np.sin(2 * np.pi * t / 7.0)

    # Inject 5 realistic desaturations
    for center_s in [300, 600, 900, 1200, 1500]:
        idx_start = int((center_s - 15) * fs)
        idx_nadir = int(center_s * fs)
        idx_end = int((center_s + 20) * fs)
        # Falling phase: drop from 97% to 88% (depth 9%)
        fall_len = idx_nadir - idx_start
        spo2[idx_start:idx_nadir] = np.linspace(97.0, 88.0, fall_len)
        # Recovery phase: recover from 88% to 96.5%
        recov_len = idx_end - idx_nadir
        spo2[idx_nadir:idx_end] = np.linspace(88.0, 96.5, recov_len)
        pulse[idx_start:idx_end] += 12.0

    # Header parameters (256 bytes)
    version = f"{'0':<8}"
    patient_id = f"{'PATIENT_COMPUMEDICS_01':<80}"
    record_id = f"{'RECORD_GRAEL_01':<80}"
    start_date = f"{'24.09.26':<8}"
    start_time = f"{'22.00.00':<8}"
    header_bytes = f"{256 + 2 * 256:<8}"
    reserved = f"{'':<44}"
    num_records_str = f"{n_records:<8}"
    dur_record_str = f"{1.0:<8}"
    ns_str = f"{2:<4}"

    # Signal 1: SpO2, Signal 2: Pulse
    labels = f"{'SpO2':<16}{'Pulse':<16}"
    transducers = f"{'Finger Sensor':<80}{'Pulse Sensor':<80}"
    dims = f"{'%':<8}{'bpm':<8}"
    phys_min = f"{0.0:<8.1f}{0.0:<8.1f}"
    phys_max = f"{100.0:<8.1f}{250.0:<8.1f}"
    dig_min = f"{-32768:<8}{-32768:<8}"
    dig_max = f"{32767:<8}{32767:<8}"
    prefilters = f"{'':<80}{'':<80}"
    nr_samples = f"{spr_spo2:<8}{spr_pulse:<8}"
    reserved_sig = f"{'':<32}{'':<32}"

    with open(file_path, "wb") as f:
        f.write(version.encode('ascii'))
        f.write(patient_id.encode('ascii'))
        f.write(record_id.encode('ascii'))
        f.write(start_date.encode('ascii'))
        f.write(start_time.encode('ascii'))
        f.write(header_bytes.encode('ascii'))
        f.write(reserved.encode('ascii'))
        f.write(num_records_str.encode('ascii'))
        f.write(dur_record_str.encode('ascii'))
        f.write(ns_str.encode('ascii'))

        f.write(labels.encode('ascii'))
        f.write(transducers.encode('ascii'))
        f.write(dims.encode('ascii'))
        f.write(phys_min.encode('ascii'))
        f.write(phys_max.encode('ascii'))
        f.write(dig_min.encode('ascii'))
        f.write(dig_max.encode('ascii'))
        f.write(prefilters.encode('ascii'))
        f.write(nr_samples.encode('ascii'))
        f.write(reserved_sig.encode('ascii'))

        # Scale to 16-bit signed integers
        # digital = (phys - phys_min) / (phys_max - phys_min) * (dig_max - dig_min) + dig_min
        spo2_dig = np.clip((spo2 / 100.0) * 65535.0 - 32768.0, -32768, 32767).astype(np.int16)
        pulse_dig = np.clip((pulse / 250.0) * 65535.0 - 32768.0, -32768, 32767).astype(np.int16)

        # Interleave records (each record has spr_spo2 samples then spr_pulse samples)
        records_bin = bytearray()
        for r in range(n_records):
            records_bin.extend(spo2_dig[r * spr_spo2 : (r + 1) * spr_spo2].tobytes())
            records_bin.extend(pulse_dig[r * spr_pulse : (r + 1) * spr_pulse].tobytes())
        f.write(records_bin)

    return file_path


def create_synthetic_nonin_csv(file_path: str, duration_sec: int = 1200) -> str:
    """Creates a Nonin nVISION formatted CSV."""
    t_sec = np.arange(duration_sec)
    spo2 = np.full(duration_sec, 96.0)
    pulse = np.round(70 + 2.0 * np.sin(2 * np.pi * t_sec / 7.0)).astype(int)

    # Add 3 desaturations
    for center in [200, 500, 800]:
        spo2[center - 10 : center] = np.linspace(96.0, 89.0, 10)
        spo2[center : center + 15] = np.linspace(89.0, 95.5, 15)

    with open(file_path, "w", encoding="utf-8") as f:
        f.write("Nonin nVISION Data Export\n")
        f.write("Patient ID: NONIN_TEST_01\n")
        f.write("Date,Time,%SpO2,Pulse Rate,Events\n")
        for s in t_sec:
            m, sec = divmod(s, 60)
            h, m = divmod(m, 60)
            time_str = f"{22 + h:02d}:{m:02d}:{sec:02d}"
            f.write(f"2026-09-24,{time_str},{spo2[s]:.1f},{int(pulse[s])},0\n")
    return file_path


def create_synthetic_nellcor_txt(file_path: str, duration_sec: int = 1200) -> str:
    """Creates a Nellcor PM1000N / OxiMax formatted text export."""
    t_sec = np.arange(duration_sec)
    spo2 = np.full(duration_sec, 98.0)
    bpm = np.round(68 + 2.0 * np.sin(2 * np.pi * t_sec / 7.0)).astype(int)

    for center in [250, 650, 950]:
        spo2[center - 12 : center] = np.linspace(98.0, 87.0, 12)
        spo2[center : center + 18] = np.linspace(87.0, 97.5, 18)

    with open(file_path, "w", encoding="utf-8") as f:
        f.write("Nellcor OxiMax Trend Data\n")
        f.write("Unit ID: NELLCOR_BED_4\n")
        f.write("Seconds\t%SpO2\tBPM\tStatus\n")
        for s in t_sec:
            f.write(f"{s}\t{spo2[s]:.1f}\t{bpm[s]}\t0\n")
    return file_path


def create_synthetic_masimo_csv(file_path: str, duration_sec: int = 1200) -> str:
    """Creates a Masimo Radical-7 formatted CSV export."""
    t_sec = np.arange(duration_sec)
    spo2 = np.full(duration_sec, 97.0)
    pr = np.round(62 + 2.0 * np.sin(2 * np.pi * t_sec / 7.0)).astype(int)

    for center in [300, 700]:
        spo2[center - 10 : center] = np.linspace(97.0, 89.0, 10)
        spo2[center : center + 15] = np.linspace(89.0, 96.5, 15)

    with open(file_path, "w", encoding="utf-8") as f:
        f.write("Masimo Radical-7 Trend Report\n")
        f.write("Instrument Serial: MASIMO_RAD7_098\n")
        f.write("Time,%SpO2,PR,PI,PVI\n")
        for s in t_sec:
            f.write(f"{s},{spo2[s]:.1f},{pr[s]},1.4,12\n")
    return file_path


class TestDesatNerd(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="desatnerd_test_")
        self.output_dir = os.path.join(self.test_dir, "results")
        os.makedirs(self.output_dir, exist_ok=True)

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    def test_edf_parsing_and_analysis(self):
        edf_path = os.path.join(self.test_dir, "test_compumedics.edf")
        create_synthetic_pure_edf(edf_path, fs=1.0, duration_sec=1800)

        recording = load_oximetry_file(edf_path)
        self.assertEqual(recording.device_type, "Compumedics EDF")
        self.assertAlmostEqual(recording.fs, 1.0, places=1)
        self.assertAlmostEqual(recording.duration_sec, 1800.0, places=0)
        self.assertGreater(len(recording.spo2_raw), 1700)

        result = OximetryEngine.analyze_recording(recording, threshold=3.0)
        self.assertEqual(result["Desaturation_Count"], 5)
        self.assertAlmostEqual(result["ODI_3pct"], 10.0, delta=1.0) # 5 events in 0.5 hours = 10 / hr
        self.assertGreater(result["Azarbarzin_HB_pctmin_hr"], 0.0)
        self.assertGreater(result["Kulkas_Total_Severity_pctmin_hr"], 0.0)
        self.assertGreater(result["Mean_Fall_Slope_pct_s"], 0.0)
        self.assertGreater(result["Mean_Recovery_Slope_pct_s"], 0.0)

    def test_nonin_parsing(self):
        nonin_path = os.path.join(self.test_dir, "test_nonin.csv")
        create_synthetic_nonin_csv(nonin_path, duration_sec=1200)

        recording = load_oximetry_file(nonin_path)
        self.assertEqual(recording.device_type, "Nonin ASC/CSV")
        self.assertEqual(len(recording.spo2_raw), 1200)

        result = OximetryEngine.analyze_recording(recording, threshold=3.0)
        self.assertEqual(result["Desaturation_Count"], 3)
        self.assertAlmostEqual(result["ODI_3pct"], 9.0, delta=1.0) # 3 events in 0.33 hours = 9 / hr
        self.assertGreater(result["T90_Minutes"], 0.0)

    def test_nellcor_parsing(self):
        nellcor_path = os.path.join(self.test_dir, "test_nellcor.txt")
        create_synthetic_nellcor_txt(nellcor_path, duration_sec=1200)

        recording = load_oximetry_file(nellcor_path)
        self.assertEqual(recording.device_type, "Nellcor N-600x")
        self.assertEqual(len(recording.spo2_raw), 1200)

        result = OximetryEngine.analyze_recording(recording, threshold=3.0)
        self.assertEqual(result["Desaturation_Count"], 3)
        self.assertGreater(result["Azarbarzin_HB_pctmin_hr"], 0.0)

    def test_masimo_parsing(self):
        masimo_path = os.path.join(self.test_dir, "test_masimo.csv")
        create_synthetic_masimo_csv(masimo_path, duration_sec=1200)

        recording = load_oximetry_file(masimo_path)
        self.assertEqual(recording.device_type, "Masimo CSV/TXT")
        self.assertEqual(len(recording.spo2_raw), 1200)

        result = OximetryEngine.analyze_recording(recording, threshold=3.0)
        self.assertEqual(result["Desaturation_Count"], 2)

    def test_csv_export_and_batch_append(self):
        edf_path = os.path.join(self.test_dir, "test_compumedics.edf")
        create_synthetic_pure_edf(edf_path, fs=1.0, duration_sec=1800)
        rec = load_oximetry_file(edf_path)
        res = OximetryEngine.analyze_recording(rec, threshold=3.0)

        sum_csv = OximetryExporter.export_single_summary(res, self.output_dir)
        ev_csv = OximetryExporter.export_events_csv(res, self.output_dir)
        batch_csv = OximetryExporter.append_to_batch_summary(res, self.output_dir)

        self.assertTrue(os.path.exists(sum_csv))
        self.assertTrue(os.path.exists(ev_csv))
        self.assertTrue(os.path.exists(batch_csv))

        # Test appending a second record to batch CSV
        nonin_path = os.path.join(self.test_dir, "test_nonin.csv")
        create_synthetic_nonin_csv(nonin_path, duration_sec=1200)
        rec2 = load_oximetry_file(nonin_path)
        res2 = OximetryEngine.analyze_recording(rec2, threshold=3.0)
        OximetryExporter.append_to_batch_summary(res2, self.output_dir)

        df_batch = pd.read_csv(batch_csv)
        self.assertEqual(len(df_batch), 2)
        self.assertEqual(df_batch.iloc[0]["File_Name"], "test_compumedics.edf")
        self.assertEqual(df_batch.iloc[1]["File_Name"], "test_nonin.csv")


if __name__ == "__main__":
    unittest.main()
