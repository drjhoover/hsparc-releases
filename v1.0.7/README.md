# HSPARC v1.0.7 - Controller Calibration Release

## Installation
```bash
cd v1.0.7
./install_v1.0.7.sh
```

## What's New

### Controller Calibration System
- Calibrate joystick axes and buttons during controller assignment
- Assign construct labels (e.g., "Arousal", "Valence") to each input
- Values automatically normalized to -1.0 to 1.0 range
- Filter recording to only configured inputs

### Bug Fixes
- Fixed Wii Nunchuck button detection
- Fixed analysis report generation
- Fixed polling errors in dialogs

## Requirements

- python-docx (installed automatically by script)

See RELEASE_NOTES_v1.0.7.md for complete details.
