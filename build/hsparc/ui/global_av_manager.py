# hsparc/ui/global_av_manager.py
"""
Unified Global Audio/Video Manager for HSPARC

Manages all A/V device settings globally across the application:
- Camera selection (for recording)
- Microphone selection (for recording)  
- Audio output selection (for playback)
- Volume levels
- Frame rate

Settings persist across app restarts and are shared across all windows.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional, List

from PySide6.QtCore import QObject, Signal
from PySide6.QtMultimedia import QMediaDevices, QAudioOutput, QAudioInput, QCamera

# Configuration file for global A/V settings
AV_CONFIG_FILE = Path.home() / ".local" / "share" / "hsparc" / "global_av.json"


class GlobalAVManager(QObject):
    """
    Singleton manager for global audio/video configuration.
    
    Signals:
        camera_changed: Emitted when camera selection changes (index)
        microphone_changed: Emitted when microphone selection changes (index)
        speaker_changed: Emitted when audio output changes (index)
        mic_volume_changed: Emitted when mic volume changes (0.0-1.0)
        speaker_volume_changed: Emitted when speaker volume changes (0.0-1.0)
        fps_changed: Emitted when frame rate changes (int)
    """
    
    # Singleton instance
    _instance: Optional['GlobalAVManager'] = None
    
    # Signals
    camera_changed = Signal(int)
    microphone_changed = Signal(int)
    speaker_changed = Signal(int)
    mic_volume_changed = Signal(float)
    speaker_volume_changed = Signal(float)
    fps_changed = Signal(int)
    
    def __init__(self):
        """Initialize the global A/V manager. Use GlobalAVManager.instance() instead."""
        super().__init__()
        
        # Current settings
        self._camera_index: int = 0
        self._mic_index: int = 0
        self._speaker_index: int = 0
        self._mic_volume: float = 0.8
        self._speaker_volume: float = 0.8
        self._speaker_muted: bool = False
        self._fps: int = 30
        
        # Track active audio outputs for live updates
        self._audio_outputs: List[QAudioOutput] = []
        
        # Load settings
        self._load_settings()
    
    @classmethod
    def instance(cls) -> 'GlobalAVManager':
        """Get the singleton instance."""
        if cls._instance is None:
            cls._instance = GlobalAVManager()
        return cls._instance
    
    @classmethod
    def initialize(cls):
        """Initialize the global A/V manager. Call once at app startup."""
        cls.instance()
        print("[global_av] Global A/V manager initialized")
    
    def _load_settings(self):
        """Load A/V settings from config file."""
        try:
            if AV_CONFIG_FILE.exists():
                with open(AV_CONFIG_FILE, 'r') as f:
                    settings = json.load(f)
                    self._camera_index = settings.get("camera_index", 0)
                    self._mic_index = settings.get("microphone_index", 0)
                    self._speaker_index = settings.get("speaker_index", 0)
                    self._mic_volume = settings.get("mic_volume", 0.8)
                    self._speaker_volume = settings.get("speaker_volume", 0.8)
                    self._fps = settings.get("fps", 30)
                    print(f"[global_av] Loaded settings: cam={self._camera_index}, "
                          f"mic={self._mic_index}, spk={self._speaker_index}, "
                          f"fps={self._fps}")
            else:
                print(f"[global_av] No config file, using defaults")
        except Exception as e:
            print(f"[global_av] Error loading settings: {e}")
    
    def _save_settings(self):
        """Save A/V settings to config file."""
        try:
            AV_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
            settings = {
                "camera_index": self._camera_index,
                "microphone_index": self._mic_index,
                "speaker_index": self._speaker_index,
                "mic_volume": self._mic_volume,
                "speaker_volume": self._speaker_volume,
                "fps": self._fps
            }
            with open(AV_CONFIG_FILE, 'w') as f:
                json.dump(settings, f, indent=2)
            print(f"[global_av] Saved settings")
        except Exception as e:
            print(f"[global_av] Error saving settings: {e}")
    
    # ========== Getters ==========
    
    def get_camera_index(self) -> int:
        return self._camera_index
    
    def get_microphone_index(self) -> int:
        return self._mic_index
    
    def get_speaker_index(self) -> int:
        return self._speaker_index
    
    def get_mic_volume(self) -> float:
        return self._mic_volume
    
    def get_speaker_volume(self) -> float:
        return self._speaker_volume
    
    def is_speaker_muted(self) -> bool:
        return self._speaker_muted
    
    def get_fps(self) -> int:
        return self._fps
    
    def get_available_cameras(self) -> List:
        """Get list of available camera devices."""
        return QMediaDevices.videoInputs()
    
    def get_available_microphones(self) -> List:
        """Get list of available audio input devices."""
        return QMediaDevices.audioInputs()
    
    def get_available_speakers(self) -> List:
        """Get list of available audio output devices."""
        return QMediaDevices.audioOutputs()
    
    def get_current_camera(self):
        """Get the currently selected camera device."""
        cameras = self.get_available_cameras()
        if 0 <= self._camera_index < len(cameras):
            return cameras[self._camera_index]
        return None
    
    def get_current_microphone(self):
        """Get the currently selected microphone device."""
        mics = self.get_available_microphones()
        if 0 <= self._mic_index < len(mics):
            return mics[self._mic_index]
        return None
    
    def get_current_speaker(self):
        """Get the currently selected speaker device."""
        speakers = self.get_available_speakers()
        if 0 <= self._speaker_index < len(speakers):
            return speakers[self._speaker_index]
        return None
    
    # ========== Setters ==========
    
    def set_camera(self, index: int):
        """Set the camera device by index."""
        cameras = self.get_available_cameras()
        if not (0 <= index < len(cameras)):
            print(f"[global_av] Invalid camera index: {index}")
            return
        
        self._camera_index = index
        camera = cameras[index]
        print(f"[global_av] Camera set to: {camera.description()}")
        
        self._save_settings()
        self.camera_changed.emit(index)
    
    def set_microphone(self, index: int):
        """Set the microphone device by index."""
        mics = self.get_available_microphones()
        if not (0 <= index < len(mics)):
            print(f"[global_av] Invalid microphone index: {index}")
            return
        
        self._mic_index = index
        mic = mics[index]
        print(f"[global_av] Microphone set to: {mic.description()}")
        
        self._save_settings()
        self.microphone_changed.emit(index)
    
    def set_speaker(self, index: int):
        """Set the speaker device by index."""
        speakers = self.get_available_speakers()
        if not (0 <= index < len(speakers)):
            print(f"[global_av] Invalid speaker index: {index}")
            return
        
        self._speaker_index = index
        speaker = speakers[index]
        print(f"[global_av] Speaker set to: {speaker.description()}")
        
        # Update all registered audio outputs
        for audio_output in self._audio_outputs:
            try:
                audio_output.setDevice(speaker)
            except Exception as e:
                print(f"[global_av] Error updating audio output: {e}")
        
        self._save_settings()
        self.speaker_changed.emit(index)
    
    def set_mic_volume(self, volume: float):
        """Set microphone input volume (0.0-1.0)."""
        self._mic_volume = max(0.0, min(1.0, volume))
        self._save_settings()
        self.mic_volume_changed.emit(self._mic_volume)
    
    def set_speaker_volume(self, volume: float):
        """Set speaker output volume (0.0-1.0)."""
        self._speaker_volume = max(0.0, min(1.0, volume))
        
        # Update all registered audio outputs
        for audio_output in self._audio_outputs:
            try:
                if not self._speaker_muted:
                    audio_output.setVolume(self._speaker_volume)
            except Exception as e:
                print(f"[global_av] Error updating volume: {e}")
        
        self._save_settings()
        self.speaker_volume_changed.emit(self._speaker_volume)
    
    def set_speaker_muted(self, muted: bool):
        """Mute or unmute speaker output."""
        self._speaker_muted = muted
        
        # Update all registered audio outputs
        for audio_output in self._audio_outputs:
            try:
                if muted:
                    audio_output.setVolume(0.0)
                else:
                    audio_output.setVolume(self._speaker_volume)
            except Exception as e:
                print(f"[global_av] Error updating mute: {e}")
    
    def set_fps(self, fps: int):
        """Set recording frame rate."""
        self._fps = max(15, min(60, fps))
        self._save_settings()
        self.fps_changed.emit(self._fps)
    
    # ========== Audio Output Management ==========
    
    def configure_audio_output(self, audio_output: QAudioOutput):
        """Configure an audio output with current global settings."""
        speaker = self.get_current_speaker()
        if speaker:
            audio_output.setDevice(speaker)
        
        audio_output.setVolume(0.0 if self._speaker_muted else self._speaker_volume)
        
        # Register for updates
        if audio_output not in self._audio_outputs:
            self._audio_outputs.append(audio_output)
        
        print(f"[global_av] Configured audio output")
    
    def create_audio_output(self) -> QAudioOutput:
        """Create and configure a new QAudioOutput."""
        speaker = self.get_current_speaker()
        if speaker:
            audio_output = QAudioOutput(speaker)
        else:
            audio_output = QAudioOutput()
        
        audio_output.setVolume(0.0 if self._speaker_muted else self._speaker_volume)
        self._audio_outputs.append(audio_output)
        
        return audio_output
    
    def unregister_audio_output(self, audio_output: QAudioOutput):
        """Unregister an audio output (call when destroying a window)."""
        if audio_output in self._audio_outputs:
            self._audio_outputs.remove(audio_output)
    
    def cleanup(self):
        """Clean up all registered audio outputs."""
        self._audio_outputs.clear()


# Convenience functions
def get_av_manager() -> GlobalAVManager:
    """Get the global A/V manager instance."""
    return GlobalAVManager.instance()
