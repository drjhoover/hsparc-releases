#!/usr/bin/env bash
set -euo pipefail
# HSPARC Update Script
# Updates existing HSPARC installation to latest version

INSTALL_DIR="/opt/hsparc"
KIOSK_USER="hsparc"
VERSION_URL="https://raw.githubusercontent.com/drjhoover/hsparc-releases/main/version.json"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo_info() { echo -e "${GREEN}[INFO]${NC} $*"; }
echo_warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
echo_error() { echo -e "${RED}[ERROR]${NC} $*"; }
echo_step() { echo -e "${BLUE}[STEP]${NC} $*"; }

# Check root
if [ "$EUID" -ne 0 ]; then
    echo_error "This script must be run as root (use sudo)"
    exit 1
fi

echo_info "=========================================="
echo_info "       HSPARC Updater"
echo_info "=========================================="
echo ""

# Clean up legacy systemd service if it exists
if [ -f /etc/systemd/system/hsparc.service ]; then
    echo_step "Removing legacy systemd service..."
    systemctl stop hsparc 2>/dev/null || true
    systemctl disable hsparc 2>/dev/null || true
    rm -f /etc/systemd/system/hsparc.service
    systemctl daemon-reload
    echo_info "Legacy service removed ✓"
fi

# Check if HSPARC is installed
if [ ! -d "$INSTALL_DIR" ]; then
    echo_error "HSPARC is not installed at $INSTALL_DIR"
    echo_info "Run setup-hsparc.sh to install first"
    exit 1
fi

# Get current version
CURRENT_VERSION="unknown"
if [ -f "$INSTALL_DIR/.version" ]; then
    CURRENT_VERSION=$(cat "$INSTALL_DIR/.version")
fi
echo_info "Current version: $CURRENT_VERSION"

# Check for latest version
echo_step "Checking for updates..."
if ! LATEST_INFO=$(curl -fsSL "$VERSION_URL"); then
    echo_error "Could not check for updates (network error)"
    exit 1
fi

LATEST_VERSION=$(echo "$LATEST_INFO" | grep -Po '"version":\s*"\K[^"]+')
DOWNLOAD_URL=$(echo "$LATEST_INFO" | grep -Po '"download_url":\s*"\K[^"]+')

echo_info "Latest version: $LATEST_VERSION"

# Compare versions
if [ "$CURRENT_VERSION" = "$LATEST_VERSION" ]; then
    echo_info "Already up to date!"
    echo ""
    read -p "Re-apply kiosk configuration anyway? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 0
    fi
else
    echo_warn "Update available: $CURRENT_VERSION → $LATEST_VERSION"
    echo ""
    read -p "Continue with update? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo_info "Update cancelled"
        exit 0
    fi

    # Kill any running HSPARC processes
    echo_step "Stopping HSPARC..."
    pkill -f "python.*main.py" 2>/dev/null || true
    sleep 2

    # Backup current installation
    BACKUP_DIR="${INSTALL_DIR}.backup-$(date +%Y%m%d-%H%M%S)"
    echo_step "Backing up to: $BACKUP_DIR"
    cp -r "$INSTALL_DIR" "$BACKUP_DIR"

    # Download new version
    echo_step "Downloading HSPARC v${LATEST_VERSION}..."
    mkdir -p /tmp/hsparc-update
    cd /tmp/hsparc-update
    if ! wget -q --show-progress "$DOWNLOAD_URL" -O hsparc.tar.gz; then
        echo_error "Download failed!"
        echo_info "Backup is at: $BACKUP_DIR"
        exit 1
    fi

    # Extract update (preserve venv)
    echo_step "Installing update..."
    mv "$INSTALL_DIR/venv" /tmp/hsparc-update/venv.backup
    rm -rf "$INSTALL_DIR"/*
    tar -xzf hsparc.tar.gz -C "$INSTALL_DIR" --strip-components=1
    mv /tmp/hsparc-update/venv.backup "$INSTALL_DIR/venv"

    # Update Python dependencies
    echo_step "Updating dependencies..."
    cd "$INSTALL_DIR"
    source venv/bin/activate
    pip install --upgrade -r requirements.txt

    # Set permissions
    chown -R $KIOSK_USER:$KIOSK_USER "$INSTALL_DIR"

    # Cleanup download
    rm -rf /tmp/hsparc-update

    # Keep only last 3 backups
    echo_step "Cleaning old backups..."
    ls -dt ${INSTALL_DIR}.backup-* 2>/dev/null | tail -n +4 | xargs rm -rf 2>/dev/null || true
fi

# Update kiosk configuration
echo_step "Updating kiosk configuration..."

# Ensure sudoers file exists for shutdown
if [ ! -f /etc/sudoers.d/hsparc-shutdown ]; then
    echo_info "Adding shutdown privileges..."
    cat > /etc/sudoers.d/hsparc-shutdown << 'EOFSUDO'
# Allow hsparc user to shutdown/reboot without password
hsparc ALL=(ALL) NOPASSWD: /sbin/shutdown, /sbin/reboot, /sbin/poweroff
EOFSUDO
    chmod 0440 /etc/sudoers.d/hsparc-shutdown
fi

# Update IceWM preferences with comprehensive keyboard lockdown
mkdir -p /home/$KIOSK_USER/.icewm
cat > /home/$KIOSK_USER/.icewm/preferences << 'EOFPREFS'
# HSPARC Kiosk Mode - IceWM Preferences
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

# Update IceWM prefoverride for background
cat > /home/$KIOSK_USER/.icewm/prefoverride << 'EOFPREFOVER'
DesktopBackgroundImage="/opt/hsparc/resources/hsparc_background.jpg"
DesktopBackgroundScaled=1
DesktopBackgroundCenter=0
EOFPREFOVER

# Update IceWM startup script
cat > /home/$KIOSK_USER/.icewm/startup << 'EOFSTARTUP'
#!/bin/bash
sleep 2
if [ -f /opt/hsparc/resources/hsparc_background.jpg ]; then
    feh --bg-fill /opt/hsparc/resources/hsparc_background.jpg
fi
killall icewmbg 2>/dev/null
icewmbg -r &
xset s off -dpms s noblank
unclutter -idle 3 -root &
export HSPARC_KIOSK=1
cd /opt/hsparc
/opt/hsparc/venv/bin/python /opt/hsparc/main.py
EOFSTARTUP

chmod +x /home/$KIOSK_USER/.icewm/startup
chown -R $KIOSK_USER:$KIOSK_USER /home/$KIOSK_USER/.icewm

echo_info "Kiosk configuration updated ✓"

echo ""
echo_info "=========================================="
echo_info "  Update Complete!"
echo_info "=========================================="
echo ""
if [ "$CURRENT_VERSION" != "$LATEST_VERSION" ]; then
    echo_info "Updated: $CURRENT_VERSION → $LATEST_VERSION"
fi
echo_info "Kiosk configuration refreshed"
echo ""
echo_info "Reboot to apply changes: sudo reboot"
echo ""
