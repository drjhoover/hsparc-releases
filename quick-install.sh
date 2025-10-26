#!/usr/bin/env bash
set -euo pipefail

echo "======================================"
echo "HSPARC Quick Installer"
echo "======================================"
echo ""

# Download full setup script from GitHub
SETUP_URL="https://raw.githubusercontent.com/drjhoover/hsparc-releases/main/setup-hsparc.sh"

echo "Downloading setup script..."
wget -q "$SETUP_URL" -O /tmp/setup-hsparc.sh

if [ ! -f /tmp/setup-hsparc.sh ]; then
    echo "Error: Failed to download setup script"
    exit 1
fi

chmod +x /tmp/setup-hsparc.sh

echo "Launching installer..."
echo ""

/tmp/setup-hsparc.sh

rm -f /tmp/setup-hsparc.sh
