#!/usr/bin/env bash
set -euo pipefail

# HSPARC Installation Script
# Downloads and installs HSPARC from GitHub releases
# 
# Usage (public repo):
#   curl -fsSL https://raw.githubusercontent.com/drjhoover/hsparc-releases/main/setup-hsparc.sh | sudo bash
#
# Usage (private repo):
#   curl -H "Authorization: token YOUR_TOKEN" -fsSL https://raw.githubusercontent.com/drjhoover/hsparc-releases/main/setup-hsparc.sh | sudo bash -s -- YOUR_TOKEN

VERSION="1.2.11"
GITHUB_REPO="drjhoover/hsparc-releases"
GITHUB_TOKEN="${1:-}"
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
if [ -n "$GITHUB_TOKEN" ]; then
    echo_info "  (Using authenticated GitHub access)"
fi

# Clean up legacy systemd service if it exists
if [ -f /etc/systemd/system/hsparc.service ]; then
    echo_step "Removing legacy systemd service..."
    systemctl stop hsparc 2>/dev/null || true
    systemctl disable hsparc 2>/dev/null || true
    rm -f /etc/systemd/system/hsparc.service
    systemctl daemon-reload
    echo_info "Legacy service removed ✓"
fi
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
    exfat-fuse exfatprogs libevdev2 libevdev-dev libxcb-xinerama0 libxcb-cursor0 libxkbcommon-x11-0 libxcb-xinerama0 libxcb-cursor0 libxkbcommon-x11-0

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

if [ -n "$GITHUB_TOKEN" ]; then
    # Private repo - use GitHub API
    ASSET_URL=$(curl -sL -H "Authorization: token $GITHUB_TOKEN" \
        "https://api.github.com/repos/${GITHUB_REPO}/releases/tags/v${VERSION}" | \
        grep "browser_download_url.*tar.gz" | cut -d '"' -f 4)
    
    if [ -z "$ASSET_URL" ]; then
        echo_error "Could not find release v${VERSION}"
        exit 1
    fi
    
    curl -L -H "Authorization: token $GITHUB_TOKEN" -H "Accept: application/octet-stream" \
        -o hsparc.tar.gz "$ASSET_URL"
else
    # Public repo - direct download
    DOWNLOAD_URL="https://github.com/${GITHUB_REPO}/releases/download/v${VERSION}/hsparc-${VERSION}.tar.gz"
    wget -q --show-progress "$DOWNLOAD_URL" -O hsparc.tar.gz
fi
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
hsparc ALL=(ALL) NOPASSWD: /sbin/shutdown, /sbin/reboot, /sbin/poweroff, /usr/bin/systemctl, /usr/local/bin/hsparc-admin-escape.sh, /usr/bin/sed, /bin/umount
EOFSUDO
chmod 0440 /etc/sudoers.d/hsparc-shutdown

# Configure USB auto-mount for hsparc user
echo_step "Configuring USB auto-mount..."
mkdir -p /media/hsparc
chown "$KIOSK_USER:$KIOSK_USER" /media/hsparc

# Get hsparc user's UID/GID
HSPARC_UID=$(id -u "$KIOSK_USER")
HSPARC_GID=$(id -g "$KIOSK_USER")

# Create mount script
cat > /usr/local/bin/hsparc-usb-mount.sh << 'EOFMOUNT'
#!/bin/bash
DEVICE="$1"
MOUNT_BASE="/media/hsparc"

# Get label from blkid
LABEL=$(blkid -o value -s LABEL "$DEVICE" 2>/dev/null)
LABEL=$(echo "$LABEL" | tr -cd '[:alnum:]._-' | head -c 32)
[ -z "$LABEL" ] && LABEL="USB"

MOUNT_POINT="${MOUNT_BASE}/${LABEL}"
mkdir -p "$MOUNT_POINT"
chown hsparc:hsparc "$MOUNT_POINT"

# Get filesystem type
FSTYPE=$(blkid -o value -s TYPE "$DEVICE" 2>/dev/null)

case "$FSTYPE" in
    vfat|exfat)
        mount -t "$FSTYPE" -o uid=1001,gid=1001,umask=0002 "$DEVICE" "$MOUNT_POINT"
        ;;
    ntfs)
        mount -t ntfs-3g -o uid=1001,gid=1001,umask=0002 "$DEVICE" "$MOUNT_POINT"
        ;;
    *)
        mount "$DEVICE" "$MOUNT_POINT"
        chown hsparc:hsparc "$MOUNT_POINT" 2>/dev/null || true
        ;;
esac
EOFMOUNT
chmod +x /usr/local/bin/hsparc-usb-mount.sh

# Create unmount script
cat > /usr/local/bin/hsparc-usb-unmount.sh << 'EOFUNMOUNT'
#!/bin/bash
DEVICE="$1"
MOUNT_BASE="/media/hsparc"

# Find and unmount any mounts from this device
for mp in "$MOUNT_BASE"/*; do
    if [ -d "$mp" ] && mountpoint -q "$mp" 2>/dev/null; then
        umount "$mp" 2>/dev/null || umount -l "$mp" 2>/dev/null || true
        rmdir "$mp" 2>/dev/null || true
        logger "HSPARC: Unmounted $mp"
    fi
done
EOFUNMOUNT
chmod +x /usr/local/bin/hsparc-usb-unmount.sh

# Disable Ubuntu automounter for USB drives
cat > /etc/udev/rules.d/85-no-automount.rules << 'EOFNOAUTO'
ENV{ID_BUS}=="usb", ENV{UDISKS_AUTO}="0", ENV{UDISKS_IGNORE}="1"
EOFNOAUTO

# Create systemd service for USB mounting
cat > /etc/systemd/system/hsparc-usb-mount@.service << 'EOFSVC'
[Unit]
Description=Mount USB drive for HSPARC
After=dev-%i.device

[Service]
Type=oneshot
ExecStart=/usr/local/bin/hsparc-usb-mount.sh /dev/%I
RemainAfterExit=no
EOFSVC

# Create udev rule for USB auto-mount
cat > /etc/udev/rules.d/99-hsparc-usb.rules << 'EOFUDEV'
# HSPARC USB Auto-mount Rule
# Automatically mount USB drives for hsparc user

# Mount USB storage devices when inserted
ACTION=="add", SUBSYSTEM=="block", ENV{ID_FS_USAGE}=="filesystem", ENV{ID_BUS}=="usb", TAG+="systemd", ENV{SYSTEMD_WANTS}="hsparc-usb-mount@%k.service"

# Unmount when removed
ACTION=="remove", SUBSYSTEM=="block", ENV{ID_BUS}=="usb", RUN+="/usr/local/bin/hsparc-usb-unmount.sh %E{DEVNAME}"
EOFUDEV

# Reload udev rules
udevadm control --reload-rules
udevadm trigger

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

# Re-enable GDM autologin (in case admin disabled it)
sudo sed -i "s/AutomaticLoginEnable=false/AutomaticLoginEnable=true/" /etc/gdm3/custom.conf
# Launch HSPARC in kiosk mode
export HSPARC_KIOSK=1
cd /opt/hsparc
# Loop to restart after eject
while true; do
    /opt/hsparc/venv/bin/python /opt/hsparc/main.py
    sleep 2
done
EOFSTARTUP

chmod +x /home/$KIOSK_USER/.icewm/startup

# Create admin escape script for exiting kiosk mode
cat > /usr/local/bin/hsparc-admin-escape.sh << 'EOFADMIN'
#!/bin/bash
sed -i "s/AutomaticLoginEnable=true/AutomaticLoginEnable=false/" /etc/gdm3/custom.conf
pkill -u hsparc
EOFADMIN
chmod +x /usr/local/bin/hsparc-admin-escape.sh

# Make hsparc own GDM config so admin escape works without sudo
chown hsparc:hsparc /etc/gdm3/custom.conf

# Create service to re-enable autologin on boot
cat > /etc/systemd/system/hsparc-autologin.service << 'EOFAUTOSVC'
[Unit]
Description=Re-enable HSPARC autologin
Before=gdm.service

[Service]
Type=oneshot
ExecStart=/bin/sed -i 's/AutomaticLoginEnable=false/AutomaticLoginEnable=true/' /etc/gdm3/custom.conf

[Install]
WantedBy=multi-user.target
EOFAUTOSVC
systemctl daemon-reload
systemctl enable hsparc-autologin.service

# Configure AccountsService for IceWM session
mkdir -p /var/lib/AccountsService/users
cat > /var/lib/AccountsService/users/hsparc << 'EOFACCT'
[User]
Session=icewm-session
XSession=icewm-session
SystemAccount=false
EOFACCT

# Configure GDM autologin for hsparc user
mkdir -p /etc/gdm3
cat > /etc/gdm3/custom.conf << EOFGDM
[daemon]
AutomaticLoginEnable=true
AutomaticLogin=$KIOSK_USER

[security]

[xdmcp]

[chooser]

[debug]
EOFGDM

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
echo_info "  ✓ USB auto-mount configured"
echo_info "  ✓ Auto-login enabled"
echo ""
echo_info "Next steps:"
echo_info "  1. Reboot: sudo reboot"
echo_info "  2. System will auto-login and start HSPARC"
echo ""

# Create update script
cat > /usr/local/bin/hsparc-update.sh << 'EOFUPDATESCRIPT'
#!/bin/bash
echo "Updating HSPARC..."
curl -fsSL "https://raw.githubusercontent.com/drjhoover/hsparc-releases/main/setup-hsparc.sh?$(date +%s)" | sudo bash
echo ""
echo "Update complete. Press Enter to reboot..."
read
sudo reboot
EOFUPDATESCRIPT
chmod +x /usr/local/bin/hsparc-update.sh

# Create desktop shortcut for admin user
for user_home in /home/*; do
    if [ -d "$user_home/Desktop" ] && [ "$(basename $user_home)" != "$KIOSK_USER" ]; then
        cat > "$user_home/Desktop/Update-HSPARC.desktop" << 'EOFDESKTOP'
[Desktop Entry]
Version=1.0
Type=Application
Name=Update HSPARC
Comment=Download and install latest HSPARC
Exec=gnome-terminal -- /usr/local/bin/hsparc-update.sh
Icon=system-software-update
Terminal=false
Categories=Utility;
EOFDESKTOP
        chmod +x "$user_home/Desktop/Update-HSPARC.desktop"
    fi
done
