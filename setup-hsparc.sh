#!/usr/bin/env bash
set -euo pipefail
# HSPARC Installation Script
# Downloads and installs HSPARC from GitHub releases

VERSION="1.0.8"
DOWNLOAD_URL="https://github.com/drjhoover/hsparc-releases/releases/download/v${VERSION}/hsparc-${VERSION}.tar.gz"
INSTALL_DIR="/opt/hsparc"
KIOSK_USER="hsparc"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

echo_info() { echo -e "${GREEN}[INFO]${NC} $*"; }
echo_error() { echo -e "${RED}[ERROR]${NC} $*"; }
echo_step() { echo -e "${BLUE}[STEP]${NC} $*"; }

# Check root
if [ "$EUID" -ne 0 ]; then
    echo_error "This script must be run as root (use sudo)"
    exit 1
fi

echo_info "=========================================="
echo_info "  HSPARC Installation v${VERSION}"
echo_info "=========================================="
echo ""

# Install system dependencies
echo_step "Installing system dependencies..."
apt-get update
apt-get install -y \
    python3 python3-pip python3-venv python3-dev \
    build-essential portaudio19-dev \
    icewm x11-xserver-utils unclutter feh \
    ffmpeg v4l-utils pulseaudio \
    sqlite3 curl wget git \
    libevdev2 libevdev-dev

# Create user
echo_step "Creating hsparc user..."
if ! id "$KIOSK_USER" &>/dev/null; then
    useradd -m -s /bin/bash "$KIOSK_USER"
fi
usermod -aG video,audio,input "$KIOSK_USER"

# Download release
echo_step "Downloading HSPARC v${VERSION}..."
mkdir -p /tmp/hsparc-install
cd /tmp/hsparc-install
wget -q --show-progress "$DOWNLOAD_URL" -O hsparc.tar.gz

# Extract to install directory
echo_step "Installing to ${INSTALL_DIR}..."
mkdir -p "$INSTALL_DIR"
tar -xzf hsparc.tar.gz -C "$INSTALL_DIR" --strip-components=1

# Install Python dependencies
echo_step "Installing Python dependencies..."
cd "$INSTALL_DIR"
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# Set permissions
chown -R "$KIOSK_USER:$KIOSK_USER" "$INSTALL_DIR"

# Configure sudo privileges for shutdown/reboot
echo_step "Configuring shutdown privileges..."
cat > /etc/sudoers.d/hsparc-shutdown << 'EOFSUDO'
# Allow hsparc user to shutdown/reboot without password
hsparc ALL=(ALL) NOPASSWD: /sbin/shutdown, /sbin/reboot, /sbin/poweroff
EOFSUDO
chmod 0440 /etc/sudoers.d/hsparc-shutdown

# Setup IceWM kiosk
echo_step "Configuring IceWM kiosk mode..."

# Create IceWM config directory
mkdir -p /home/$KIOSK_USER/.icewm

# IceWM preferences - comprehensive keyboard lockdown
cat > /home/$KIOSK_USER/.icewm/preferences << 'EOFPREFS'
# HSPARC Kiosk Mode - IceWM Preferences
# Disable all system shortcuts

# Appearance
DesktopBackgroundColor="rgb:00/00/00"
TaskBarAutoHide=1
TaskBarShowWorkspaces=0
TaskBarShowAllWindows=0
TaskBarShowClock=0
ShowTaskBar=0

# Comprehensive keyboard lockdown
KeySysWinMenu=""
KeySysMenu=""
KeySysWindowList=""
KeySysDialog=""
KeySysWinListMenu=""
KeySysAddressBar=""
KeySysWorkspacePrev=""
KeySysWorkspaceNext=""
KeySysWorkspaceLast=""
KeySysWorkspace1=""
KeySysWorkspace2=""
KeySysWorkspace3=""
KeySysWorkspace4=""
KeySysWorkspace5=""
KeySysWorkspace6=""
KeySysWorkspace7=""
KeySysWorkspace8=""
KeySysWorkspace9=""
KeySysWorkspace10=""
KeySysWorkspace11=""
KeySysWorkspace12=""
KeySysTileVertical=""
KeySysTileHorizontal=""
KeySysCascade=""
KeySysArrange=""
KeySysUndoArrange=""
KeySysArrangeIcons=""
KeySysMinimizeAll=""
KeySysHideAll=""
KeySysShowDesktop=""
KeySysCollapseTaskBar=""
KeySysRun=""
KeySysWindowMenu=""
KeyWinClose=""
KeyWinMaximize=""
KeyWinMaximizeVert=""
KeyWinMaximizeHoriz=""
KeyWinMinimize=""
KeyWinHide=""
KeyWinRollup=""
KeyWinFullscreen=""
KeyWinMenu=""
KeyWinArrangeN=""
KeyWinArrangeNE=""
KeyWinArrangeE=""
KeyWinArrangeSE=""
KeyWinArrangeS=""
KeyWinArrangeSW=""
KeyWinArrangeW=""
KeyWinArrangeNW=""
KeyWinArrangeC=""
EOFPREFS

# IceWM prefoverride - desktop background
cat > /home/$KIOSK_USER/.icewm/prefoverride << 'EOFPREFOVER'
# Override theme background with HSPARC splash
DesktopBackgroundImage="/opt/hsparc/resources/hsparc_background.jpg"
DesktopBackgroundScaled=1
DesktopBackgroundCenter=0
EOFPREFOVER

# IceWM startup script
cat > /home/$KIOSK_USER/.icewm/startup << 'EOFSTARTUP'
#!/bin/bash

# Wait for X server
sleep 2

# Set desktop background with feh
if [ -f /opt/hsparc/resources/hsparc_background.jpg ]; then
    feh --bg-fill /opt/hsparc/resources/hsparc_background.jpg
fi

# Restart icewmbg to apply settings
killall icewmbg 2>/dev/null
icewmbg -r &

# Disable screen blanking
xset s off -dpms s noblank

# Hide cursor after inactivity
unclutter -idle 3 -root &

# Launch HSPARC in kiosk mode
export HSPARC_KIOSK=1
cd /opt/hsparc
/opt/hsparc/venv/bin/python /opt/hsparc/main.py
EOFSTARTUP

chmod +x /home/$KIOSK_USER/.icewm/startup

# Auto-login via getty
mkdir -p /etc/systemd/system/getty@tty1.service.d
cat > /etc/systemd/system/getty@tty1.service.d/autologin.conf << EOFAUTOLOGIN
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin $KIOSK_USER --noclear %I \$TERM
EOFAUTOLOGIN

# .xinitrc for auto-start X with IceWM
cat > /home/$KIOSK_USER/.xinitrc << 'EOFXINITRC'
#!/bin/bash
exec icewm-session
EOFXINITRC
chmod +x /home/$KIOSK_USER/.xinitrc

# Auto-start X on login
cat > /home/$KIOSK_USER/.bash_profile << 'EOFBASH'
if [ -z "$DISPLAY" ] && [ "$(tty)" = "/dev/tty1" ]; then
    exec startx
fi
EOFBASH

# Set ownership
chown -R "$KIOSK_USER:$KIOSK_USER" /home/$KIOSK_USER

# Cleanup
rm -rf /tmp/hsparc-install

echo ""
echo_info "=========================================="
echo_info "  Installation Complete!"
echo_info "=========================================="
echo ""
echo_info "HSPARC v${VERSION} has been installed"
echo_info "Location: ${INSTALL_DIR}"
echo ""
echo_info "Configuration applied:"
echo_info "  ✓ IceWM keyboard shortcuts disabled"
echo_info "  ✓ Desktop background configured"
echo_info "  ✓ Shutdown privileges granted"
echo_info "  ✓ Auto-login enabled"
echo ""
echo_info "Next steps:"
echo_info "  1. Reboot: sudo reboot"
echo_info "  2. System will auto-login and start HSPARC"
echo ""
