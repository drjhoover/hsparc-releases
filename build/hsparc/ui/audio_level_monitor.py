# hsparc/ui/audio_level_monitor.py
"""Real-time audio level monitoring."""

import struct
from PySide6.QtCore import QIODevice

class AudioLevelMonitor(QIODevice):
    """Custom IO device to monitor audio levels from microphone."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.level = 0.0
        self._max_level = 0.0
        self._sample_count = 0
        
    def readData(self, maxlen):
        """Required by QIODevice."""
        return bytes(maxlen)
    
    def writeData(self, data):
        """Process incoming audio data to calculate level."""
        if len(data) == 0:
            return 0
        
        try:
            # Convert bytes to 16-bit signed integers
            num_samples = len(data) // 2
            if num_samples == 0:
                return len(data)
            
            samples = struct.unpack(f'{num_samples}h', data[:num_samples * 2])
            
            # Calculate RMS level
            sum_squares = sum(s * s for s in samples)
            rms = (sum_squares / len(samples)) ** 0.5
            
            # Normalize to 0-100 range (16-bit audio: max value is 32768)
            # Multiply by factor to make it more visible (200 = good sensitivity)
            self.level = min(100, (rms / 32768.0) * 200)
            
            # Track max for debugging
            if self.level > self._max_level:
                self._max_level = self.level
            
            self._sample_count += 1
            
            # Debug output every 100 samples (~5 seconds at 20Hz)
            if self._sample_count % 100 == 0:
                print(f"[audio_monitor] Current: {self.level:.1f}, Max: {self._max_level:.1f}, Samples: {len(samples)}")
            
        except Exception as e:
            print(f"[audio_monitor] Error processing audio: {e}")
        
        return len(data)
