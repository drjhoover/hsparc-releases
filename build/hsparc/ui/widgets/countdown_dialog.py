# hsparc/ui/widgets/countdown_dialog.py
"""
Countdown dialog before observer session starts.
Shows a large 5-second countdown.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel
from PySide6.QtGui import QKeyEvent


class CountdownDialog(QDialog):
    """
    Shows a 5-second countdown before observer session starts.

    Features:
    - Large countdown display
    - Fullscreen lockdown
    - Cannot be cancelled
    - Auto-closes when countdown completes
    """

    countdown_complete = Signal()

    def __init__(self, parent=None, seconds: int = 5):
        super().__init__(parent)

        self.seconds_remaining = seconds
        self.total_seconds = seconds

        self._setup_ui()
        self._start_countdown()

        # LOCKDOWN MODE
        self.setWindowFlags(
            Qt.Window |
            Qt.CustomizeWindowHint |
            Qt.WindowTitleHint |
            Qt.WindowStaysOnTopHint
        )
        self.setWindowTitle("Starting Observer Session")
        self.setWindowModality(Qt.ApplicationModal)
        self.showFullScreen()

    def _setup_ui(self):
        """Build the UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(60, 60, 60, 60)

        # Title
        title = QLabel("Starting Observer Session")
        title.setStyleSheet("font-size: 36px; font-weight: bold; color: #333;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        layout.addStretch()

        # Countdown number (huge)
        self.countdown_label = QLabel(str(self.seconds_remaining))
        self.countdown_label.setStyleSheet("""
            font-size: 180px;
            font-weight: bold;
            color: #4CAF50;
        """)
        self.countdown_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.countdown_label)

        layout.addStretch()

        # Helper text
        helper = QLabel("Get ready...")
        helper.setStyleSheet("font-size: 24px; color: #666;")
        helper.setAlignment(Qt.AlignCenter)
        layout.addWidget(helper)

    def _start_countdown(self):
        """Start the countdown timer."""
        self.timer = QTimer(self)
        self.timer.setInterval(1000)  # 1 second
        self.timer.timeout.connect(self._tick)
        self.timer.start()

    def _tick(self):
        """Update countdown each second."""
        self.seconds_remaining -= 1

        if self.seconds_remaining <= 0:
            self.timer.stop()
            self._complete()
        else:
            self.countdown_label.setText(str(self.seconds_remaining))

            # Change color as countdown progresses
            if self.seconds_remaining <= 2:
                self.countdown_label.setStyleSheet("""
                    font-size: 180px;
                    font-weight: bold;
                    color: #FF9800;
                """)

    def _complete(self):
        """Countdown complete - show GO and close."""
        self.countdown_label.setText("GO!")
        self.countdown_label.setStyleSheet("""
            font-size: 180px;
            font-weight: bold;
            color: #4CAF50;
        """)

        # Emit signal and close after brief display
        QTimer.singleShot(500, self.countdown_complete.emit)
        QTimer.singleShot(500, self.accept)

    def keyPressEvent(self, event: QKeyEvent):
        """Block all keyboard input."""
        event.ignore()

    def closeEvent(self, event):
        """Prevent closing during countdown."""
        if self.seconds_remaining > 0:
            event.ignore()
        else:
            if hasattr(self, 'timer'):
                self.timer.stop()
            event.accept()