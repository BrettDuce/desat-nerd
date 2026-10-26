"""
Main Entry Point for DesatNerd: Oxygen Desaturations & Hypoxic Burden Analyzer
Part of the Metro South SleepNerd suite.
Supports:
  1. Full interactive PySide6 graphical user interface with SleepNerd icons
  2. Headless command-line execution for automated batch pipelines:
     python main.py --cli --input <file_or_dir> --output <dir> [--threshold 3.0]
"""

import argparse
import ctypes
import os
import sys

# Configure Windows Application ID for proper taskbar grouping under SleepNerd
APP_ID = "MetroSouth.SleepNerd.DesatNerd.1.0"
if sys.platform == "win32":
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass


def resource_path(relative_path: str) -> str:
    """Get absolute path to resource, works for dev and for PyInstaller."""
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)


def find_icon():
    candidates = [
        os.path.join(os.path.dirname(sys.executable), "assets", "SleepNerd.ico"),
        os.path.join(os.path.abspath("."), "assets", "SleepNerd.ico"),
        os.path.join(os.path.dirname(__file__), "assets", "SleepNerd.ico"),
        resource_path(os.path.join("assets", "SleepNerd.ico")),
    ]
    if hasattr(sys, "_MEIPASS"):
        candidates.insert(0, os.path.join(sys._MEIPASS, "assets", "SleepNerd.ico"))

    for path in candidates:
        if os.path.exists(path):
            return os.path.abspath(path)
    return None


def force_win32_taskbar_icon(hwnd, icon_path):
    """Bypasses Qt and binds the icon directly to the Windows OS window handle."""
    if not os.path.exists(icon_path) or sys.platform != "win32":
        return
    try:
        IMAGE_ICON = 1
        LR_LOADFROMFILE = 0x00000010
        LR_DEFAULTSIZE = 0x00000040
        WM_SETICON = 0x0080
        ICON_SMALL = 0
        ICON_BIG = 1

        h_icon_big = ctypes.windll.user32.LoadImageW(
            None, icon_path, IMAGE_ICON, 0, 0, LR_LOADFROMFILE | LR_DEFAULTSIZE
        )
        h_icon_small = ctypes.windll.user32.LoadImageW(
            None, icon_path, IMAGE_ICON, 16, 16, LR_LOADFROMFILE
        )

        if h_icon_big:
            ctypes.windll.user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, h_icon_big)
        if h_icon_small:
            ctypes.windll.user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, h_icon_small)
    except Exception as e:
        print(f"[Warning] Could not set Win32 window icon handle: {e}")


def run_cli(args):
    """Headless CLI mode for batch automation or server environments."""
    from parsers import load_oximetry_file
    from oximetry_engine import OximetryEngine
    from exporter import OximetryExporter

    input_path = args.input
    output_dir = args.output or os.path.join(os.getcwd(), "oximetry_results")
    threshold = float(args.threshold)
    os.makedirs(output_dir, exist_ok=True)

    if os.path.isdir(input_path):
        valid_exts = {'.edf', '.rec', '.bdf', '.csv', '.txt', '.tsv', '.dat'}
        file_list = [os.path.join(input_path, f) for f in sorted(os.listdir(input_path)) if os.path.splitext(f)[1].lower() in valid_exts]
    else:
        file_list = [input_path]

    print(f"[{APP_ID}] Processing {len(file_list)} file(s) into: {output_dir}")
    for idx, fpath in enumerate(file_list):
        fname = os.path.basename(fpath)
        print(f"[{idx + 1}/{len(file_list)}] Analyzing: {fname}...")
        try:
            recording = load_oximetry_file(fpath)
            res = OximetryEngine.analyze_recording(recording, threshold=threshold)
            sum_csv = OximetryExporter.export_single_summary(res, output_dir)
            ev_csv = OximetryExporter.export_events_csv(res, output_dir)
            master_csv = OximetryExporter.append_to_batch_summary(res, output_dir)
            print(f"  -> ODI 3%: {res['ODI_3pct']:.1f}, ODI 4%: {res['ODI_4pct']:.1f}, T90: {res['T90_Percent']:.1f}%, Azarbarzin HB: {res['Azarbarzin_HB_pctmin_hr']:.2f}")
            print(f"  -> Saved summary: {os.path.basename(sum_csv)}, events: {os.path.basename(ev_csv)}")
        except Exception as e:
            print(f"  -> [ERROR] Failed {fname}: {e}")

    print(f"Batch processing completed. Master results appended to: {os.path.join(output_dir, 'batch_oximetry_hypoxic_burden_summary.csv')}")


def run_gui():
    """Launches the PySide6 Graphical User Interface."""
    try:
        from PySide6.QtGui import QIcon
        from PySide6.QtWidgets import QApplication
        from gui import MainWindow
    except ImportError:
        print("[Error] PySide6 is not installed. To launch the graphical interface, please install PySide6:")
        print("  pip install PySide6")
        print("\nAlternatively, run in headless CLI mode:")
        print("  python main.py --cli --input <file_or_folder> --output <results_folder>")
        sys.exit(1)

    app = QApplication(sys.argv)
    ico_path = find_icon()
    if ico_path:
        app.setWindowIcon(QIcon(ico_path))

    window = MainWindow()
    if ico_path:
        window.setWindowIcon(QIcon(ico_path))

    window.show()

    if ico_path and sys.platform == "win32":
        try:
            hwnd = int(window.winId())
            force_win32_taskbar_icon(hwnd, ico_path)
        except Exception:
            pass

    sys.exit(app.exec())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="DesatNerd: Oxygen Desaturations & Hypoxic Burden Analyzer")
    parser.add_argument("--cli", action="store_true", help="Run in headless command-line mode without GUI")
    parser.add_argument("--input", "-i", type=str, help="Path to single file or folder containing oximetry recordings")
    parser.add_argument("--output", "-o", type=str, default="", help="Directory to save CSV outputs")
    parser.add_argument("--threshold", "-t", type=float, default=3.0, help="Desaturation drop threshold in percent (default: 3.0)")

    args = parser.parse_args()

    if args.cli or args.input:
        if not args.input:
            print("[Error] --input is required when running in CLI mode.")
            sys.exit(1)
        run_cli(args)
    else:
        run_gui()
