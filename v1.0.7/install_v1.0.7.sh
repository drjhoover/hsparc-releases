#!/bin/bash
# HSPARC v1.0.7 Installation Script

set -e

echo "Installing HSPARC v1.0.7..."

# Check if running from correct directory
if [ ! -f "db.py" ]; then
    echo "Error: Must run from v1.0.7 directory"
    exit 1
fi

# Install python-docx dependency
echo "Installing python-docx..."
pip install python-docx --break-system-packages

# Copy files to installation directory
echo "Copying files..."
sudo cp db.py /opt/hsparc/hsparc/models/db.py
sudo cp controller_calibration_dialog.py /opt/hsparc/hsparc/ui/widgets/controller_calibration_dialog.py
sudo cp assign_dialog.py /opt/hsparc/hsparc/ui/widgets/assign_dialog.py
sudo cp gamepad.py /opt/hsparc/hsparc/input/gamepad.py
sudo cp observer.py /opt/hsparc/hsparc/ui/observer.py
sudo cp recorder.py /opt/hsparc/hsparc/ui/recorder.py
sudo cp observer_instructions_dialog.py /opt/hsparc/hsparc/ui/widgets/observer_instructions_dialog.py
sudo cp recognition_check_dialog.py /opt/hsparc/hsparc/ui/widgets/recognition_check_dialog.py
sudo cp researcher.py /opt/hsparc/hsparc/ui/researcher.py

echo ""
echo "✓ Installation complete!"
echo ""
echo "Database migration will run automatically on first launch."
echo "New features:"
echo "  - Controller calibration with construct assignment"
echo "  - Normalized input values (-1.0 to 1.0)"
echo "  - Input filtering (record only what you need)"
echo "  - Fixed analysis report generation"
echo ""
