"""
Configuration, constants, channel aliases, and UI styling for DesatNerd.
Part of the Metro South SleepNerd suite for clinical and research sleep physiology.
"""

APP_NAME = "DesatNerd"
APP_TITLE = "DesatNerd: Oxygen Desaturations & Hypoxic Burden"
APP_VERSION = "1.0.0"
APP_ID = "MetroSouth.SleepNerd.DesatNerd.1.0.0"

# Target / Resampling Frequencies
TARGET_SPO2_SF = 1.0  # Standardized 1 Hz analysis rate (literature standard)

# Time Window Presets for Interactive Trace Inspection
TIME_WINDOW_PRESETS = [
    ("Full Recording", 0.0),
    ("1 Hour", 3600.0),
    ("15 Minutes", 900.0),
    ("5 Minutes", 300.0),
    ("1 Minute", 60.0),
    ("30 Seconds (1 Epoch)", 30.0)
]

# Sleep Stage Simplex Mapping (0=Wake, 1=N1, 2=N2, 3=N3, 4=REM)
STAGE_NAMES = {0: "Wake", 1: "N1", 2: "N2", 3: "N3", 4: "REM"}
STAGE_COLORS = {
    0: "#c8c8c8",  # Wake (Grey)
    1: "#ffff00",  # N1 (Yellow)
    2: "#008000",  # N2 (Green)
    3: "#008080",  # N3 (Turquoise)
    4: "#800000"   # REM (Dark Red)
}

# Channel Name Aliases across Manufacturers
CHANNEL_ALIASES = {
    'SpO2': [
        'spo2', 'sao2', 'oxy', 'o2 sat', 'sp02', 'pulse oximetry',
        'pleth_spo2', 'spo2_bb', 'o2', 'oximeter', 'sat', 'saturation',
        'spo2_rem', 'oximeter spo2', 'spo2 raw', 'pulseox', 'oxygen'
    ],
    'Pulse': [
        'pulse', 'pulse rate', 'pr', 'hr', 'heart rate', 'bpm',
        'pleth_pulse', 'pulse_ox', 'oximeter pulse', 'cardiac'
    ],
    'Pleth': [
        'pleth', 'plethysmogram', 'ppg', 'pulse wave'
    ]
}

# CSV Column Name Aliases (Nonin, Nellcor, Masimo, etc.)
CSV_COLUMN_ALIASES = {
    'SpO2': ['spo2', '%spo2', 'sao2', 'o2', 'sat', 'saturation', 'oxygen', 'oximeter', '% spo2'],
    'Pulse': ['pulse', 'pulse rate', 'pr', 'hr', 'heart rate', 'bpm', 'pr (bpm)', 'pulse (bpm)'],
    'Time': ['time', 'timestamp', 'date/time', 'date_time', 'elapsed', 'seconds', 'sec', 't(s)']
}

# Analysis Default Settings
DEFAULT_SETTINGS = {
    'threshold': 3.0,               # Desaturation drop threshold (3.0% or 4.0%)
    'min_duration': 5.0,            # Minimum desaturation duration (seconds)
    'max_duration': 120.0,          # Maximum desaturation duration (seconds)
    'baseline_window_sec': 300.0,   # Rolling baseline quantile window (seconds)
    'baseline_quantile': 0.98,      # Rolling baseline quantile (0.98 standard)
    'artifact_drop_below': 50.0,    # Artifact threshold (< 50% SpO2)
    'artifact_jump_rate': 8.0,      # Artifact jump threshold (% per second)
    'artifact_pad_sec': 2.0,        # Padding around detected artifacts (seconds)
    'hb_algorithm': 'all',          # 'all', 'azarbarzin', 'redta', 'kulkas'
    'analysis_window': 'TRT',       # 'TRT' (Total Recording Time), 'TST' (Total Sleep Time)
    'export_events_csv': True,      # Whether to export individual event CSVs
    'batch_append_csv': True,       # Whether to append to single master batch CSV
}

# UI Palette and Stylesheet
APP_STYLESHEET = """
QMainWindow#AppWindow, QWidget#CentralWidget { 
    background-color: #f5faff; 
}
QWidget { 
    font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif; 
    font-size: 10pt; 
    color: #222222;
}
QGroupBox { 
    background-color: white; 
    border: 1px solid #d0d0d0; 
    border-radius: 8px; 
    margin-top: 15px; 
    font-weight: bold; 
    color: #11417f; 
}
QGroupBox::title { 
    subcontrol-origin: margin; 
    subcontrol-position: top left; 
    padding: 0 5px; 
    left: 10px; 
    top: 0px; 
}
QFrame.StatBox { 
    background-color: #e6f2ff; 
    border: 1px solid #b0c4de; 
    border-radius: 10px; 
}
QFrame.StatBox:hover { 
    border: 1px solid #11417f; 
    background-color: #f0f7ff; 
}
QLabel.StatTitle { 
    color: #555555; 
    font-size: 9pt; 
    font-weight: bold; 
}
QLabel.StatValue { 
    color: #11417f; 
    font-size: 13pt; 
    font-weight: 800; 
}
QLabel.StatValue#RedValue { 
    color: #d62728; 
    font-size: 15pt; 
}
QPushButton { 
    background-color: #e6f2ff; 
    border: 1px solid #b0c4de; 
    border-radius: 6px; 
    padding: 8px 12px; 
    font-weight: bold; 
    color: #11417f;
}
QPushButton:hover { 
    background-color: #d0e7ff; 
    border: 1px solid #3399ff; 
}
QPushButton:pressed { 
    background-color: #b8dcff; 
}
QPushButton:disabled { 
    background-color: #f0f0f0; 
    color: #999999; 
    border-color: #dddddd; 
}
QPushButton#RunButton { 
    background-color: #2ca02c; 
    color: white; 
    padding: 13px; 
    font-size: 11pt; 
    border: none; 
    border-radius: 6px; 
    font-weight: bold; 
}
QPushButton#RunButton:hover { 
    background-color: #258825; 
}
QPushButton#RunButton:pressed { 
    background-color: #1e6e1e; 
}
QPushButton#CancelButton { 
    background-color: #d62728; 
    color: white; 
    padding: 10px; 
    border: none; 
    border-radius: 6px; 
    font-weight: bold; 
}
QPushButton#CancelButton:hover { 
    background-color: #b51f20; 
}
QPushButton#NavButton {
    background-color: #ffffff;
    border: 1px solid #b0c4de;
    padding: 5px 10px;
    font-size: 9pt;
}
QPushButton#NavButton:hover {
    background-color: #e6f2ff;
}
QTableWidget { 
    background-color: white; 
    gridline-color: #e0e0e0; 
    border: 1px solid #d0d0d0; 
    alternate-background-color: #fbfdff;
    selection-background-color: #cfe4ff;
    selection-color: #11417f;
}
QHeaderView::section { 
    background-color: #f0f7ff; 
    font-weight: bold; 
    border: 1px solid #d0d0d0; 
    color: #11417f; 
    padding: 5px;
}
QProgressBar { 
    border: 1px solid #bbb; 
    border-radius: 5px; 
    text-align: center; 
    height: 20px; 
    background-color: white; 
    font-weight: bold;
}
QProgressBar::chunk { 
    background-color: #2ca02c; 
    width: 10px; 
}
QProgressBar#BatchProgress::chunk { 
    background-color: #11417f; 
}
QTabWidget::pane { 
    border: 1px solid #d0d0d0; 
    background: white; 
    border-radius: 4px; 
}
QTabBar::tab { 
    background: #e6f2ff; 
    border: 1px solid #b0c4de; 
    padding: 8px 16px; 
    border-top-left-radius: 4px; 
    border-top-right-radius: 4px; 
    margin-right: 2px; 
    color: #11417f;
    font-weight: bold;
}
QTabBar::tab:selected { 
    background: white; 
    border-bottom-color: white; 
    font-weight: bold; 
    color: #11417f; 
}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    background-color: white;
    border: 1px solid #b0c4de;
    border-radius: 4px;
    padding: 5px;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {
    border: 1px solid #11417f;
}
QSlider::groove:horizontal {
    border: 1px solid #b0c4de;
    background: white;
    height: 8px;
    border-radius: 4px;
}
QSlider::sub-page:horizontal {
    background: #11417f;
    border-radius: 4px;
}
QSlider::handle:horizontal {
    background: #2ca02c;
    border: 1px solid #1e6e1e;
    width: 16px;
    margin-top: -5px;
    margin-bottom: -5px;
    border-radius: 8px;
}
QSlider::handle:horizontal:hover {
    background: #39cc39;
}
QTextEdit#LogConsole {
    background-color: #1e222b;
    color: #e6edf3;
    font-family: "Consolas", "Courier New", monospace;
    font-size: 9.5pt;
    border: 1px solid #b0c4de;
    border-radius: 6px;
}
"""
