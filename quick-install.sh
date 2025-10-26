#!/usr/bin/env bash
set -euo pipefail

echo "======================================"
echo "HSPARC Quick Installer"
echo "======================================"
echo ""

# Download full setup script from GitHub
SETUP_URL="https://raw.githubusercontent.com/drjhoover/hsparc-releases/main/setup-hsparc.sh"
TEMP_SCRIPT="/tmp/setup-hsparc-$$.sh"

echo "Downloading setup script..."
if ! curl -fsSL "$SETUP_URL" -o "$TEMP_SCRIPT"; then
    echo "Error: Failed to download setup script"
    exit 1
fi

chmod +x "$TEMP_SCRIPT"

echo "Launching installer..."
echo ""

# Execute the script directly (not piped, so stdin works)
exec "$TEMP_SCRIPT"
