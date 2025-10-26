#!/usr/bin/env bash
set -euo pipefail

# HSPARC Setup Utility
# Handles installation, reinstallation, updates, and uninstallation

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_NAME="hsparc"
APP_DIR="/opt/${APP_NAME}"
KIOSK_USER="hsparc"
KIOSK_HOME="/home/${KIOSK_USER}"
BACKUP_DIR="${KIOSK_HOME}/backups"
GIT_REPO="https://github.com/drjhoover/hsparc-releases.git"
GIT_BRANCH="main"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

echo_info() { echo -e "${GREEN}[INFO]${NC} $*"; }
echo_warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
echo_error() { echo -e "${RED}[ERROR]${NC} $*"; }
echo_step() { echo -e "${BLUE}[STEP]${NC} $*"; }
echo_prompt() { echo -e "${CYAN}[INPUT]${NC} $*"; }

show_banner() {
    echo ""
    echo_info "=========================================="
    echo_info "       HSPARC Setup Utility v1.0"
    echo_info "    Human Factors Research Application"
    echo_info "=========================================="
}

is_installed() {
    [ -d "$APP_DIR" ] && [ -f "$APP_DIR/hsparc" ]
}

get_installed_version() {
    if [ -f "$APP_DIR/version.txt" ]; then
        cat "$APP_DIR/version.txt"
    else
        echo "unknown"
    fi
}

backup_data() {
    local backup_name="${1:-backup-$(date +%Y%m%d-%H%M%S)}"
    local backup_path="${BACKUP_DIR}/${backup_name}"
    
    echo_step "Creating backup: ${backup_name}"
    
    mkdir -p "$BACKUP_DIR"
    mkdir -p "${backup_path}"
    
    if [ -d "${KIOSK_HOME}/.local/share/hsparc" ]; then
        cp -r "${KIOSK_HOME}/.local/share/hsparc" "${backup_path}/"
        echo_info "Data backed up ✓"
    else
        echo_warn "No data to backup"
    fi
    
    if [ -d "${KIOSK_HOME}/.config/hsparc" ]; then
        cp -r "${KIOSK_HOME}/.config/hsparc" "${backup_path}/"
        echo_info "Config backed up ✓"
    fi
    
    echo "$(get_installed_version)" > "${backup_path}/version.txt"
    chown -R ${KIOSK_USER}:${KIOSK_USER} "$BACKUP_DIR"
}

install_dependencies() {
    echo_step "Installing system dependencies..."
    
    local packages="icewm unclutter xdotool x11-xserver-utils pavucontrol pulseaudio python3 python3-pip python3-dev gcc g++ git"
    
    echo_info "Installing: ${packages}"
    apt-get update -qq
    apt-get install -y ${packages} >/dev/null 2>&1
    
    echo_info "Dependencies installed ✓"
}

create_user() {
    echo_step "Creating ${KIOSK_USER} user..."
    
    if id "$KIOSK_USER" &>/dev/null; then
        echo_warn "User ${KIOSK_USER} already exists"
    else
        useradd -m -s /bin/bash "$KIOSK_USER"
        echo_info "User created ✓"
    fi
    
    echo_info "Adding user to required groups..."
    usermod -a -G video,audio,input,plugdev "$KIOSK_USER"
    echo_info "Groups configured ✓"
}

configure_icewm() {
    echo_step "Configuring IceWM window manager..."
    
    mkdir -p "${KIOSK_HOME}/.icewm"
    
    cat > "${KIOSK_HOME}/.icewm/preferences" << 'EOF'
DesktopBackgroundColor="rgb:00/00/00"
TaskBarAutoHide=1
TaskBarShowWorkspaces=0
TaskBarShowAllWindows=0
TaskBarShowClock=0
ShowTaskBar=0
EOF
    
    chown -R ${KIOSK_USER}:${KIOSK_USER} "${KIOSK_HOME}/.icewm"
    echo_info "IceWM configured ✓"
}

install_application() {
    local source_method="$1"
    local source_path="$2"
    
    echo_step "Installing HSPARC application..."
    
    if [ -d "$APP_DIR" ]; then
        echo_info "Removing old installation..."
        rm -rf "$APP_DIR"
    fi
    
    mkdir -p "$APP_DIR"
    
    if [ "$source_method" = "download" ]; then
        echo_info "Downloading latest release..."
        
        local temp_dir=$(mktemp -d)
        local release_url="https://github.com/drjhoover/hsparc-releases/releases/download/1.0/hsparc-1.0.0-linux-x64.tar.gz"
        
        cd "$temp_dir"
        wget -L -q --show-progress "$release_url" -O hsparc.tar.gz
        
        if [ ! -f hsparc.tar.gz ]; then
            echo_error "Failed to download release"
            rm -rf "$temp_dir"
            return 1
        fi
        
        echo_info "Extracting..."
        tar -xzf hsparc.tar.gz -C "$APP_DIR"
        rm -rf "$temp_dir"
        
    elif [ "$source_method" = "local" ]; then
        echo_info "Installing from: ${source_path}"
        
        if [[ "$source_path" =~ \.tar\.gz$ ]]; then
            tar -xzf "$source_path" -C "$APP_DIR" --strip-components=1
        elif [ -d "$source_path" ]; then
            cp -r "$source_path/"* "$APP_DIR/"
        else
            echo_error "Invalid source path: $source_path"
            return 1
        fi
    fi
    
    chmod +x "$APP_DIR/hsparc" 2>/dev/null || true
    chown -R ${KIOSK_USER}:${KIOSK_USER} "$APP_DIR"
    
    echo_info "Application installed ✓"
}

create_kiosk_launcher() {
    echo_step "Creating kiosk launcher..."
    
    mkdir -p "${KIOSK_HOME}/.local/bin"
    
    cat > "${KIOSK_HOME}/.local/bin/hsparc-kiosk-start.sh" << 'SCRIPT_EOF'
#!/usr/bin/env bash
set -euo pipefail

LOG="/tmp/hsparc-kiosk-$(date +%Y%m%d-%H%M%S).log"
: "${DISPLAY:=:0}"

log() {
    echo "[$(date --iso-8601=seconds)] $*" | tee -a "$LOG"
}

log "======================================"
log "HSPARC Kiosk Startup"
log "======================================"

# Wait for X server
for i in {1..60}; do
    if xset q &>/dev/null; then
        log "X server ready"
        break
    fi
    [ $i -eq 60 ] && { log "ERROR: X server timeout"; exit 1; }
    sleep 0.5
done

# Configure display
xset s off
xset -dpms
xset s noblank

# Hide cursor
unclutter -idle 0.1 -root &

# Launch HSPARC
log "Launching HSPARC..."
cd /opt/hsparc
./hsparc 2>&1 | tee -a "$LOG"
SCRIPT_EOF
    
    chmod +x "${KIOSK_HOME}/.local/bin/hsparc-kiosk-start.sh"
    chown -R ${KIOSK_USER}:${KIOSK_USER} "${KIOSK_HOME}/.local"
    
    echo_info "Kiosk launcher created ✓"
}

configure_autologin() {
    echo_step "Configuring GDM auto-login..."
    
    local GDM_CONF="/etc/gdm3/custom.conf"
    
    if [ ! -f "$GDM_CONF" ]; then
        echo_error "GDM config not found"
        return 1
    fi
    
    if ! grep -q "AutomaticLoginEnable = true" "$GDM_CONF"; then
        sed -i '/\[daemon\]/a AutomaticLoginEnable = true' "$GDM_CONF"
        sed -i "/AutomaticLoginEnable = true/a AutomaticLogin = ${KIOSK_USER}" "$GDM_CONF"
        echo_info "Auto-login configured ✓"
    else
        echo_warn "Auto-login already configured"
    fi
    
    mkdir -p "${KIOSK_HOME}/.config/autostart"
    cat > "${KIOSK_HOME}/.config/autostart/hsparc-kiosk.desktop" << EOF
[Desktop Entry]
Type=Application
Name=HSPARC Kiosk
Exec=${KIOSK_HOME}/.local/bin/hsparc-kiosk-start.sh
X-GNOME-Autostart-enabled=true
EOF
    
    chown -R ${KIOSK_USER}:${KIOSK_USER} "${KIOSK_HOME}/.config"
}

full_install() {
    echo ""
    echo_info "=========================================="
    echo_info "   FULL INSTALLATION"
    echo_info "=========================================="
    
    install_dependencies
    create_user
    configure_icewm
    
    echo ""
    echo_prompt "Installation source:"
    echo "  1) Download latest from GitHub"
    echo "  2) Install from local archive/directory"
    echo -n "Select (1-2): "
    read -r source_choice
    
    case $source_choice in
        1)
            install_application "download" ""
            ;;
        2)
            echo_prompt "Enter path to archive (.tar.gz) or directory:"
            read -r source_path
            install_application "local" "$source_path"
            ;;
        *)
            echo_error "Invalid choice"
            return 1
            ;;
    esac
    
    create_kiosk_launcher
    configure_autologin
    
    echo ""
    echo_info "=========================================="
    echo_info "   INSTALLATION COMPLETE!"
    echo_info "=========================================="
    echo ""
    echo_info "Reboot to start HSPARC in kiosk mode"
    echo ""
}

show_menu() {
    clear
    show_banner
    
    if is_installed; then
        echo_info "Status: INSTALLED (version $(get_installed_version))"
    else
        echo_info "Status: NOT INSTALLED"
    fi
    
    echo ""
    echo "Select an operation:"
    echo ""
    echo "  1) Full Installation     - Install HSPARC with user and system config"
    echo "  2) Reinstall App Only    - Reinstall app, preserve data and config"
    echo "  3) Update App Only       - Update to latest version from repository"
    echo "  4) Uninstall            - Remove HSPARC from this system"
    echo "  5) List Backups         - Show available backups"
    echo "  6) Restore Backup       - Restore data from backup"
    echo "  0) Exit"
    echo ""
    echo -n "Enter choice [0-6]: "
}

main() {
    if [ "$EUID" -ne 0 ]; then
        echo_error "This script must be run as root (use sudo)"
        exit 1
    fi
    
    while true; do
        show_menu
        read -r choice
        
        case $choice in
            1) full_install ;;
            0) echo ""; echo_info "Goodbye!"; exit 0 ;;
            *) echo_error "Invalid choice"; sleep 2 ;;
        esac
        
        echo ""
        echo_prompt "Press Enter to continue..."
        read -r
    done
}

main
