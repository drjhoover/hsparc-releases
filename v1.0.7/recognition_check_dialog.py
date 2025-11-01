# hsparc/ui/widgets/recognition_check_dialog.py
"""
Recognition check dialog for observer sessions.
Displays 6 random video frames and asks participants if they recognize anyone.
"""
from __future__ import annotations

import time
from typing import List, Dict, Optional
from enum import Enum

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QGridLayout,
    QWidget, QFrame
)
from PySide6.QtGui import QPixmap, QKeyEvent

try:
    from evdev import InputDevice, ecodes
except:
    InputDevice = None
    ecodes = None


class RecognitionResponse(Enum):
    """Possible responses to recognition check."""
    NO_RESPONSE = 0
    RECOGNIZE = 1  # "I recognize someone"
    NOT_RECOGNIZE = 2  # "I don't recognize anyone"


class RecognitionCheckDialog(QDialog):
    """
    Dialog for recognition check before observer session.

    Features:
    - Displays 6 random video thumbnails (2 rows of 3)
    - Gamepad-navigable interface
    - Tracks responses from multiple controllers
    - Fullscreen lockdown mode
    - Cannot be closed without completing check
    - Only 2 options: Recognize or Don't Recognize
    """

    check_completed = Signal(bool)  # True if passed (all said "no"), False if failed

    def __init__(
            self,
            parent=None,
            frames: List[QPixmap] = None,
            assigned_controllers: Dict[str, Optional[dict]] = None,
            regenerate_callback=None  # Not used anymore but kept for compatibility
    ):
        super().__init__(parent)

        self.frames = frames or []
        self.assigned_controllers = assigned_controllers or {}

        # Track responses from each controller
        self.responses: Dict[str, RecognitionResponse] = {}  # {controller_path: response}

        # Currently selected option (0 or 1)
        self.selected_option = 1  # Start on "I don't recognize anyone" (safe default)

        # Gamepad polling
        self._devices: List[InputDevice] = []
        self._poll_timer: Optional[QTimer] = None
        self._last_input_time: Dict[str, float] = {}  # Debounce input

        self._setup_ui()
        self._setup_gamepad_polling()

        # LOCKDOWN MODE - same as observer
        self.setWindowFlags(
            Qt.Window |
            Qt.CustomizeWindowHint |
            Qt.WindowTitleHint |
            Qt.WindowStaysOnTopHint
        )
        self.setWindowTitle("Recognition Check")
        self.setWindowModality(Qt.ApplicationModal)
        self.showFullScreen()

    def _setup_ui(self):
        """Build the UI - COMPACT LAYOUT FOR KIOSK."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 20, 30, 20)  # Reduced margins
        layout.setSpacing(10)  # Reduced spacing

        # Title (smaller)
        title = QLabel("Recognition Check")
        title.setStyleSheet("font-size: 24px; font-weight: bold; color: #333;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        # Instructions (more compact)
        instructions = QLabel(
            "Do you recognize anyone in these images?\n"
            "Use D-pad UP/DOWN to select, press A/X to confirm."
        )
        instructions.setStyleSheet("font-size: 14px; color: #555; padding: 8px;")
        instructions.setAlignment(Qt.AlignCenter)
        instructions.setWordWrap(True)
        layout.addWidget(instructions)

        # Frame display (smaller thumbnails - 2 rows of 3)
        frame_container = QWidget()
        frame_layout = QGridLayout(frame_container)
        frame_layout.setSpacing(10)
        frame_layout.setContentsMargins(10, 10, 10, 10)

        # Display up to 6 frames in a 2x3 grid - SMALLER SIZE FOR KIOSK
        for i, frame in enumerate(self.frames[:6]):
            row = i // 3
            col = i % 3

            frame_widget = QLabel()
            # Reduced size for kiosk mode (was 320x240)
            scaled = frame.scaled(280, 200, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            frame_widget.setPixmap(scaled)
            frame_widget.setStyleSheet("border: 2px solid #ddd; background: #000;")
            frame_widget.setAlignment(Qt.AlignCenter)
            frame_layout.addWidget(frame_widget, row, col)

        layout.addWidget(frame_container)

        layout.addSpacing(10)  # Reduced spacing

        # Options (2 buttons only) - MORE COMPACT
        options_layout = QVBoxLayout()
        options_layout.setSpacing(10)

        self.option_widgets = []

        options = [
            ("❌ Yes, I recognize someone", "option-recognize", RecognitionResponse.RECOGNIZE),
            ("✅ No, I don't recognize anyone", "option-not-recognize", RecognitionResponse.NOT_RECOGNIZE),
        ]

        for text, obj_name, response_type in options:
            btn = QLabel(text)
            btn.setObjectName(obj_name)
            btn.setAlignment(Qt.AlignCenter)
            btn.setStyleSheet(self._get_option_style(False))
            btn.setMinimumHeight(50)  # Reduced from 70
            btn.setProperty("response_type", response_type)
            options_layout.addWidget(btn)
            self.option_widgets.append(btn)

        layout.addLayout(options_layout)

        # Response status (more compact)
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("font-size: 14px; color: #666; padding: 8px;")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        # Update selection highlight
        self._update_selection_display()
        self._update_status()

    def _get_option_style(self, selected: bool) -> str:
        """Get stylesheet for option based on selection state."""
        if selected:
            return """
                QLabel {
                    background: #4CAF50;
                    color: white;
                    border: 3px solid #45a049;
                    border-radius: 8px;
                    padding: 15px;
                    font-size: 20px;
                    font-weight: bold;
                }
            """
        else:
            return """
                QLabel {
                    background: #f0f0f0;
                    color: #333;
                    border: 2px solid #ccc;
                    border-radius: 8px;
                    padding: 15px;
                    font-size: 20px;
                }
            """

    def _update_selection_display(self):
        """Update visual display of selected option."""
        for i, widget in enumerate(self.option_widgets):
            is_selected = (i == self.selected_option)
            widget.setStyleSheet(self._get_option_style(is_selected))

    def _update_status(self):
        """Update status label showing who has responded."""
        controller_names = []
        for slot in ("A", "B"):
            ctrl = self.assigned_controllers.get(slot)
            if ctrl and ctrl.get("path"):
                name = ctrl.get("name", f"Participant {slot}")
                controller_names.append(name)

        if not controller_names:
            self.status_label.setText("No controllers assigned")
            return

        status_parts = []
        for slot in ("A", "B"):
            ctrl = self.assigned_controllers.get(slot)
            if not ctrl or not ctrl.get("path"):
                continue

            name = ctrl.get("name", f"Participant {slot}")
            path = ctrl.get("path")
            response = self.responses.get(path, RecognitionResponse.NO_RESPONSE)

            if response == RecognitionResponse.NO_RESPONSE:
                status_parts.append(f"{name}: ⏳ Waiting...")
            elif response == RecognitionResponse.RECOGNIZE:
                status_parts.append(f"{name}: ❌ Recognizes someone")
            elif response == RecognitionResponse.NOT_RECOGNIZE:
                status_parts.append(f"{name}: ✅ Doesn't recognize")

        self.status_label.setText("  |  ".join(status_parts))

    def _setup_gamepad_polling(self):
        """Setup gamepad input polling."""
        if InputDevice is None:
            print("[recognition_check] evdev not available")
            return

        # Open assigned controllers
        for slot in ("A", "B"):
            ctrl = self.assigned_controllers.get(slot)
            if ctrl and ctrl.get("path"):
                try:
                    device = InputDevice(ctrl["path"])
                    self._devices.append(device)
                    self._last_input_time[ctrl["path"]] = 0
                    print(f"[recognition_check] Opened controller {slot}: {ctrl['path']}")
                except Exception as e:
                    print(f"[recognition_check] Failed to open {ctrl['path']}: {e}")

        if self._devices:
            self._poll_timer = QTimer(self)
            self._poll_timer.setInterval(16)  # ~60 Hz
            self._poll_timer.timeout.connect(self._poll_gamepad_input)
            self._poll_timer.start()

    def _poll_gamepad_input(self):
        """Poll for gamepad input."""
        if not self._devices:
            return

        current_time = time.time()

        for device in self._devices:
            device_path = device.path

            try:
                # Read all available events
                for event in device.read():
                    # Debounce - ignore inputs within 200ms
                    if current_time - self._last_input_time.get(device_path, 0) < 0.2:
                        continue

                    # Navigation: D-pad or left stick (toggle between 2 options)
                    if event.type == ecodes.EV_ABS:
                        if event.code == ecodes.ABS_HAT0Y:  # D-pad vertical
                            if event.value == -1:  # Up
                                self._move_selection(-1)
                                self._last_input_time[device_path] = current_time
                            elif event.value == 1:  # Down
                                self._move_selection(1)
                                self._last_input_time[device_path] = current_time
                        elif event.code == ecodes.ABS_Y:  # Left stick Y
                            # Support both controller types:
                            # - Standard gamepads: -32768 to 32767 (center = 0)
                            # - Wii Nunchuck: 0 to 255 (center = 128)
                            
                            # Detect controller type by value range
                            if abs(event.value) > 1000:
                                # Standard gamepad range (-32768 to 32767)
                                if event.value < -20000:  # Up
                                    self._move_selection(-1)
                                    self._last_input_time[device_path] = current_time
                                elif event.value > 20000:  # Down
                                    self._move_selection(1)
                                    self._last_input_time[device_path] = current_time
                            else:
                                # Wii Nunchuck range (0 to 255, center ~128)
                                if event.value < 64:  # Up (below center)
                                    self._move_selection(-1)
                                    self._last_input_time[device_path] = current_time
                                elif event.value > 192:  # Down (above center)
                                    self._move_selection(1)
                                    self._last_input_time[device_path] = current_time

                    # Selection: Any button press (supports all controller types)
                    elif event.type == ecodes.EV_KEY and event.value == 1:  # Button press
                        # Accept any button press to support diverse controllers
                        # (Wii Nunchuck uses BTN_TRIGGER/BTN_THUMB, Xbox uses BTN_SOUTH, etc.)
                        self._handle_selection(device_path)
                        self._last_input_time[device_path] = current_time

            except Exception as e:
                print(f"[recognition_check] Error polling {device_path}: {e}")

    def _move_selection(self, delta: int):
        """Move selection up or down (toggle between 2 options)."""
        self.selected_option = (self.selected_option + delta) % len(self.option_widgets)
        self._update_selection_display()

    def _handle_selection(self, device_path: str):
        """Handle selection from a controller."""
        # Get the selected response type
        selected_widget = self.option_widgets[self.selected_option]
        response_type = selected_widget.property("response_type")

        print(f"[recognition_check] Controller {device_path} selected: {response_type}")

        # Record response
        self.responses[device_path] = response_type
        self._update_status()

        # Check if all controllers have responded
        expected_controllers = []
        for slot in ("A", "B"):
            ctrl = self.assigned_controllers.get(slot)
            if ctrl and ctrl.get("path"):
                expected_controllers.append(ctrl["path"])

        if not expected_controllers:
            return

        all_responded = all(self.responses.get(path) != RecognitionResponse.NO_RESPONSE
                            for path in expected_controllers)

        if not all_responded:
            return

        # All have responded - determine outcome
        responses = [self.responses.get(path) for path in expected_controllers]

        # If anyone recognizes someone, fail the check
        if RecognitionResponse.RECOGNIZE in responses:
            self._handle_recognition_failure()
            return

        # If all said "don't recognize", pass the check
        if all(r == RecognitionResponse.NOT_RECOGNIZE for r in responses):
            self._handle_recognition_success()
            return

    def _handle_recognition_failure(self):
        """Handle case where someone recognizes someone in the video."""
        print("[recognition_check] Recognition check FAILED")

        # Stop polling
        if self._poll_timer:
            self._poll_timer.stop()

        # Show failure message
        self.status_label.setText(
            "⚠️ Recognition Detected\n\n"
            "Please ask the researcher for assistance."
        )
        self.status_label.setStyleSheet("font-size: 24px; color: #d32f2f; font-weight: bold;")

        # Emit failure signal after delay
        QTimer.singleShot(3000, lambda: self.check_completed.emit(False))
        QTimer.singleShot(3000, self.accept)

    def _handle_recognition_success(self):
        """Handle case where no one recognizes anyone."""
        print("[recognition_check] Recognition check PASSED")

        # Stop polling
        if self._poll_timer:
            self._poll_timer.stop()

        # Show success message
        self.status_label.setText("✅ Check Complete\n\nStarting observer session...")
        self.status_label.setStyleSheet("font-size: 24px; color: #4CAF50; font-weight: bold;")

        # Emit success signal after delay
        QTimer.singleShot(1500, lambda: self.check_completed.emit(True))
        QTimer.singleShot(1500, self.accept)

    def keyPressEvent(self, event: QKeyEvent):
        """Block all keyboard input except for debugging."""
        # Block Alt+Tab, Alt+F4, etc.
        if event.modifiers() & Qt.AltModifier:
            event.ignore()
            return
        if event.key() in (Qt.Key_Escape, Qt.Key_F4):
            event.ignore()
            return

        # Allow arrow keys for debugging/testing
        if event.key() == Qt.Key_Up:
            self._move_selection(-1)
        elif event.key() == Qt.Key_Down:
            self._move_selection(1)
        elif event.key() == Qt.Key_Return or event.key() == Qt.Key_Space:
            # Simulate selection from first controller for testing
            controllers = [c.get("path") for c in self.assigned_controllers.values() if c and c.get("path")]
            if controllers:
                self._handle_selection(controllers[0])

    def closeEvent(self, event):
        """Prevent closing except through completion."""
        # Only allow close if check is complete
        if self._poll_timer and self._poll_timer.isActive():
            event.ignore()
            return

        # Cleanup
        if self._poll_timer:
            self._poll_timer.stop()

        for device in self._devices:
            try:
                device.close()
            except:
                pass

        event.accept()