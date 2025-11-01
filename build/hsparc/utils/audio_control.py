# hsparc/utils/audio_control.py
"""System-level audio control for microphone and speaker gain."""

import subprocess
import shutil
import re


def set_microphone_gain(device_name: str, volume_percent: int) -> bool:
    """
    Set microphone input gain at system level.
    
    Args:
        device_name: Device description from QMediaDevices
        volume_percent: Volume level 0-100 (can go beyond 100 for boost)
    
    Returns:
        True if successful, False otherwise
    """
    volume_percent = max(0, min(200, volume_percent))  # Allow up to 200%
    volume_decimal = volume_percent / 100.0
    
    # Try PipeWire first (most common on modern Linux)
    if shutil.which('wpctl'):
        try:
            subprocess.run(
                ['wpctl', 'set-volume', '@DEFAULT_AUDIO_SOURCE@', str(volume_decimal)],
                check=True,
                capture_output=True
            )
            print(f"[audio_control] Set PipeWire source to {volume_percent}%")
            return True
        except Exception as e:
            print(f"[audio_control] PipeWire source control failed: {e}")
    
    # Try PulseAudio
    if shutil.which('pactl'):
        try:
            subprocess.run(
                ['pactl', 'set-source-volume', '@DEFAULT_SOURCE@', f'{volume_percent}%'],
                check=True,
                capture_output=True
            )
            print(f"[audio_control] Set PulseAudio source to {volume_percent}%")
            return True
        except Exception as e:
            print(f"[audio_control] PulseAudio control failed: {e}")
    
    # Fall back to ALSA
    if shutil.which('amixer'):
        try:
            subprocess.run(
                ['amixer', 'set', 'Capture', f'{volume_percent}%'],
                check=True,
                capture_output=True
            )
            print(f"[audio_control] Set ALSA Capture to {volume_percent}%")
            return True
        except Exception as e:
            print(f"[audio_control] ALSA control failed: {e}")
    
    print(f"[audio_control] No audio control method available")
    return False


def set_speaker_volume(volume_percent: int) -> bool:
    """
    Set speaker/playback volume at system level.
    
    Args:
        volume_percent: Volume level 0-100 (can go beyond 100 for boost)
    
    Returns:
        True if successful, False otherwise
    """
    volume_percent = max(0, min(200, volume_percent))  # Allow up to 200%
    volume_decimal = volume_percent / 100.0
    
    # Try PipeWire first
    if shutil.which('wpctl'):
        try:
            subprocess.run(
                ['wpctl', 'set-volume', '@DEFAULT_AUDIO_SINK@', str(volume_decimal)],
                check=True,
                capture_output=True
            )
            print(f"[audio_control] Set PipeWire sink to {volume_percent}%")
            return True
        except Exception as e:
            print(f"[audio_control] PipeWire sink control failed: {e}")
    
    # Try PulseAudio
    if shutil.which('pactl'):
        try:
            subprocess.run(
                ['pactl', 'set-sink-volume', '@DEFAULT_SINK@', f'{volume_percent}%'],
                check=True,
                capture_output=True
            )
            print(f"[audio_control] Set PulseAudio sink to {volume_percent}%")
            return True
        except Exception as e:
            print(f"[audio_control] PulseAudio sink control failed: {e}")
    
    # Fall back to ALSA Master control
    if shutil.which('amixer'):
        try:
            subprocess.run(
                ['amixer', 'set', 'Master', f'{volume_percent}%'],
                check=True,
                capture_output=True
            )
            print(f"[audio_control] Set ALSA Master to {volume_percent}%")
            return True
        except Exception as e:
            print(f"[audio_control] ALSA Master control failed: {e}")
    
    print(f"[audio_control] No speaker control method available")
    return False


def get_microphone_gain() -> int:
    """Get current microphone gain from system."""
    # Try PipeWire first
    if shutil.which('wpctl'):
        try:
            result = subprocess.run(
                ['wpctl', 'get-volume', '@DEFAULT_AUDIO_SOURCE@'],
                capture_output=True,
                text=True,
                check=True
            )
            # Output format: "Volume: 0.80"
            match = re.search(r'Volume:\s+([\d.]+)', result.stdout)
            if match:
                volume = int(float(match.group(1)) * 100)
                print(f"[audio_control] Current PipeWire source volume: {volume}%")
                return volume
        except Exception as e:
            print(f"[audio_control] Failed to get PipeWire volume: {e}")
    
    # Try PulseAudio
    if shutil.which('pactl'):
        try:
            result = subprocess.run(
                ['pactl', 'list', 'sources'],
                capture_output=True,
                text=True,
                check=True
            )
            match = re.search(r'Volume:.*?(\d+)%', result.stdout)
            if match:
                volume = int(match.group(1))
                print(f"[audio_control] Current PulseAudio volume: {volume}%")
                return volume
        except Exception as e:
            print(f"[audio_control] Failed to get PulseAudio volume: {e}")
    
    # Try ALSA
    if shutil.which('amixer'):
        try:
            result = subprocess.run(
                ['amixer', 'get', 'Capture'],
                capture_output=True,
                text=True,
                check=True
            )
            match = re.search(r'\[(\d+)%\]', result.stdout)
            if match:
                volume = int(match.group(1))
                print(f"[audio_control] Current ALSA volume: {volume}%")
                return volume
        except Exception as e:
            print(f"[audio_control] Failed to get ALSA volume: {e}")
    
    return 80  # Default fallback
