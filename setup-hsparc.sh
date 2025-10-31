#!/usr/bin/env bash
set -euo pipefail

# HSPARC Installation Script
# Downloads and installs HSPARC from GitHub releases

VERSION="1.0.4"
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
    icewm x11-xserver-utils unclutter \
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

# Create systemd service
echo_step "Creating systemd service..."
cat > /etc/systemd/system/hsparc.service << 'EOFSERVICE'
[Unit]
Description=HSPARC Research Application
After=graphical.target

[Service]
Type=simple
User=hsparc
WorkingDirectory=/opt/hsparc
Environment="DISPLAY=:0"
ExecStart=/opt/hsparc/venv/bin/python /opt/hsparc/main.py
Restart=always
RestartSec=10

[Install]
WantedBy=graphical.target
EOFSERVICE

systemctl daemon-reload
systemctl enable hsparc

# Setup IceWM kiosk
echo_step "Configuring IceWM kiosk mode..."

# Auto-login
mkdir -p /etc/systemd/system/getty@tty1.service.d
cat > /etc/systemd/system/getty@tty1.service.d/autologin.conf << EOFAUTOLOGIN
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin $KIOSK_USER --noclear %I \$TERM
EOFAUTOLOGIN

# .xinitrc for auto-start X and HSPARC
cat > /home/$KIOSK_USER/.xinitrc << 'EOFXINITRC'
#!/bin/bash
xset s off
xset -dpms
xset s noblank
unclutter -idle 0.5 -root &
icewm-session &
sleep 2
/opt/hsparc/venv/bin/python /opt/hsparc/main.py
EOFXINITRC

chmod +x /home/$KIOSK_USER/.xinitrc

# Auto-start X on login
cat >> /home/$KIOSK_USER/.bash_profile << 'EOFBASH'
if [ -z "$DISPLAY" ] && [ "$(tty)" = "/dev/tty1" ]; then
    exec startx
fi
EOFBASH

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
echo_info "Next steps:"
echo_info "  1. Reboot: sudo reboot"
echo_info "  2. System will auto-login and start HSPARC"
echo ""
echo_info "Manual start: sudo systemctl start hsparc"
echo_info "Check status: sudo systemctl status hsparc"
echo ""

