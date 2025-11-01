# hsparc/ui/researcher.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Set, Tuple, Optional
from pathlib import Path
import json
import hashlib

from PySide6.QtCore import Qt, QUrl, QTimer
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QCheckBox, QPushButton, QSplitter, QGroupBox, QGridLayout,
    QSpinBox, QMessageBox, QFileDialog, QDialog, QDialogButtonBox,
    QListView, QSlider, QInputDialog, QLineEdit, QProgressDialog, QApplication,
    QComboBox
)
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtMultimediaWidgets import QVideoWidget

import numpy as np
import pandas as pd
import pyreadstat
import pyqtgraph as pg

# --- imports that resolve in-package or fall back for dev ---
try:
    from hsparc.models import db as dbm
    from hsparc.ui.controlmap import ControlMapDialog
    from hsparc.analysis.convergence import ConvergenceAnalyzer, AnalysisResults
    from hsparc.analysis.comprehensive_analyzer import ComprehensiveTraceAnalyzer
    from hsparc.ui.widgets.analysis_results import AnalysisResultsDialog
    from hsparc.ui.widgets.comprehensive_results_dialog import ComprehensiveResultsDialog
    from hsparc.ui.global_av_manager import GlobalAVManager
    from hsparc.ui.av_settings_dialog import AVSettingsDialog
except Exception:
    try:
        import db as dbm  # type: ignore
        from controlmap import ControlMapDialog  # type: ignore
        from analysis.convergence import ConvergenceAnalyzer, AnalysisResults  # type: ignore
        from analysis.comprehensive_analyzer import ComprehensiveTraceAnalyzer  # type: ignore
        from widgets.analysis_results import AnalysisResultsDialog  # type: ignore
        from widgets.comprehensive_results_dialog import ComprehensiveResultsDialog  # type: ignore
        from global_av_manager import GlobalAVManager  # type: ignore
        from av_settings_dialog import AVSettingsDialog  # type: ignore
    except Exception:

        class ControlMapDialog(QDialog):
            def __init__(self, *a, **k):
                super().__init__(*a, **k)
                self.setWindowTitle("Mapping (stub) - missing hsparc.ui.controlmap")

            def exec(self):  # type: ignore
                return QDialog.Rejected


        class ConvergenceAnalyzer:
            def analyze(self, *args, **kwargs):
                raise NotImplementedError("Missing convergence module")


        class AnalysisResultsDialog(QDialog):
            def __init__(self, *a, **k):
                super().__init__(*a, **k)
                self.setWindowTitle("Analysis (stub)")


        class AVSettingsDialog(QDialog):
            def __init__(self, *a, **k):
                super().__init__(*a, **k)
                self.setWindowTitle("AV Settings (stub)")

# --- plotting / export constants ---
INVERT_AXIS_DEFAULT = {"ABS_Y", "ABS_RY"}  # invert so "up" is positive
HIDE_SENTINEL = "__HIDE__"  # special label to hide signals


# ========== Security Helpers (duplicated for independence) ==========
def hash_pin(pin: str) -> str:
    """Hash a PIN using SHA256."""
    return hashlib.sha256(pin.encode('utf-8')).hexdigest()


def verify_pin(stored_hash: str, entered_pin: str) -> bool:
    """Verify an entered PIN against stored hash."""
    return hash_pin(entered_pin) == stored_hash


def log_access(case_id: str, action: str, success: bool = True):
    """Log security-relevant actions."""
    from datetime import datetime
    timestamp = datetime.utcnow().isoformat()
    status = "SUCCESS" if success else "FAILED"
    print(f"[ACCESS LOG] {timestamp} | Case: {case_id[:8]} | {action} | {status}")


class PinDialog(QMessageBox):
    """Simple dialog for entering case PIN."""

    def __init__(self, parent=None, title="Enter Case PIN", message="Enter the PIN:"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setText(message)
        self.setIcon(QMessageBox.Question)

        self.pin_input = QLineEdit()
        self.pin_input.setEchoMode(QLineEdit.Password)
        self.pin_input.setPlaceholderText("Enter 4-8 digit PIN")
        self.pin_input.setMaxLength(8)

        layout = self.layout()
        layout.addWidget(self.pin_input, 1, 1)

        self.addButton(QMessageBox.Ok)
        self.addButton(QMessageBox.Cancel)
        self.setDefaultButton(QMessageBox.Ok)

    def get_pin(self) -> str:
        return self.pin_input.text().strip()

    @staticmethod
    def get_pin_from_user(parent=None, title="Enter Case PIN", message="Enter the PIN:"):
        dialog = PinDialog(parent, title, message)
        dialog.pin_input.setFocus()
        if dialog.exec() == QMessageBox.Ok:
            return dialog.get_pin()
        return None


# ---------------- Data containers ----------------
@dataclass
class AxisSeries:
    times_ms: List[int]
    values_raw: List[int]  # centered (0 == stick center)
    vmin: int
    vmax: int


@dataclass
class ButtonSeries:
    presses_ms: List[int]
    releases_ms: List[int]


@dataclass
class StreamData:
    id: str
    device_name: str
    profile_id: Optional[str]
    alias: Optional[str]
    control_labels: Dict[str, str]
    axes: Dict[str, AxisSeries]
    buttons: Dict[str, ButtonSeries]
    session_id: str  # NEW: Store parent session ID
    session_label: str  # NEW: Store parent session label


@dataclass
class SessionData:
    id: str
    label: str
    streams: Dict[str, StreamData]


# -------------- mm:ss axis --------------
class TimeAxis(pg.AxisItem):
    def tickStrings(self, values, scale, spacing):
        out = []
        for v in values:
            if v < 0:
                v = 0
            s = int(round(v))
            m, s = divmod(s, 60)
            h, m = divmod(m, 60)
            out.append(f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}")
        return out


# ---------------- Researcher Window ----------------
class ResearcherWindow(QMainWindow):
    """
    Researcher view: video + synchronized controller streams
      • NLE-style follow (auto-scroll) with a visible playhead.
      • Scrub bar with current/duration labels.
      • Participant list (multi-select), per-control mapping (constructs), hide sentinel.
      • Delete participants functionality with PIN protection.
      • Convergence/Divergence Analysis with interactive results.
      • Exports (XLSX/CSV/SPSS).
      • Zoom In/Out, Reset View, Fit Time.
    """

    def __init__(self, recording_id: str, study_pin: Optional[str] = None):
        super().__init__()
        self.recording_id = recording_id
        self.study_pin = study_pin  # Store PIN for decryption
        self._temp_video_path: Optional[str] = None  # Track temp decrypted file
        self.setWindowTitle("Researcher Review - HSPARC")
        self.resize(1280, 800)

        # Create menu bar with styled settings button
        menubar = self.menuBar()

        # Style the menubar
        menubar.setStyleSheet("""
            QMenuBar {
                background-color: #f8f9fa;
                padding: 4px;
            }
            QMenuBar::item {
                padding: 8px 16px;
                background: transparent;
                border-radius: 4px;
            }
            QMenuBar::item:selected {
                background: #e9ecef;
            }
        """)

        settings_menu = menubar.addMenu("⚙️  Settings")
        settings_menu.setStyleSheet("""
            QMenu {
                background-color: white;
                border: 1px solid #ddd;
                padding: 4px;
            }
            QMenu::item {
                padding: 8px 24px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background-color: #007bff;
                color: white;
            }
        """)

        av_settings_action = settings_menu.addAction("🎤 Audio/Video Settings...")
        av_settings_action.triggered.connect(self._open_av_settings)

        # --- state ---
        self._seeking = False
        self._tmin_ms: Optional[int] = None
        self._tmax_ms: Optional[int] = None
        self._last_ms: int = -1
        self._window_seconds: float = 20.0
        self._follow_enabled: bool = True
        self._time_offset_ms: int = 0

        # persistent plot items
        self._curve_items: Dict[str, pg.PlotDataItem] = {}
        self._press_items: Dict[str, pg.ScatterPlotItem] = {}
        self._release_items: Dict[str, pg.ScatterPlotItem] = {}
        self._color_cache: Dict[str, tuple] = {}

        # --- load recording/video ---
        with dbm.get_session() as s:
            rec = s.query(dbm.Recording).filter_by(id=recording_id).first()
            if not rec:
                QMessageBox.critical(self, "Missing", "Recording not found.")
                self.close()
                return

            # Handle encrypted videos
            if rec.video_path:
                video_path = Path(rec.video_path)
                print(f"[researcher] Loading video: {video_path}")
                print(f"[researcher] Is encrypted: {video_path.suffix == '.enc'}")
                print(f"[researcher] Study PIN available: {self.study_pin is not None}")
                print(f"[researcher] Case ID available: {rec.case_id is not None}")

                if video_path.suffix == '.enc':
                    if self.study_pin and rec.case_id:
                        try:
                            from hsparc.utils.study_encryption import decrypt_file
                            print(f"[researcher] Decrypting video: {video_path}")
                            temp_path = decrypt_file(str(video_path), rec.case_id, self.study_pin)
                            self._temp_video_path = temp_path
                            self.video_path = Path(temp_path)
                            print(f"[researcher] Video decrypted to: {temp_path}")
                        except Exception as e:
                            print(f"[researcher] Decryption error: {e}")
                            import traceback
                            traceback.print_exc()
                            QMessageBox.critical(self, "Decryption Failed",
                                                 f"Cannot decrypt video:\n{e}\n\nInvalid PIN or corrupted file.")
                            self.close()
                            return
                    else:
                        error_msg = "Cannot decrypt video: "
                        if not self.study_pin:
                            error_msg += "Study PIN not available"
                        elif not rec.case_id:
                            error_msg += "Case ID not available"
                        print(f"[researcher] ERROR: {error_msg}")
                        QMessageBox.critical(self, "Decryption Error", error_msg)
                        self.close()
                        return
                else:
                    # Plain video (legacy or not encrypted)
                    print(f"[researcher] Loading plain video: {video_path}")
                    self.video_path = video_path
            else:
                self.video_path = None

            self._case_id = rec.case_id

        # --- MAIN LAYOUT: Horizontal splitter (sidebar | content) ---
        main_splitter = QSplitter(Qt.Horizontal, self)
        self.setCentralWidget(main_splitter)

        # ============================================================
        # LEFT SIDEBAR - Full height controls
        # ============================================================
        sidebar = QWidget()
        sidebar_l = QVBoxLayout(sidebar)
        sidebar_l.setContentsMargins(8, 8, 8, 8)
        sidebar_l.setSpacing(8)

        # Set fixed/minimum width for sidebar
        sidebar.setMinimumWidth(300)
        sidebar.setMaximumWidth(400)

        # Participants section
        src_box = QGroupBox("Participants")
        src_l = QVBoxLayout(src_box)
        self.participant_list = QListWidget()
        self.participant_list.setSelectionMode(QListView.ExtendedSelection)
        src_l.addWidget(self.participant_list)

        # Participant management buttons
        mgmt_row = QHBoxLayout()
        self.btn_map = QPushButton("Map Controls…")
        self.btn_delete_participant = QPushButton("Delete Participant…")
        self.btn_delete_participant.setStyleSheet("background-color: #d9534f; color: white;")
        mgmt_row.addWidget(self.btn_map)
        mgmt_row.addWidget(self.btn_delete_participant)
        src_l.addLayout(mgmt_row)
        sidebar_l.addWidget(src_box)

        # Plot Controls section
        ctrl_box = QGroupBox("Plot Controls")
        ctrl_l = QGridLayout(ctrl_box)
        self.chk_axes = QCheckBox("Axes (sticks / triggers)")
        self.chk_btns = QCheckBox("Buttons")
        self.chk_axes.setChecked(True)
        self.chk_btns.setChecked(True)
        self.btn_refresh = QPushButton("Refresh Plot")
        self.btn_fit = QPushButton("Fit Time")
        ctrl_l.addWidget(self.chk_axes, 0, 0)
        ctrl_l.addWidget(self.chk_btns, 0, 1)
        ctrl_l.addWidget(self.btn_refresh, 1, 0)
        ctrl_l.addWidget(self.btn_fit, 1, 1)
        sidebar_l.addWidget(ctrl_box)

        # Analysis section
        analysis_box = QGroupBox("Analysis")
        ag = QVBoxLayout(analysis_box)

        # Instructions
        instr = QLabel(
            "Select trace(s) to analyze:\n"
            "• 1 trace: Descriptive stats, change detection\n"
            "• 2 traces: Correlation, convergence/divergence\n"
            "• 3+ traces: PCA, clustering, correlation matrix"
        )
        instr.setWordWrap(True)
        instr.setStyleSheet("color: #666; font-size: 10px; padding: 4px;")
        ag.addWidget(instr)

        # Trace selection list
        ag.addWidget(QLabel("<b>Available Traces:</b>"))
        self.analysis_trace_list = QListWidget()
        self.analysis_trace_list.setSelectionMode(QListView.ExtendedSelection)
        self.analysis_trace_list.setMaximumHeight(150)
        self.analysis_trace_list.setToolTip(
            "Select one or more traces to analyze.\n"
            "Each participant may have multiple traces (axes, buttons)."
        )
        ag.addWidget(self.analysis_trace_list)

        # Analysis button
        self.btn_run_analysis = QPushButton("Run Comprehensive Analysis")
        self.btn_run_analysis.setToolTip(
            "Analyze selected trace(s).\n"
            "Analysis type adapts based on selection count."
        )
        self.btn_run_analysis.setMinimumHeight(35)
        ag.addWidget(self.btn_run_analysis)
        sidebar_l.addWidget(analysis_box)

        # Export section
        export_box = QGroupBox("Export")
        export_layout = QVBoxLayout(export_box)
        export_layout.setSpacing(8)

        # Data format selection
        format_row = QHBoxLayout()
        format_label = QLabel("Data Format:")
        self.export_format_combo = QComboBox()
        self.export_format_combo.addItem("Change-based (Events only)", "changes")
        self.export_format_combo.addItem("Time-series (Regular sampling)", "timeseries")
        self.export_format_combo.setToolTip(
            "Change-based: Only records when input changes (smaller files)\n"
            "Time-series: Regular sampling at fixed rate (better for analysis)"
        )
        format_row.addWidget(format_label)
        format_row.addWidget(self.export_format_combo, 1)
        export_layout.addLayout(format_row)

        # Sampling rate selection (only for time-series)
        self.rate_row = QHBoxLayout()
        self.rate_label = QLabel("Sampling Rate:")
        self.sampling_rate_combo = QComboBox()
        self.sampling_rate_combo.addItem("30 Hz (33ms)", 30)
        self.sampling_rate_combo.addItem("20 Hz (50ms)", 20)
        self.sampling_rate_combo.addItem("10 Hz (100ms)", 10)
        self.sampling_rate_combo.addItem("5 Hz (200ms)", 5)
        self.sampling_rate_combo.addItem("1 Hz (1000ms)", 1)
        self.sampling_rate_combo.setCurrentIndex(1)  # Default to 30 Hz
        self.sampling_rate_combo.setToolTip(
            "Higher rates = more detailed data but larger files\n"
            "30 Hz matches video framerate (recommended)"
        )
        self.rate_row.addWidget(self.rate_label)
        self.rate_row.addWidget(self.sampling_rate_combo, 1)
        export_layout.addLayout(self.rate_row)

        # Show/hide sampling rate based on format
        self.export_format_combo.currentIndexChanged.connect(self._update_export_ui)
        self._update_export_ui()  # Set initial state

        # Export format buttons (vertical stack)
        self.btn_export_xlsx = QPushButton("Export XLSX")
        self.btn_export_csv = QPushButton("Export CSV")
        self.btn_export_sav = QPushButton("Export SPSS")
        export_layout.addWidget(self.btn_export_xlsx)
        export_layout.addWidget(self.btn_export_csv)
        export_layout.addWidget(self.btn_export_sav)
        sidebar_l.addWidget(export_box)

        # Add stretch to push everything to top
        sidebar_l.addStretch(1)

        main_splitter.addWidget(sidebar)

        # ============================================================
        # RIGHT CONTENT AREA - Video + Plot
        # ============================================================
        content = QWidget()
        content_l = QVBoxLayout(content)
        content_l.setContentsMargins(0, 0, 0, 0)
        content_l.setSpacing(4)

        # --- Video section ---
        video_container = QWidget()
        video_container.setMinimumHeight(300)  # Ensure video stays visible
        video_l = QVBoxLayout(video_container)
        video_l.setContentsMargins(8, 8, 8, 4)

        # video widget
        self.video_widget = QVideoWidget()
        self.media = QMediaPlayer(self)
        self.media.setVideoOutput(self.video_widget)
        self.audio_out = GlobalAVManager.instance().create_audio_output()
        self.media.setAudioOutput(self.audio_out)
        try:
            self.audio_out.setVolume(0.8)
        except Exception:
            pass

        title = QLabel("Researcher Review")
        title.setStyleSheet("font-size:16px;font-weight:600;")
        video_l.addWidget(title)
        video_l.addWidget(self.video_widget, 1)

        # Transport controls
        controls = QHBoxLayout()
        self.btn_play = QPushButton("Play")
        self.btn_pause = QPushButton("Pause")
        self.btn_stop = QPushButton("Stop")
        for b in (self.btn_play, self.btn_pause, self.btn_stop):
            controls.addWidget(b)
        self.chk_follow = QCheckBox("Follow (NLE)")
        self.chk_follow.setChecked(True)
        self.win_label = QLabel("Init/Window (s):")
        self.win_spin = QSpinBox()
        self.win_spin.setRange(3, 180)
        self.win_spin.setValue(int(self._window_seconds))
        self.btn_zoom_in = QPushButton("Zoom In")
        self.btn_zoom_out = QPushButton("Zoom Out")
        self.btn_reset = QPushButton("Reset View")
        controls.addStretch(1)
        controls.addWidget(self.chk_follow)
        controls.addWidget(self.win_label)
        controls.addWidget(self.win_spin)
        controls.addWidget(self.btn_zoom_in)
        controls.addWidget(self.btn_zoom_out)
        controls.addWidget(self.btn_reset)

        # Close button for kiosk mode
        self.btn_close_window = QPushButton("Close Researcher")
        self.btn_close_window.setStyleSheet("""
            QPushButton {
                background-color: #5bc0de;
                color: white;
                padding: 8px 16px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #46b8da;
            }
        """)
        self.btn_close_window.clicked.connect(self.close)
        controls.addWidget(self.btn_close_window)
        video_l.addLayout(controls)

        # scrub bar + time labels
        scrub = QHBoxLayout()
        self.lbl_pos = QLabel("0:00")
        self.lbl_dur = QLabel("0:00")
        self.scrub = QSlider(Qt.Horizontal)
        self.scrub.setMinimum(0)
        self.scrub.setSingleStep(50)
        scrub.addWidget(self.lbl_pos)
        scrub.addWidget(self.scrub, 1)
        scrub.addWidget(self.lbl_dur)
        video_l.addLayout(scrub)

        content_l.addWidget(video_container, 55)  # Video gets 55% of height

        if self.video_path and self.video_path.exists():
            self.media.setSource(QUrl.fromLocalFile(str(self.video_path)))

        # --- Plot section ---
        plot_container = QWidget()
        plot_container.setMinimumHeight(250)  # Ensure plot stays usable
        plot_l = QVBoxLayout(plot_container)
        plot_l.setContentsMargins(8, 4, 8, 8)

        pg.setConfigOptions(antialias=True)
        self.plot_widget = pg.PlotWidget(axisItems={"bottom": TimeAxis(orientation="bottom")})
        self.plot_widget.setBackground("w")
        self.plot_item: pg.PlotItem = self.plot_widget.getPlotItem()
        self.plot_item.showGrid(x=True, y=True, alpha=0.25)
        self.plot_item.setLabel("left", "Axis value (normalized)")
        self.plot_item.setYRange(-1.2, 1.2, padding=0.0)
        self.plot_item.addLegend(offset=(-5, 5))
        plot_l.addWidget(self.plot_widget, 1)

        # status line
        self.status_lbl = QLabel("")
        self.status_lbl.setStyleSheet("color:#555; font-size:11px;")
        plot_l.addWidget(self.status_lbl)

        content_l.addWidget(plot_container, 45)  # Plot gets 45% of height

        # playhead line
        self.playhead = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen((70, 70, 70), width=2, style=Qt.DashLine))
        self.playhead.setZValue(10_000)
        self.plot_item.addItem(self.playhead)

        main_splitter.addWidget(content)

        # Set initial splitter sizes (sidebar gets 1/4, content gets 3/4)
        total_width = self.width()
        main_splitter.setSizes([int(total_width * 0.25), int(total_width * 0.75)])

        # transport wiring
        self.btn_play.clicked.connect(self.media.play)
        self.btn_pause.clicked.connect(self.media.pause)
        self.btn_stop.clicked.connect(self.media.stop)

        # media signals
        self.media.positionChanged.connect(self._on_media_pos_changed)
        self.media.durationChanged.connect(self._on_media_dur_changed)
        try:
            self.media.playbackStateChanged.connect(self._on_state_changed)
        except Exception:
            pass

        # scrub signals
        self.scrub.sliderPressed.connect(self._on_scrub_pressed)
        self.scrub.sliderMoved.connect(self._on_scrub_moved)
        self.scrub.sliderReleased.connect(self._on_scrub_released)

        # ============================================================
        # WIRE UP ALL BUTTONS AND SIGNALS
        # ============================================================

        # transport wiring
        self.btn_play.clicked.connect(self.media.play)
        self.btn_pause.clicked.connect(self.media.pause)
        self.btn_stop.clicked.connect(self.media.stop)

        # media signals
        self.media.positionChanged.connect(self._on_media_pos_changed)
        self.media.durationChanged.connect(self._on_media_dur_changed)
        try:
            self.media.playbackStateChanged.connect(self._on_state_changed)
        except Exception:
            pass

        # scrub signals
        self.scrub.sliderPressed.connect(self._on_scrub_pressed)
        self.scrub.sliderMoved.connect(self._on_scrub_moved)
        self.scrub.sliderReleased.connect(self._on_scrub_released)

        # wire buttons
        self.btn_refresh.clicked.connect(self._refresh_plot_full)
        self.btn_fit.clicked.connect(self._reset_view)
        self.btn_zoom_in.clicked.connect(lambda: self._zoom(1 / 1.3))
        self.btn_zoom_out.clicked.connect(lambda: self._zoom(1.3))
        self.btn_reset.clicked.connect(self._reset_view)
        self.btn_map.clicked.connect(self._open_map_dialog_for_selection)
        self.btn_delete_participant.clicked.connect(self._delete_participant)
        self.btn_run_analysis.clicked.connect(self._run_comprehensive_analysis)
        self.chk_follow.stateChanged.connect(self._on_follow_changed)
        self.win_spin.valueChanged.connect(self._on_window_changed)
        self.btn_export_xlsx.clicked.connect(self._export_xlsx)
        self.btn_export_sav.clicked.connect(self._export_sav)
        self.btn_export_csv.clicked.connect(self._export_csv)

        # initial load + plot
        self.sessions: Dict[str, SessionData] = self._load_sessions_strict(recording_id)
        self._populate_participant_list()  # UPDATED
        self._plot()

        # playhead timer
        self._cursor_timer = QTimer(self)
        self._cursor_timer.setInterval(33)
        self._cursor_timer.timeout.connect(self._tick_playhead)
        self._cursor_timer.start()

        # Note: Initial autorange happens in _plot(), don't override it here

    def _open_av_settings(self):
        """Open A/V settings dialog."""
        dialog = AVSettingsDialog(self)
        dialog.exec()

    # -------------- DELETE PARTICIPANT --------------
    def _delete_participant(self):
        """Delete selected participant(s) (input streams). Requires confirmation and PIN if case is locked."""
        # Get selected items
        selected_items = self.participant_list.selectedItems()
        if not selected_items:
            QMessageBox.information(self, "Select Participant", "Please select at least one participant to delete.")
            return

        # Collect stream IDs from selected participants
        stream_ids_to_delete: List[str] = []
        stream_info: List[Tuple[str, str, str]] = []  # (stream_id, session_label, participant_name)

        for item in selected_items:
            stream_id = item.data(Qt.UserRole)
            if not stream_id:
                continue

            # Find the stream in sessions
            stream = None
            session_label = ""
            for session in self.sessions.values():
                if stream_id in session.streams:
                    stream = session.streams[stream_id]
                    session_label = session.label
                    break

            if stream:
                participant_name = stream.alias or stream.device_name or "Unknown"
                stream_ids_to_delete.append(stream_id)
                stream_info.append((stream_id, session_label, participant_name))

        if not stream_ids_to_delete:
            QMessageBox.information(self, "No Participants", "No valid participants found in selection.")
            return

        # Check if case is locked
        with dbm.get_session() as s:
            case = s.query(dbm.Case).filter_by(id=self._case_id).first()
            if not case:
                QMessageBox.warning(self, "Error", "Case not found.")
                return

            is_locked = getattr(case, 'is_locked', False)
            security_hash = getattr(case, 'security_hash', None)

        # Build warning message
        participant_list = "\n".join([f"  • {info[2]} ({info[1]})" for info in stream_info[:10]])
        if len(stream_info) > 10:
            participant_list += f"\n  ... and {len(stream_info) - 10} more"

        # First warning: Confirm deletion
        reply = QMessageBox.warning(
            self,
            "Delete Participant(s)",
            f"⚠️ DELETE {len(stream_ids_to_delete)} PARTICIPANT(S)\n\n"
            f"This will permanently delete:\n"
            f"{participant_list}\n\n"
            f"This includes:\n"
            f"  • All input events (button presses, stick movements)\n"
            f"  • Control mappings to constructs\n"
            f"  • All associated metadata\n\n"
            f"THIS CANNOT BE UNDONE!\n\n"
            f"Are you absolutely sure you want to delete these participants?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if reply != QMessageBox.Yes:
            log_access(self._case_id, "PARTICIPANT_DELETE_CANCELLED")
            return

        # Second confirmation: Type "DELETE" to confirm
        confirmation_text, ok = QInputDialog.getText(
            self,
            "Confirm Deletion",
            f"To confirm deletion of {len(stream_ids_to_delete)} participant(s), type DELETE in all caps:"
        )

        if not ok or confirmation_text != "DELETE":
            QMessageBox.information(self, "Cancelled", "Deletion cancelled - confirmation text did not match.")
            log_access(self._case_id, "PARTICIPANT_DELETE_CANCELLED")
            return

        # Third check: PIN if case is locked
        if is_locked and security_hash:
            pin = PinDialog.get_pin_from_user(
                self,
                "Delete Participant(s) - PIN Required",
                f"Enter case PIN to authorize deletion of {len(stream_ids_to_delete)} participant(s):"
            )

            if pin is None:
                log_access(self._case_id, "PARTICIPANT_DELETE_CANCELLED")
                return

            if not verify_pin(security_hash, pin):
                QMessageBox.warning(self, "Incorrect PIN", "Cannot delete participants - incorrect PIN.")
                log_access(self._case_id, "PARTICIPANT_DELETE_DENIED", success=False)
                return

        # Perform deletion
        try:
            self._do_delete_streams(stream_ids_to_delete)
            QMessageBox.information(
                self,
                "Deleted",
                f"{len(stream_ids_to_delete)} participant(s) have been permanently deleted."
            )
            log_access(self._case_id, f"PARTICIPANT_DELETE_COMPLETED ({len(stream_ids_to_delete)} participants)")

            # Reload and refresh
            self.sessions = self._load_sessions_strict(self.recording_id)
            self._populate_participant_list()
            self._plot()

        except Exception as e:
            QMessageBox.critical(self, "Delete Failed", f"Could not delete participants:\n{e}")
            log_access(self._case_id, "PARTICIPANT_DELETE_FAILED", success=False)

    def _do_delete_streams(self, stream_ids: List[str]):
        """Actually delete the input streams and all associated events."""
        with dbm.get_session() as s:
            for stream_id in stream_ids:
                stream = s.query(dbm.InputStream).filter_by(id=stream_id).first()
                if stream:
                    # Delete stream (cascades to events via relationship)
                    s.delete(stream)
            s.commit()

    # -------------- CONVERGENCE ANALYSIS --------------
    # This is the corrected _run_convergence_analysis method for researcher.py
    # Replace the existing method in your researcher.py file

    # This is the corrected _run_convergence_analysis method for researcher.py
    # Replace the existing method in your researcher.py file

    # This is the corrected _run_convergence_analysis method for researcher.py
    # Replace the existing method in your researcher.py file

    def _run_comprehensive_analysis(self):
        """Run comprehensive analysis on selected traces."""
        # Get selected traces
        selected_items = self.analysis_trace_list.selectedItems()

        if len(selected_items) == 0:
            QMessageBox.information(
                self,
                "Select Traces",
                "Please select at least one trace to analyze.\n\n"
                "• 1 trace: Descriptive statistics and change detection\n"
                "• 2 traces: Correlation and convergence analysis\n"
                "• 3+ traces: Multi-variate analysis with PCA"
            )
            return

        # Collect trace data
        trace_data = {}
        for item in selected_items:
            display_name = item.data(Qt.UserRole)
            data = self._trace_data_map.get(display_name)

            if not data:
                continue

            if data["kind"] == "axis":
                # Extract axis data
                series = data["series"]
                times_ms = np.array(series.times_ms, dtype=float)

                # Normalize values to -1 to 1
                vmin, vmax = series.vmin, series.vmax
                maxabs = max(abs(vmin), abs(vmax), 1)
                values = np.array(series.values_raw, dtype=float) / maxabs

                # Apply inversion if needed
                code = data["code"]
                if code in INVERT_AXIS_DEFAULT:
                    values = -values

                trace_data[display_name] = {
                    "times_ms": times_ms,
                    "values": values
                }

        if not trace_data:
            QMessageBox.warning(self, "No Data", "No valid trace data found.")
            return

        print(f"[researcher] Running comprehensive analysis on {len(trace_data)} trace(s)")

        # Show progress
        progress = QProgressDialog("Running comprehensive analysis...", None, 0, 0, self)
        progress.setWindowTitle("Analysis")
        progress.setWindowModality(Qt.WindowModal)
        progress.show()
        QApplication.processEvents()

        # Run analysis
        try:
            analyzer = ComprehensiveTraceAnalyzer(
                convergence_threshold=0.3,
                divergence_threshold=0.7,
                change_sensitivity=2.0,
                window_ms=2000
            )

            results = analyzer.analyze(trace_data)

            progress.close()

            # Create seek callback
            def seek_to_time(ms: int):
                """Callback to seek video to specific timestamp"""
                try:
                    self.scrub.setValue(int(ms))
                    self.media.setPosition(int(ms))
                    self._set_playhead_x(ms / 1000.0)
                    if self._follow_enabled:
                        self._recenter_on_playhead()
                except Exception as e:
                    print(f"[analysis] Seek failed: {e}")

            # Show results dialog with seek callback (exec makes it modal so it stays open)
            dialog = ComprehensiveResultsDialog(self, results, seek_callback=seek_to_time)
            dialog.exec()

        except Exception as e:
            progress.close()
            print(f"[researcher] Analysis error: {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(
                self,
                "Analysis Error",
                f"An error occurred during analysis:\n\n{e}"
            )

    # Keep the old convergence analysis for backward compatibility (optional)
    def _run_convergence_analysis(self):
        """Legacy convergence analysis - redirects to comprehensive analysis."""
        self._run_comprehensive_analysis()

    def _align_all_signals(self, signal_dict: Dict[str, Dict[str, np.ndarray]]) -> Dict[str, np.ndarray]:
        """
        Align all control signals to a common time base.

        Args:
            signal_dict: {"Signal Name": {"times_ms": array, "values": array}, ...}

        Returns:
            {"Signal Name": aligned_values_array, ...}
        """
        if not signal_dict:
            return {}

        # Find common time range across ALL signals
        try:
            min_time = max(data["times_ms"][0] for data in signal_dict.values() if len(data["times_ms"]) > 0)
            max_time = min(data["times_ms"][-1] for data in signal_dict.values() if len(data["times_ms"]) > 0)
        except (ValueError, IndexError) as e:
            print(f"[researcher] Error finding time range: {e}")
            return {}

        print(f"[researcher] Common time range: {min_time:.0f}ms to {max_time:.0f}ms")

        if min_time >= max_time:
            print(f"[researcher] No time overlap! min_time={min_time}, max_time={max_time}")
            # Try to use the broadest range instead
            min_time = min(data["times_ms"][0] for data in signal_dict.values() if len(data["times_ms"]) > 0)
            max_time = max(data["times_ms"][-1] for data in signal_dict.values() if len(data["times_ms"]) > 0)
            print(f"[researcher] Using broadest range instead: {min_time:.0f}ms to {max_time:.0f}ms")

        # Create common time base (1ms resolution)
        common_times = np.arange(min_time, max_time, 1, dtype=float)
        print(f"[researcher] Created common time base with {len(common_times)} points")

        # Interpolate each signal to common time base
        aligned_signals = {}
        for signal_name, data in signal_dict.items():
            times = data["times_ms"]
            values = data["values"]

            if len(times) < 2:
                print(f"[researcher] Skipping {signal_name}: insufficient data points ({len(times)})")
                continue

            try:
                # Interpolate (extrapolate if needed)
                interpolated = np.interp(common_times, times, values)
                aligned_signals[signal_name] = interpolated
                print(f"[researcher] Aligned {signal_name}: {len(interpolated)} points")
            except Exception as e:
                print(f"[researcher] Failed to align {signal_name}: {e}")
                continue

        print(f"[researcher] Successfully aligned {len(aligned_signals)} signals")
        return aligned_signals

        # -------------- helpers: playhead --------------

    def _set_playhead_x(self, x_seconds: float):
        self.playhead.setPos(x_seconds)

    def _recenter_on_playhead(self, init: bool = False):
        """Center the view around the playhead with the configured window width."""
        x = self.scrub.value() / 1000.0
        tmin, tmax = self._get_union_bounds_seconds()
        width = max(0.2, float(self._window_seconds))
        if tmax > tmin:
            half = width * 0.5
            left = max(tmin, min(x - half, tmax - width))
            right = left + width
        else:
            left, right = 0.0, width
        self.plot_item.setXRange(left, right, padding=0.0)

    # -------------- media & scrub --------------
    def _fmt(self, ms: int) -> str:
        ms = max(0, int(ms))
        s, _ = divmod(ms, 1000)
        m, s = divmod(s, 60)
        h, m = divmod(m, 60)
        return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

    def _on_media_pos_changed(self, ms: int):
        if not self._seeking:
            self.scrub.setValue(int(ms))
            self.lbl_pos.setText(self._fmt(ms))

    def _on_media_dur_changed(self, ms: int):
        self.scrub.setMaximum(max(0, int(ms)))
        self.lbl_dur.setText(self._fmt(ms))

    def _on_state_changed(self, _state):
        return

    def _tick_playhead(self):
        """Runs ~30 fps: update playhead & ensure NLE scroll."""
        try:
            ms_media = int(self.media.position())
            ms = ms_media

            try:
                playing = getattr(QMediaPlayer, "PlayingState", None)
                is_playing = (self.media.playbackState() == playing) if playing is not None else True
            except Exception:
                is_playing = True

            if is_playing and (ms_media <= 0 or (self._last_ms >= 0 and ms_media == self._last_ms)):
                ms = int(self.scrub.value())

            self._last_ms = ms

            x = ms / 1000.0
            self._set_playhead_x(x)

            if not self._seeking:
                self.scrub.setValue(ms)
                self.lbl_pos.setText(self._fmt(ms))

            if self._follow_enabled:
                left, right = self.plot_item.getViewBox().viewRange()[0]
                width = right - left
                if width <= 1e-6:
                    width = max(0.1, self._window_seconds)
                margin = min(0.5, width * 0.08)
                new_left, new_right = left, right
                if x >= right - margin:
                    desired_right = x + margin
                    new_left = desired_right - width
                    new_right = desired_right
                elif x <= left + margin:
                    desired_left = x - margin
                    new_left = desired_left
                    new_right = desired_left + width

                tmin, tmax = self._get_union_bounds_seconds()
                if new_left < tmin:
                    new_left, new_right = tmin, tmin + width
                if new_right > tmax:
                    new_right, new_left = tmax, tmax - width
                self.plot_item.setXRange(new_left, new_right, padding=0.0)
        except Exception:
            pass

    def _on_scrub_pressed(self):
        self._seeking = True

    def _on_scrub_moved(self, ms: int):
        self.media.setPosition(int(ms))

    def _on_scrub_released(self):
        self._seeking = False
        self.media.setPosition(int(self.scrub.value()))

    def _on_follow_changed(self, _state: int):
        self._follow_enabled = self.chk_follow.isChecked()
        if self._follow_enabled:
            self._recenter_on_playhead()

    def _on_window_changed(self, val: int):
        self._window_seconds = max(1.0, float(val))
        self._recenter_on_playhead()

    # -------------- DB load --------------
    def _load_sessions_strict(self, recording_id: str) -> Dict[str, SessionData]:
        """Load streams for sessions of this recording and fetch events."""
        with dbm.get_session() as s:
            sess = s.query(dbm.ObserverSession).filter_by(recording_id=recording_id).all()
            if not sess:
                return {}

            streams = s.query(dbm.InputStream).filter(
                dbm.InputStream.session_id.in_([x.id for x in sess])
            ).all()
            stream_ids = [st.id for st in streams]

            sessions_map: Dict[str, SessionData] = {}
            for ssn in sess:
                label = (ssn.label or "").strip() or f"Session {ssn.id[:8]}"
                sessions_map[ssn.id] = SessionData(id=ssn.id, label=label, streams={})

            for st in streams:
                ss = sessions_map.get(st.session_id)
                if not ss:
                    continue
                mapping: Dict[str, str] = {}
                raw = getattr(st, "construct_mapping", None)
                if raw is not None:
                    if isinstance(raw, dict):
                        mapping = {str(k): str(v) for k, v in raw.items() if v is not None}
                    else:
                        try:
                            d = json.loads(raw)
                            if isinstance(d, dict):
                                mapping = {str(k): str(v) for k, v in d.items() if v is not None}
                        except Exception:
                            mapping = {}

                alias = getattr(st, "alias", None)
                if alias:
                    alias = alias.strip() or None

                # NEW: Include session info in StreamData
                ss.streams[st.id] = StreamData(
                    id=st.id,
                    device_name=st.device_name or "Input",
                    profile_id=st.profile_id,
                    alias=alias,
                    control_labels=mapping,
                    axes={},
                    buttons={},
                    session_id=ss.id,
                    session_label=ss.label
                )

            if not stream_ids:
                return {k: v for k, v in sessions_map.items() if v.streams}

            axis_q = s.query(dbm.InputEvent).filter(
                dbm.InputEvent.stream_id.in_(list(stream_ids)),
                dbm.InputEvent.kind == "axis"
            ).order_by(
                dbm.InputEvent.stream_id, dbm.InputEvent.t_ms, dbm.InputEvent.code
            ).all()

            btn_q = s.query(dbm.InputEvent).filter(
                dbm.InputEvent.stream_id.in_(list(stream_ids)),
                dbm.InputEvent.kind == "button"
            ).order_by(
                dbm.InputEvent.stream_id, dbm.InputEvent.t_ms, dbm.InputEvent.code
            ).all()

            evkey_q = s.query(dbm.InputEvent).filter(
                dbm.InputEvent.stream_id.in_(list(stream_ids)),
                dbm.InputEvent.kind == "EV_KEY"
            ).order_by(
                dbm.InputEvent.stream_id, dbm.InputEvent.t_ms, dbm.InputEvent.code
            ).all()

            for ev in axis_q:
                ss = sessions_map.get(ev.session_id)
                if not ss:
                    continue
                st = ss.streams.get(ev.stream_id)
                if not st:
                    continue
                code = ev.code
                ser = st.axes.get(code)
                if not ser:
                    v0 = ev.value if ev.value is not None else 0
                    ser = AxisSeries(times_ms=[], values_raw=[], vmin=v0, vmax=v0)
                    st.axes[code] = ser
                ser.times_ms.append(ev.t_ms)
                ser.values_raw.append(ev.value if ev.value is not None else 0)
                ser.vmin = min(ser.vmin, ser.values_raw[-1])
                ser.vmax = max(ser.vmax, ser.values_raw[-1])

            for ev in btn_q:
                ss = sessions_map.get(ev.session_id)
                if not ss:
                    continue
                st = ss.streams.get(ev.stream_id)
                if not st:
                    continue
                code = ev.code
                bs = st.buttons.get(code)
                if not bs:
                    bs = ButtonSeries(presses_ms=[], releases_ms=[])
                    st.buttons[code] = bs
                if ev.is_press is True:
                    bs.presses_ms.append(ev.t_ms)
                elif ev.is_press is False:
                    bs.releases_ms.append(ev.t_ms)
                else:
                    bs.presses_ms.append(ev.t_ms)

            for ev in evkey_q:
                ss = sessions_map.get(ev.session_id)
                if not ss:
                    continue
                st = ss.streams.get(ev.stream_id)
                if not st:
                    continue
                code = ev.code
                bs = st.buttons.get(code)
                if not bs:
                    bs = ButtonSeries(presses_ms=[], releases_ms=[])
                    st.buttons[code] = bs
                val = getattr(ev, "value", None)
                if val == 1:
                    bs.presses_ms.append(ev.t_ms)
                elif val == 0:
                    bs.releases_ms.append(ev.t_ms)

        return {k: v for k, v in sessions_map.items() if v.streams}

    def _populate_participant_list(self):
        """Populate list with individual participants (streams) instead of sessions."""
        self.participant_list.clear()

        if not self.sessions:
            it = QListWidgetItem("(No participants found for this recording)")
            it.setFlags(it.flags() & ~Qt.ItemIsSelectable)
            self.participant_list.addItem(it)
            return

        # Iterate through sessions and list each stream (participant) separately
        for session_id, session_data in self.sessions.items():
            for stream_id, stream in session_data.streams.items():
                # Create display name
                participant_name = stream.alias or stream.device_name or "Unknown"
                session_label = session_data.label or f"Session {session_id[:8]}"

                display_text = f"{participant_name} ({session_label})"

                item = QListWidgetItem(display_text)
                # Store the stream_id (this is what we select/operate on)
                item.setData(Qt.UserRole, stream_id)
                # Store session_id as secondary data (for reference if needed)
                item.setData(Qt.UserRole + 1, session_id)
                item.setSelected(True)
                self.participant_list.addItem(item)

        # Also populate analysis trace list
        self._populate_analysis_traces()

    def _populate_analysis_traces(self):
        """Populate the analysis trace list with all available traces."""
        self.analysis_trace_list.clear()

        # Store trace data for quick access
        self._trace_data_map = {}  # {display_name: {data}}

        if not self.sessions:
            return

        for session_id, session_data in self.sessions.items():
            for stream_id, stream in session_data.streams.items():
                participant_name = stream.alias or stream.device_name or "Unknown"
                session_label = session_data.label or f"Session {session_id[:8]}"
                label_map = stream.control_labels or {}

                # Add all axes
                for code, series in stream.axes.items():
                    # Skip hidden controls
                    if label_map.get(code) == HIDE_SENTINEL:
                        continue

                    # Create display name
                    construct = label_map.get(code, code)
                    display_name = f"{participant_name}: {construct} ({session_label})"

                    # Add to list
                    item = QListWidgetItem(display_name)
                    item.setData(Qt.UserRole, display_name)
                    self.analysis_trace_list.addItem(item)

                    # Store trace data
                    self._trace_data_map[display_name] = {
                        "stream": stream,
                        "code": code,
                        "series": series,
                        "kind": "axis"
                    }

        print(f"[researcher] Populated {self.analysis_trace_list.count()} traces for analysis")

    # -------------- plotting --------------
    @staticmethod
    def _normalize_centered(values: List[int], code: str, vmin: int, vmax: int) -> np.ndarray:
        arr = np.asarray(values, dtype=float)
        arr = np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0)
        vmin = 0 if vmin is None else vmin
        vmax = 0 if vmax is None else vmax
        maxabs = max(abs(vmin), abs(vmax), 1)
        sgn = -1.0 if code in INVERT_AXIS_DEFAULT else 1.0
        return sgn * (arr / float(maxabs))

    @staticmethod
    def _pretty_label(labels: Dict[str, str], code: str, participant_name: Optional[str] = None) -> Tuple[str, bool]:
        lab = (labels or {}).get(code)
        if lab is None or lab.strip() == "":
            base_label = code
        elif lab.strip() == HIDE_SENTINEL:
            return code, True
        else:
            base_label = lab

        if participant_name:
            return f"{participant_name}: {base_label}", False
        return base_label, False

    def _color_for_code(self, code: str):
        if code in self._color_cache:
            return self._color_cache[code]
        tab = [
            (31, 119, 180), (255, 127, 14), (44, 160, 44), (214, 39, 40), (148, 103, 189),
            (140, 86, 75), (227, 119, 194), (127, 127, 127), (188, 189, 34), (23, 190, 207),
            (174, 199, 232), (255, 187, 120), (152, 223, 138), (255, 152, 150), (197, 176, 213),
            (196, 156, 148), (247, 182, 210), (199, 199, 199), (219, 219, 141), (158, 218, 229)
        ]
        h = int(hashlib.sha1(code.encode("utf-8")).hexdigest(), 16)
        color = tab[h % len(tab)]
        self._color_cache[code] = color
        return color

    def _clear_plot(self):
        self.plot_item.clear()
        self.plot_item.showGrid(x=True, y=True, alpha=0.25)
        self.plot_item.setLabel("left", "Axis value (normalized)")
        self.plot_item.setYRange(-1.2, 1.2, padding=0.0)
        self.plot_item.addLegend(offset=(-5, 5))
        self.playhead = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen((70, 70, 70), width=2, style=Qt.DashLine))
        self.playhead.setZValue(10_000)
        self.plot_item.addItem(self.playhead)
        self._curve_items.clear()
        self._press_items.clear()
        self._release_items.clear()

    def _accum_extent(self, tmin_ms: int, tmax_ms: int):
        self._tmin_ms = tmin_ms if self._tmin_ms is None else min(self._tmin_ms, tmin_ms)
        self._tmax_ms = tmax_ms if self._tmax_ms is None else max(self._tmax_ms, tmax_ms)

    def _get_duration_bounds_seconds(self) -> Tuple[float, float]:
        dur_s = float(self.scrub.maximum()) / 1000.0
        return (0.0, dur_s) if dur_s > 0 else (0.0, 0.0)

    def _get_data_bounds_seconds(self) -> Tuple[float, float]:
        if self._tmin_ms is not None and self._tmax_ms is not None and self._tmax_ms > self._tmin_ms:
            return float(self._tmin_ms) / 1000.0, float(self._tmax_ms) / 1000.0
        return float("inf"), float("-inf")

    def _get_union_bounds_seconds(self) -> Tuple[float, float]:
        d0, d1 = self._get_duration_bounds_seconds()
        a0, a1 = self._get_data_bounds_seconds()
        left = min(d0, a0) if np.isfinite(a0) else d0
        right = max(d1, a1) if np.isfinite(a1) else d1
        if right <= left:
            right = max(left + 0.1, right)
        return left, right

    def _as_step_xy(self, x: np.ndarray, y: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        if x.size == 0 or y.size == 0:
            return x, y
        if x.size == y.size + 1:
            return x, y
        if x.size == y.size:
            if x.size == 1:
                x_pad = np.array([x[0] + 0.033], dtype=float)
            else:
                dt = float(np.median(np.diff(x)))
                if not np.isfinite(dt) or dt <= 0:
                    dt = 0.033
                x_pad = np.array([x[-1] + dt], dtype=float)
            return np.concatenate([x, x_pad]), y
        return x, y

    def _plot(self):
        """Plot selected participants' data."""
        self._clear_plot()

        show_axes = self.chk_axes.isChecked()
        show_btns = self.chk_btns.isChecked()

        # Get selected stream IDs
        selected_stream_ids: Set[str] = {
            self.participant_list.item(i).data(Qt.UserRole)
            for i in range(self.participant_list.count())
            if self.participant_list.item(i).isSelected()
        }

        # If nothing selected, select all
        if not selected_stream_ids and self.participant_list.count() > 0:
            for i in range(self.participant_list.count()):
                it = self.participant_list.item(i)
                if it.flags() & Qt.ItemIsSelectable:
                    it.setSelected(True)
            selected_stream_ids = {
                self.participant_list.item(i).data(Qt.UserRole)
                for i in range(self.participant_list.count())
                if self.participant_list.item(i).isSelected()
            }

        self._tmin_ms = None
        self._tmax_ms = None
        any_points = False

        # Calculate time offset
        self._time_offset_ms = 0
        min_ms = None
        for session in self.sessions.values():
            for stream_id, st in session.streams.items():
                if stream_id not in selected_stream_ids:
                    continue
                for ser in st.axes.values():
                    if ser.times_ms:
                        t0 = min(ser.times_ms)
                        min_ms = t0 if min_ms is None else min(min_ms, t0)
                for bs in st.buttons.values():
                    if bs.presses_ms:
                        t0 = min(bs.presses_ms)
                        min_ms = t0 if min_ms is None else min(min_ms, t0)
                    if bs.releases_ms:
                        t0 = min(bs.releases_ms)
                        min_ms = t0 if min_ms is None else min(min_ms, t0)
        if min_ms is not None and min_ms > 1000:
            self._time_offset_ms = int(min_ms)

        # Plot each selected participant
        for session in self.sessions.values():
            for stream_id, st in session.streams.items():
                if stream_id not in selected_stream_ids:
                    continue

                labels = st.control_labels or {}
                participant_name = st.alias

                if show_axes:
                    for code, ser in st.axes.items():
                        if not ser.times_ms:
                            continue
                        disp, hidden = self._pretty_label(labels, code, participant_name)
                        if hidden:
                            continue

                        x = (np.asarray(ser.times_ms, dtype=float) - float(self._time_offset_ms)) / 1000.0
                        y = self._normalize_centered(ser.values_raw, code, ser.vmin, ser.vmax)

                        m = np.isfinite(x) & np.isfinite(y)
                        if not np.any(m):
                            continue
                        x = x[m]
                        y = y[m]

                        if x.size == 1:
                            x = np.array([x[0], x[0] + 0.033], dtype=float)
                            y = np.array([y[0]], dtype=float)

                        color = self._color_for_code(code)
                        x_step, y_step = self._as_step_xy(x, y)

                        if x_step.size == y_step.size + 1 and y_step.size > 0:
                            curve = pg.PlotDataItem(
                                x_step, y_step, stepMode=True, connect="finite",
                                pen=pg.mkPen(color, width=1.3),
                                name=disp
                            )
                        else:
                            if x.size < 2:
                                continue
                            curve = pg.PlotDataItem(
                                x, y, connect="finite",
                                pen=pg.mkPen(color, width=1.3),
                                name=disp
                            )

                        self.plot_item.addItem(curve)
                        self._curve_items[f"{st.id}|{code}"] = curve
                        self._accum_extent(int(1000 * x.min()), int(1000 * x.max()))
                        any_points = True

                if show_btns:
                    for code, bs in st.buttons.items():
                        disp, hidden = self._pretty_label(labels, code, participant_name)
                        if hidden:
                            continue
                        color = self._color_for_code(code)

                        pts = 0
                        if bs.presses_ms:
                            xp = (np.asarray(bs.presses_ms, dtype=float) - float(self._time_offset_ms)) / 1000.0
                            yp = np.full_like(xp, 1.05, dtype=float)
                            press_item = pg.ScatterPlotItem(
                                x=xp, y=yp,
                                pen=pg.mkPen(color),
                                brush=pg.mkBrush(color),
                                size=5,
                                name=f"{disp} press"
                            )
                            self.plot_item.addItem(press_item)
                            self._press_items[f"{st.id}|{code}"] = press_item
                            self._accum_extent(int(1000 * xp.min()), int(1000 * xp.max()))
                            pts += len(bs.presses_ms)

                        if bs.releases_ms:
                            xr = (np.asarray(bs.releases_ms, dtype=float) - float(self._time_offset_ms)) / 1000.0
                            yr = np.full_like(xr, -1.05, dtype=float)
                            release_item = pg.ScatterPlotItem(
                                x=xr, y=yr,
                                pen=pg.mkPen(color),
                                brush=pg.mkBrush(color),
                                size=5,
                                name=f"{disp} release"
                            )
                            self.plot_item.addItem(release_item)
                            self._release_items[f"{st.id}|{code}"] = release_item
                            self._accum_extent(int(1000 * xr.min()), int(1000 * xr.max()))
                            pts += len(bs.releases_ms)

                        if pts:
                            any_points = True

        self._set_playhead_x(self.scrub.value() / 1000.0)

        if any_points:
            # Auto-range Y-axis only (not X-axis) to fit the data properly
            vb = self.plot_item.getViewBox()

            # Get current X range to preserve/modify it
            left, right = vb.viewRange()[0]

            # Enable auto-range for Y-axis only, then update it
            vb.enableAutoRange(axis=vb.YAxis)
            vb.updateAutoRange()
            vb.disableAutoRange(axis=vb.YAxis)

            # Now handle X-axis positioning
            d0, d1 = self._get_data_bounds_seconds()

            if not hasattr(self, '_initial_plot_done'):
                # On initial load, show the data from 0 to either:
                # - the end of data (if data is short), or
                # - window_seconds (if data is longer than window)
                if np.isfinite(d0) and np.isfinite(d1):
                    data_span = d1 - d0
                    # Show all data if it fits in window, otherwise show window_seconds
                    if data_span <= self._window_seconds:
                        # Show all data with a bit of padding
                        span = max(data_span * 1.1, 1.0)
                    else:
                        # Data is longer than window, just show window_seconds
                        span = self._window_seconds
                else:
                    span = max(self._window_seconds, 1.0)
                self.plot_item.setXRange(0.0, span, padding=0.0)
                self._initial_plot_done = True
            elif np.isfinite(d0) and np.isfinite(d1) and (right < d0 or left > d1):
                # View is outside data bounds, reset to show data starting at d0
                span = max(self._window_seconds, 1.0)
                self.plot_item.setXRange(d0, d0 + span, padding=0.0)
            # else: keep current X range (don't change it for normal redraws)

        # Count axes and buttons across all sessions
        axes_cnt = sum(len(st.axes) for ss in self.sessions.values() for st in ss.streams.values())
        btn_cnt = sum(len(st.buttons) for ss in self.sessions.values() for st in ss.streams.values())
        d0, d1 = self._get_data_bounds_seconds()
        if np.isfinite(d0) and np.isfinite(d1):
            self.status_lbl.setText(
                f"Loaded: {axes_cnt} axis series, {btn_cnt} button codes; data window {d0:.2f}s -> {d1:.2f}s")
        else:
            self.status_lbl.setText(f"Loaded: {axes_cnt} axis series, {btn_cnt} button codes; no time bounds detected")

    def _refresh_plot_full(self):
        """Refresh plot and reset to initial auto-range view (like first load)."""
        # Reset the flag so _plot() will do full auto-range
        if hasattr(self, '_initial_plot_done'):
            delattr(self, '_initial_plot_done')
        self._plot()

    def _reset_view(self):
        left, right = self._get_union_bounds_seconds()
        span = right - left
        if span <= 0.0:
            left, right = 0.0, max(0.1, self._window_seconds)
        elif span > self._window_seconds:
            right = left + self._window_seconds
        self.plot_item.setXRange(left, right, padding=0.0)
        if self._follow_enabled:
            self._recenter_on_playhead()

    def _zoom(self, factor: float):
        vb = self.plot_item.getViewBox()
        (left, right), _ = vb.viewRange()
        width = max(1e-6, right - left)
        x = self.scrub.value() / 1000.0
        tmin, tmax = self._get_union_bounds_seconds()
        full_span = max(0.2, tmax - tmin)
        new_width = max(0.2, min(width * factor, full_span))
        new_left = x - (x - left) * (new_width / width)
        new_right = new_left + new_width
        if new_left < tmin:
            new_left, new_right = tmin, tmin + new_width
        if new_right > tmax:
            new_right, new_left = tmax, tmax - new_width
        vb.setXRange(new_left, new_right, padding=0.0)

    def _open_map_dialog_for_selection(self):
        """Open control mapping dialog for selected participant."""
        selected_items = [
            self.participant_list.item(i)
            for i in range(self.participant_list.count())
            if self.participant_list.item(i).isSelected()
        ]

        if not selected_items:
            QMessageBox.information(self, "Map Controls", "Select at least one participant.")
            return

        # Get stream IDs
        stream_ids = [item.data(Qt.UserRole) for item in selected_items if item.data(Qt.UserRole)]

        if not stream_ids:
            return

        stream_id: Optional[str] = None
        if len(stream_ids) == 1:
            stream_id = stream_ids[0]
        else:
            # Multiple selected - let user choose
            dlg = QDialog(self)
            dlg.setWindowTitle("Choose a participant to map")
            v = QVBoxLayout(dlg)
            lst = QListWidget()
            v.addWidget(lst)

            for sid in stream_ids:
                # Find the stream
                for session in self.sessions.values():
                    if sid in session.streams:
                        stream = session.streams[sid]
                        participant_name = stream.alias or stream.device_name or "Unknown"
                        session_label = session.label
                        display = f"{participant_name} ({session_label})"
                        it = QListWidgetItem(display)
                        it.setData(Qt.UserRole, sid)
                        lst.addItem(it)
                        break

            btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            v.addWidget(btns)
            btns.accepted.connect(dlg.accept)
            btns.rejected.connect(dlg.reject)
            if dlg.exec() == QDialog.Accepted:
                it = lst.currentItem()
                if not it:
                    return
                stream_id = it.data(Qt.UserRole)

        if not stream_id:
            return

        try:
            m = ControlMapDialog(self, stream_id=stream_id)
            if m.exec() == QDialog.Accepted:
                # Remember old selection
                old_selected = {
                    self.participant_list.item(i).data(Qt.UserRole)
                    for i in range(self.participant_list.count())
                    if self.participant_list.item(i).isSelected()
                }
                # Reload data
                self.sessions = self._load_sessions_strict(self.recording_id)
                self._populate_participant_list()
                # Restore selection
                for i in range(self.participant_list.count()):
                    sid = self.participant_list.item(i).data(Qt.UserRole)
                    if sid in old_selected:
                        self.participant_list.item(i).setSelected(True)
                self._plot()
        except Exception as e:
            QMessageBox.critical(self, "Map Controls", f"Could not open mapping dialog:\n{e}")

    # -------------- export helpers --------------
    def _collect_selected(self) -> List[StreamData]:
        """Collect selected participant streams for export."""
        selected_stream_ids: Set[str] = {
            self.participant_list.item(i).data(Qt.UserRole)
            for i in range(self.participant_list.count())
            if self.participant_list.item(i).isSelected()
        }

        streams: List[StreamData] = []
        for session in self.sessions.values():
            for stream_id, stream in session.streams.items():
                if stream_id in selected_stream_ids:
                    streams.append(stream)

        return streams

    def _update_export_ui(self):
        """Show/hide sampling rate based on export format."""
        is_timeseries = self.export_format_combo.currentData() == "timeseries"

        # Show/hide the sampling rate row
        self.rate_label.setVisible(is_timeseries)
        self.sampling_rate_combo.setVisible(is_timeseries)

    def _build_dataframes(self) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """Build DataFrames in either event-driven or time-series format."""
        export_format = self.export_format_combo.currentData()

        if export_format == "event":
            return self._build_event_dataframes()
        else:  # timeseries
            sampling_rate = self.sampling_rate_combo.currentData()
            return self._build_timeseries_dataframes(sampling_rate)

    def _build_event_dataframes(self) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """Build event-driven DataFrames (existing implementation)."""
        streams = self._collect_selected()
        axes_rows: List[dict] = []
        btn_rows: List[dict] = []

        case_id = self._case_id

        for st in streams:
            labels = st.control_labels or {}
            participant_name = st.alias or st.device_name

            for code, ser in st.axes.items():
                construct = (labels.get(code) or "").strip()
                if construct == HIDE_SENTINEL:
                    continue
                for t_ms, val in zip(ser.times_ms, ser.values_raw):
                    axes_rows.append({
                        "recording_id": self.recording_id, "case_id": case_id,
                        "session_id": st.session_id, "session_label": st.session_label,
                        "stream_id": st.id, "participant": participant_name,
                        "device_name": st.device_name,
                        "profile_id": st.profile_id, "code": code,
                        "construct": construct, "t_ms": int(t_ms), "value": int(val),
                    })
            for code, bs in st.buttons.items():
                construct = (labels.get(code) or "").strip()
                if construct == HIDE_SENTINEL:
                    continue
                for t_ms in bs.presses_ms:
                    btn_rows.append({
                        "recording_id": self.recording_id, "case_id": case_id,
                        "session_id": st.session_id, "session_label": st.session_label,
                        "stream_id": st.id, "participant": participant_name,
                        "device_name": st.device_name,
                        "profile_id": st.profile_id, "code": code,
                        "construct": construct, "t_ms": int(t_ms), "event": "press",
                    })
                for t_ms in bs.releases_ms:
                    btn_rows.append({
                        "recording_id": self.recording_id, "case_id": case_id,
                        "session_id": st.session_id, "session_label": st.session_label,
                        "stream_id": st.id, "participant": participant_name,
                        "device_name": st.device_name,
                        "profile_id": st.profile_id, "code": code,
                        "construct": construct, "t_ms": int(t_ms), "event": "release",
                    })

        axes_df = pd.DataFrame(axes_rows)
        btn_df = pd.DataFrame(btn_rows)
        if not axes_df.empty:
            axes_df = axes_df.sort_values(["session_id", "stream_id", "code", "t_ms"]).reset_index(drop=True)
        if not btn_df.empty:
            btn_df = btn_df.sort_values(["session_id", "stream_id", "code", "t_ms"]).reset_index(drop=True)
        return axes_df, btn_df

    def _build_timeseries_dataframes(self, sampling_rate_hz: int) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """Build time-series DataFrames with regular sampling."""
        from hsparc.utils.timeseries_converter import TimeSeriesConverter

        converter = TimeSeriesConverter(sampling_rate_hz=sampling_rate_hz)
        streams = self._collect_selected()
        case_id = self._case_id

        # Find total duration (max timestamp across all streams)
        max_time_ms = 0
        for st in streams:
            for ser in st.axes.values():
                if ser.times_ms:
                    max_time_ms = max(max_time_ms, max(ser.times_ms))
            for bs in st.buttons.values():
                if bs.presses_ms:
                    max_time_ms = max(max_time_ms, max(bs.presses_ms))
                if bs.releases_ms:
                    max_time_ms = max(max_time_ms, max(bs.releases_ms))

        if max_time_ms == 0:
            return pd.DataFrame(), pd.DataFrame()

        # Build time-series rows
        axes_rows: List[dict] = []
        btn_rows: List[dict] = []

        for st in streams:
            labels = st.control_labels or {}
            participant_name = st.alias or st.device_name

            # Convert axes
            for code, ser in st.axes.items():
                construct = (labels.get(code) or "").strip()
                if construct == HIDE_SENTINEL:
                    continue

                if not ser.times_ms:
                    continue

                regular_times, regular_values = converter.convert_axis_events(
                    ser.times_ms, ser.values_raw, interpolation="forward_fill"
                )

                for t_ms, val in zip(regular_times, regular_values):
                    axes_rows.append({
                        "recording_id": self.recording_id, "case_id": case_id,
                        "session_id": st.session_id, "session_label": st.session_label,
                        "stream_id": st.id, "participant": participant_name,
                        "device_name": st.device_name,
                        "profile_id": st.profile_id, "code": code,
                        "construct": construct, "t_ms": int(t_ms), "value": int(val),
                    })

            # Convert buttons
            for code, bs in st.buttons.items():
                construct = (labels.get(code) or "").strip()
                if construct == HIDE_SENTINEL:
                    continue

                regular_times, button_state = converter.convert_button_events(
                    bs.presses_ms, bs.releases_ms, max_time_ms
                )

                for t_ms, state in zip(regular_times, button_state):
                    btn_rows.append({
                        "recording_id": self.recording_id, "case_id": case_id,
                        "session_id": st.session_id, "session_label": st.session_label,
                        "stream_id": st.id, "participant": participant_name,
                        "device_name": st.device_name,
                        "profile_id": st.profile_id, "code": code,
                        "construct": construct, "t_ms": int(t_ms),
                        "state": int(state),  # 0=released, 1=pressed
                    })

        axes_df = pd.DataFrame(axes_rows)
        btn_df = pd.DataFrame(btn_rows)

        if not axes_df.empty:
            axes_df = axes_df.sort_values(["t_ms", "session_id", "stream_id", "code"]).reset_index(drop=True)
        if not btn_df.empty:
            btn_df = btn_df.sort_values(["t_ms", "session_id", "stream_id", "code"]).reset_index(drop=True)

        return axes_df, btn_df
        axes_df = pd.DataFrame(axes_rows)
        btn_df = pd.DataFrame(btn_rows)
        if not axes_df.empty:
            axes_df = axes_df.sort_values(["session_id", "stream_id", "code", "t_ms"]).reset_index(drop=True)
        if not btn_df.empty:
            btn_df = btn_df.sort_values(["session_id", "stream_id", "code", "t_ms"]).reset_index(drop=True)
        return axes_df, btn_df

    def _export_xlsx(self):
        axes_df, btn_df = self._build_dataframes()
        if axes_df.empty and btn_df.empty:
            QMessageBox.information(self, "Export", "No data to export for the current selection.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save XLSX", "hsparc_export.xlsx", "Excel Workbook (*.xlsx)")
        if not path:
            return
        try:
            with pd.ExcelWriter(path, engine="openpyxl") as writer:
                if not axes_df.empty:
                    axes_df.to_excel(writer, sheet_name="axes_changes", index=False)
                if not btn_df.empty:
                    btn_df.to_excel(writer, sheet_name="button_events", index=False)
            QMessageBox.information(self, "Export", f"Saved:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "Export failed", f"Could not save XLSX files:\n{e}")

    def _export_sav(self):
        axes_df, btn_df = self._build_dataframes()
        if axes_df.empty and btn_df.empty:
            QMessageBox.information(self, "Export", "No data to export for the current selection.")
            return
        dir_path = QFileDialog.getExistingDirectory(self, "Choose folder for SPSS .sav files")
        if not dir_path:
            return
        try:
            axes_path = str(Path(dir_path) / "hsparc_axes_changes.sav")
            btn_path = str(Path(dir_path) / "hsparc_button_events.sav")

            if not axes_df.empty:
                df = axes_df.copy()
                column_labels_axes = {
                    "recording_id": "Recording ID", "case_id": "Case ID", "session_id": "Session ID",
                    "session_label": "Session Label", "stream_id": "Stream ID",
                    "participant": "Participant Name",
                    "device_name": "Device Name",
                    "profile_id": "Profile ID", "code": "Axis code",
                    "construct": "Mapped construct label (blank if none)",
                    "t_ms": "Time (ms)", "value": "Raw axis value (centered)"
                }
                pyreadstat.write_sav(df, axes_path, column_labels=column_labels_axes)

            if not btn_df.empty:
                df = btn_df.copy()
                df["event_code"] = df["event"].map({"press": 1, "release": 2}).astype("Int64")
                column_labels_btn = {
                    "recording_id": "Recording ID", "case_id": "Case ID", "session_id": "Session ID",
                    "session_label": "Session Label", "stream_id": "Stream ID",
                    "participant": "Participant Name",
                    "device_name": "Device Name",
                    "profile_id": "Profile ID", "code": "Button code",
                    "construct": "Mapped construct label (blank if none)",
                    "t_ms": "Time (ms)", "event": "Button event (press/release)",
                    "event_code": "Button event code"
                }
                value_labels = {"event_code": {1: "press", 2: "release"}}
                pyreadstat.write_sav(df, btn_path, column_labels=column_labels_btn,
                                     variable_value_labels=value_labels)

            QMessageBox.information(self, "Export", f"Saved:\n{axes_path}\n{btn_path}")
        except Exception as e:
            QMessageBox.critical(self, "Export failed", f"Could not save SPSS files:\n{e}")

    def _export_csv(self):
        axes_df, btn_df = self._build_dataframes()
        if axes_df.empty and btn_df.empty:
            QMessageBox.information(self, "Export", "No data to export for the current selection.")
            return
        dir_path = QFileDialog.getExistingDirectory(self, "Choose folder for CSV files")
        if not dir_path:
            return
        try:
            axes_path = Path(dir_path) / "hsparc_axes_changes.csv"
            btn_path = Path(dir_path) / "hsparc_button_events.csv"
            if not axes_df.empty:
                axes_df.to_csv(axes_path, index=False)
            if not btn_df.empty:
                btn_df.to_csv(btn_path, index=False)
            QMessageBox.information(self, "Export", f"Saved:\n{axes_path}\n{btn_path}")
        except Exception as e:
            QMessageBox.critical(self, "Export failed", f"Could not save CSV files:\n{e}")

    def closeEvent(self, ev):
        try:
            self._cursor_timer.stop()
        except Exception:
            pass
        try:
            self.media.stop()
            self.media.setSource(QUrl())
        except Exception:
            pass

        # Clean up temp decrypted file
        if self._temp_video_path:
            try:
                Path(self._temp_video_path).unlink(missing_ok=True)
                print(f"[researcher] Cleaned up temp video: {self._temp_video_path}")
            except Exception as e:
                print(f"[researcher] Failed to clean up temp video: {e}")

        super().closeEvent(ev)

    def _open_av_settings(self):
        """Open A/V settings dialog."""
        dialog = AVSettingsDialog(self)
        dialog.exec()