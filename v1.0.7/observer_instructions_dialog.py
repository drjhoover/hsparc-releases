# hsparc/ui/widgets/observer_instructions_dialog.py
"""
Observer instructions dialog - shown before observer session starts.
Displays custom markdown/HTML instructions with optional image.
Supports markdown formatting.
"""
from __future__ import annotations

import time
from typing import Optional
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextBrowser, QWidget
)
from PySide6.QtGui import QPixmap, QKeyEvent

# Import markdown converter
try:
    import markdown
    HAS_MARKDOWN = True
except ImportError:
    HAS_MARKDOWN = False
    print("[observer_instructions] Warning: markdown library not available")
    print("[observer_instructions] Install with: pip install markdown")

try:
    from evdev import InputDevice, ecodes
except:
    InputDevice = None
    ecodes = None


class ObserverInstructionsDialog(QDialog):
    """
    Dialog showing custom instructions to observer before session starts.

    Features:
    - Displays markdown/HTML formatted instructions
    - Shows optional instructional image
    - Gamepad-navigable "I'm Ready" button
    - Fullscreen lockdown mode
    """

    ready_confirmed = Signal()

    def __init__(
            self,
            parent=None,
            instructions_html: str = "",
            image_path: Optional[Path] = None,
            assigned_controllers: dict = None
    ):
        super().__init__(parent)

        # Convert markdown to HTML if it's markdown
        if HAS_MARKDOWN and instructions_html:
            # Try to detect if it's markdown (not already HTML)
            if not instructions_html.strip().startswith('<'):
                try:
                    instructions_html = markdown.markdown(
                        instructions_html,
                        extensions=['nl2br', 'sane_lists']
                    )
                except Exception as e:
                    print(f"[observer_instructions] Markdown conversion failed: {e}")
                    # Fallback: wrap in <p> tags and convert newlines
                    instructions_html = f"<p>{instructions_html.replace(chr(10), '<br>')}</p>"

        self.instructions_html = instructions_html or "<p>No instructions provided.</p>"
        self.image_path = image_path
        self.assigned_controllers = assigned_controllers or {}

        # Gamepad polling
        self._devices = []
        self._poll_timer = None
        self._last_input_time = {}

        self._setup_ui()
        self._setup_gamepad_polling()

        # LOCKDOWN MODE
        self.setWindowFlags(
            Qt.Window |
            Qt.CustomizeWindowHint |
            Qt.WindowTitleHint |
            Qt.WindowStaysOnTopHint
        )
        self.setWindowTitle("Observer Instructions")
        self.setWindowModality(Qt.ApplicationModal)
        self.showFullScreen()

    def _setup_ui(self):
        """Build the UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(60, 40, 60, 40)
        layout.setSpacing(20)

        # Title
        title = QLabel("Instructions")
        title.setStyleSheet("font-size: 32px; font-weight: bold; color: #333;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        # Instructions text (HTML/Markdown)
        self.text_browser = QTextBrowser()
        self.text_browser.setHtml(self.instructions_html)
        self.text_browser.setStyleSheet("""
            QTextBrowser {
                background: white;
                border: 2px solid #ddd;
                border-radius: 8px;
                padding: 20px;
                font-size: 16px;
            }
        """)
        self.text_browser.setMinimumHeight(300)
        layout.addWidget(self.text_browser, 1)

        # Optional image
        if self.image_path and self.image_path.exists():
            image_label = QLabel()
            pixmap = QPixmap(str(self.image_path))
            # Scale to reasonable size while maintaining aspect ratio
            scaled = pixmap.scaled(800, 400, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            image_label.setPixmap(scaled)
            image_label.setAlignment(Qt.AlignCenter)
            image_label.setStyleSheet("border: 2px solid #ddd; background: white; padding: 10px;")
            layout.addWidget(image_label)

        layout.addSpacing(20)

        # Ready button (large and prominent)
        self.btn_ready = QPushButton("I'm Ready")
        self.btn_ready.setMinimumHeight(80)
        self.btn_ready.setStyleSheet("""
            QPushButton {
                background: #4CAF50;
                color: white;
                border: 3px solid #45a049;
                border-radius: 12px;
                font-size: 28px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: #45a049;
            }
        """)
        self.btn_ready.clicked.connect(self._handle_ready)
        layout.addWidget(self.btn_ready)

        # Helper text
        helper = QLabel("Use joystick to scroll • Press any button to continue")
        helper.setStyleSheet("font-size: 14px; color: #666; font-style: italic;")
        helper.setAlignment(Qt.AlignCenter)
        layout.addWidget(helper)

    def _setup_gamepad_polling(self):
        """Setup gamepad input polling."""
        if InputDevice is None:
            print("[instructions] evdev not available")
            return

        # Open assigned controllers
        for slot in ("A", "B"):
            ctrl = self.assigned_controllers.get(slot)
            if ctrl and ctrl.get("path"):
                try:
                    device = InputDevice(ctrl["path"])
                    self._devices.append(device)
                    self._last_input_time[ctrl["path"]] = 0
                    print(f"[instructions] Opened controller {slot}: {ctrl['path']}")
                except Exception as e:
                    print(f"[instructions] Failed to open {ctrl['path']}: {e}")

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
                # Use non-blocking read
                while True:
                    event = device.read_one()
                    if event is None:
                        break
                    
                    # Skip sync and MSC events
                    if event.type in (ecodes.EV_SYN, ecodes.EV_MSC):
                        continue
                    
                    # Debounce for buttons (0.3s)
                    # But allow continuous scrolling for joystick
                    debounce_time = 0.3 if event.type == ecodes.EV_KEY else 0.1

                    if current_time - self._last_input_time.get(device_path, 0) < debounce_time:
                        continue

                    # Joystick scrolling (up/down scrolls instructions)
                    if event.type == ecodes.EV_ABS and event.code == ecodes.ABS_Y:
                        scroll_bar = self.text_browser.verticalScrollBar()
                        
                        # Auto-detect controller type by value range
                        if abs(event.value) > 1000:
                            # Standard gamepad range (-32768 to 32767)
                            if event.value < -20000:  # Up
                                scroll_bar.setValue(scroll_bar.value() - 50)
                                self._last_input_time[device_path] = current_time
                            elif event.value > 20000:  # Down
                                scroll_bar.setValue(scroll_bar.value() + 50)
                                self._last_input_time[device_path] = current_time
                        else:
                            # Wii Nunchuck range (0 to 255, center ~128)
                            if event.value < 64:  # Up
                                scroll_bar.setValue(scroll_bar.value() - 50)
                                self._last_input_time[device_path] = current_time
                            elif event.value > 192:  # Down
                                scroll_bar.setValue(scroll_bar.value() + 50)
                                self._last_input_time[device_path] = current_time

                    # Any button press confirms ready (supports all controller types)
                    elif event.type == ecodes.EV_KEY and event.value == 1:
                        # Accept any button press to support diverse controllers
                        # (Wii Nunchuck uses BTN_TRIGGER/BTN_THUMB, Xbox uses BTN_SOUTH, etc.)
                        self._handle_ready()
                        self._last_input_time[device_path] = current_time

            except BlockingIOError:
                pass
            except Exception as e:
                # Only print non-trivial errors
                if "Resource temporarily unavailable" not in str(e):
                    print(f"[instructions] Error polling {device_path}: {e}")

    def _handle_ready(self):
        """Handle ready confirmation."""
        print("[instructions] Observer confirmed ready")

        # Stop polling
        if self._poll_timer:
            self._poll_timer.stop()

        # Visual feedback
        self.btn_ready.setText("Ready!")
        self.btn_ready.setStyleSheet("""
            QPushButton {
                background: #2e7d32;
                color: white;
                border: 3px solid #1b5e20;
                border-radius: 12px;
                font-size: 28px;
                font-weight: bold;
            }
        """)

        # Emit signal and close after brief delay
        QTimer.singleShot(500, self.ready_confirmed.emit)
        QTimer.singleShot(500, self.accept)

    def keyPressEvent(self, event: QKeyEvent):
        """Block keyboard except for testing."""
        if event.modifiers() & Qt.AltModifier:
            event.ignore()
            return
        if event.key() in (Qt.Key_Escape, Qt.Key_F4):
            event.ignore()
            return

        # Allow Enter/Space for testing
        if event.key() in (Qt.Key_Return, Qt.Key_Space):
            self._handle_ready()

    def closeEvent(self, event):
        """Cleanup on close."""
        if self._poll_timer:
            self._poll_timer.stop()

        for device in self._devices:
            try:
                device.close()
            except:
                pass

        event.accept()