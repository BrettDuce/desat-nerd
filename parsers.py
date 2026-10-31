"""Universal Oximetry File Parsers for desatNerd.

Supports:
  - Compumedics-based EDF files & companion annotation files (<study-name>.edf.XML, <study-name>.edf.xml, etc.)
  - Nox-based EDF files & Nox events
  - REMlogic-based EDF files & annotations
  - Nonin oximetry files (.asc / .csv / .txt / .dat from nVISION / WristOx2)
  - Nellcor oximetry files (.csv / .txt trend/real-time exports with 25-line recurring headers)
  - Masimo oximetry files (.out / .txt / .csv from Rad-5 TrendCom key-value dumps & Rad-97/Rad-67 exports)
  - Generic CSV / TSV oximetry files
Includes a robust pure-Python EDF reader fallback.
"""

from dataclasses import dataclass, field
from datetime import datetime
import io
import os
import re
from typing import Any, Dict, List, Optional, Tuple
import xml.etree.ElementTree as ET

import numpy as np
import pandas as pd

from config import CHANNEL_ALIASES, CSV_COLUMN_ALIASES, TARGET_SPO2_SF


@dataclass
class OximetryRecording:
  file_path: str
  file_name: str
  device_type: str
  patient_id: str = ""
  start_time: Optional[datetime] = None
  duration_sec: float = 0.0
  fs: float = 1.0
  time_axis: np.ndarray = field(default_factory=lambda: np.array([]))
  spo2_raw: np.ndarray = field(default_factory=lambda: np.array([]))
  pulse_raw: Optional[np.ndarray] = None
  respiratory_events: List[Dict[str, Any]] = field(default_factory=list)
  sleep_epochs: Optional[List[int]] = None
  sleep_summary: Dict[str, Any] = field(default_factory=dict)
  annotation_file_loaded: str = ""
  metadata: Dict[str, Any] = field(default_factory=dict)


def _match_alias(name: str, aliases: List[str]) -> bool:
  clean_name = name.lower().strip()
  for cand in aliases:
    if clean_name == cand.lower().strip():
      return True
  for cand in aliases:
    if cand.lower().strip() in clean_name:
      return True
  return False


def _find_channel_idx(
    channel_names: List[str], target_key: str
) -> Optional[int]:
  aliases = CHANNEL_ALIASES.get(target_key, [])
  for i, ch in enumerate(channel_names):
    ch_clean = ch.lower().strip()
    for cand in aliases:
      if ch_clean == cand.lower().strip():
        return i
  for i, ch in enumerate(channel_names):
    ch_clean = ch.lower().strip()
    for cand in aliases:
      if cand.lower().strip() in ch_clean:
        return i
  return None


def read_edf_pure_python(
    edf_path: str,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]], Dict[str, np.ndarray]]:
  with open(edf_path, "rb") as f:
    version = f.read(8).decode("ascii", errors="ignore").strip()
    patient_id = f.read(80).decode("ascii", errors="ignore").strip()
    record_id = f.read(80).decode("ascii", errors="ignore").strip()
    start_date = f.read(8).decode("ascii", errors="ignore").strip()
    start_time_str = f.read(8).decode("ascii", errors="ignore").strip()
    header_bytes = int(f.read(8).decode("ascii", errors="ignore").strip())
    reserved = f.read(44).decode("ascii", errors="ignore").strip()
    num_records = int(f.read(8).decode("ascii", errors="ignore").strip())
    record_duration = float(f.read(8).decode("ascii", errors="ignore").strip())
    ns = int(f.read(4).decode("ascii", errors="ignore").strip())

    labels = [
        f.read(16).decode("ascii", errors="ignore").strip() for _ in range(ns)
    ]
    transducers = [
        f.read(80).decode("ascii", errors="ignore").strip() for _ in range(ns)
    ]
    physical_dims = [
        f.read(8).decode("ascii", errors="ignore").strip() for _ in range(ns)
    ]
    phys_mins = [
        float(f.read(8).decode("ascii", errors="ignore").strip())
        for _ in range(ns)
    ]
    phys_maxs = [
        float(f.read(8).decode("ascii", errors="ignore").strip())
        for _ in range(ns)
    ]
    dig_mins = [
        float(f.read(8).decode("ascii", errors="ignore").strip())
        for _ in range(ns)
    ]
    dig_maxs = [
        float(f.read(8).decode("ascii", errors="ignore").strip())
        for _ in range(ns)
    ]
    prefilterings = [
        f.read(80).decode("ascii", errors="ignore").strip() for _ in range(ns)
    ]
    samples_per_record = [
        int(f.read(8).decode("ascii", errors="ignore").strip())
        for _ in range(ns)
    ]
    reserved_signals = [
        f.read(32).decode("ascii", errors="ignore").strip() for _ in range(ns)
    ]

    header = {
        "version": version,
        "patient_id": patient_id,
        "record_id": record_id,
        "start_date": start_date,
        "start_time": start_time_str,
        "header_bytes": header_bytes,
        "num_records": num_records,
        "record_duration": record_duration,
        "num_signals": ns,
    }

    signal_headers = []
    for i in range(ns):
      scale = (
          (phys_maxs[i] - phys_mins[i]) / (dig_maxs[i] - dig_mins[i])
          if (dig_maxs[i] != dig_mins[i])
          else 1.0
      )
      signal_headers.append({
          "label": labels[i],
          "transducer": transducers[i],
          "dimension": physical_dims[i],
          "phys_min": phys_mins[i],
          "phys_max": phys_maxs[i],
          "dig_min": dig_mins[i],
          "dig_max": dig_maxs[i],
          "prefiltering": prefilterings[i],
          "samples_per_record": samples_per_record[i],
          "fs": (
              samples_per_record[i] / record_duration
              if record_duration > 0
              else 1.0
          ),
          "scale": scale,
          "offset": phys_mins[i] - dig_mins[i] * scale,
      })

    f.seek(header_bytes)
    record_samples_total = sum(samples_per_record)
    bytes_per_record = record_samples_total * 2

    raw_records = f.read(num_records * bytes_per_record)
    signals = {
        sig["label"]: np.zeros(
            num_records * sig["samples_per_record"], dtype=np.float32
        )
        for sig in signal_headers
    }

    int16_arr = np.frombuffer(raw_records, dtype=np.int16)
    if len(int16_arr) == num_records * record_samples_total:
      matrix = int16_arr.reshape((num_records, record_samples_total))
      col_start = 0
      for i, sig in enumerate(signal_headers):
        lbl = sig["label"]
        spr = sig["samples_per_record"]
        col_end = col_start + spr
        sig_raw = matrix[:, col_start:col_end].flatten()
        signals[lbl] = (sig_raw * sig["scale"] + sig["offset"]).astype(
            np.float32
        )
        col_start = col_end
    else:
      offset = 0
      for r in range(num_records):
        for i, sig in enumerate(signal_headers):
          spr = sig["samples_per_record"]
          raw_chunk = int16_arr[offset : offset + spr]
          offset += spr
          lbl = sig["label"]
          scaled = raw_chunk * sig["scale"] + sig["offset"]
          signals[lbl][r * spr : (r + 1) * spr] = scaled

    return header, signal_headers, signals


def parse_compumedics_annotation_xml(
    edf_path: str,
) -> Tuple[List[Dict[str, Any]], Optional[List[int]], Dict[str, Any], str]:
  events = []
  sleep_epoch_list = []
  sleep_summary = {}
  matched_xml_path = ""

  directory = os.path.dirname(os.path.abspath(edf_path))
  file_name = os.path.basename(edf_path)
  file_stem = os.path.splitext(file_name)[0]

  candidates = [
      f"{edf_path}.XML",
      f"{edf_path}.xml",
      os.path.join(directory, f"{file_name}.XML"),
      os.path.join(directory, f"{file_name}.xml"),
      os.path.join(directory, f"{file_stem}.XML"),
      os.path.join(directory, f"{file_stem}.xml"),
      os.path.join(directory, f"{file_stem}_Profusion.xml"),
      os.path.join(directory, f"{file_stem}_Profusion.XML"),
      os.path.join(directory, f"{file_stem}_events.xml"),
      os.path.join(directory, f"{file_stem}_events.XML"),
  ]

  if not any(os.path.exists(p) for p in candidates):
    if os.path.exists(directory):
      for f in os.listdir(directory):
        f_lower = f.lower()
        if (
            file_stem.lower() in f_lower or file_name.lower() in f_lower
        ) and f_lower.endswith(".xml"):
          candidates.append(os.path.join(directory, f))

  for cand in candidates:
    if os.path.exists(cand):
      matched_xml_path = cand
      break

  if not matched_xml_path:
    return events, None, sleep_summary, ""

  def safe_get_text(element, tags, default=""):
    for tag in tags:
      node = element.find(tag)
      if node is not None and node.text is not None:
        return node.text.strip()
    return default

  try:
    tree = ET.parse(matched_xml_path)
    root = tree.getroot()

    stages_container = (
        root.find("SleepStages")
        or root.find("SLEEPSTAGES")
        or root.find("Stages")
        or root.find("STAGES")
    )
    if stages_container is not None:
      profusion_to_simplex = {
          0: 0,
          10: 0,
          1: 1,
          2: 2,
          3: 3,
          4: 3,
          5: 4,
          6: 0,
          9: 0,
      }
      for elem in stages_container:
        tag_up = elem.tag.upper()
        if "STAGE" in tag_up or "EPOCH" in tag_up:
          val_str = elem.text.strip() if elem.text else ""
          if not val_str and "STAGE" in elem.attrib:
            val_str = elem.attrib.get("STAGE", "").strip()
          if val_str and val_str.isdigit():
            raw_val = int(val_str)
            simplex_val = profusion_to_simplex.get(raw_val, 0)
            sleep_epoch_list.append(simplex_val)

    if sleep_epoch_list:
      total_epochs = len(sleep_epoch_list)
      sleep_epochs = [st for st in sleep_epoch_list if st in [1, 2, 3, 4]]
      tst_minutes = len(sleep_epochs) * 0.5
      trt_minutes = total_epochs * 0.5
      sleep_efficiency = (
          (tst_minutes / trt_minutes) * 100.0 if trt_minutes > 0 else 0.0
      )

      non_wake_indices = [
          i for i, st in enumerate(sleep_epoch_list) if st in [1, 2, 3, 4]
      ]
      if non_wake_indices:
        first_sleep_idx = non_wake_indices[0]
        last_sleep_idx = non_wake_indices[-1]
        spt_epochs = last_sleep_idx - first_sleep_idx + 1
        spt_minutes = spt_epochs * 0.5
        spt_start_sec = first_sleep_idx * 30.0
        spt_end_sec = (last_sleep_idx + 1) * 30.0
        waso_epochs = sum(
            1
            for st in sleep_epoch_list[first_sleep_idx : last_sleep_idx + 1]
            if st == 0
        )
        waso_minutes = waso_epochs * 0.5
      else:
        first_sleep_idx = 0
        last_sleep_idx = 0
        spt_minutes = 0.0
        spt_start_sec = 0.0
        spt_end_sec = 0.0
        waso_minutes = 0.0

      n1_epochs = sum(1 for st in sleep_epoch_list if st == 1)
      n2_epochs = sum(1 for st in sleep_epoch_list if st == 2)
      n3_epochs = sum(1 for st in sleep_epoch_list if st == 3)
      rem_epochs = sum(1 for st in sleep_epoch_list if st == 4)

      sleep_summary = {
          "Total_Epochs": total_epochs,
          "First_Sleep_Epoch": first_sleep_idx + 1,
          "Last_Sleep_Epoch": last_sleep_idx + 1,
          "SPT_Start_sec": spt_start_sec,
          "SPT_End_sec": spt_end_sec,
          "SPT_Minutes": spt_minutes,
          "SPT_Hours": spt_minutes / 60.0,
          "TST_Minutes": tst_minutes,
          "TST_Hours": tst_minutes / 60.0,
          "TRT_Minutes": trt_minutes,
          "TRT_Hours": trt_minutes / 60.0,
          "WASO_Minutes": waso_minutes,
          "Sleep_Efficiency_pct": sleep_efficiency,
          "N1_pct": (
              (n1_epochs / len(sleep_epochs)) * 100.0 if sleep_epochs else 0.0
          ),
          "N2_pct": (
              (n2_epochs / len(sleep_epochs)) * 100.0 if sleep_epochs else 0.0
          ),
          "N3_pct": (
              (n3_epochs / len(sleep_epochs)) * 100.0 if sleep_epochs else 0.0
          ),
          "REM_pct": (
              (rem_epochs / len(sleep_epochs)) * 100.0 if sleep_epochs else 0.0
          ),
      }

    events_container = (
        root.find("ScoredEvents")
        or root.find("SCOREDEVENTS")
        or root.find("Events")
    )
    if events_container is not None:
      for event in events_container:
        name = safe_get_text(
            event, ["Name", "NAME", "EventConcept", "Concept"], default=""
        )
        start_str = safe_get_text(
            event, ["Start", "START", "StartTime", "TIME"], default=""
        )
        dur_str = safe_get_text(event, ["Duration", "DURATION"], default="")
        type_str = safe_get_text(event, ["Type", "TYPE"], default="")

        if name and start_str and dur_str:
          try:
            start_val = float(start_str)
            dur_val = float(dur_str)
            name_lower = name.lower()
            is_resp = any(
                k in name_lower
                for k in [
                    "apnea",
                    "hypopnea",
                    "obstructive",
                    "central",
                    "mixed",
                    "rera",
                ]
            ) or (type_str in ["1", "2", "3"])
            is_desat = "desat" in name_lower or type_str == "4"

            events.append({
                "Name": name,
                "Start": start_val,
                "Duration": dur_val,
                "End": start_val + dur_val,
                "Type": type_str,
                "Is_Respiratory": is_resp,
                "Is_Desat": is_desat,
            })
          except (ValueError, TypeError):
            continue

  except Exception as e:
    print(f"[Warning] Error parsing XML {matched_xml_path}: {e}")

  return (
      events,
      (sleep_epoch_list if sleep_epoch_list else None),
      sleep_summary,
      matched_xml_path,
  )


def parse_edf_oximetry(edf_path: str) -> OximetryRecording:
  file_name = os.path.basename(edf_path)
  patient_id = ""
  start_dt = None
  signals_dict = {}

  loaded = False
  try:
    import pyedflib

    f = pyedflib.EdfReader(edf_path)
    labels = f.getSignalLabels()
    patient_id = f.getPatientCode() or ""
    try:
      start_dt = f.getStartdatetime()
    except Exception:
      start_dt = None

    spo2_idx = _find_channel_idx(labels, "SpO2")
    if spo2_idx is not None:
      spo2_sig = f.readSignal(spo2_idx)
      fs_spo2 = float(f.getSampleFrequency(spo2_idx))
      signals_dict["SpO2"] = (spo2_sig, fs_spo2, labels[spo2_idx])
      loaded = True

    pulse_idx = _find_channel_idx(labels, "Pulse")
    if pulse_idx is not None:
      pulse_sig = f.readSignal(pulse_idx)
      fs_pulse = float(f.getSampleFrequency(pulse_idx))
      signals_dict["Pulse"] = (pulse_sig, fs_pulse, labels[pulse_idx])

    embedded_events = []
    try:
      annots = f.readAnnotations()
      if annots and len(annots[0]) > 0:
        starts, durs, texts = annots[0], annots[1], annots[2]
        for s, d, txt in zip(starts, durs, texts):
          txt_lower = txt.lower()
          is_resp = any(
              k in txt_lower
              for k in ["apnea", "hypopnea", "obstructive", "central", "mixed"]
          )
          embedded_events.append({
              "Name": txt,
              "Start": float(s),
              "Duration": float(d),
              "End": float(s) + float(d),
              "Is_Respiratory": is_resp,
              "Is_Desat": "desat" in txt_lower,
          })
    except Exception:
      pass

    f._close()
    del f
  except Exception:
    loaded = False

  if not loaded:
    header, sig_headers, raw_signals = read_edf_pure_python(edf_path)
    labels = [s["label"] for s in sig_headers]
    patient_id = header.get("patient_id", "")

    try:
      date_str = header.get("start_date", "01.01.20")
      time_str = header.get("start_time", "00.00.00")
      date_clean = re.sub(r"[^0-9]", ".", date_str)
      time_clean = re.sub(r"[^0-9]", ":", time_str)
      start_dt = datetime.strptime(
          f"{date_clean} {time_clean}", "%d.%m.%y %H:%M:%S"
      )
    except Exception:
      start_dt = None

    spo2_idx = _find_channel_idx(labels, "SpO2")
    if spo2_idx is None:
      raise ValueError(
          "Could not find SpO2 / SaO2 channel in EDF. Available channels:"
          f" {', '.join(labels)}"
      )

    spo2_hdr = sig_headers[spo2_idx]
    spo2_lbl = spo2_hdr["label"]
    signals_dict["SpO2"] = (raw_signals[spo2_lbl], spo2_hdr["fs"], spo2_lbl)

    pulse_idx = _find_channel_idx(labels, "Pulse")
    if pulse_idx is not None:
      pulse_hdr = sig_headers[pulse_idx]
      pulse_lbl = pulse_hdr["label"]
      signals_dict["Pulse"] = (
          raw_signals[pulse_lbl],
          pulse_hdr["fs"],
          pulse_lbl,
      )

    embedded_events = []

  spo2_raw_arr, fs_spo2, matched_ch_name = signals_dict["SpO2"]
  spo2_clean = np.array(spo2_raw_arr, dtype=np.float64)

  valid_finite = spo2_clean[np.isfinite(spo2_clean)]
  if len(valid_finite) > 0:
    max_val = np.percentile(valid_finite, 99.5)
    if 0.05 < max_val <= 1.05:
      spo2_clean *= 100.0

  duration_sec = len(spo2_clean) / fs_spo2
  time_axis = np.linspace(0.0, duration_sec, len(spo2_clean), endpoint=False)

  pulse_clean = None
  if "Pulse" in signals_dict:
    pulse_raw_arr, fs_pulse, _ = signals_dict["Pulse"]
    if len(pulse_raw_arr) == len(spo2_clean):
      pulse_clean = np.array(pulse_raw_arr, dtype=np.float64)
    else:
      dur_pulse = len(pulse_raw_arr) / fs_pulse
      t_pulse = np.linspace(0.0, dur_pulse, len(pulse_raw_arr), endpoint=False)
      pulse_clean = np.interp(time_axis, t_pulse, pulse_raw_arr)

  xml_events, sleep_stages, sleep_summary, xml_matched = (
      parse_compumedics_annotation_xml(edf_path)
  )
  all_events = xml_events if xml_events else embedded_events
  resp_events = [e for e in all_events if e.get("Is_Respiratory", False)]

  upper_fname = file_name.upper()
  upper_ch = matched_ch_name.upper()
  if (
      xml_matched
      or "COMPUMEDICS" in upper_fname
      or "GRAEL" in upper_fname
      or "SOMTE" in upper_fname
      or "SAO2" in upper_ch
  ):
    device_type = "Compumedics EDF"
  elif "NOX" in upper_fname or "A1" in upper_fname or "T3" in upper_fname:
    device_type = "Nox EDF"
  elif (
      "REMLOGIC" in upper_fname
      or "EMBLA" in upper_fname
      or "OXIMETER" in upper_ch
  ):
    device_type = "REMlogic EDF"
  else:
    device_type = "Standard EDF"

  return OximetryRecording(
      file_path=edf_path,
      file_name=file_name,
      device_type=device_type,
      patient_id=patient_id,
      start_time=start_dt,
      duration_sec=duration_sec,
      fs=fs_spo2,
      time_axis=time_axis,
      spo2_raw=spo2_clean,
      pulse_raw=pulse_clean,
      respiratory_events=resp_events,
      sleep_epochs=sleep_stages,
      sleep_summary=sleep_summary,
      annotation_file_loaded=xml_matched,
      metadata={
          "channel_name": matched_ch_name,
          "all_xml_events": all_events,
      },
  )


def _clean_nellcor_stream(lines: List[str]) -> Tuple[List[str], str]:
  clean_lines = []
  header_found = False

  for line in lines:
    line_str = line.strip()
    if not line_str or line_str.startswith("Output Complete"):
      continue

    if any(
        token in line_str
        for token in ["VERSION", "SpO2 Limit:", "RESP MODE:", "CRC:"]
    ):
      continue

    if re.search(r"\bTIME\b", line_str, re.I) and re.search(
        r"%SPO2", line_str, re.I
    ):
      if not header_found:
        clean_lines.append(line_str)
        header_found = True
      continue

    cleaned_row = re.sub(r"(\d+)\*", r"\1", line_str)
    clean_lines.append(cleaned_row)

  return clean_lines, "Nellcor ASCII"


def _clean_masimo_stream(lines: List[str]) -> Tuple[pd.DataFrame, bool]:
  """Parses Masimo Rad-5/TrendCom key-value trend exports:

  Format: MM/DD/YY HH:MM:SS SpO2=097 PR=069 PI=04.69 EXC=800: SET
  """
  records = []
  pattern = re.compile(
      r"(?P<date>\d{1,2}[/\\]\d{1,2}[/\\]\d{2,4})\s+"
      r"(?P<time>\d{1,2}:\d{2}:\d{2})\s+"
      r".*?SpO2=(?P<spo2>[\d\-]+)"
      r".*?PR=(?P<pr>[\d\-]+)"
      r"(?:.*?PI=(?P<pi>[\d\.\-]+))?"
  )

  for line in lines:
    line_str = line.strip()
    if not line_str:
      continue
    match = pattern.search(line_str)
    if match:
      date_str = match.group("date").replace("\\", "/")
      time_str = match.group("time")
      spo2_val = match.group("spo2")
      pr_val = match.group("pr")
      pi_val = match.group("pi")

      records.append({
          "DateTime": f"{date_str} {time_str}",
          "SpO2": np.nan if (spo2_val == "000" or "-" in spo2_val) else spo2_val,
          "Pulse": np.nan if (pr_val == "000" or "-" in pr_val) else pr_val,
          "PI": np.nan if (pi_val is None or "-" in pi_val) else pi_val,
      })

  if len(records) > 5:
    return pd.DataFrame(records), True
  return pd.DataFrame(), False


def parse_text_oximetry(file_path: str) -> OximetryRecording:
  file_name = os.path.basename(file_path)
  ext = os.path.splitext(file_name)[1].lower()

  with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
    raw_lines = f.readlines()

  preview = "".join(raw_lines[:60]).lower()

  is_nellcor = (
      "n600" in preview
      or "oximax" in preview
      or ("%spo2" in preview and "resp mode" in preview)
  )
  is_nonin = (
      ext == ".asc"
      or "nonin" in preview
      or "nvision" in preview
      or "wristox" in preview
  )
  is_masimo_tag = (
      "spo2=" in preview
      or "exc=" in preview
      or "trendcom" in preview
      or "masimo" in preview
      or "rad-5" in preview
      or "rad-97" in preview
      or "rad-67" in preview
  )

  df = None
  device_type = "Generic Oximetry CSV"

  if is_masimo_tag:
    masimo_df, matched_masimo = _clean_masimo_stream(raw_lines)
    if matched_masimo:
      df = masimo_df
      device_type = "Masimo Rad-5/TrendCom"

  if df is None:
    if is_nellcor:
      device_type = "Nellcor N-600x"
      filtered_lines, _ = _clean_nellcor_stream(raw_lines)
    else:
      filtered_lines = raw_lines
      if is_nonin:
        device_type = "Nonin ASC/CSV"
      elif is_masimo_tag:
        device_type = "Masimo CSV/TXT"
      else:
        device_type = "Generic Oximetry CSV"

    header_line_idx = -1
    delimiter = ","

    for idx, line in enumerate(filtered_lines[:80]):
      line_clean = line.strip()
      if (
          not line_clean
          or line_clean.startswith("#")
          or line_clean.startswith("//")
      ):
        continue

      for d in [",", "\t", ";", " "]:
        parts = [
            p.strip()
            for p in re.split(rf"\{d}+" if d == " " else d, line_clean)
            if p.strip()
        ]
        has_spo2 = any(_match_alias(p, CSV_COLUMN_ALIASES["SpO2"]) for p in parts)
        if has_spo2 and len(parts) >= 2:
          header_line_idx = idx
          delimiter = d
          break
      if header_line_idx != -1:
        break

    # Re-join with explicit newlines: the Nellcor cleaner strips line endings,
    # so a bare "".join() would collapse the whole file onto one line.
    buffer_data = "\n".join(line.rstrip("\r\n") for line in filtered_lines)
    sep_regex = rf"\{delimiter}+" if delimiter == " " else delimiter

    if header_line_idx >= 0:
      df = pd.read_csv(
          io.StringIO(buffer_data),
          sep=sep_regex,
          skiprows=header_line_idx,
          engine="python",
          on_bad_lines="skip",
      )
    else:
      df = pd.read_csv(
          io.StringIO(buffer_data),
          sep=sep_regex,
          header=None,
          engine="python",
          on_bad_lines="skip",
      )

  df.columns = [str(c).strip() for c in df.columns]
  df.replace(["---", "--", " ", "000"], np.nan, inplace=True)

  spo2_col = None
  for col in df.columns:
    if _match_alias(str(col), CSV_COLUMN_ALIASES["SpO2"]):
      spo2_col = col
      break
  if spo2_col is None:
    for col in df.columns:
      series = pd.to_numeric(df[col], errors="coerce").dropna()
      if len(series) > 10 and 70 <= series.median() <= 100:
        spo2_col = col
        break

  if spo2_col is None:
    raise ValueError(
        f"Could not identify SpO2 column in {file_name}. Columns:"
        f" {list(df.columns)}"
    )

  pulse_col = None
  for col in df.columns:
    if col != spo2_col and _match_alias(str(col), CSV_COLUMN_ALIASES["Pulse"]):
      pulse_col = col
      break
  if pulse_col is None:
    for col in df.columns:
      if col != spo2_col:
        series = pd.to_numeric(df[col], errors="coerce").dropna()
        if len(series) > 10 and 40 <= series.median() <= 180:
          pulse_col = col
          break

  time_col = None
  for col in df.columns:
    if col not in (spo2_col, pulse_col) and _match_alias(
        str(col), CSV_COLUMN_ALIASES["Time"]
    ):
      time_col = col
      break

  spo2_arr = pd.to_numeric(df[spo2_col], errors="coerce").values
  pulse_arr = (
      pd.to_numeric(df[pulse_col], errors="coerce").values
      if pulse_col is not None
      else None
  )

  fs = 1.0
  start_dt = None
  fs_from_numeric = False

  if time_col is not None:
    time_series = df[time_col].astype(str).str.strip()
    try:
      numeric_time = pd.to_numeric(time_series, errors="coerce").dropna()
      if len(numeric_time) > 10:
        diffs = np.diff(numeric_time.values)
        pos_diffs = diffs[diffs > 0]
        if len(pos_diffs) > 0 and np.median(pos_diffs) > 0:
          fs = round(1.0 / np.median(pos_diffs), 2)
          fs_from_numeric = True
    except Exception:
      pass

    # Only fall back to date/time parsing when the time column is not a plain
    # numeric seconds counter (otherwise "0, 1, 2..." gets misread as dates).
    if not fs_from_numeric:
      try:
        parsed_dt = pd.to_datetime(
            time_series, format="mixed", errors="coerce"
        )
        valid_dt = parsed_dt.dropna()
        if len(valid_dt) > 1:
          start_dt = valid_dt.iloc[0].to_pydatetime()
          diffs_sec = valid_dt.diff().dt.total_seconds().dropna()
          pos_sec = diffs_sec[diffs_sec > 0]
          if len(pos_sec) > 0 and np.median(pos_sec) > 0:
            fs = round(1.0 / np.median(pos_sec), 2)
      except Exception:
        pass

  if not np.isfinite(fs) or fs <= 0:
    fs = 1.0

  n_samples = len(spo2_arr)
  duration_sec = n_samples / fs if fs > 0 else float(n_samples)
  time_axis = np.linspace(0.0, duration_sec, n_samples, endpoint=False)

  return OximetryRecording(
      file_path=file_path,
      file_name=file_name,
      device_type=device_type,
      patient_id="",
      start_time=start_dt,
      duration_sec=duration_sec,
      fs=fs,
      time_axis=time_axis,
      spo2_raw=spo2_arr,
      pulse_raw=pulse_arr,
      respiratory_events=[],
      sleep_epochs=None,
      sleep_summary={},
      annotation_file_loaded="",
      metadata={"columns": list(df.columns), "spo2_col": str(spo2_col)},
  )


def load_oximetry_file(file_path: str) -> OximetryRecording:
  if not os.path.exists(file_path):
    raise FileNotFoundError(f"File not found: {file_path}")

  ext = os.path.splitext(file_path)[1].lower()
  if ext in [".edf", ".rec", ".bdf"]:
    return parse_edf_oximetry(file_path)
  else:
    return parse_text_oximetry(file_path)