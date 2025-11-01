# hsparc/ui/widgets/global_av_panel.py
"""
Global A/V Control Panel Widget

Always-visible control panel for managing all audio/video devices.
Can be embedded in any window for immediate access to A/V settings.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QSlider, QPushButton, QGroupBox, QSpinBox
)
from PySide6.QtMultimedia import QMediaDevices

from hsparc.ui.global_av_manager import GlobalAVManager


class GlobalAVPanel(QWidget):
    """
    Unified A/V control panel with all device settings.
    
    Features:
    - Camera selection
    - Microphone selection with volume
    - Speaker selection with volume and mute
    - Frame rate selection
    - All changes apply immediately
    - Settings persist automatically
    """
    
    def __init__(self, parent=None, show_camera: bool = True, show_microphone: bool = True):
        """
        Args:
            parent: Parent widget
            show_camera: Whether to show camera controls (hide for playback-only windows)
            show_microphone: Whether to show microphone controls (hide for playback-only windows)
        """
        super().__init__(parent)
        
        self.av_manager = GlobalAVManager.instance()
        self.show_camera = show_camera
        self.show_microphone = show_microphone
        
        self._setup_ui()
        self._populate_devices()
        self._connect_signals()
        self._update_from_manager()
    
    def _setup_ui(self):
        """Build the UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        
        # Title
        title = QLabel("Audio/Video Settings")
        title.setStyleSheet("font-weight: bold; font-size: 13px;")
        layout.addWidget(title)
        
        # Camera controls (for recording)
        if self.show_camera:
            camera_group = QGroupBox("Camera (Recording)")
            camera_layout = QVBoxLayout(camera_group)
            
            self.camera_combo = QComboBox()
            self.camera_combo.setToolTip("Select camera for video recording")
            camera_layout.addWidget(self.camera_combo)
            
            # FPS control
            fps_row = QHBoxLayout()
            fps_row.addWidget(QLabel("FPS:"))
            self.fps_spin = QSpinBox()
            self.fps_spin.setRange(15, 60)
            self.fps_spin.setValue(30)
            self.fps_spin.setToolTip("Recording frame rate")
            fps_row.addWidget(self.fps_spin)
            fps_row.addStretch()
            camera_layout.addLayout(fps_row)
            
            layout.addWidget(camera_group)
        
        # Microphone controls (for recording)
        if self.show_microphone:
            mic_group = QGroupBox("Microphone (Recording)")
            mic_layout = QVBoxLayout(mic_group)
            
            self.mic_combo = QComboBox()
            self.mic_combo.setToolTip("Select microphone for audio recording")
            mic_layout.addWidget(self.mic_combo)
            
            # Mic volume
            mic_vol_row = QHBoxLayout()
            mic_vol_row.addWidget(QLabel("Input Volume:"))
            self.mic_volume_slider = QSlider(Qt.Horizontal)
            self.mic_volume_slider.setRange(0, 100)
            self.mic_volume_slider.setValue(80)
            self.mic_volume_slider.setToolTip("Microphone input gain")
            mic_vol_row.addWidget(self.mic_volume_slider, 1)
            self.mic_volume_label = QLabel("80%")
            self.mic_volume_label.setMinimumWidth(40)
            mic_vol_row.addWidget(self.mic_volume_label)
            mic_layout.addLayout(mic_vol_row)
            
            layout.addWidget(mic_group)
        
        # Speaker controls (for playback - always show)
        speaker_group = QGroupBox("Speakers (Playback)")
        speaker_layout = QVBoxLayout(speaker_group)
        
        self.speaker_combo = QComboBox()
        self.speaker_combo.setToolTip("Select audio output for video playback")
        speaker_layout.addWidget(self.speaker_combo)
        
        # Speaker volume
        spk_vol_row = QHBoxLayout()
        self.btn_mute = QPushButton("🔊")
        self.btn_mute.setFixedSize(32, 32)
        self.btn_mute.setToolTip("Mute/Unmute playback")
        spk_vol_row.addWidget(self.btn_mute)
        
        spk_vol_row.addWidget(QLabel("Volume:"))
        self.speaker_volume_slider = QSlider(Qt.Horizontal)
        self.speaker_volume_slider.setRange(0, 100)
        self.speaker_volume_slider.setValue(80)
        self.speaker_volume_slider.setToolTip("Playback volume")
        spk_vol_row.addWidget(self.speaker_volume_slider, 1)
        self.speaker_volume_label = QLabel("80%")
        self.speaker_volume_label.setMinimumWidth(40)
        spk_vol_row.addWidget(self.speaker_volume_label)
        speaker_layout.addLayout(spk_vol_row)
        
        layout.addWidget(speaker_group)
        
        layout.addStretch()
    
    def _populate_devices(self):
        """Populate device dropdowns."""
        # Cameras
        if self.show_camera:
            self.camera_combo.clear()
            cameras = QMediaDevices.videoInputs()
            if not cameras:
                self.camera_combo.addItem("No cameras found", -1)
            else:
                for idx, camera in enumerate(cameras):
                    self.camera_combo.addItem(camera.description(), idx)
        
        # Microphones
        if self.show_microphone:
            self.mic_combo.clear()
            mics = QMediaDevices.audioInputs()
            if not mics:
                self.mic_combo.addItem("No microphones found", -1)
            else:
                for idx, mic in enumerate(mics):
                    self.mic_combo.addItem(mic.description(), idx)
        
        # Speakers
        self.speaker_combo.clear()
        speakers = QMediaDevices.audioOutputs()
        if not speakers:
            self.speaker_combo.addItem("No speakers found", -1)
        else:
            for idx, speaker in enumerate(speakers):
                self.speaker_combo.addItem(speaker.description(), idx)
    
    def _connect_signals(self):
        """Connect UI signals to manager."""
        if self.show_camera:
            self.camera_combo.currentIndexChanged.connect(self._on_camera_changed)
            self.fps_spin.valueChanged.connect(self._on_fps_changed)
        
        if self.show_microphone:
            self.mic_combo.currentIndexChanged.connect(self._on_mic_changed)
            self.mic_volume_slider.valueChanged.connect(self._on_mic_volume_changed)
        
        self.speaker_combo.currentIndexChanged.connect(self._on_speaker_changed)
        self.speaker_volume_slider.valueChanged.connect(self._on_speaker_volume_changed)
        self.btn_mute.clicked.connect(self._toggle_mute)
    
    def _update_from_manager(self):
        """Update UI from manager's current state."""
        if self.show_camera:
            cam_idx = self.av_manager.get_camera_index()
            if cam_idx < self.camera_combo.count():
                self.camera_combo.setCurrentIndex(cam_idx)
            self.fps_spin.setValue(self.av_manager.get_fps())
        
        if self.show_microphone:
            mic_idx = self.av_manager.get_microphone_index()
            if mic_idx < self.mic_combo.count():
                self.mic_combo.setCurrentIndex(mic_idx)
            mic_vol = int(self.av_manager.get_mic_volume() * 100)
            self.mic_volume_slider.setValue(mic_vol)
            self.mic_volume_label.setText(f"{mic_vol}%")
        
        spk_idx = self.av_manager.get_speaker_index()
        if spk_idx < self.speaker_combo.count():
            self.speaker_combo.setCurrentIndex(spk_idx)
        spk_vol = int(self.av_manager.get_speaker_volume() * 100)
        self.speaker_volume_slider.setValue(spk_vol)
        self.speaker_volume_label.setText(f"{spk_vol}%")
        
        self._update_mute_button()
    
    def _on_camera_changed(self, index: int):
        """Handle camera selection change."""
        device_index = self.camera_combo.itemData(index)
        if device_index is not None and device_index >= 0:
            self.av_manager.set_camera(device_index)
    
    def _on_mic_changed(self, index: int):
        """Handle microphone selection change."""
        device_index = self.mic_combo.itemData(index)
        if device_index is not None and device_index >= 0:
            self.av_manager.set_microphone(device_index)
    
    def _on_speaker_changed(self, index: int):
        """Handle speaker selection change."""
        device_index = self.speaker_combo.itemData(index)
        if device_index is not None and device_index >= 0:
            self.av_manager.set_speaker(device_index)
    
    def _on_mic_volume_changed(self, value: int):
        """Handle microphone volume change."""
        volume = value / 100.0
        self.av_manager.set_mic_volume(volume)
        self.mic_volume_label.setText(f"{value}%")
    
    def _on_speaker_volume_changed(self, value: int):
        """Handle speaker volume change."""
        volume = value / 100.0
        self.av_manager.set_speaker_volume(volume)
        self.speaker_volume_label.setText(f"{value}%")
        
        # Unmute if slider moved
        if self.av_manager.is_speaker_muted() and value > 0:
            self.av_manager.set_speaker_muted(False)
            self._update_mute_button()
    
    def _on_fps_changed(self, value: int):
        """Handle FPS change."""
        self.av_manager.set_fps(value)
    
    def _toggle_mute(self):
        """Toggle mute state."""
        muted = not self.av_manager.is_speaker_muted()
        self.av_manager.set_speaker_muted(muted)
        self._update_mute_button()
        
        if muted:
            self.speaker_volume_label.setText("Muted")
        else:
            value = self.speaker_volume_slider.value()
            self.speaker_volume_label.setText(f"{value}%")
    
    def _update_mute_button(self):
        """Update mute button appearance."""
        if self.av_manager.is_speaker_muted():
            self.btn_mute.setText("🔇")
            self.btn_mute.setStyleSheet("background-color: #ff6b6b;")
        else:
            self.btn_mute.setText("🔊")
            self.btn_mute.setStyleSheet("")
    
    def refresh_devices(self):
        """Refresh device lists (call when devices added/removed)."""
        self._populate_devices()
        self._update_from_manager()
