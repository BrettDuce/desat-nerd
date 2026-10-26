"""
CSV Export Engine for Oximetry & Hypoxic Burden Results
Handles:
  - Single file summary export
  - Detailed individual event morphology export
  - Batch summary CSV export with thread-safe append support
"""

import csv
import os
from typing import Any, Dict, List
import pandas as pd


SUMMARY_FIELDNAMES = [
    "File_Name",
    "Device_Type",
    "Patient_ID",
    "Annotation_File",
    "Analysis_Window_Type",
    "Total_Duration_Hours",
    "Analysis_Duration_Hours",
    "SPT_Minutes",
    "TST_Minutes",
    "TRT_Minutes",
    "Sleep_Efficiency_pct",
    "First_Sleep_Epoch",
    "Last_Sleep_Epoch",
    "Sampling_Rate_Hz",
    "Baseline_SpO2",
    "Mean_SpO2",
    "Min_SpO2",
    "Desaturation_Threshold",
    "Desaturation_Count",
    "ODI_Selected",
    "ODI_3pct",
    "ODI_4pct",
    "Mean_Desat_Duration_sec",
    "Mean_Desat_Depth_pct",
    "Mean_Fall_Slope_pct_s",
    "Mean_Recovery_Slope_pct_s",
    "Mean_Desat_Area_pct_sec",
    "Mean_Desat_Area_pct_min",
    "T90_Percent",
    "T90_Minutes",
    "T88_Percent",
    "T88_Minutes",
    "T85_Percent",
    "T85_Minutes",
    "T80_Percent",
    "T80_Minutes",
    "Artifact_Percent",
    "Artifact_Minutes",
    "Azarbarzin_HB_pctmin_hr",
    "Azarbarzin_HB_Total_pctmin",
    "Azarbarzin_Method",
    "REDTA_pct_hours",
    "REDTA_Rate_pctmin_hr",
    "REDTA_Method",
    "Kulkas_DesSev_pctmin_hr",
    "Kulkas_RecSev_pctmin_hr",
    "Kulkas_Total_Severity_pctmin_hr",
    "Kulkas_Mean_Fall_Slope",
    "Kulkas_Mean_Recovery_Slope"
]

EVENT_FIELDNAMES = [
    "Event_ID",
    "Start_sec",
    "End_sec",
    "Duration_sec",
    "Fall_Duration_sec",
    "Recovery_Duration_sec",
    "Baseline_SpO2_pct",
    "Nadir_SpO2_pct",
    "Depth_pct",
    "Fall_Slope_pct_s",
    "Recovery_Slope_pct_s",
    "Fall_Area_pct_sec",
    "Fall_Area_pct_min",
    "Recovery_Area_pct_sec",
    "Recovery_Area_pct_min",
    "Total_Area_pct_sec",
    "Total_Area_pct_min",
    "Is_In_SPT",
    "Is_In_TST"
]


class OximetryExporter:
    @staticmethod
    def _build_summary_row(result: Dict[str, Any]) -> Dict[str, Any]:
        sleep_sum = result.get("Sleep_Summary", {})
        row = {}
        for k in SUMMARY_FIELDNAMES:
            if k in result:
                row[k] = result[k]
            elif k in sleep_sum:
                row[k] = sleep_sum[k]
            else:
                row[k] = ""
        return row
    @staticmethod
    def export_single_summary(result: Dict[str, Any], output_dir: str) -> str:
        os.makedirs(output_dir, exist_ok=True)
        file_stem = os.path.splitext(result["File_Name"])[0]
        csv_path = os.path.join(output_dir, f"{file_stem}_oximetry_summary.csv")

        row = OximetryExporter._build_summary_row(result)
        df = pd.DataFrame([row])
        df.to_csv(csv_path, index=False)
        return csv_path

    @staticmethod
    def export_events_csv(result: Dict[str, Any], output_dir: str) -> str:
        os.makedirs(output_dir, exist_ok=True)
        file_stem = os.path.splitext(result["File_Name"])[0]
        csv_path = os.path.join(output_dir, f"{file_stem}_desaturation_events.csv")

        events = result.get("desaturation_events", [])
        rows = []
        for ev in events:
            rows.append({
                "Event_ID": ev.get("Event_ID"),
                "Start_sec": round(ev.get("Start", 0.0), 2),
                "End_sec": round(ev.get("End", 0.0), 2),
                "Duration_sec": round(ev.get("Duration", 0.0), 2),
                "Fall_Duration_sec": round(ev.get("Fall_Duration", 0.0), 2),
                "Recovery_Duration_sec": round(ev.get("Recovery_Duration", 0.0), 2),
                "Baseline_SpO2_pct": round(ev.get("Baseline", 0.0), 1),
                "Nadir_SpO2_pct": round(ev.get("Nadir", 0.0), 1),
                "Depth_pct": round(ev.get("Depth", 0.0), 1),
                "Fall_Slope_pct_s": round(ev.get("Fall_Slope", 0.0), 3),
                "Recovery_Slope_pct_s": round(ev.get("Recovery_Slope", 0.0), 3),
                "Fall_Area_pct_sec": round(ev.get("Fall_Area_sec", 0.0), 2),
                "Fall_Area_pct_min": round(ev.get("Fall_Area_min", 0.0), 4),
                "Recovery_Area_pct_sec": round(ev.get("Recovery_Area_sec", 0.0), 2),
                "Recovery_Area_pct_min": round(ev.get("Recovery_Area_min", 0.0), 4),
                "Total_Area_pct_sec": round(ev.get("Total_Area_sec", 0.0), 2),
                "Total_Area_pct_min": round(ev.get("Total_Area_min", 0.0), 4)
            })

        df = pd.DataFrame(rows)
        df.to_csv(csv_path, index=False)
        return csv_path

    @staticmethod
    def append_to_batch_summary(result: Dict[str, Any], output_dir: str, master_filename: str = "batch_oximetry_hypoxic_burden_summary.csv") -> str:
        os.makedirs(output_dir, exist_ok=True)
        csv_path = os.path.join(output_dir, master_filename)
        file_exists = os.path.exists(csv_path)

        row = OximetryExporter._build_summary_row(result)

        with open(csv_path, mode='a', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=SUMMARY_FIELDNAMES)
            if not file_exists:
                writer.writeheader()
            writer.writerow(row)

        return csv_path
