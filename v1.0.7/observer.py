# hsparc/ui/observer.py
from __future__ import annotations

import os
import time
import hashlib
from datetime import datetime, timezone
from typing import Optional, Dict, Tuple, List
from uuid import uuid4
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, QEvent
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QMessageBox, QStatusBar, QSlider, QLineEdit, QCheckBox,
    QTextEdit, QFileDialog, QGroupBox
)
from PySide6.QtGui import QKeyEvent, QPixmap
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtMultimediaWidgets import QVideoWidget

from hsparc.models import db as dbm
from hsparc.ui.global_av_manager import GlobalAVManager
from hsparc.models.db import Recording, ObserverSession, InputStream, InputEvent
from hsparc.ui.widgets.assign_dialog import AssignControllersDialog
from hsparc.ui.widgets.controller_calibration_dialog import ControllerCalibrationDialog
from hsparc.input.gamepad import GamepadPoller

# Import recognition check components
try:
    from hsparc.ui.widgets.recognition_check_dialog import RecognitionCheckDialog
except ImportError:
    RecognitionCheckDialog = None
    print("[observer] Warning: RecognitionCheckDialog not available")

try:
    from hsparc.utils.frame_extractor import SimpleFrameExtractor
except ImportError:
    SimpleFrameExtractor = None
    print("[observer] Warning: SimpleFrameExtractor not available")

# Import instructions and countdown dialogs
try:
    from hsparc.ui.widgets.observer_instructions_dialog import ObserverInstructionsDialog
except ImportError:
    ObserverInstructionsDialog = None
    print("[observer] Warning: ObserverInstructionsDialog not available")

try:
    from hsparc.ui.widgets.countdown_dialog import CountdownDialog
except ImportError:
    CountdownDialog = None
    print("[observer] Warning: CountdownDialog not available")


def _ms_to_clock(ms: int) -> str:
    if ms < 0:
        ms = 0
    s, ms = divmod(ms, 1000)
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h:d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


# ========== Security Helpers ==========
def hash_pin(pin: str) -> str:
    """Hash a PIN using SHA256."""
    return hashlib.sha256(pin.encode('utf-8')).hexdigest()


def verify_pin(stored_hash: str, entered_pin: str) -> bool:
    """Verify an entered PIN against stored hash."""
    return hash_pin(entered_pin) == stored_hash


def log_access(case_id: str, action: str, success: bool = True):
    """Log security-relevant actions."""
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


class ObserverWindow(QMainWindow):
    """
    Observer mode with lockdown and optional recognition check + instructions.
    """

    def __init__(self, parent=None, recording_id: Optional[str] = None,
                 session_id: Optional[str] = None, case_id: Optional[str] = None,
                 study_pin: Optional[str] = None, **_kw):
        super().__init__(parent)

        self.recording_id: Optional[str] = recording_id
        self._session_id: Optional[str] = session_id
        self._case_id: Optional[str] = case_id
        self.study_pin = study_pin  # Store PIN for decryption
        self._temp_video_path: Optional[str] = None  # Track temp decrypted file
        self._poller: Optional[GamepadPoller] = None
        self.assigned: Dict[str, Optional[dict]] = {"A": None, "B": None}
        self._allow_close: bool = False

        # Recognition check state
        self._recognition_check_enabled: bool = False
        self.video_path: Optional[Path] = None

        # Instructions state (loaded from study)
        self._instructions_text: Optional[str] = None
        self._instructions_image_path: Optional[Path] = None
        self._load_study_instructions()

        # OBSERVER MODE LOCKDOWN
        self.setWindowFlags(
            Qt.Window |
            Qt.CustomizeWindowHint |
            Qt.WindowTitleHint |
            Qt.WindowStaysOnTopHint |
            Qt.WindowMaximizeButtonHint
        )
        self.setWindowTitle("HSPARC — Observer Mode [LOCKED]")
        self.resize(1100, 680)
        self.setWindowModality(Qt.ApplicationModal)

        # ---- UI ----
        central = QWidget(self)
        root = QVBoxLayout(central)

        # Header with exit button
        header = QHBoxLayout()
        header_label = QLabel("Observer Mode")
        header_label.setStyleSheet("font-size:16px;font-weight:600;")
        header.addWidget(header_label)
        header.addStretch(1)

        self.btn_exit = QPushButton("🔒 Exit Observer Mode (Requires PIN)", self)
        self.btn_exit.setStyleSheet("""
            QPushButton {
                background-color: #d9534f;
                color: white;
                padding: 10px 20px;
                border-radius: 4px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #c9302c;
            }
        """)
        self.btn_exit.clicked.connect(self._exit_with_pin)
        header.addWidget(self.btn_exit)
        root.addLayout(header)

        # Controls row
        top = QHBoxLayout()
        self.btn_assign = QPushButton("Assign Controllers…", self)

        # Recognition check checkbox
        self.chk_recognition = QCheckBox("Require Recognition Check", self)
        self.chk_recognition.setToolTip(
            "Show random frames from the video and ask participants\n"
            "if they recognize anyone before starting the session."
        )

        # Instructions checkbox (only shown if instructions are configured)
        self.chk_instructions = QCheckBox("Show Instructions", self)
        self.chk_instructions.setToolTip(
            "Display custom instructions to participants before the session starts."
        )
        # Enable only if instructions exist
        if not self._instructions_text:
            self.chk_instructions.setEnabled(False)
            self.chk_instructions.setToolTip(
                "No instructions configured for this study.\n"
                "Use 'Edit Observer Instructions' button to set up instructions."
            )

        self.btn_start = QPushButton("Start Observer Session", self)
        self.btn_stop = QPushButton("Stop", self)
        self.btn_stop.setEnabled(False)

        top.addWidget(self.btn_assign)
        top.addWidget(self.chk_recognition)
        top.addWidget(self.chk_instructions)
        top.addWidget(self.btn_start)
        top.addWidget(self.btn_stop)
        top.addStretch(1)
        root.addLayout(top)

        # Video area
        self.video = QVideoWidget(self)
        root.addWidget(self.video, 10)

        # Transport: position + seek slider
        transport = QHBoxLayout()
        self.slider = QSlider(Qt.Horizontal, self)
        self.slider.setRange(0, 0)
        self.slider.setEnabled(False)
        self.lbl_pos = QLabel("00:00", self)
        self.lbl_dur = QLabel("00:00", self)
        transport.addWidget(self.lbl_pos)
        transport.addWidget(self.slider, 1)
        transport.addWidget(self.lbl_dur)
        root.addLayout(transport)

        # Status
        self.setCentralWidget(central)
        self.setStatusBar(QStatusBar(self))
        self.lbl_status = QLabel("Idle. Click 'Start Observer Session' to begin.", self)
        root.addWidget(self.lbl_status)

        # Media player
        self.player = QMediaPlayer(self)
        self.audio = GlobalAVManager.instance().create_audio_output()
        self.player.setVideoOutput(self.video)
        self.player.setAudioOutput(self.audio)

        # Wire signals
        self.btn_assign.clicked.connect(self._assign)
        self.btn_start.clicked.connect(self._start)
        self.btn_stop.clicked.connect(self._stop)
        self.player.positionChanged.connect(self._on_position)
        self.player.durationChanged.connect(self._on_duration)
        self.slider.sliderMoved.connect(self._on_slider_moved)

        # Load video if recording_id given
        if self.recording_id:
            try:
                with dbm.get_session() as s:
                    rec = s.get(Recording, self.recording_id)
                    if rec and rec.video_path and os.path.exists(rec.video_path):
                        video_path = Path(rec.video_path)
                        print(f"[observer] Loading video: {video_path}")
                        print(f"[observer] Is encrypted: {video_path.suffix == '.enc'}")
                        print(f"[observer] Study PIN available: {self.study_pin is not None}")
                        print(f"[observer] Case ID available: {self._case_id is not None}")

                        # Check if encrypted (.enc extension)
                        if video_path.suffix == '.enc':
                            if self.study_pin and self._case_id:
                                try:
                                    from hsparc.utils.study_encryption import decrypt_file
                                    print(f"[observer] Decrypting video: {video_path}")
                                    temp_path = decrypt_file(str(video_path), self._case_id, self.study_pin)
                                    self._temp_video_path = temp_path
                                    self.video_path = Path(temp_path)
                                    self.player.setSource(QUrl.fromLocalFile(temp_path))
                                    self.statusBar().showMessage(f"Loaded encrypted video", 4000)
                                    print(f"[observer] Video decrypted to: {temp_path}")
                                except Exception as e:
                                    self.statusBar().showMessage(f"Failed to decrypt video: {e}", 5000)
                                    print(f"[observer] Decryption error: {e}")
                                    import traceback
                                    traceback.print_exc()
                            else:
                                error_msg = "Cannot decrypt video: "
                                if not self.study_pin:
                                    error_msg += "Study PIN not available"
                                elif not self._case_id:
                                    error_msg += "Case ID not available"
                                print(f"[observer] ERROR: {error_msg}")
                                self.statusBar().showMessage(error_msg, 5000)
                        else:
                            # Plain video (legacy or not encrypted)
                            print(f"[observer] Loading plain video: {video_path}")
                            self.video_path = video_path
                            self.player.setSource(QUrl.fromLocalFile(str(video_path)))
                            self.statusBar().showMessage(f"Loaded video: {rec.video_path}", 4000)
                    else:
                        print(f"[observer] No video found - rec={rec}, video_path={rec.video_path if rec else None}")
                        self.statusBar().showMessage("No video found for this recording.", 4000)
            except Exception as e:
                self.statusBar().showMessage(f"Failed to load video: {e}", 5000)
                print(f"[observer] Video loading exception: {e}")
                import traceback
                traceback.print_exc()

        self.showFullScreen()
        self.show()

        self._prompt_initial_assignment()

    def _load_study_instructions(self):
        """Load observer instructions from the study database."""
        if not self._case_id:
            return

        try:
            with dbm.get_session() as s:
                study = s.query(dbm.Study).filter_by(id=self._case_id).first()
                if study:
                    self._instructions_text = study.observer_instructions_text
                    if study.observer_instructions_image:
                        img_path = Path(study.observer_instructions_image)
                        if img_path.exists():
                            self._instructions_image_path = img_path

                    if self._instructions_text:
                        print(f"[observer] Loaded instructions from study: {len(self._instructions_text)} chars")
                    if self._instructions_image_path:
                        print(f"[observer] Loaded instructions image: {self._instructions_image_path}")
        except Exception as e:
            print(f"[observer] Error loading study instructions: {e}")

    def _prompt_initial_assignment(self):
        """Prompt researcher to assign controllers before starting observer session."""
        reply = QMessageBox.question(
            self,
            "Assign Controllers",
            "Observer mode requires at least one controller to capture input.\n\n"
            "Would you like to assign controllers now?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes
        )

        if reply == QMessageBox.Yes:
            self._assign()
            if not self.assigned.get("A") and not self.assigned.get("B"):
                QMessageBox.warning(
                    self,
                    "No Controllers Assigned",
                    "At least one controller must be assigned for observer mode.\n\n"
                    "Exiting observer mode."
                )
                self._allow_close = True
                self.close()
        else:
            QMessageBox.information(
                self,
                "Observer Mode Cancelled",
                "Observer mode requires controller assignment.\n\n"
                "Exiting observer mode."
            )
            self._allow_close = True
            self.close()

    def keyPressEvent(self, event: QKeyEvent):
        """Block Alt+Tab, Alt+F4, and other escape key combos."""
        if event.modifiers() & Qt.AltModifier and event.key() == Qt.Key_Tab:
            event.ignore()
            return
        if event.modifiers() & Qt.AltModifier and event.key() == Qt.Key_F4:
            event.ignore()
            return
        if (event.modifiers() & Qt.ControlModifier and
                event.modifiers() & Qt.AltModifier and
                event.key() == Qt.Key_Delete):
            event.ignore()
            return
        if event.key() == Qt.Key_Escape:
            event.ignore()
            return

        super().keyPressEvent(event)

    def _exit_with_pin(self):
        """Exit observer mode - requires case PIN if case is locked."""
        # DON'T stop here - controls will become visible!
        # self._stop()  # REMOVED - only stop AFTER successful PIN

        if not self._case_id:
            self._stop()  # Safe to stop here
            self._force_close()
            return

        with dbm.get_session() as s:
            case = s.query(dbm.Case).filter_by(id=self._case_id).first()
            if not case:
                self._stop()  # Safe to stop here
                self._force_close()
                return

            if getattr(case, 'is_locked', False) and getattr(case, 'security_hash', None):
                attempts = 0
                max_attempts = 3

                while attempts < max_attempts:
                    pin = PinDialog.get_pin_from_user(
                        self,
                        "Exit Observer Mode",
                        "Enter case PIN to return to main application:"
                    )

                    if pin is None:
                        log_access(self._case_id, "OBSERVER_EXIT_CANCELLED")
                        # User cancelled - don't stop, don't show controls
                        return

                    if verify_pin(case.security_hash, pin):
                        log_access(self._case_id, "OBSERVER_EXIT_GRANTED")
                        self._stop()  # Only stop after successful PIN
                        self._force_close()
                        return
                    else:
                        attempts += 1
                        remaining = max_attempts - attempts
                        log_access(self._case_id, f"OBSERVER_EXIT_DENIED_ATTEMPT_{attempts}", success=False)

                        if remaining > 0:
                            QMessageBox.warning(
                                self,
                                "Incorrect PIN",
                                f"Incorrect PIN.\n{remaining} attempt(s) remaining."
                            )
                        else:
                            QMessageBox.critical(
                                self,
                                "Access Denied",
                                "Maximum attempts exceeded.\nCannot exit observer mode."
                            )
                            return
            else:
                self._stop()  # Safe to stop here
                self._force_close()

    def _force_close(self):
        """Actually close the window, bypassing the closeEvent block."""
        self._allow_close = True
        self.close()

    def _assign(self):
        """Assign controllers."""
        self.assigned = AssignControllersDialog.assign(self, "Assign Controllers")
        a = (self.assigned.get("A") or {}).get("path") if self.assigned.get("A") else "—"
        b = (self.assigned.get("B") or {}).get("path") if self.assigned.get("B") else "—"
        print(f"[observer] assigned A={a}  B={b}")
        self.statusBar().showMessage(f"Assigned A={a}  B={b}", 4000)

    def _start(self):
        """Start observer session - with optional recognition check and instructions."""
        if not self.recording_id:
            QMessageBox.warning(self, "Observer", "No recording selected.\nOpen a recording first.")
            return

        if not self.assigned.get("A") and not self.assigned.get("B"):
            QMessageBox.warning(
                self,
                "No Controllers Assigned",
                "Please assign at least one controller before starting the observer session."
            )
            return

        # Start the flow
        if self.chk_recognition.isChecked():
            self._start_with_recognition_check()
        else:
            self._continue_after_recognition()

    def _start_with_recognition_check(self):
        """Start session with recognition check."""
        print("[observer] Starting with recognition check...")

        if not self.video_path or not self.video_path.exists():
            QMessageBox.critical(
                self,
                "Video Not Found",
                "Cannot perform recognition check - video file not found."
            )
            return

        if SimpleFrameExtractor is None or RecognitionCheckDialog is None:
            QMessageBox.warning(
                self,
                "Feature Unavailable",
                "Recognition check feature is not available.\n"
                "Continuing without recognition check."
            )
            self._continue_after_recognition()
            return

        # Extract random frames
        self.lbl_status.setText("Extracting video frames for recognition check...")
        self.statusBar().showMessage("Extracting frames...", 2000)

        try:
            frames = self._extract_frames()

            if not frames or len(frames) < 6:
                QMessageBox.warning(
                    self,
                    "Frame Extraction Failed",
                    f"Could not extract enough frames from video (got {len(frames)}/6).\n"
                    "Continuing without recognition check."
                )
                self._continue_after_recognition()
                return

            print(f"[observer] Extracted {len(frames)} frames")

            # Show recognition check dialog
            self._show_recognition_check_dialog(frames)

        except Exception as e:
            print(f"[observer] Frame extraction error: {e}")
            import traceback
            traceback.print_exc()

            QMessageBox.critical(
                self,
                "Recognition Check Failed",
                f"Could not perform recognition check:\n{e}\n\n"
                "Continuing without recognition check."
            )
            self._continue_after_recognition()

    def _extract_frames(self) -> List[QPixmap]:
        """Extract random frames from the video."""
        return SimpleFrameExtractor.extract_frames_simple(str(self.video_path), count=6)

    def _show_recognition_check_dialog(self, frames: List[QPixmap]):
        """Show the recognition check dialog."""
        dialog = RecognitionCheckDialog(
            parent=self,
            frames=frames,
            assigned_controllers=self.assigned
        )

        dialog.check_completed.connect(self._handle_recognition_result)
        dialog.exec()

    def _handle_recognition_result(self, passed: bool):
        """Handle recognition check result."""
        print(f"[observer] Recognition check result: {'PASSED' if passed else 'FAILED'}")

        # Create session first to store the check result
        if not self._session_id:
            now = datetime.now(timezone.utc)
            with dbm.get_session() as s:
                sess_id = uuid4().hex
                s.add(ObserverSession(
                    id=sess_id,
                    recording_id=self.recording_id,
                    created_utc=now,
                    label="Observer Session",
                    recognition_check_required=True,
                    recognition_check_passed=passed,
                    recognition_check_timestamp=datetime.utcnow().isoformat()
                ))
                s.commit()
            self._session_id = sess_id
        else:
            # Update existing session
            try:
                with dbm.get_session() as s:
                    session = s.query(ObserverSession).filter_by(id=self._session_id).first()
                    if session:
                        session.recognition_check_required = True
                        session.recognition_check_passed = passed
                        session.recognition_check_timestamp = datetime.utcnow().isoformat()
                        s.commit()
            except Exception as e:
                print(f"[observer] Failed to update session with recognition result: {e}")

        if passed:
            # Continue with instructions or countdown
            self._continue_after_recognition()
        else:
            # Recognition check FAILED
            print("[observer] Recognition check FAILED - session will NOT start")

            self.lbl_status.setText(
                "⚠️ Recognition Check Failed\n\n"
                "A participant recognized someone in the video.\n"
                "No video playback or data recording will occur.\n\n"
                "Please consult with the researcher."
            )
            self.lbl_status.setStyleSheet("color: #d32f2f; font-size: 16px; font-weight: bold;")

            self.btn_start.setEnabled(False)
            self.btn_stop.setEnabled(False)
            self.btn_assign.setEnabled(True)
            self.chk_recognition.setEnabled(True)
            self.chk_instructions.setEnabled(True)

            QMessageBox.warning(
                self,
                "Recognition Check Failed",
                "A participant recognized someone in the video.\n\n"
                "The observer session will NOT start.\n"
                "No video playback or data recording will occur.",
                QMessageBox.Ok
            )

    def _continue_after_recognition(self):
        """Continue to instructions or countdown after recognition check."""
        if self.chk_instructions.isChecked() and self._instructions_text:
            self._show_instructions()
        else:
            self._show_countdown()

    def _show_instructions(self):
        """Show instructions dialog to participants."""
        print("[observer] Showing instructions...")

        if ObserverInstructionsDialog is None:
            QMessageBox.warning(
                self,
                "Feature Unavailable",
                "Instructions feature is not available.\n"
                "Continuing to countdown."
            )
            self._show_countdown()
            return

        if not self._instructions_text:
            print("[observer] No instructions text available, skipping to countdown")
            self._show_countdown()
            return

        # Pass markdown text directly (not pre-formatted HTML)
        # The dialog will convert markdown to HTML
        dialog = ObserverInstructionsDialog(
            parent=self,
            instructions_html=self._instructions_text,  # Pass raw markdown/text
            image_path=self._instructions_image_path,
            assigned_controllers=self.assigned
        )

        dialog.ready_confirmed.connect(self._show_countdown)
        dialog.exec()

    def _show_countdown(self):
        """Show 5-second countdown before starting session."""
        print("[observer] Showing countdown...")

        if CountdownDialog is None:
            QMessageBox.warning(
                self,
                "Feature Unavailable",
                "Countdown feature is not available.\n"
                "Starting session immediately."
            )
            self._start_session()
            return

        dialog = CountdownDialog(parent=self, seconds=5)
        dialog.countdown_complete.connect(self._start_session)
        dialog.exec()

    def _start_session(self):
        """Actually start the observer session."""
        print("[observer] _start_session() called")

        # CRITICAL SAFEGUARD
        if self.chk_recognition.isChecked() and self._session_id:
            with dbm.get_session() as s:
                session = s.query(ObserverSession).filter_by(id=self._session_id).first()
                if session and session.recognition_check_passed == False:
                    print("[observer] BLOCKED: Recognition check failed")
                    QMessageBox.critical(
                        self,
                        "Session Blocked",
                        "Cannot start session - recognition check failed."
                    )
                    return

        now = datetime.now(timezone.utc)
        t0 = int(self.player.position())
        
        # Create session if needed
        if not self._session_id:
            with dbm.get_session() as s:
                sess_id = uuid4().hex
                s.add(ObserverSession(
                    id=sess_id,
                    recording_id=self.recording_id,
                    created_utc=now,
                    label="Observer Session",
                    recognition_check_required=self.chk_recognition.isChecked(),
                    recognition_check_passed=None if not self.chk_recognition.isChecked() else True
                ))
                s.commit()
            self._session_id = sess_id

        # Setup gamepad capture with calibrations from assignment
        assigned_map: Dict[str, Tuple[str, str]] = {}
        calibrations: Dict[str, Any] = {}

        for slot in ("A", "B"):
            slotv = self.assigned.get(slot)
            if not slotv:
                continue
            realpath = slotv.get("path")
            alias = (slotv.get("name") or f"Participant {slot}").strip() or f"Participant {slot}"
            cal_state = slotv.get("calibration")  # Get calibration from assignment

            # Create InputStream
            st_id = uuid4().hex
            with dbm.get_session() as s:
                stream = InputStream(
                    id=st_id,
                    session_id=self._session_id,
                    device_name=realpath,
                    profile_id="gamepad.evdev.v1",
                    created_utc=now,
                    alias=alias,
                    construct_mapping="{}"
                )
                
                # Save calibration if available
                if cal_state:
                    stream.calibration_data = cal_state.to_dict()
                    stream.allowed_inputs = cal_state.get_allowed_inputs()
                    stream.construct_mapping = cal_state.get_construct_mapping()
                    calibrations[st_id] = cal_state
                
                s.add(stream)
                s.add(InputEvent(
                    id=uuid4().hex,
                    recording_id=self.recording_id,
                    session_id=self._session_id,
                    stream_id=st_id,
                    t_ms=t0,
                    kind="button",
                    code="INIT",
                    value=None,
                    is_press=None
                ))
                s.commit()

            assigned_map[realpath] = (st_id, alias)

        # Start poller with calibrations
        if assigned_map:
            self._poller = GamepadPoller(
                recording_id=self.recording_id,
                session_id=self._session_id,
                time_source=lambda: float(self.player.position()),
                assigned=assigned_map,
                calibrations=calibrations,
            )
            if hasattr(self._poller, "start"):
                try:
                    self._poller.start()
                except Exception:
                    pass

        # Start playback
        print("[observer] Starting video playback")
        try:
            self.player.play()
        except Exception as e:
            print(f"[observer] Failed to start playback: {e}")

        # HIDE ALL RESEARCHER CONTROLS - PARTICIPANTS SHOULD ONLY SEE VIDEO
        self.slider.setVisible(False)  # Hide seek slider
        self.btn_assign.setVisible(False)
        self.chk_recognition.setVisible(False)
        self.chk_instructions.setVisible(False)
        self.btn_start.setVisible(False)
        self.btn_stop.setVisible(False)  # NO STOP BUTTON FOR PARTICIPANTS

        # Hide transport controls too
        self.lbl_pos.setVisible(False)
        self.lbl_dur.setVisible(False)

        self.lbl_status.setText("Observer session in progress...")
        self.lbl_status.setStyleSheet("font-size: 14px; color: #4CAF50;")
        self.statusBar().showMessage("Observer running", 0)

    def _stop(self):
        """Stop the observer session."""
        try:
            self.player.pause()
        except Exception:
            pass
        try:
            if self._poller:
                if hasattr(self._poller, "stop"):
                    self._poller.stop()
                if hasattr(self._poller, "join"):
                    self._poller.join(timeout=1.0)
        except Exception:
            pass
        self._poller = None

        # Show controls again (for researcher intervention if needed)
        self.slider.setVisible(True)
        self.btn_assign.setVisible(True)
        self.chk_recognition.setVisible(True)
        if self._instructions_text:
            self.chk_instructions.setVisible(True)
        self.btn_start.setVisible(True)
        self.btn_stop.setVisible(False)  # Keep stop hidden
        self.lbl_pos.setVisible(True)
        self.lbl_dur.setVisible(True)

        self.lbl_status.setText("Stopped.")
        self.lbl_status.setStyleSheet("")

    def _on_position(self, pos: int):
        try:
            self.slider.blockSignals(True)
            self.slider.setValue(pos)
            self.lbl_pos.setText(_ms_to_clock(pos))
        finally:
            self.slider.blockSignals(False)

    def _on_duration(self, dur: int):
        self.slider.setRange(0, dur if dur and dur > 0 else 0)
        self.lbl_dur.setText(_ms_to_clock(dur))

    def _on_slider_moved(self, pos: int):
        try:
            self.player.setPosition(pos)
        except Exception:
            pass

    def closeEvent(self, ev):
        """Prevent ALL closing attempts without PIN."""
        if self._allow_close:
            # Clean up temp decrypted file
            if self._temp_video_path:
                try:
                    Path(self._temp_video_path).unlink(missing_ok=True)
                    print(f"[observer] Cleaned up temp video: {self._temp_video_path}")
                except Exception as e:
                    print(f"[observer] Failed to clean up temp video: {e}")
            ev.accept()
            return

        ev.ignore()
        QMessageBox.warning(
            self,
            "Observer Mode Locked",
            "Observer mode is locked.\n\n"
            "Use the 'Exit Observer Mode' button and enter the case PIN to exit."
        )