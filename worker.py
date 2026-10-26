"""
Asynchronous Worker Thread for Single File & Batch Oximetry Analysis
"""

import os
import traceback
from typing import Any, Dict, List, Union

try:
    from PySide6.QtCore import QThread, Signal
except ImportError:
    # Dummy mock for headless / non-GUI testing environments
    class Signal:
        def __init__(self, *types):
            self._callbacks = []
        def connect(self, cb):
            self._callbacks.append(cb)
        def emit(self, *args):
            for cb in self._callbacks:
                try:
                    cb(*args)
                except Exception:
                    pass

    class QThread:
        def __init__(self):
            pass
        def start(self):
            self.run()

from parsers import load_oximetry_file
from oximetry_engine import OximetryEngine
from exporter import OximetryExporter


class AnalysisWorker(QThread):
    log_signal = Signal(str)
    progress_signal = Signal(int)
    batch_progress_signal = Signal(int, int)
    result_signal = Signal(dict)
    file_completed_signal = Signal(int)
    finished_signal = Signal()
    error_signal = Signal(str)

    def __init__(self, file_list: Union[str, List[str]], output_folder: str, settings: Dict[str, Any]):
        super().__init__()
        self.file_list = file_list if isinstance(file_list, list) else [file_list]
        self.output_folder = output_folder
        self.settings = settings
        self._is_running = True

    def stop(self):
        self._is_running = False

    def run(self):
        total_files = len(self.file_list)
        self.log_signal.emit(f"Starting oximetry analysis for {total_files} file(s)...")

        threshold = float(self.settings.get("threshold", 3.0))
        min_duration = float(self.settings.get("min_duration", 5.0))
        max_duration = float(self.settings.get("max_duration", 120.0))
        baseline_win_sec = float(self.settings.get("baseline_window_sec", 300.0))
        baseline_quantile = float(self.settings.get("baseline_quantile", 0.98))
        analysis_window = self.settings.get("analysis_window", "TRT")
        batch_append = self.settings.get("batch_append_csv", True)
        export_events = self.settings.get("export_events_csv", True)

        os.makedirs(self.output_folder, exist_ok=True)

        for idx, file_path in enumerate(self.file_list):
            if not self._is_running:
                self.log_signal.emit("[Cancelled] Batch analysis stopped by user.")
                break

            fname = os.path.basename(file_path)
            self.log_signal.emit(f"\n[{idx + 1}/{total_files}] Processing: {fname}")
            self.batch_progress_signal.emit(idx, total_files)
            self.progress_signal.emit(10)

            try:
                # 1. Load File
                self.log_signal.emit(f"Parsing recording: {fname}...")
                recording = load_oximetry_file(file_path)
                self.progress_signal.emit(35)

                # 2. Run Engine
                self.log_signal.emit(f"Detecting desaturations & calculating hypoxic burden ({recording.device_type})...")
                result = OximetryEngine.analyze_recording(
                    recording,
                    threshold=threshold,
                    min_duration=min_duration,
                    max_duration=max_duration,
                    baseline_win_sec=baseline_win_sec,
                    baseline_quantile=baseline_quantile,
                    analysis_window_type=analysis_window
                )
                self.progress_signal.emit(70)

                # 3. Export CSV files
                summary_csv = OximetryExporter.export_single_summary(result, self.output_folder)
                self.log_signal.emit(f"Saved summary CSV: {os.path.basename(summary_csv)}")

                if export_events:
                    events_csv = OximetryExporter.export_events_csv(result, self.output_folder)
                    self.log_signal.emit(f"Saved event morphology CSV: {os.path.basename(events_csv)}")

                if total_files > 1 or batch_append:
                    master_csv = OximetryExporter.append_to_batch_summary(result, self.output_folder)
                    self.log_signal.emit(f"Appended to master batch CSV: {os.path.basename(master_csv)}")

                self.progress_signal.emit(100)
                self.result_signal.emit(result)
                self.file_completed_signal.emit(idx + 1)

            except Exception as e:
                err_msg = f"ERROR processing {fname}: {str(e)}"
                self.log_signal.emit(f"[FAIL] {err_msg}")
                traceback.print_exc()
                self.error_signal.emit(err_msg)

        self.batch_progress_signal.emit(total_files, total_files)
        self.progress_signal.emit(100)
        self.log_signal.emit("\nAnalysis process complete.")
        self.finished_signal.emit()
