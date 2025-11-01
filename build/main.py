#!/usr/bin/env python3
"""HSPARC - Human Subject Participation in Research and Counseling"""

import os
import sys

# Set runtime directory for audio system access
if not os.environ.get('XDG_RUNTIME_DIR'):
    uid = os.getuid()
    runtime_dir = f'/run/user/{uid}'
    os.environ['XDG_RUNTIME_DIR'] = runtime_dir

# Ensure PulseAudio runtime path matches
if os.environ.get('XDG_RUNTIME_DIR'):
    os.environ['PULSE_RUNTIME_PATH'] = os.environ['XDG_RUNTIME_DIR'] + '/pulse'

# CRITICAL: Disable VAAPI hardware encoding (broken on many systems)
# Force FFmpeg to use software H.264 encoding instead
os.environ['LIBVA_DRIVER_NAME'] = 'null'
print("[main] Disabled VAAPI - using software H.264 encoding")

from hsparc.ui.app import run

if __name__ == "__main__":
    run()
