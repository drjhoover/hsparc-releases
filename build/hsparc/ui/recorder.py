# hsparc/ui/recorder.py
"""
HSPARC Video Recorder Window

This module provides the recording interface for capturing video and synchronized
gamepad input. Uses GlobalAVManager for all A/V device settings.
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Tuple

from uuid import uuid4

from PySide6.QtCore import Qt, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QComboBox, QCheckBox, QMessageBox, QStatusBar, QSplitter
)
from PySide6.QtMultimedia import (
    QMediaRecorder, QMediaCaptureSession, QCamera, QAudioInput,
    QMediaFormat, QAudioDevice, QMediaDevices, QAudioOutput
)
from PySide6.QtMultimediaWidgets import QVideoWidget

from hsparc.models import db as dbm
from hsparc.models.db import Recording, ObserverSession, InputStream, InputEvent, Study
from hsparc.ui.widgets.assign_dialog import AssignControllersDialog
from hsparc.input.gamepad import GamepadPoller
from hsparc.ui.global_av_manager import GlobalAVManager
from hsparc.ui.av_settings_dialog import AVSettingsDialog

# Media output directory
MEDIA_ROOT = Path.home() / ".local" / "share" / "hsparc" / "media"
MEDIA_ROOT.mkdir(parents=True, exist_ok=True)


class RecorderWindow(QMainWindow):
    """
    Main recorder window for capturing video and gamepad input.

    This window provides:
    - Live camera preview
    - Unified A/V control panel (always visible)
    - Controller assignment and input capture
    - Recording start/stop controls

    Signals:
        recordingSaved: Emitted when a recording is successfully saved (with recording_id)
    """

    # Signal emitted when recording is saved
    recordingSaved = Signal(str)

    def __init__(self, parent=None, case_id: Optional[str] = None, study_pin: Optional[str] = None):
        """
        Initialize the recorder window.

        Args:
            parent: Parent widget
            case_id: Optional study ID to pre-select in dropdown
            study_pin: Study PIN for automatic video encryption
        """
        super().__init__(parent)
        self.setWindowTitle("HSPARC – Recorder")
        self.resize(1400, 800)
        self.setWindowFlags(Qt.Window)

        # Store study PIN for automatic encryption
        self.study_pin = study_pin

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

        # Study/recording state
        self.case_id = case_id
        self._recording_id: Optional[str] = None
        self._session_id: Optional[str] = None
        self._t0_monotonic: float = 0.0  # Time reference for gamepad timestamps
        self._poller: Optional[GamepadPoller] = None  # Gamepad polling thread

        # Controller assignments: {"A": {path, name}, "B": {path, name}}
        self.assigned: Dict[str, Optional[dict]] = {"A": None, "B": None}

        # Window state
        self._is_closing = False
        self._is_recording = False

        # Qt6 multimedia components (created fresh each time)
        self._camera: Optional[QCamera] = None
        self._audio_input: Optional[QAudioInput] = None
        self._capture_session: Optional[QMediaCaptureSession] = None
        self._recorder: Optional[QMediaRecorder] = None
        self._video_widget: Optional[QVideoWidget] = None

        # Flag to track camera initialization
        self._camera_initialized = False

        # Get global A/V manager
        self.av_manager = GlobalAVManager.instance()

        # ========== Build UI ==========
        self._setup_ui()

        # Show window
        self.show()

    def _setup_ui(self):
        """Build the user interface."""
        central = QWidget(self)
        root = QVBoxLayout(central)

        # ===== Top Control Row =====
        row = QHBoxLayout()

        # Study selection
        row.addWidget(QLabel("Study:", self))
        self.case_combo = QComboBox(self)
        row.addWidget(self.case_combo, 1)

        # Controller capture checkbox
        self.chk_capture_pad = QCheckBox("Capture Controller Input", self)
        self.chk_capture_pad.setChecked(True)
        self.chk_capture_pad.setToolTip(
            "Check this to record gamepad input synchronized with video.\n"
            "Uncheck for video-only recording."
        )
        row.addWidget(self.chk_capture_pad)

        # Assign controllers button
        self.btn_assign = QPushButton("Assign Controllers…", self)
        self.btn_assign.setToolTip("Assign physical controllers to Participant A and B")
        row.addWidget(self.btn_assign)

        root.addLayout(row)

        # ===== Main Content: Splitter =====
        splitter = QSplitter(Qt.Horizontal)
        root.addWidget(splitter, 1)

        # Left side: Camera preview
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)

        preview_label = QLabel("Camera Preview")
        preview_label.setStyleSheet("font-weight: bold;")
        left_layout.addWidget(preview_label)

        # Create video widget for camera preview
        self._video_widget = QVideoWidget(self)
        self._video_widget.setMinimumSize(640, 480)
        left_layout.addWidget(self._video_widget, 1)

        # Status label (shown when camera unavailable)
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #666; font-size: 14px;")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.hide()
        left_layout.addWidget(self.status_label)

        splitter.addWidget(left_widget)

        splitter.setSizes([800, 600])

        # ===== Recording Controls =====
        ctrl = QHBoxLayout()

        self.btn_start = QPushButton("Start Recording", self)
        self.btn_start.setStyleSheet("""
            QPushButton {
                background-color: #d9534f;
                color: white;
                padding: 10px 20px;
                font-size: 14px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #c9302c;
            }
            QPushButton:disabled {
                background-color: #cccccc;
                color: #666666;
            }
        """)

        self.btn_stop = QPushButton("Stop", self)
        self.btn_stop.setEnabled(False)
        self.btn_stop.setStyleSheet("""
            QPushButton {
                padding: 10px 20px;
                font-size: 14px;
            }
        """)

        ctrl.addWidget(self.btn_start)
        ctrl.addWidget(self.btn_stop)
        ctrl.addStretch(1)

        # Close button
        self.btn_close = QPushButton("Close Recorder", self)
        self.btn_close.setStyleSheet("""
            QPushButton {
                background-color: #5bc0de;
                color: white;
                padding: 8px 16px;
                border-radius: 4px;
            }
        """)
        self.btn_close.clicked.connect(self.close)
        ctrl.addWidget(self.btn_close)

        root.addLayout(ctrl)

        # ===== Set Central Widget =====
        self.setCentralWidget(central)
        self.setStatusBar(QStatusBar(self))

        # ===== Connect Signals =====
        self.btn_assign.clicked.connect(self._assign_controllers)
        self.btn_start.clicked.connect(self._start)
        self.btn_stop.clicked.connect(self._stop)

        # ===== Populate Studies =====
        self._populate_cases()

    def _populate_cases(self):
        """Populate the study dropdown with available studies."""
        self.case_combo.clear()

        with dbm.get_session() as s:
            # Get all studies
            rows = list(s.query(Study).order_by(Study.created_utc).all())

            # Create default study if none exist
            if not rows:
                cid = uuid4().hex
                s.add(Study(
                    id=cid,
                    label="Default",
                    created_utc=datetime.now(timezone.utc)
                ))
                s.commit()
                rows = [s.get(Study, cid)]

            # Add studies to dropdown
            for r in rows:
                self.case_combo.addItem(r.label, r.id)

        # Pre-select provided case_id
        if self.case_id:
            idx = max(0, self.case_combo.findData(self.case_id))
            self.case_combo.setCurrentIndex(idx)
        else:
            # Use currently selected
            idx = self.case_combo.currentIndex()
            if idx >= 0:
                self.case_id = self.case_combo.itemData(idx)

    def _initialize_camera(self):
        """
        Initialize camera and audio for preview.

        This is called when the window is first shown or after device changes.
        Creates fresh Qt6 multimedia objects and starts the camera preview.
        """
        print("[recorder] Initializing camera...")

        # CRITICAL: Full cleanup first to release any held devices
        self._cleanup_media_completely()

        # Give OS time to release devices
        time.sleep(0.3)

        try:
            # ========== Get Camera Device from GlobalAVManager ==========
            camera_device = self.av_manager.get_current_camera()
            if not camera_device:
                print("[recorder] No camera available")
                self._show_error("No cameras detected")
                return

            print(f"[recorder] Using camera: {camera_device.description()}")

            # Create camera object
            self._camera = QCamera(camera_device)

            # ========== Create Capture Session ==========
            self._capture_session = QMediaCaptureSession()
            self._capture_session.setCamera(self._camera)
            self._capture_session.setVideoOutput(self._video_widget)

            # ========== Connect Error Signals ==========
            self._camera.errorOccurred.connect(self._on_camera_error)

            # ========== Start Camera ==========
            self._camera.start()

            # Wait for camera to start
            time.sleep(0.1)

            if self._camera.isActive():
                print("[recorder] Camera started successfully")
                self.status_label.hide()
                self._video_widget.show()
            else:
                print("[recorder] Camera failed to start")
                self._show_error("Camera failed to start")

        except Exception as e:
            print(f"[recorder] Camera initialization error: {e}")
            import traceback
            traceback.print_exc()
            self._show_error(f"Camera error: {e}")

    def _cleanup_media_completely(self):
        """Complete cleanup of all media objects."""
        print("[recorder] Starting complete media cleanup...")

        # Stop and delete recorder
        if self._recorder:
            try:
                if self._recorder.recorderState() == QMediaRecorder.RecordingState:
                    print("[recorder] Stopping active recorder...")
                    self._recorder.stop()
                    # Wait for it to actually stop
                    for _ in range(10):
                        if self._recorder.recorderState() == QMediaRecorder.StoppedState:
                            break
                        time.sleep(0.1)
                self._recorder.deleteLater()
            except Exception as e:
                print(f"[recorder] Error cleaning up recorder: {e}")
            self._recorder = None

        # Stop and delete camera
        if self._camera:
            try:
                if self._camera.isActive():
                    print("[recorder] Stopping camera...")
                    self._camera.stop()
                    # Wait for camera to stop
                    for _ in range(10):
                        if not self._camera.isActive():
                            break
                        time.sleep(0.1)
                self._camera.deleteLater()
            except Exception as e:
                print(f"[recorder] Error cleaning up camera: {e}")
            self._camera = None

        # Clean up audio input
        if self._audio_input:
            try:
                self._audio_input.deleteLater()
            except Exception as e:
                print(f"[recorder] Error cleaning up audio: {e}")
            self._audio_input = None

        # Clean up capture session
        if self._capture_session:
            try:
                self._capture_session.setCamera(None)
                self._capture_session.setAudioInput(None)
                self._capture_session.setRecorder(None)
                self._capture_session.setVideoOutput(None)
                self._capture_session.deleteLater()
            except Exception as e:
                print(f"[recorder] Error cleaning up session: {e}")
            self._capture_session = None

        print("[recorder] Media cleanup complete")

    def _show_error(self, message: str):
        """Show error message in place of video preview."""
        self._video_widget.hide()
        self.status_label.setText(message)
        self.status_label.show()

    @Slot(QCamera.Error, str)
    def _on_camera_error(self, error, error_string):
        """Handle camera errors."""
        print(f"[recorder] Camera error: {error} - {error_string}")
        self._show_error(f"Camera error: {error_string}")

    def _assign_controllers(self):
        """Open dialog to assign controllers to participants."""
        res = AssignControllersDialog.assign(self, "Assign Controllers")
        self.assigned = res

        # Log assignments
        a = res.get("A")["path"] if res.get("A") else "–"
        b = res.get("B")["path"] if res.get("B") else "–"
        print(f"[recorder] Controller assignments: A={a}  B={b}")
        self.statusBar().showMessage(f"Assigned A={a}  B={b}", 5000)

    def _start(self):
        """Start recording video and gamepad input."""
        print("[recorder] Starting recording...")

        if self._is_recording:
            print("[recorder] Already recording!")
            return

        try:
            # ========== Ensure Study Exists ==========
            self._ensure_case()

            # ========== Prepare Output File ==========
            out_dir = MEDIA_ROOT / self.case_id
            out_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            out_file = out_dir / f"rec_{ts}.mp4"

            # ========== Create Database Entries ==========
            now = datetime.now(timezone.utc)

            # Create Recording entry
            rec_id = uuid4().hex
            with dbm.get_session() as s:
                s.add(Recording(
                    id=rec_id,
                    case_id=self.case_id,
                    created_utc=now,
                    video_path=str(out_file),
                    notes=""
                ))

                # Create ObserverSession entry
                sess_id = uuid4().hex
                s.add(ObserverSession(
                    id=sess_id,
                    recording_id=rec_id,
                    created_utc=now,
                    label="Recording Session"
                ))
                s.commit()

            self._recording_id = rec_id
            self._session_id = sess_id
            self._t0_monotonic = time.monotonic()  # Time reference

            # ========== Setup Gamepad Capture ==========
            assigned_map: Dict[str, Tuple[str, str]] = {}

            if self.chk_capture_pad.isChecked():
                # Build map of {device_path: (stream_id, participant_name)}
                for slot in ("A", "B"):
                    slotv = self.assigned.get(slot)
                    if not slotv:
                        continue

                    realpath = slotv.get("path")
                    alias = (slotv.get("name") or f"Participant {slot}").strip() or f"Participant {slot}"

                    # Create InputStream entry in database
                    with dbm.get_session() as s:
                        st_id = uuid4().hex
                        s.add(InputStream(
                            id=st_id,
                            session_id=sess_id,
                            device_name=realpath,
                            profile_id="gamepad.evdev.v1",
                            created_utc=now,
                            alias=alias,
                            construct_mapping="{}"
                        ))

                        # Add INIT event at t=0
                        s.add(InputEvent(
                            id=uuid4().hex,
                            recording_id=rec_id,
                            session_id=sess_id,
                            stream_id=st_id,
                            t_ms=0,
                            kind="button",
                            code="INIT",
                            value=None,
                            is_press=None
                        ))
                        s.commit()

                    assigned_map[realpath] = (st_id, alias)

            # ========== Setup Qt6 Recorder ==========
            # Force software encoding (disable VAAPI hardware encoding which is broken)
            import os
            os.environ['LIBVA_DRIVER_NAME'] = 'null'  # Disable VAAPI

            self._recorder = QMediaRecorder()

            # Set output location
            self._recorder.setOutputLocation(QUrl.fromLocalFile(str(out_file)))

            # Set quality
            self._recorder.setQuality(QMediaRecorder.HighQuality)

            # CRITICAL: Set frame rate from GlobalAVManager
            fps = self.av_manager.get_fps()
            self._recorder.setVideoFrameRate(fps)
            print(f"[recorder] Set frame rate: {fps} fps")

            # Configure media format (H.264 video + AAC audio in MP4 container)
            media_format = QMediaFormat()
            media_format.setFileFormat(QMediaFormat.MPEG4)
            media_format.setVideoCodec(QMediaFormat.VideoCodec.H264)
            media_format.setAudioCodec(QMediaFormat.AudioCodec.AAC)
            self._recorder.setMediaFormat(media_format)

            # ========== Setup Audio Input from GlobalAVManager ==========
            # CRITICAL: Clean up any existing audio input first
            if self._audio_input:
                try:
                    self._capture_session.setAudioInput(None)
                    self._audio_input.deleteLater()
                    self._audio_input = None
                except Exception as e:
                    print(f"[recorder] Error cleaning old audio input: {e}")

            # Get the selected microphone device
            mic_device = self.av_manager.get_current_microphone()
            if not mic_device:
                print(f"[recorder] ERROR: No microphone selected in settings!")
                QMessageBox.critical(self, "No Microphone",
                                     "No microphone is selected in Audio/Video Settings.\n\n"
                                     "Please select a microphone before recording.")
                return

            print(f"[recorder] Creating QAudioInput with device: {mic_device.description()}")
            print(f"[recorder] Device ID: {mic_device.id()}")

            # Create fresh audio input with the selected device
            self._audio_input = QAudioInput(mic_device)

            # Set input volume from global manager
            mic_volume = self.av_manager.get_mic_volume()
            self._audio_input.setVolume(mic_volume)
            print(f"[recorder] Set microphone volume to {mic_volume:.2f}")

            # CRITICAL: Set audio input BEFORE setting recorder
            self._capture_session.setAudioInput(self._audio_input)
            print(f"[recorder] Audio input configured")

            # CRITICAL ORDER: Set recorder AFTER camera and audio are configured
            # This ensures the recorder picks up the correct audio device
            self._capture_session.setRecorder(self._recorder)
            print(f"[recorder] Recorder connected to capture session")

            # ========== Connect Signals ==========
            self._recorder.recorderStateChanged.connect(self._on_recorder_state_changed)
            self._recorder.errorOccurred.connect(self._on_recorder_error)

            # ========== Start Recording ==========
            print(f"[recorder] Starting Qt6 recording to: {out_file}")
            self._recorder.record()

            # ========== Start Gamepad Polling ==========
            if self.chk_capture_pad.isChecked() and assigned_map:
                self._poller = GamepadPoller(
                    recording_id=rec_id,
                    session_id=sess_id,
                    time_source=lambda: (time.monotonic() - self._t0_monotonic) * 1000.0,
                    assigned=assigned_map,
                )
                if hasattr(self._poller, 'start'):
                    try:
                        self._poller.start()
                        print(f"[recorder] Started gamepad polling for {len(assigned_map)} device(s)")
                    except Exception as e:
                        print(f"[recorder] Poller start error: {e}")

            # ========== Update UI ==========
            self._is_recording = True
            self.btn_start.setEnabled(False)
            self.btn_stop.setEnabled(True)
            self.statusBar().showMessage("Recording…", 2000)

            # Note: recordingSaved signal is emitted in _stop_recording() after encryption

        except Exception as e:
            QMessageBox.critical(self, "Recording Error", f"Failed to start recording:\n{e}")
            print(f"[recorder] Error: {e}")
            import traceback
            traceback.print_exc()

    @Slot(QMediaRecorder.RecorderState)
    def _on_recorder_state_changed(self, state):
        """Handle recorder state changes."""
        print(f"[recorder] Recorder state: {state}")
        if state == QMediaRecorder.RecordingState:
            self.statusBar().showMessage("● Recording", 0)
        elif state == QMediaRecorder.StoppedState:
            self.statusBar().showMessage("Stopped", 3000)

    @Slot(QMediaRecorder.Error, str)
    def _on_recorder_error(self, error, error_string):
        """Handle recorder errors."""
        print(f"[recorder] ========== RECORDER ERROR ==========")
        print(f"[recorder] Error code: {error}")
        print(f"[recorder] Error string: {error_string}")

        # Log current state
        if self._recorder:
            print(f"[recorder] Recorder state: {self._recorder.recorderState()}")
            print(f"[recorder] Media status: {self._recorder.mediaStatus()}")
            print(f"[recorder] Output location: {self._recorder.outputLocation()}")

            # Log format details
            fmt = self._recorder.mediaFormat()
            print(f"[recorder] File format: {fmt.fileFormat()}")
            print(f"[recorder] Video codec: {fmt.videoCodec()}")
            print(f"[recorder] Audio codec: {fmt.audioCodec()}")

        # Log camera state
        if self._camera:
            print(f"[recorder] Camera active: {self._camera.isActive()}")
            print(f"[recorder] Camera error: {self._camera.error()}")

        # Log audio state
        if self._audio_input:
            print(f"[recorder] Audio device: {self._audio_input.device().description()}")
            print(f"[recorder] Audio volume: {self._audio_input.volume()}")

        print(f"[recorder] ====================================")

        QMessageBox.critical(self, "Recording Error", f"Recorder error: {error_string}")

    def _stop(self):
        """Stop recording."""
        print("[recorder] Stopping recording...")

        if not self._is_recording:
            print("[recorder] Not recording!")
            return

        # ========== Show Immediate Feedback ==========
        self.btn_stop.setEnabled(False)
        self.btn_stop.setText("Stopping...")
        self.statusBar().showMessage("⏹ Stopping recording, please wait...", 0)

        # Process events to update UI immediately
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()

        # ========== Stop Gamepad Polling ==========
        if self._poller:
            try:
                if hasattr(self._poller, 'stop'):
                    self._poller.stop()
                if hasattr(self._poller, 'join'):
                    self._poller.join(timeout=1.0)
                print("[recorder] Stopped gamepad polling")
            except Exception as e:
                print(f"[recorder] Poller stop error: {e}")
            finally:
                self._poller = None

        # ========== Stop Recorder ==========
        if self._recorder:
            try:
                print("[recorder] Stopping Qt6 recorder...")
                self._recorder.stop()

                # Wait for recorder to finish with progress updates
                for i in range(50):  # Wait up to 5 seconds
                    if self._recorder.recorderState() == QMediaRecorder.StoppedState:
                        print("[recorder] Recorder stopped successfully")
                        break

                    # Update status every 10 iterations (0.5 seconds)
                    if i % 10 == 0:
                        dots = "." * (i // 10)
                        self.statusBar().showMessage(f"⏹ Finalizing recording{dots}", 0)
                        QApplication.processEvents()

                    time.sleep(0.1)
                else:
                    print("[recorder] WARNING: Recorder didn't stop cleanly")

            except Exception as e:
                print(f"[recorder] Error stopping recorder: {e}")

        # ========== ENCRYPT VIDEO AUTOMATICALLY ==========
        if self._recording_id and self.study_pin:
            self.statusBar().showMessage("🔒 Encrypting video...", 0)
            QApplication.processEvents()

            try:
                from hsparc.utils.study_encryption import encrypt_file

                # Get video path from database
                with dbm.get_session() as s:
                    rec = s.query(Recording).filter_by(id=self._recording_id).first()
                    if rec and rec.video_path:
                        video_path = Path(rec.video_path)

                        # Wait for video file to be fully written and available
                        max_wait = 10  # Wait up to 10 seconds
                        for i in range(max_wait):
                            if video_path.exists() and video_path.stat().st_size > 0:
                                # Give it one more moment to ensure file is fully flushed
                                time.sleep(0.5)
                                break
                            if i % 2 == 0:
                                dots = "." * (i // 2)
                                self.statusBar().showMessage(f"🔒 Waiting for video file{dots}", 0)
                                QApplication.processEvents()
                            time.sleep(1)

                        if not video_path.exists():
                            print(f"[recorder] ERROR: Video file not found: {video_path}")
                            self.statusBar().showMessage("⚠️ Recording saved but encryption failed (file not found).",
                                                         5000)
                        elif video_path.stat().st_size == 0:
                            print(f"[recorder] ERROR: Video file is empty: {video_path}")
                            self.statusBar().showMessage("⚠️ Recording saved but encryption failed (empty file).", 5000)
                        else:
                            # Encrypt the video file
                            print(
                                f"[recorder] Encrypting video: {video_path} (size: {video_path.stat().st_size} bytes)")
                            encrypted_path = encrypt_file(str(video_path), self.case_id, self.study_pin)

                            # Update database with encrypted path
                            print(f"[recorder] Updating database: {rec.video_path} -> {encrypted_path}")
                            rec.video_path = encrypted_path
                            s.commit()
                            print(f"[recorder] Database committed successfully")

                            # Verify update
                            s.refresh(rec)
                            print(f"[recorder] Verified database path: {rec.video_path}")

                            print(f"[recorder] ✓ Video encrypted: {encrypted_path}")
                            self.statusBar().showMessage("✓ Recording saved and encrypted.", 3000)
                    else:
                        print("[recorder] WARNING: Could not find recording in database")
                        self.statusBar().showMessage("✓ Recording saved (encryption skipped).", 3000)

            except Exception as e:
                print(f"[recorder] ERROR encrypting video: {e}")
                import traceback
                traceback.print_exc()
                self.statusBar().showMessage("⚠️ Recording saved but encryption failed.", 5000)
        else:
            if not self.study_pin:
                print("[recorder] WARNING: No study PIN available - video not encrypted")
            self.statusBar().showMessage("✓ Recording saved.", 3000)

        # ========== Update UI ==========
        self._is_recording = False
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(True)
        self.btn_stop.setText("Stop")

        # ========== Emit Signal to Refresh Parent Window ==========
        # Emit AFTER encryption so parent window gets updated path
        if self._recording_id:
            try:
                print(f"[recorder] Emitting recordingSaved signal for: {self._recording_id}")
                self.recordingSaved.emit(self._recording_id)
            except Exception as e:
                print(f"[recorder] Failed to emit signal: {e}")

    def _ensure_case(self) -> str:
        """Ensure a valid study is selected."""
        # Try to get from dropdown
        if hasattr(self, "case_combo"):
            idx = self.case_combo.currentIndex()
            if idx >= 0:
                cid = self.case_combo.itemData(idx)
                if cid:
                    self.case_id = cid
                    return cid

        # Use stored case_id if available
        if self.case_id:
            return self.case_id

        # Create default study
        with dbm.get_session() as s:
            row = s.query(Study).filter(Study.label == "Default").first()
            if row is None:
                cid = uuid4().hex
                s.add(Study(
                    id=cid,
                    label="Default",
                    created_utc=datetime.now(timezone.utc)
                ))
                s.commit()
                self.case_id = cid
            else:
                self.case_id = row.id

        return self.case_id

    def closeEvent(self, ev):
        """Handle window close event."""
        print("[recorder] Closing window...")
        self._is_closing = True

        # Stop recording if active
        if self._is_recording:
            try:
                self._stop()
            except Exception as e:
                print(f"[recorder] Error stopping during close: {e}")

        # Full cleanup
        try:
            self._cleanup_media_completely()
        except Exception as e:
            print(f"[recorder] Cleanup error: {e}")

        super().closeEvent(ev)

    def showEvent(self, event):
        """Handle window show event."""
        super().showEvent(event)

        # Only initialize once when first shown, or after being hidden
        if not self._camera_initialized and not self._is_recording:
            print("[recorder] Window shown, initializing camera...")
            self._camera_initialized = True
            QTimer.singleShot(200, self._initialize_camera)

    def hideEvent(self, event):
        """Handle window hide event."""
        super().hideEvent(event)
        print("[recorder] Window hidden, will reinitialize camera on next show")
        self._camera_initialized = False

    def _open_av_settings(self):
        """Open A/V settings dialog."""
        dialog = AVSettingsDialog(self)
        dialog.exec()