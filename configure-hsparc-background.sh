#!/usr/bin/env bash
set -euo pipefail

# HSPARC Background Configuration Script
# Sets up desktop background for IceWM kiosk

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

echo_info() { echo -e "${GREEN}[INFO]${NC} $*"; }
echo_step() { echo -e "${BLUE}[STEP]${NC} $*"; }
echo_error() { echo -e "${RED}[ERROR]${NC} $*"; }

KIOSK_USER="hsparc"
BACKGROUND_IMAGE="/opt/hsparc/resources/hsparc_background.jpg"

# Check root
if [ "$EUID" -ne 0 ]; then
    echo_error "This script must be run as root (use sudo)"
    exit 1
fi

echo ""
echo_info "=========================================="
echo_info "  HSPARC Background Configuration"
echo_info "=========================================="
echo ""

# Verify background image exists
if [ ! -f "$BACKGROUND_IMAGE" ]; then
    echo_error "Background image not found: $BACKGROUND_IMAGE"
    exit 1
fi
echo_info "✓ Background image found"

# Configure IceWM background
echo_step "Configuring IceWM desktop background..."
ICEWM_DIR="/home/$KIOSK_USER/.icewm"
mkdir -p "$ICEWM_DIR"

# Create/update prefoverride file
cat > "$ICEWM_DIR/prefoverride" << EOFPREFS
# HSPARC Kiosk Mode - Desktop Background
DesktopBackgroundImage="$BACKGROUND_IMAGE"
DesktopBackgroundCenter=0
DesktopBackgroundScaled=1
EOFPREFS

chown "$KIOSK_USER:$KIOSK_USER" "$ICEWM_DIR/prefoverride"
echo_info "✓ IceWM background configured"

echo ""
echo_info "=========================================="
echo_info "  Configuration Complete!"
echo_info "=========================================="
echo ""
echo_info "Background set to: hsparc_background.jpg"
echo ""
echo_info "To apply changes:"
echo_info "  Option 1: sudo systemctl restart gdm3"
echo_info "  Option 2: sudo reboot"
echo ""
