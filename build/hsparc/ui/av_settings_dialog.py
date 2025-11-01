# hsparc/ui/av_settings_dialog.py
"""Simplified Audio/Video Settings Dialog"""

from __future__ import annotations
import subprocess
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QPushButton, QGroupBox, QSpinBox, QMessageBox, QDialogButtonBox
)
from PySide6.QtMultimedia import QMediaDevices
from PySide6.QtMultimediaWidgets import QVideoWidget

from hsparc.ui.global_av_manager import GlobalAVManager


class AVSettingsDialog(QDialog):
    """Simplified settings dialog with camera selection and audio button."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Audio/Video Settings")
        self.setModal(True)
        self.resize(600, 400)
        
        self.av_manager = GlobalAVManager.instance()
        self._setup_ui()
        self._populate_devices()
        self._update_from_manager()
    
    def _setup_ui(self):
        """Build the UI."""
        layout = QVBoxLayout(self)
        
        # Title
        title = QLabel("Audio/Video Device Settings")
        title.setStyleSheet("font-size: 16px; font-weight: bold;")
        layout.addWidget(title)
        
        # Camera group
        camera_group = QGroupBox("Video Settings")
        camera_layout = QVBoxLayout(camera_group)
        
        # Camera selection
        cam_layout = QHBoxLayout()
        cam_layout.addWidget(QLabel("Camera:"))
        self.camera_combo = QComboBox()
        cam_layout.addWidget(self.camera_combo, 1)
        camera_layout.addLayout(cam_layout)
        
        # FPS
        fps_layout = QHBoxLayout()
        fps_layout.addWidget(QLabel("Frame Rate:"))
        self.fps_spin = QSpinBox()
        self.fps_spin.setRange(15, 60)
        self.fps_spin.setValue(30)
        self.fps_spin.setSuffix(" fps")
        fps_layout.addWidget(self.fps_spin)
        fps_layout.addStretch()
        camera_layout.addLayout(fps_layout)
        
        layout.addWidget(camera_group)
        
        # Audio button
        audio_group = QGroupBox("Audio Settings")
        audio_layout = QVBoxLayout(audio_group)
        
        audio_btn = QPushButton("Adjust Audio Settings")
        audio_btn.setMinimumHeight(50)
        audio_btn.setToolTip("Open system audio mixer to configure microphones, speakers, and volume")
        audio_btn.clicked.connect(self._launch_pavucontrol)
        audio_layout.addWidget(audio_btn)
        
        info = QLabel("Opens the system audio control panel where you can:\n"
                     "• Select microphone and speaker devices\n"
                     "• Adjust input and output volume levels\n"
                     "• Configure audio boost and gain settings")
        info.setWordWrap(True)
        info.setStyleSheet("color: #666; margin-top: 10px;")
        audio_layout.addWidget(info)
        
        layout.addWidget(audio_group)
        
        # Dialog buttons
        layout.addStretch()
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.accept)
        layout.addWidget(buttons)
        
        # Connect signals
        self.camera_combo.currentIndexChanged.connect(self._on_camera_changed)
        self.fps_spin.valueChanged.connect(self._on_fps_changed)
    
    def _populate_devices(self):
        """Populate camera dropdown."""
        self.camera_combo.clear()
        cameras = QMediaDevices.videoInputs()
        
        if not cameras:
            self.camera_combo.addItem("No cameras found", -1)
            return
        
        for idx, camera in enumerate(cameras):
            self.camera_combo.addItem(camera.description(), idx)
    
    def _update_from_manager(self):
        """Load current settings."""
        cam_idx = self.av_manager.get_camera_index()
        if 0 <= cam_idx < self.camera_combo.count():
            self.camera_combo.setCurrentIndex(cam_idx)
        
        self.fps_spin.setValue(self.av_manager.get_fps())
    
    def _on_camera_changed(self, index: int):
        """Handle camera selection."""
        device_index = self.camera_combo.itemData(index)
        if device_index is not None and device_index >= 0:
            self.av_manager.set_camera(device_index)
    
    def _on_fps_changed(self, value: int):
        """Handle FPS change."""
        self.av_manager.set_fps(value)
    
    def _launch_pavucontrol(self):
        """Launch pavucontrol for audio settings."""
        try:
            import os
            # Use the current DISPLAY from the app's environment
            env = os.environ.copy()
            subprocess.Popen(['pavucontrol'], env=env)
        except FileNotFoundError:
            QMessageBox.warning(
                self,
                "Audio Control Not Available",
                "pavucontrol is not installed.\n\n"
                "Install it with: sudo apt install pavucontrol"
            )
