from __future__ import annotations
"""
Graphical User Interface for desatNerd: Oxygen Desaturations & Hypoxic Burden Analyzer
Features:
  - SleepNerd clinical visual design (#f5faff background, #11417f headers, #e6f2ff StatBoxes)
  - SleepNerd icon at the top of the left sidebar & window title / taskbar
  - Multi-scale Interactive Oximetry Trace:
      * Preset inspection windows: Full Recording, 1 Hour, 15 Minutes, 5 Minutes, 1 Minute, 30 Seconds (1 Epoch)
      * Navigation controls: Previous / Next window, Start / End buttons
      * Time / Epoch slider for fluid continuous timeline scrolling
      * Dual-plot display: detailed zoomable SpO2 trace with hypnogram banner + full recording overview minimap
  - Compumedics XML stage integration (<study-name>.edf.XML) with TST/SPT accounting
  - Side-by-side literature hypoxic burden comparison (Azarbarzin, REDTA, Kulkas)
"""

import os
import sys
import subprocess
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

try:
    from PySide6.QtCore import Qt, QUrl
    from PySide6.QtGui import QAction, QColor, QDesktopServices, QFont, QIcon, QPixmap
    from PySide6.QtWidgets import (
        QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout,
        QFrame, QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel,
        QLineEdit, QMainWindow, QMessageBox, QProgressBar, QPushButton,
        QSizePolicy, QSlider, QSpinBox, QSplitter, QTabWidget, QTableWidget,
        QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget
    )
    PYSIDE6_AVAILABLE = True
except ImportError:
    PYSIDE6_AVAILABLE = False

try:
    import matplotlib
    matplotlib.use("QtAgg")
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
    from matplotlib.backends.backend_qtagg import NavigationToolbar2QT as NavigationToolbar
    from matplotlib.figure import Figure
    from matplotlib.patches import Rectangle
    MATPLOTLIB_AVAILABLE = True
except Exception:
    MATPLOTLIB_AVAILABLE = False

import numpy as np

from config import (
    APP_NAME, APP_STYLESHEET, APP_TITLE, DEFAULT_SETTINGS,
    STAGE_COLORS, STAGE_NAMES, TIME_WINDOW_PRESETS
)
from worker import AnalysisWorker


def resource_path(relative_path: str) -> str:
    """Get absolute path to resource, works for dev and for PyInstaller."""
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)


class MainWindow(QMainWindow if PYSIDE6_AVAILABLE else object):
    def __init__(self):
        if not PYSIDE6_AVAILABLE:
            raise RuntimeError("PySide6 is required to run the GUI. Please install PySide6.")
        super().__init__()
        self.setObjectName("AppWindow")
        self.setWindowTitle(APP_TITLE)
        self.resize(1380, 920)

        # Set Window Icon
        icon_path = resource_path(os.path.join("assets", "SleepNerd.ico"))
        if not os.path.exists(icon_path):
            alt_icon = os.path.join(os.path.dirname(__file__), "assets", "SleepNerd.ico")
            if os.path.exists(alt_icon):
                icon_path = alt_icon
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        self.is_batch_mode = False
        self.worker: Optional[AnalysisWorker] = None
        self.current_result: Optional[Dict[str, Any]] = None
        self.batch_results: List[Dict[str, Any]] = []

        # Interactive Trace View State
        self.current_window_sec = 0.0  # 0.0 means Full Recording
        self.current_start_sec = 0.0

        self.apply_styles()
        self.create_menu_bar()
        self.setup_ui()

    def apply_styles(self):
        self.setStyleSheet(APP_STYLESHEET)

    def create_menu_bar(self):
        menubar = self.menuBar()

        file_menu = menubar.addMenu("File")
        act_open_file = QAction("Open Single Oximetry File...", self)
        act_open_file.triggered.connect(self.browse_input_file)
        file_menu.addAction(act_open_file)

        act_open_folder = QAction("Open Batch Folder...", self)
        act_open_folder.triggered.connect(self.browse_input_folder)
        file_menu.addAction(act_open_folder)

        act_open_out = QAction("Open Output Directory", self)
        act_open_out.triggered.connect(self.open_output_folder_in_explorer)
        file_menu.addAction(act_open_out)

        file_menu.addSeparator()
        act_exit = QAction("Exit", self)
        act_exit.triggered.connect(self.close)
        file_menu.addAction(act_exit)

        settings_menu = menubar.addMenu("Analysis Settings")
        self.act_thresh_3 = QAction("3% Desaturation Threshold", self, checkable=True, checked=True)
        self.act_thresh_4 = QAction("4% Desaturation Threshold", self, checkable=True)
        self.act_thresh_3.triggered.connect(lambda: self.set_threshold(3.0))
        self.act_thresh_4.triggered.connect(lambda: self.set_threshold(4.0))
        settings_menu.addAction(self.act_thresh_3)
        settings_menu.addAction(self.act_thresh_4)
        settings_menu.addSeparator()

        self.act_win_spt = QAction("Window: Sleep Period Time (SPT: Onset to Offset)", self, checkable=True, checked=True)
        self.act_win_tst = QAction("Window: Total Sleep Time (TST: Sleep Epochs Only)", self, checkable=True)
        self.act_win_trt = QAction("Window: Total Recording Time (TRT: Full Study)", self, checkable=True)
        self.act_win_spt.triggered.connect(lambda: self.set_window("SPT"))
        self.act_win_tst.triggered.connect(lambda: self.set_window("TST"))
        self.act_win_trt.triggered.connect(lambda: self.set_window("TRT"))
        settings_menu.addAction(self.act_win_spt)
        settings_menu.addAction(self.act_win_tst)
        settings_menu.addAction(self.act_win_trt)
        settings_menu.addSeparator()

        area_menu = settings_menu.addMenu("Area Integration Method")
        self.act_area_trap = QAction("Trapezoidal Rule (Linear / 1st-Order)", self, checkable=True, checked=True)
        self.act_area_nc = QAction("Newton-Cotes Method (Simpson / 2nd-Order)", self, checkable=True)
        self.act_area_trap.triggered.connect(lambda: self.set_area_method("Trapezoidal"))
        self.act_area_nc.triggered.connect(lambda: self.set_area_method("Newton-Cotes"))
        area_menu.addAction(self.act_area_trap)
        area_menu.addAction(self.act_area_nc)

        help_menu = menubar.addMenu("Help")
        act_user_guide = QAction("User Guide & Methodology", self)
        act_user_guide.triggered.connect(self.show_methodology_dialog)
        help_menu.addAction(act_user_guide)
        act_about = QAction("About desatNerd", self)
        act_about.triggered.connect(self.show_about_dialog)
        help_menu.addAction(act_about)

    def set_threshold(self, val: float):
        if val == 3.0:
            self.act_thresh_3.setChecked(True)
            self.act_thresh_4.setChecked(False)
            self.combo_thresh.setCurrentText("3% SpO2 Drop")
        else:
            self.act_thresh_3.setChecked(False)
            self.act_thresh_4.setChecked(True)
            self.combo_thresh.setCurrentText("4% SpO2 Drop")

    def set_window(self, win: str):
        self.act_win_spt.setChecked(win == "SPT")
        self.act_win_tst.setChecked(win == "TST")
        self.act_win_trt.setChecked(win == "TRT")
        if win == "SPT":
            self.combo_win.setCurrentText("SPT (Sleep Period Time: Onset to Offset)")
        elif win == "TST":
            self.combo_win.setCurrentText("TST (Total Sleep Time: Sleep Epochs Only)")
        else:
            self.combo_win.setCurrentText("TRT (Total Recording Time: Full Study)")

    def set_area_method(self, method: str):
        is_nc = "newton" in method.lower() or "cotes" in method.lower()
        self.act_area_trap.setChecked(not is_nc)
        self.act_area_nc.setChecked(is_nc)
        if is_nc:
            self.combo_area.setCurrentText("Newton-Cotes (Simpson)")
        else:
            self.combo_area.setCurrentText("Trapezoidal (Linear)")

    def on_area_combo_changed(self, text: str):
        if "newton" in text.lower() or "cotes" in text.lower():
            self.set_area_method("Newton-Cotes")
        else:
            self.set_area_method("Trapezoidal")

    def setup_ui(self):
        central_widget = QWidget()
        central_widget.setObjectName("CentralWidget")
        self.setCentralWidget(central_widget)

        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(18)

        # ==========================================
        # LEFT SIDEBAR (Width: 320px)
        # ==========================================
        sidebar = QVBoxLayout()
        sidebar.setSpacing(10)

        # SleepNerd Icon at Top of Sidebar
        logo_lbl = QLabel()
        logo_lbl.setAlignment(Qt.AlignCenter)
        logo_lbl.setMinimumHeight(130)

        icon_img_path = resource_path(os.path.join("assets", "SleepNerd_icon.png"))
        if not os.path.exists(icon_img_path):
            alt_img = os.path.join(os.path.dirname(__file__), "assets", "SleepNerd_icon.png")
            if os.path.exists(alt_img):
                icon_img_path = alt_img

        if os.path.exists(icon_img_path):
            pixmap = QPixmap(icon_img_path)
            logo_lbl.setPixmap(pixmap.scaled(200, 200, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            logo_lbl.setText("SleepNerd")
            logo_lbl.setStyleSheet("font-size: 16pt; font-weight: bold; color: #11417f;")
        sidebar.addWidget(logo_lbl)

        # Batch Mode Checkbox
        self.chk_batch = QCheckBox("Enable Batch Processing Mode")
        self.chk_batch.setStyleSheet("font-weight: bold; color: #11417f; font-size: 9.5pt;")
        self.chk_batch.stateChanged.connect(self.toggle_batch_mode)
        sidebar.addWidget(self.chk_batch)

        # File Selection GroupBox
        grp_io = QGroupBox("File & Directory Selection")
        io_lay = QVBoxLayout()
        io_lay.setContentsMargins(10, 16, 10, 8)
        io_lay.setSpacing(5)

        self.lbl_input = QLabel("Input Oximetry File:")
        self.input_path = QLineEdit()
        self.input_path.setPlaceholderText("Select EDF or CSV file...")
        self.btn_browse = QPushButton("Browse File")
        self.btn_browse.clicked.connect(self.browse_input)

        io_lay.addWidget(self.lbl_input)
        io_lay.addWidget(self.input_path)
        io_lay.addWidget(self.btn_browse)
        io_lay.addSpacing(4)

        io_lay.addWidget(QLabel("Output Directory (CSV Results):"))
        self.out_path = QLineEdit()
        default_out = os.path.join(os.getcwd(), "oximetry_results")
        self.out_path.setText(default_out)
        btn_out = QPushButton("Browse Output Folder")
        btn_out.clicked.connect(self.browse_output_folder)

        io_lay.addWidget(self.out_path)
        io_lay.addWidget(btn_out)
        grp_io.setLayout(io_lay)
        sidebar.addWidget(grp_io)

        # Analysis Parameters GroupBox
        grp_params = QGroupBox("Analysis Parameters")
        params_lay = QVBoxLayout()
        params_lay.setContentsMargins(10, 16, 10, 8)
        params_lay.setSpacing(5)

        params_lay.addWidget(QLabel("Desaturation Threshold:"))
        self.combo_thresh = QComboBox()
        self.combo_thresh.addItems(["3% SpO2 Drop", "4% SpO2 Drop"])
        self.combo_thresh.currentTextChanged.connect(self.on_thresh_combo_changed)
        params_lay.addWidget(self.combo_thresh)

        params_lay.addWidget(QLabel("Baseline Window:"))
        self.combo_baseline = QComboBox()
        self.combo_baseline.addItems(["300 seconds (Standard)", "180 seconds", "600 seconds"])
        params_lay.addWidget(self.combo_baseline)

        params_lay.addWidget(QLabel("Analysis Time Window:"))
        self.combo_win = QComboBox()
        self.combo_win.addItems([
            "SPT (Sleep Period Time: Onset to Offset)",
            "TST (Total Sleep Time: Sleep Epochs Only)",
            "TRT (Total Recording Time: Full Study)"
        ])
        self.combo_win.setCurrentText("SPT (Sleep Period Time: Onset to Offset)")
        self.combo_win.currentTextChanged.connect(self.on_win_combo_changed)
        params_lay.addWidget(self.combo_win)

        params_lay.addWidget(QLabel("Area Integration Method:"))
        self.combo_area = QComboBox()
        self.combo_area.addItems([
            "Trapezoidal (Linear)",
            "Newton-Cotes (Simpson)"
        ])
        self.combo_area.setCurrentText("Trapezoidal (Linear)")
        self.combo_area.setToolTip("Numerical quadrature algorithm used to calculate desaturation and hypoxic burden areas.")
        self.combo_area.currentTextChanged.connect(self.on_area_combo_changed)
        params_lay.addWidget(self.combo_area)

        grp_params.setLayout(params_lay)
        sidebar.addWidget(grp_params)

        sidebar.addStretch()

        # Batch Progress Bar
        self.lbl_batch_progress = QLabel("Batch Progress:")
        self.pbar_batch = QProgressBar()
        self.pbar_batch.setObjectName("BatchProgress")
        self.pbar_batch.setValue(0)
        self.lbl_batch_progress.setVisible(False)
        self.pbar_batch.setVisible(False)
        sidebar.addWidget(self.lbl_batch_progress)
        sidebar.addWidget(self.pbar_batch)

        # File Progress Bar
        self.lbl_file_progress = QLabel("File Progress:")
        self.pbar_file = QProgressBar()
        self.pbar_file.setValue(0)
        sidebar.addWidget(self.lbl_file_progress)
        sidebar.addWidget(self.pbar_file)

        # Action Buttons
        self.btn_run = QPushButton("START ANALYSIS")
        self.btn_run.setObjectName("RunButton")
        self.btn_run.setCursor(Qt.PointingHandCursor)
        self.btn_run.clicked.connect(self.start_analysis)
        sidebar.addWidget(self.btn_run)

        self.btn_cancel = QPushButton("CANCEL")
        self.btn_cancel.setObjectName("CancelButton")
        self.btn_cancel.setVisible(False)
        self.btn_cancel.clicked.connect(self.cancel_analysis)
        sidebar.addWidget(self.btn_cancel)

        self.btn_help = QPushButton("User Guide")
        self.btn_help.setToolTip("Open the comprehensive PDF User Guide in the assets folder")
        self.btn_help.setStyleSheet("background-color: #f0f4f8; color: #555555; padding: 6px; border: 1px solid #d0d0d0;")
        self.btn_help.clicked.connect(self.show_methodology_dialog)
        sidebar.addWidget(self.btn_help)

        sidebar_container = QWidget()
        sidebar_container.setLayout(sidebar)
        sidebar_container.setFixedWidth(320)
        main_layout.addWidget(sidebar_container)

        # ==========================================
        # RIGHT DASHBOARD AREA
        # ==========================================
        dashboard_layout = QVBoxLayout()
        dashboard_layout.setSpacing(12)

        # Top Section: 12 Elevated StatBox Cards
        self.grp_metrics = QGroupBox("Key Clinical Metrics Summary")
        self.grp_metrics.setFixedHeight(275)
        grid_metrics = QGridLayout()
        grid_metrics.setContentsMargins(12, 22, 12, 8)
        grid_metrics.setSpacing(8)

        self.box_dur, self.val_dur = self.create_stat_box("Duration / TST", "--")
        self.box_mean, self.val_mean = self.create_stat_box("Mean SpO2 (%)", "--")
        self.box_min, self.val_min = self.create_stat_box("Min SpO2 (%)", "--", is_red=True)
        self.box_base, self.val_base = self.create_stat_box("Baseline SpO2 (%)", "--")

        self.box_odi3, self.val_odi3 = self.create_stat_box("ODI (3% Drop)", "--", is_red=True)
        self.box_odi4, self.val_odi4 = self.create_stat_box("ODI (4% Drop)", "--", is_red=True)
        self.box_t90_pct, self.val_t90_pct = self.create_stat_box("T90 (% Time <90%)", "--", is_red=True)
        self.box_t90_min, self.val_t90_min = self.create_stat_box("T90 (Minutes <90%)", "--")

        self.box_hb_azar, self.val_hb_azar = self.create_stat_box("Azarbarzin HB (%min/h)", "--", is_red=True)
        self.box_redta, self.val_redta = self.create_stat_box("REDTA Rate (%min/h)", "--")
        self.box_kulkas, self.val_kulkas = self.create_stat_box("Kulkas DesSev (%min/h)", "--")
        self.box_slopes, self.val_slopes = self.create_stat_box("Fall / Recov Slope (%/s)", "-- / --")

        grid_metrics.addWidget(self.box_dur, 0, 0)
        grid_metrics.addWidget(self.box_mean, 0, 1)
        grid_metrics.addWidget(self.box_min, 0, 2)
        grid_metrics.addWidget(self.box_base, 0, 3)

        grid_metrics.addWidget(self.box_odi3, 1, 0)
        grid_metrics.addWidget(self.box_odi4, 1, 1)
        grid_metrics.addWidget(self.box_t90_pct, 1, 2)
        grid_metrics.addWidget(self.box_t90_min, 1, 3)

        grid_metrics.addWidget(self.box_hb_azar, 2, 0)
        grid_metrics.addWidget(self.box_redta, 2, 1)
        grid_metrics.addWidget(self.box_kulkas, 2, 2)
        grid_metrics.addWidget(self.box_slopes, 2, 3)

        self.grp_metrics.setLayout(grid_metrics)
        dashboard_layout.addWidget(self.grp_metrics)

        # Middle Section: Tabbed Content Views
        self.tab_widget = QTabWidget()

        # Tab 1: Interactive Oximetry Trace (Multi-Scale)
        self.tab_viewer = QWidget()
        lay_viewer = QVBoxLayout(self.tab_viewer)
        lay_viewer.setContentsMargins(8, 8, 8, 8)
        lay_viewer.setSpacing(6)

        # Navigation & Interval Control Bar
        ctrl_bar = QHBoxLayout()
        ctrl_bar.setSpacing(8)

        ctrl_bar.addWidget(QLabel("<b>Window Interval:</b>"))
        self.combo_interval = QComboBox()
        for label, _ in TIME_WINDOW_PRESETS:
            self.combo_interval.addItem(label)
        self.combo_interval.setCurrentText("Full Recording")
        self.combo_interval.currentTextChanged.connect(self.on_interval_preset_changed)
        ctrl_bar.addWidget(self.combo_interval)

        ctrl_bar.addSpacing(10)
        self.btn_nav_start = QPushButton("⏮ Start")
        self.btn_nav_start.setObjectName("NavButton")
        self.btn_nav_start.clicked.connect(self.nav_to_start)
        ctrl_bar.addWidget(self.btn_nav_start)

        self.btn_nav_prev = QPushButton("◀ Prev Window")
        self.btn_nav_prev.setObjectName("NavButton")
        self.btn_nav_prev.clicked.connect(self.nav_prev_window)
        ctrl_bar.addWidget(self.btn_nav_prev)

        self.btn_nav_next = QPushButton("Next Window ▶")
        self.btn_nav_next.setObjectName("NavButton")
        self.btn_nav_next.clicked.connect(self.nav_next_window)
        ctrl_bar.addWidget(self.btn_nav_next)

        self.btn_nav_end = QPushButton("End ⏭")
        self.btn_nav_end.setObjectName("NavButton")
        self.btn_nav_end.clicked.connect(self.nav_to_end)
        ctrl_bar.addWidget(self.btn_nav_end)

        ctrl_bar.addStretch()

        self.lbl_time_window_info = QLabel("Position: Full Study (0.0 - 0.0 min)")
        self.lbl_time_window_info.setStyleSheet("font-weight: bold; color: #11417f; font-size: 9.5pt;")
        ctrl_bar.addWidget(self.lbl_time_window_info)

        lay_viewer.addLayout(ctrl_bar)

        # Continuous Timeline / Epoch Slider
        slider_lay = QHBoxLayout()
        slider_lay.addWidget(QLabel("Timeline Pan:"))
        self.time_slider = QSlider(Qt.Horizontal)
        self.time_slider.setRange(0, 1000)
        self.time_slider.setValue(0)
        self.time_slider.valueChanged.connect(self.on_slider_moved)
        slider_lay.addWidget(self.time_slider)
        lay_viewer.addLayout(slider_lay)

        # Embedded Dual Matplotlib Canvas
        if MATPLOTLIB_AVAILABLE:
            self.fig = Figure(figsize=(9, 4.5), dpi=100, facecolor='#ffffff')
            self.canvas = FigureCanvas(self.fig)
            self.canvas.mpl_connect('button_press_event', self.on_canvas_click)
            lay_viewer.addWidget(self.canvas)

            # Two Subplots: Top = Detailed Zoom View (80%), Bottom = Overview Minimap (20%)
            gs = self.fig.add_gridspec(2, 1, height_ratios=[4, 1], hspace=0.35)
            self.ax_detail = self.fig.add_subplot(gs[0])
            self.ax_overview = self.fig.add_subplot(gs[1])

            self.ax_detail.set_title("Detailed SpO2 Window", color="#11417f", fontweight="bold", fontsize=10)
            self.ax_detail.set_ylabel("SpO2 (%)", fontweight="bold")
            self.ax_detail.set_ylim(50, 102)
            self.ax_detail.grid(True, linestyle="--", alpha=0.4)

            self.ax_overview.set_ylabel("Overview", fontsize=8)
            self.ax_overview.set_xlabel("Elapsed Time (Minutes)", fontweight="bold")
            self.ax_overview.set_ylim(50, 102)
            self.ax_overview.grid(True, linestyle=":", alpha=0.3)
            self.fig.tight_layout()
        else:
            lay_viewer.addWidget(QLabel("Matplotlib not available. Install matplotlib to view interactive traces."))

        self.tab_widget.addTab(self.tab_viewer, "Interactive Oximetry Trace")

        # Tab 2: Desaturation Morphology Table
        self.tab_morphology = QWidget()
        lay_morph = QVBoxLayout(self.tab_morphology)
        self.table_events = QTableWidget(0, 15)
        self.table_events.setHorizontalHeaderLabels([
            "Event #", "Start (s)", "End (s)", "Duration (s)", "Fall Dur (s)", "Recov Dur (s)",
            "Baseline (%)", "Nadir (%)", "Depth (%)", "Fall Slope (%/s)", "Recov Slope (%/s)",
            "Fall Area (%·min)", "Recov Area (%·min)", "Total Area (%·min)", "Sleep State"
        ])
        self.table_events.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table_events.horizontalHeader().setStretchLastSection(True)
        self.table_events.verticalHeader().setVisible(False)
        self.table_events.setSelectionBehavior(QTableWidget.SelectRows)
        self.table_events.setAlternatingRowColors(True)
        self.table_events.cellClicked.connect(self.on_event_table_row_clicked)
        lay_morph.addWidget(self.table_events)
        self.tab_widget.addTab(self.tab_morphology, "Desaturations & Morphology")

        # Tab 3: Hypoxic Burden Comparison
        self.tab_hb_compare = QWidget()
        lay_compare = QVBoxLayout(self.tab_hb_compare)
        self.table_compare = QTableWidget(0, 5)
        self.table_compare.setHorizontalHeaderLabels([
            "Method / Algorithm", "Mathematical Definition", "Baseline Reference", "Current Value", "Literature Benchmark"
        ])
        self.table_compare.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table_compare.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table_compare.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table_compare.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table_compare.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table_compare.verticalHeader().setVisible(False)
        self.table_compare.setAlternatingRowColors(True)
        lay_compare.addWidget(self.table_compare)
        self.tab_widget.addTab(self.tab_hb_compare, "Hypoxic Burden Comparison")

        # Tab 4: Batch Processing Queue
        self.tab_batch = QWidget()
        lay_batch = QVBoxLayout(self.tab_batch)
        self.table_batch_queue = QTableWidget(0, 8)
        self.table_batch_queue.setHorizontalHeaderLabels([
            "Filename", "Device Flavor", "Duration", "ODI (3%)", "T90 (%)", "Azarbarzin HB", "Kulkas DesSev", "Status"
        ])
        self.table_batch_queue.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for c in range(1, 8):
            self.table_batch_queue.horizontalHeader().setSectionResizeMode(c, QHeaderView.ResizeToContents)
        self.table_batch_queue.verticalHeader().setVisible(False)
        self.table_batch_queue.setAlternatingRowColors(True)
        lay_batch.addWidget(self.table_batch_queue)
        self.tab_widget.addTab(self.tab_batch, "Batch Processing Queue")

        dashboard_layout.addWidget(self.tab_widget, 3)

        # Bottom Section: Processing Log Console
        grp_log = QGroupBox("Processing Log & Diagnostics")
        lay_log = QVBoxLayout()
        lay_log.setContentsMargins(10, 16, 10, 8)
        self.txt_log = QTextEdit()
        self.txt_log.setObjectName("LogConsole")
        self.txt_log.setReadOnly(True)
        self.txt_log.setFixedHeight(125)
        lay_log.addWidget(self.txt_log)
        grp_log.setLayout(lay_log)
        dashboard_layout.addWidget(grp_log, 1)

        main_layout.addLayout(dashboard_layout)
        self.log(f"{APP_TITLE} initialized. Select an EDF or oximetry CSV file to begin.")

    def create_stat_box(self, title: str, default_val: str, is_red: bool = False) -> Tuple[QFrame, QLabel]:
        frame = QFrame()
        frame.setProperty("class", "StatBox")
        frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        lay = QVBoxLayout()
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(2)

        lbl_title = QLabel(title)
        lbl_title.setProperty("class", "StatTitle")
        lbl_title.setAlignment(Qt.AlignCenter)

        lbl_val = QLabel(default_val)
        lbl_val.setProperty("class", "StatValue")
        if is_red:
            lbl_val.setObjectName("RedValue")
        lbl_val.setAlignment(Qt.AlignCenter)

        lay.addWidget(lbl_title)
        lay.addWidget(lbl_val)
        frame.setLayout(lay)
        return frame, lbl_val

    def log(self, text: str):
        now_str = datetime.now().strftime("%H:%M:%S")
        self.txt_log.append(f"[{now_str}] {text}")
        self.txt_log.verticalScrollBar().setValue(self.txt_log.verticalScrollBar().maximum())

    def toggle_batch_mode(self, state: int):
        self.is_batch_mode = (state == 2)
        if self.is_batch_mode:
            self.lbl_input.setText("Input Batch Directory:")
            self.btn_browse.setText("Browse Batch Folder")
            self.input_path.setPlaceholderText("Select folder containing recordings...")
            self.lbl_batch_progress.setVisible(True)
            self.pbar_batch.setVisible(True)
            self.tab_widget.setCurrentWidget(self.tab_batch)
        else:
            self.lbl_input.setText("Input Oximetry File:")
            self.btn_browse.setText("Browse File")
            self.input_path.setPlaceholderText("Select EDF or CSV file...")
            self.lbl_batch_progress.setVisible(False)
            self.pbar_batch.setVisible(False)
            self.tab_widget.setCurrentWidget(self.tab_viewer)

    def on_thresh_combo_changed(self, text: str):
        val = 4.0 if "4%" in text else 3.0
        self.set_threshold(val)

    def on_win_combo_changed(self, text: str):
        if "SPT" in text:
            val = "SPT"
        elif "TST" in text:
            val = "TST"
        else:
            val = "TRT"
        self.set_window(val)

    def browse_input(self):
        if self.is_batch_mode:
            self.browse_input_folder()
        else:
            self.browse_input_file()

    def browse_input_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Oximetry Recording",
            os.getcwd(),
            "Oximetry Files (*.edf *.rec *.bdf *.csv *.txt *.tsv *.dat);;EDF Files (*.edf *.rec);;CSV/Text Files (*.csv *.txt *.tsv);;All Files (*.*)"
        )
        if path:
            self.input_path.setText(path)
            self.log(f"Selected file: {os.path.basename(path)}")

    def browse_input_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Folder Containing Recordings", os.getcwd())
        if folder:
            self.input_path.setText(folder)
            self.log(f"Selected batch folder: {folder}")
            self.populate_batch_queue(folder)

    def browse_output_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Output Directory", self.out_path.text())
        if folder:
            self.out_path.setText(folder)
            self.log(f"Selected output directory: {folder}")

    def open_output_folder_in_explorer(self):
        out_dir = self.out_path.text()
        if os.path.exists(out_dir):
            QDesktopServices.openUrl(QUrl.fromLocalFile(out_dir))
        else:
            QMessageBox.information(self, "Info", f"Output directory does not exist yet: {out_dir}")

    def populate_batch_queue(self, folder: str):
        valid_exts = {'.edf', '.rec', '.bdf', '.csv', '.txt', '.tsv', '.dat'}
        files = [os.path.join(folder, f) for f in os.listdir(folder) if os.path.splitext(f)[1].lower() in valid_exts]
        self.table_batch_queue.setRowCount(len(files))
        for r, fpath in enumerate(sorted(files)):
            fname = os.path.basename(fpath)
            ext = os.path.splitext(fname)[1].upper()
            self.table_batch_queue.setItem(r, 0, QTableWidgetItem(fname))
            self.table_batch_queue.setItem(r, 1, QTableWidgetItem(ext))
            self.table_batch_queue.setItem(r, 2, QTableWidgetItem("--"))
            self.table_batch_queue.setItem(r, 3, QTableWidgetItem("--"))
            self.table_batch_queue.setItem(r, 4, QTableWidgetItem("--"))
            self.table_batch_queue.setItem(r, 5, QTableWidgetItem("--"))
            self.table_batch_queue.setItem(r, 6, QTableWidgetItem("--"))
            item_status = QTableWidgetItem("Queued")
            item_status.setForeground(QColor("#555555"))
            self.table_batch_queue.setItem(r, 7, item_status)

        self.log(f"Queued {len(files)} files in batch table.")

    def start_analysis(self):
        target = self.input_path.text().strip()
        if not target or not os.path.exists(target):
            QMessageBox.warning(self, "Input Error", "Please select a valid input file or directory first.")
            return

        out_dir = self.out_path.text().strip()
        if not out_dir:
            out_dir = os.path.join(os.getcwd(), "oximetry_results")
            self.out_path.setText(out_dir)

        if self.is_batch_mode and os.path.isdir(target):
            valid_exts = {'.edf', '.rec', '.bdf', '.csv', '.txt', '.tsv', '.dat'}
            file_list = [os.path.join(target, f) for f in sorted(os.listdir(target)) if os.path.splitext(f)[1].lower() in valid_exts]
            if not file_list:
                QMessageBox.warning(self, "Batch Error", f"No supported oximetry files found in: {target}")
                return
        else:
            file_list = [target]

        threshold = 4.0 if "4%" in self.combo_thresh.currentText() else 3.0
        baseline_sec = 300.0
        if "180" in self.combo_baseline.currentText():
            baseline_sec = 180.0
        elif "600" in self.combo_baseline.currentText():
            baseline_sec = 600.0

        if "SPT" in self.combo_win.currentText():
            analysis_window = "SPT"
        elif "TST" in self.combo_win.currentText():
            analysis_window = "TST"
        else:
            analysis_window = "TRT"

        area_method = "Newton-Cotes" if "newton" in self.combo_area.currentText().lower() else "Trapezoidal"

        settings = {
            "threshold": threshold,
            "min_duration": DEFAULT_SETTINGS["min_duration"],
            "max_duration": DEFAULT_SETTINGS["max_duration"],
            "baseline_window_sec": baseline_sec,
            "baseline_quantile": DEFAULT_SETTINGS["baseline_quantile"],
            "analysis_window": analysis_window,
            "area_method": area_method,
            "batch_append_csv": True,
            "export_events_csv": True
        }

        self.btn_run.setEnabled(False)
        self.btn_cancel.setVisible(True)
        self.pbar_file.setValue(0)
        self.pbar_batch.setValue(0)

        self.worker = AnalysisWorker(file_list, out_dir, settings)
        self.worker.log_signal.connect(self.log)
        self.worker.progress_signal.connect(self.pbar_file.setValue)
        self.worker.batch_progress_signal.connect(self.on_batch_progress)
        self.worker.result_signal.connect(self.on_analysis_result)
        self.worker.finished_signal.connect(self.on_analysis_finished)
        self.worker.error_signal.connect(self.on_analysis_error)
        self.worker.start()

    def cancel_analysis(self):
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.log("Cancellation requested. Waiting for active file to finish...")
            self.btn_cancel.setEnabled(False)

    def on_batch_progress(self, current_idx: int, total: int):
        if total > 0:
            pct = int((current_idx / total) * 100)
            self.pbar_batch.setValue(pct)
            self.lbl_batch_progress.setText(f"Batch Progress ({current_idx}/{total}):")

    def on_analysis_result(self, result: Dict[str, Any]):
        self.current_result = result
        self.batch_results.append(result)
        self.update_stat_cards(result)
        self.populate_morphology_table(result.get("desaturation_events", []))
        self.populate_comparison_table(result)

        # Reset trace view to Full Recording
        self.current_window_sec = 0.0
        self.current_start_sec = 0.0
        self.combo_interval.setCurrentText("Full Recording")
        self.redraw_trace()
        self.update_batch_queue_row(result)

    def on_analysis_finished(self):
        self.btn_run.setEnabled(True)
        self.btn_cancel.setVisible(False)
        self.btn_cancel.setEnabled(True)
        self.log("Done! Results saved to CSV.")
        QMessageBox.information(
            self,
            "Analysis Complete",
            f"desatNerd analysis finished successfully.\nResults saved to: {self.out_path.text()}"
        )

    def on_analysis_error(self, err_text: str):
        self.log(f"[Error Handler] {err_text}")

    def update_stat_cards(self, res: Dict[str, Any]):
        dur_h = res.get("Analysis_Duration_Hours", 0.0)
        win_type = res.get("Analysis_Window_Type", "SPT")
        has_sleep = res.get("Has_Sleep_Stages", False)
        if has_sleep:
            sleep_sum = res.get("Sleep_Summary", {})
            if win_type == "SPT":
                spt_min = sleep_sum.get("SPT_Minutes", dur_h * 60)
                waso_m = sleep_sum.get("WASO_Minutes", 0)
                self.val_dur.setText(f"SPT: {spt_min:.0f}m ({dur_h:.1f}h) [WASO: {waso_m:.0f}m]")
            elif win_type == "TST":
                tst_min = sleep_sum.get("TST_Minutes", dur_h * 60)
                se_pct = sleep_sum.get("Sleep_Efficiency_pct", 0)
                self.val_dur.setText(f"TST: {tst_min:.0f}m ({dur_h:.1f}h) [SE: {se_pct:.0f}%]")
            else:
                trt_min = sleep_sum.get("TRT_Minutes", dur_h * 60)
                self.val_dur.setText(f"TRT: {trt_min:.0f}m ({dur_h:.1f}h)")
        else:
            self.val_dur.setText(f"{dur_h:.2f} h ({win_type})")

        mean_s = res.get("Mean_SpO2", 0.0)
        self.val_mean.setText(f"{mean_s:.1f}%")

        min_s = res.get("Min_SpO2", 0.0)
        self.val_min.setText(f"{min_s:.1f}%")

        base_s = res.get("Baseline_SpO2", 0.0)
        self.val_base.setText(f"{base_s:.1f}%")

        odi3 = res.get("ODI_3pct", 0.0)
        self.val_odi3.setText(f"{odi3:.1f}")

        odi4 = res.get("ODI_4pct", 0.0)
        self.val_odi4.setText(f"{odi4:.1f}")

        t90_p = res.get("T90_Percent", 0.0)
        self.val_t90_pct.setText(f"{t90_p:.1f}%")

        t90_m = res.get("T90_Minutes", 0.0)
        self.val_t90_min.setText(f"{t90_m:.1f} min")

        hb_azar = res.get("Azarbarzin_HB_pctmin_hr", 0.0)
        self.val_hb_azar.setText(f"{hb_azar:.2f}")

        redta_r = res.get("REDTA_Rate_pctmin_hr", 0.0)
        self.val_redta.setText(f"{redta_r:.2f}")

        kulkas_s = res.get("Kulkas_Total_Severity_pctmin_hr", 0.0)
        self.val_kulkas.setText(f"{kulkas_s:.2f}")

        f_slope = res.get("Mean_Fall_Slope_pct_s", 0.0)
        r_slope = res.get("Mean_Recovery_Slope_pct_s", 0.0)
        self.val_slopes.setText(f"{f_slope:.2f} / {r_slope:.2f}")

    def populate_morphology_table(self, events: List[Dict[str, Any]]):
        self.table_events.setRowCount(len(events))
        for r, ev in enumerate(events):
            self.table_events.setItem(r, 0, QTableWidgetItem(str(ev.get("Event_ID", r + 1))))
            self.table_events.setItem(r, 1, QTableWidgetItem(f"{ev.get('Start', 0.0):.1f}"))
            self.table_events.setItem(r, 2, QTableWidgetItem(f"{ev.get('End', 0.0):.1f}"))
            self.table_events.setItem(r, 3, QTableWidgetItem(f"{ev.get('Duration', 0.0):.1f}"))
            self.table_events.setItem(r, 4, QTableWidgetItem(f"{ev.get('Fall_Duration', 0.0):.1f}"))
            self.table_events.setItem(r, 5, QTableWidgetItem(f"{ev.get('Recovery_Duration', 0.0):.1f}"))
            self.table_events.setItem(r, 6, QTableWidgetItem(f"{ev.get('Baseline', 0.0):.1f}"))
            self.table_events.setItem(r, 7, QTableWidgetItem(f"{ev.get('Nadir', 0.0):.1f}"))
            self.table_events.setItem(r, 8, QTableWidgetItem(f"{ev.get('Depth', 0.0):.1f}"))
            self.table_events.setItem(r, 9, QTableWidgetItem(f"{ev.get('Fall_Slope', 0.0):.3f}"))
            self.table_events.setItem(r, 10, QTableWidgetItem(f"{ev.get('Recovery_Slope', 0.0):.3f}"))
            self.table_events.setItem(r, 11, QTableWidgetItem(f"{ev.get('Fall_Area_min', 0.0):.4f}"))
            self.table_events.setItem(r, 12, QTableWidgetItem(f"{ev.get('Recovery_Area_min', 0.0):.4f}"))
            self.table_events.setItem(r, 13, QTableWidgetItem(f"{ev.get('Total_Area_min', 0.0):.4f}"))

            is_sleep = ev.get("Is_In_Sleep", True)
            st_item = QTableWidgetItem("Sleep" if is_sleep else "Wake")
            st_item.setForeground(QColor("#27ae60" if is_sleep else "#f39c12"))
            self.table_events.setItem(r, 14, st_item)

    def populate_comparison_table(self, res: Dict[str, Any]):
        rows_data = [
            (
                "Azarbarzin Hypoxic Burden (HB)",
                "Sum of areas between pre-event baseline and SpO2 curve in search window around event termination divided by TST/TRT",
                "100s pre-event max SpO2",
                f"{res.get('Azarbarzin_HB_pctmin_hr', 0.0):.2f} %min/h",
                "CVD mortality threshold: > 53–60 %min/h (SHHS / MrOS)"
            ),
            (
                "REDTA (de Chazal et al.)",
                "Transient area from event midpoint extending 2.5 * duration against 100% baseline",
                "100.0% fixed baseline",
                f"{res.get('REDTA_Rate_pctmin_hr', 0.0):.2f} %min/h ({res.get('REDTA_pct_hours', 0.0):.3f} %h)",
                "Predicts composite cardiovascular disease events"
            ),
            (
                "Kulkas Desaturation Severity (DesSev)",
                "Sum of falling phase areas (onset to nadir) normalized per sleep/recording hour",
                "Local pre-desat baseline",
                f"{res.get('Kulkas_DesSev_pctmin_hr', 0.0):.2f} %min/h",
                "Correlates with daytime sleepiness & PVT reaction time"
            ),
            (
                "Kulkas Recovery Severity (RecSev)",
                "Sum of resaturation recovery areas (nadir to baseline) normalized per hour",
                "Local pre-desat baseline",
                f"{res.get('Kulkas_RecSev_pctmin_hr', 0.0):.2f} %min/h",
                "Reflects ventilatory drive and recovery dynamics"
            ),
            (
                "Kulkas Total Desaturation Severity",
                "Combined DesSev + RecSev (total area under baseline per hour)",
                "Local pre-desat baseline",
                f"{res.get('Kulkas_Total_Severity_pctmin_hr', 0.0):.2f} %min/h",
                "Comprehensive nocturnal hypoxic load index"
            ),
            (
                "Conventional T90",
                "Percentage of total sleep/recording time spent below 90% SpO2",
                "Fixed 90.0% threshold",
                f"{res.get('T90_Percent', 0.0):.1f}% ({res.get('T90_Minutes', 0.0):.1f} min)",
                "Clinical criterion for nocturnal hypoxemia (>10% abnormal)"
            ),
            (
                "Area Integration Quadrature",
                f"Numerical quadrature rule: {res.get('Area_Method', 'Trapezoidal')}",
                "Discrete SpO2 samples",
                f"{res.get('Area_Method', 'Trapezoidal')} Quadrature",
                "Trapezoidal (1st-order) or Newton-Cotes / Simpson (2nd-order)"
            )
        ]

        self.table_compare.setRowCount(len(rows_data))
        for r, row in enumerate(rows_data):
            for c, val in enumerate(row):
                item = QTableWidgetItem(val)
                if c == 3:
                    item.setForeground(QColor("#11417f"))
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                self.table_compare.setItem(r, c, item)

    def on_event_table_row_clicked(self, row: int, col: int):
        if not self.current_result:
            return
        events = self.current_result.get("desaturation_events", [])
        if 0 <= row < len(events):
            ev = events[row]
            center_s = (ev["Start"] + ev["End"]) / 2.0
            self.combo_interval.setCurrentText("5 Minutes")
            self.current_window_sec = 300.0
            self.current_start_sec = max(0.0, center_s - 150.0)
            self.redraw_trace()
            self.tab_widget.setCurrentWidget(self.tab_viewer)

    # ==========================================
    # MULTI-SCALE TRACE VIEWER LOGIC
    # ==========================================
    def on_interval_preset_changed(self, text: str):
        for label, dur_sec in TIME_WINDOW_PRESETS:
            if label == text:
                self.current_window_sec = dur_sec
                break
        self.redraw_trace()

    def nav_to_start(self):
        self.current_start_sec = 0.0
        self.redraw_trace()

    def nav_to_end(self):
        if not self.current_result:
            return
        total_sec = len(self.current_result.get("clean_signal", [])) / self.current_result.get("Sampling_Rate_Hz", 1.0)
        win_len = self.current_window_sec if self.current_window_sec > 0 else total_sec
        self.current_start_sec = max(0.0, total_sec - win_len)
        self.redraw_trace()

    def nav_prev_window(self):
        step = self.current_window_sec if self.current_window_sec > 0 else 300.0
        self.current_start_sec = max(0.0, self.current_start_sec - step)
        self.redraw_trace()

    def nav_next_window(self):
        if not self.current_result:
            return
        total_sec = len(self.current_result.get("clean_signal", [])) / self.current_result.get("Sampling_Rate_Hz", 1.0)
        step = self.current_window_sec if self.current_window_sec > 0 else 300.0
        win_len = self.current_window_sec if self.current_window_sec > 0 else total_sec
        max_start = max(0.0, total_sec - win_len)
        self.current_start_sec = min(max_start, self.current_start_sec + step)
        self.redraw_trace()

    def on_slider_moved(self, value: int):
        if not self.current_result:
            return
        total_sec = len(self.current_result.get("clean_signal", [])) / self.current_result.get("Sampling_Rate_Hz", 1.0)
        win_len = self.current_window_sec if self.current_window_sec > 0 else total_sec
        max_start = max(0.0, total_sec - win_len)
        self.current_start_sec = (value / 1000.0) * max_start
        self.redraw_trace(update_slider=False)

    def on_canvas_click(self, event):
        if not self.current_result or event.inaxes != self.ax_overview or event.xdata is None:
            return
        clicked_min = event.xdata
        clicked_sec = clicked_min * 60.0
        total_sec = len(self.current_result.get("clean_signal", [])) / self.current_result.get("Sampling_Rate_Hz", 1.0)
        win_len = self.current_window_sec if self.current_window_sec > 0 else total_sec

        self.current_start_sec = max(0.0, min(total_sec - win_len, clicked_sec - win_len / 2.0))
        self.redraw_trace()

    def redraw_trace(self, update_slider: bool = True):
        if not MATPLOTLIB_AVAILABLE or not self.current_result:
            return

        clean_sig = self.current_result.get("clean_signal", np.array([]))
        raw_sig = self.current_result.get("raw_signal", clean_sig)
        art_mask = self.current_result.get("artifact_mask", np.zeros(len(clean_sig), dtype=bool))
        sr = self.current_result.get("Sampling_Rate_Hz", 1.0)
        baselines = self.current_result.get("baseline_curve", np.array([]))
        sleep_epochs = self.current_result.get("sleep_epochs")
        desats = self.current_result.get("desaturation_events", [])

        if len(clean_sig) == 0:
            return

        total_sec = len(clean_sig) / sr
        time_min_full = np.linspace(0.0, total_sec / 60.0, len(clean_sig), endpoint=False)

        # Extract continuous artifact intervals (in minutes)
        art_intervals = []
        if np.any(art_mask):
            diff_art = np.diff(np.concatenate(([0], art_mask.astype(int), [0])))
            art_starts = np.where(diff_art == 1)[0]
            art_ends = np.where(diff_art == -1)[0]
            for a_s, a_e in zip(art_starts, art_ends):
                art_intervals.append((a_s / (sr * 60.0), a_e / (sr * 60.0)))

        # Determine visible window bounds
        if self.current_window_sec <= 0.0 or self.current_window_sec >= total_sec:
            w_start_sec = 0.0
            w_end_sec = total_sec
        else:
            w_start_sec = max(0.0, min(total_sec - self.current_window_sec, self.current_start_sec))
            w_end_sec = min(total_sec, w_start_sec + self.current_window_sec)

        w_start_min = w_start_sec / 60.0
        w_end_min = w_end_sec / 60.0

        # Update Slider
        if update_slider:
            win_len = self.current_window_sec if self.current_window_sec > 0 else total_sec
            max_start = max(0.001, total_sec - win_len)
            slider_pos = int((w_start_sec / max_start) * 1000)
            self.time_slider.blockSignals(True)
            self.time_slider.setValue(slider_pos)
            self.time_slider.blockSignals(False)

        # Update Time Info Label
        start_epoch = int(w_start_sec // 30) + 1
        end_epoch = int(w_end_sec // 30) + 1
        total_epochs = int(total_sec // 30)
        window_duration_min = (w_end_sec - w_start_sec) / 60.0

        m_s, s_s = divmod(int(w_start_sec), 60)
        h_s, m_s = divmod(m_s, 60)
        m_e, s_e = divmod(int(w_end_sec), 60)
        h_e, m_e = divmod(m_e, 60)

        spt_start_sec = self.current_result.get("SPT_Start_sec", 0.0)
        spt_end_sec = self.current_result.get("SPT_End_sec", 0.0)
        spt_start_m = spt_start_sec / 60.0
        spt_end_m = spt_end_sec / 60.0

        midpoint_epoch_idx = int(((w_start_sec + w_end_sec) / 2.0) // 30)
        stage_str = ""
        if sleep_epochs and 0 <= midpoint_epoch_idx < len(sleep_epochs):
            st_code = sleep_epochs[midpoint_epoch_idx]
            stage_str = f" | Stage: {STAGE_NAMES.get(st_code, 'Unknown')}"

        spt_str = ""
        if spt_end_sec > spt_start_sec:
            first_ep = self.current_result.get("Sleep_Summary", {}).get("First_Sleep_Epoch", 1)
            last_ep = self.current_result.get("Sleep_Summary", {}).get("Last_Sleep_Epoch", total_epochs)
            if w_start_sec >= spt_start_sec and w_end_sec <= spt_end_sec:
                spt_str = f" | Inside SPT [Ep {first_ep}-{last_ep}]"
            elif w_end_sec < spt_start_sec:
                spt_str = " | Pre-Sleep Wake"
            elif w_start_sec > spt_end_sec:
                spt_str = " | Post-Sleep Wake"
            else:
                spt_str = f" | Crosses SPT [Ep {first_ep}-{last_ep}]"

        self.lbl_time_window_info.setText(
            f"Window: [{h_s:02d}:{m_s:02d}:{s_s:02d} - {h_e:02d}:{m_e:02d}:{s_e:02d}] "
            f"(Epoch {start_epoch}-{end_epoch} / {total_epochs}) | Span: {window_duration_min:.1f}m{stage_str}{spt_str}"
        )

        # --- 1. RENDER TOP DETAILED PLOT ---
        self.ax_detail.clear()

        s_idx = max(0, int(round(w_start_sec * sr)))
        e_idx = min(len(clean_sig) - 1, int(round(w_end_sec * sr)))

        if e_idx > s_idx:
            t_win = time_min_full[s_idx : e_idx + 1]
            sig_win = clean_sig[s_idx : e_idx + 1]
            base_win = baselines[s_idx : e_idx + 1] if len(baselines) == len(clean_sig) else np.full_like(sig_win, 97.0)

            # Signal line
            self.ax_detail.plot(t_win, sig_win, color="#1f77b4", linewidth=1.3, label="SpO2 (%)")
            # Dynamic baseline
            self.ax_detail.plot(t_win, base_win, color="#aec7e8", linestyle="--", linewidth=1.1, label="Baseline (98th %ile)")

            # Shade desaturation areas in window
            for ev in desats:
                if ev["End"] < w_start_sec or ev["Start"] > w_end_sec:
                    continue
                ev_s = max(w_start_sec, ev["Start"])
                ev_e = min(w_end_sec, ev["End"])
                ev_s_idx = max(0, int(round(ev_s * sr)))
                ev_e_idx = min(len(clean_sig) - 1, int(round(ev_e * sr)))
                if ev_e_idx > ev_s_idx:
                    t_ev = time_min_full[ev_s_idx : ev_e_idx + 1]
                    s_ev = clean_sig[ev_s_idx : ev_e_idx + 1]
                    b_ev = baselines[ev_s_idx : ev_e_idx + 1]
                    self.ax_detail.fill_between(t_ev, s_ev, b_ev, where=(b_ev >= s_ev), color="#ff7f0e", alpha=0.35)

            # Shade Artifact intervals in detailed view (Light Red with subtle hatch)
            art_legend_added = False
            for a_start, a_end in art_intervals:
                if a_end >= w_start_min and a_start <= w_end_min:
                    lbl = "Signal Artifact" if not art_legend_added else None
                    self.ax_detail.axvspan(
                        max(w_start_min, a_start),
                        min(w_end_min, a_end),
                        facecolor="#e74c3c",
                        edgecolor="#c0392b",
                        hatch="//",
                        alpha=0.22,
                        label=lbl,
                        zorder=2
                    )
                    art_legend_added = True

            # Mark Nadirs in window
            nadirs_in_win = [e for e in desats if w_start_sec <= e["Nadir_Time"] <= w_end_sec]
            if nadirs_in_win:
                n_t = [e["Nadir_Time"] / 60.0 for e in nadirs_in_win]
                n_v = [e["Nadir"] for e in nadirs_in_win]
                self.ax_detail.scatter(n_t, n_v, color="#d62728", s=28, zorder=6, label="Nadir Point")

            # Sleep Hypnogram Banner (Top strip of detailed plot)
            if sleep_epochs:
                for ep_idx in range(start_epoch - 1, min(len(sleep_epochs), end_epoch)):
                    st = sleep_epochs[ep_idx]
                    col = STAGE_COLORS.get(st, "#cccccc")
                    ep_start_m = (ep_idx * 30.0) / 60.0
                    ep_end_m = ((ep_idx + 1) * 30.0) / 60.0
                    if ep_end_m >= w_start_min and ep_start_m <= w_end_min:
                        rect = Rectangle((ep_start_m, 100.2), ep_end_m - ep_start_m, 1.6, facecolor=col, edgecolor='none', alpha=0.85)
                        self.ax_detail.add_patch(rect)

            if spt_end_sec > spt_start_sec:
                if w_start_min <= spt_start_m <= w_end_min:
                    self.ax_detail.axvline(spt_start_m, color="#16a085", linestyle="--", linewidth=1.4, label="Sleep Onset (SPT Start)")
                if w_start_min <= spt_end_m <= w_end_min:
                    self.ax_detail.axvline(spt_end_m, color="#c0392b", linestyle="--", linewidth=1.4, label="Sleep Offset (SPT End)")
            self.ax_detail.axhline(90.0, color="#d62728", linestyle=":", alpha=0.65, label="90% Saturation")
            self.ax_detail.set_xlim(w_start_min, w_end_min)
            
            valid_sig_samples = sig_win[np.isfinite(sig_win)]
            y_min = max(40, np.nanmin(valid_sig_samples) - 4) if len(valid_sig_samples) > 0 else 50
            self.ax_detail.set_ylim(y_min, 102.5)
            self.ax_detail.grid(True, linestyle="--", alpha=0.4)
            self.ax_detail.set_ylabel("SpO2 (%)", fontweight="bold")
            self.ax_detail.set_title(
                f"{self.current_result.get('File_Name', '')} | Inspected Window: {self.combo_interval.currentText()}",
                color="#11417f", fontweight="bold", fontsize=10
            )

        # --- 2. RENDER BOTTOM FULL OVERVIEW MINIMAP ---
        self.ax_overview.clear()
        if spt_end_sec > spt_start_sec:
            self.ax_overview.axvspan(spt_start_m, spt_end_m, color="#2ecc71", alpha=0.18, label="SPT Region")
            self.ax_overview.axvline(spt_start_m, color="#16a085", linestyle=":", linewidth=0.8)
            self.ax_overview.axvline(spt_end_m, color="#c0392b", linestyle=":", linewidth=0.8)

        # Render full trace and artifacts on overview
        self.ax_overview.plot(time_min_full, clean_sig, color="#7fb3d5", linewidth=0.6)
        if len(baselines) == len(clean_sig):
            self.ax_overview.plot(time_min_full, baselines, color="#b0c4de", linestyle=":", linewidth=0.5)

        for a_start, a_end in art_intervals:
            self.ax_overview.axvspan(a_start, a_end, color="#e74c3c", alpha=0.35, zorder=3)

        # Highlight current zoom window on overview
        self.ax_overview.axvspan(w_start_min, w_end_min, color="#ff7f0e", alpha=0.35, edgecolor="#d62728", linewidth=1.2)
        self.ax_overview.set_xlim(0, total_sec / 60.0)
        self.ax_overview.set_ylim(50, 102)
        self.ax_overview.set_xlabel("Elapsed Recording Time (Minutes)", fontweight="bold", fontsize=8.5)
        self.ax_overview.set_ylabel("Full Night", fontsize=8)
        self.ax_overview.grid(True, linestyle=":", alpha=0.3)

        self.fig.tight_layout()
        self.canvas.draw()

    def update_batch_queue_row(self, res: Dict[str, Any]):
        fname = res.get("File_Name", "")
        for r in range(self.table_batch_queue.rowCount()):
            item_f = self.table_batch_queue.item(r, 0)
            if item_f and item_f.text() == fname:
                dur = res.get("Analysis_Duration_Hours", 0.0)
                odi = res.get("ODI_3pct", 0.0)
                t90 = res.get("T90_Percent", 0.0)
                hb = res.get("Azarbarzin_HB_pctmin_hr", 0.0)
                ks = res.get("Kulkas_Total_Severity_pctmin_hr", 0.0)

                self.table_batch_queue.setItem(r, 2, QTableWidgetItem(f"{dur:.2f} h"))
                self.table_batch_queue.setItem(r, 3, QTableWidgetItem(f"{odi:.1f}"))
                self.table_batch_queue.setItem(r, 4, QTableWidgetItem(f"{t90:.1f}%"))
                self.table_batch_queue.setItem(r, 5, QTableWidgetItem(f"{hb:.2f}"))
                self.table_batch_queue.setItem(r, 6, QTableWidgetItem(f"{ks:.2f}"))

                st_item = QTableWidgetItem("Completed")
                st_item.setForeground(QColor("#2ca02c"))
                font = st_item.font()
                font.setBold(True)
                st_item.setFont(font)
                self.table_batch_queue.setItem(r, 7, st_item)
                break

    def show_methodology_dialog(self):
        """
        Locates and opens the desatNerd Clinical & Technical User Guide in the assets folder
        using the default operating system viewer.
        Falls back to other project paths and an internal reference dialog if not found.
        """
        candidate_filenames = [
            # Exact file name in your assets folder:
            "DesatNerd Clinical & Technical User Guide.pdf",
            "DesatNerd Clinical and Technical User Guide.pdf",
            "DesatNerd_Clinical_and_Technical_User_Guide.pdf",
            "DesatNerd_User_Guide.pdf",
            "User_Guide.pdf",
            "User Guide.pdf",
            "UserGuide.pdf",
            "User_Guide.docx",
            "User Guide.docx",
            "User_Guide.md",
            "User Guide.md",
            "User_Guide.html"
        ]

        found_doc = None

        # 1. Primary Check: directly via resource_path inside assets
        for name in candidate_filenames:
            p = resource_path(os.path.join("assets", name))
            if os.path.isfile(p):
                found_doc = os.path.abspath(p)
                break

        # 2. Secondary Check: scan assets folder dynamically for any PDF containing 'User Guide'
        if not found_doc:
            assets_dir = resource_path("assets")
            if os.path.isdir(assets_dir):
                for f in os.listdir(assets_dir):
                    if f.lower().endswith(".pdf") and ("guide" in f.lower() or "desatnerd" in f.lower()):
                        found_doc = os.path.abspath(os.path.join(assets_dir, f))
                        break

        # 3. Tertiary Check: typical project directories (dev & root)
        if not found_doc:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            fallback_dirs = [
                os.path.join(base_dir, "assets"),
                os.path.join(base_dir, "User_Guide"),
                os.path.join(base_dir, "docs"),
                base_dir,
                os.path.join(os.path.dirname(base_dir), "assets"),
                os.path.join(os.path.dirname(base_dir), "User_Guide")
            ]
            for d in fallback_dirs:
                if not os.path.isdir(d):
                    continue
                # Exact name check
                for name in candidate_filenames:
                    p = os.path.join(d, name)
                    if os.path.isfile(p):
                        found_doc = os.path.abspath(p)
                        break
                if found_doc:
                    break
                # Generic PDF scan in fallback folder
                for f in os.listdir(d):
                    if f.lower().endswith(".pdf") and ("guide" in f.lower() or "desatnerd" in f.lower()):
                        found_doc = os.path.abspath(os.path.join(d, f))
                        break
                if found_doc:
                    break

        # Launch document if found
        if found_doc and os.path.isfile(found_doc):
            self.log(f"Opening User Guide: {os.path.basename(found_doc)}")
            
            # Attempt 1: Native Windows os.startfile (most reliable on Windows for filenames with spaces)
            if sys.platform.startswith("win"):
                try:
                    os.startfile(os.path.normpath(found_doc))
                    return
                except Exception as e:
                    self.log(f"[Warning] os.startfile failed: {e}. Trying QDesktopServices...")

            # Attempt 2: QDesktopServices
            url = QUrl.fromLocalFile(os.path.normpath(found_doc).replace("\\", "/"))
            if QDesktopServices.openUrl(url):
                return

            # Attempt 3: Subprocess fallback
            try:
                if sys.platform.startswith("win"):
                    subprocess.Popen(['cmd', '/c', 'start', '""', os.path.normpath(found_doc)], shell=True)
                elif sys.platform.startswith("darwin"):
                    subprocess.Popen(["open", found_doc])
                else:
                    subprocess.Popen(["xdg-open", found_doc])
                return
            except Exception as e:
                QMessageBox.warning(
                    self,
                    "Open User Guide",
                    f"Found document at:\n{found_doc}\n\nCould not launch viewer: {str(e)}"
                )
                return

        # Fallback dialog if document is missing
        text = (
            "<h2>desatNerd by Dr Brett Duce, Princess Alexandra Hospital</h2>"
            "<p><b>User Guide Document Not Found:</b><br>"
            "Please ensure <code>DesatNerd Clinical & Technical User Guide.pdf</code> is located in the "
            "<code>assets/</code> directory.</p>"
            "<hr>"
            "<p><b>1. Azarbarzin Hypoxic Burden (HB):</b><br>"
            "Area under pre-event baseline curve above SpO2 during respiratory events, normalized per hour (%min/h).</p>"
            "<p><b>2. REDTA (de Chazal et al.):</b><br>"
            "Transient area across 2.5x event duration against a 100% baseline (%hours and %min/h).</p>"
            "<p><b>3. Kulkas Framework (DesSev & RecSev):</b><br>"
            "Decomposes events into falling and recovery phases to quantify collapse depth and ventilatory restitution.</p>"
            "<p><b>4. Analysis Windows:</b><br>"
            "<b>SPT:</b> From sleep onset to sleep offset (captures intervening wake/WASO).<br>"
            "<b>TST:</b> Constrained strictly to epochs scored as sleep.<br>"
            "<b>TRT:</b> Full study recording duration.</p>"
        )
        msg = QMessageBox(self)
        msg.setWindowTitle("User Guide & Methodology")
        msg.setTextFormat(Qt.RichText)
        msg.setText(text)
        msg.exec()

    def show_about_dialog(self):
        text = (
            f"<b>{APP_TITLE}</b><br><br>"
            "Clinical and scientific software tool for automated quantification of oxygen desaturations, "
            "desaturation morphology, and sleep apnea specific hypoxic burden.<br><br>"
            "<b>Supported Formats:</b> Compumedics EDF, Nox EDF, REMlogic EDF, Nonin (.asc/.csv/.txt), Nellcor ASCII, Masimo CSV/TXT.<br>"
            "<b>Companion Annotations:</b> Compumedics <code>.edf.XML</code>, Profusion XML, Nox XML.<br><br>"
            "<i>Brett Duce, Princess Alexandra Hospital, Brisbane, Australia.</i>"
        )
        QMessageBox.about(self, "About desatNerd", text)