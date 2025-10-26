#!/usr/bin/env bash
# HSPARC Setup Utility
# Handles: Install, Reinstall, Update, Uninstall
# Usage: sudo ./setup-hsparc.sh

set -euo pipefail

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

# Configuration
KIOSK_USER="hsparc"
KIOSK_HOME="/home/$KIOSK_USER"
APP_DIR="/opt/hsparc"
BACKUP_DIR="/var/backups/hsparc"
DATA_DIR="$KIOSK_HOME/.local/share/hsparc"
CONFIG_FILE="$DATA_DIR/global_av.json"
VERSION_FILE="$APP_DIR/version.json"

# Git configuration
GIT_REPO="https://github.com/drjhoover/hsparc.git"  # UPDATE THIS
GIT_BRANCH="main"

# Check root
if [[ $EUID -ne 0 ]]; then
   echo_error "This script must be run as root (use sudo)"
   exit 1
fi

# Banner
show_banner() {
    echo ""
    echo_info "=========================================="
    echo_info "       HSPARC Setup Utility v1.0"
    echo_info "    Human Factors Research Application"
    echo_info "=========================================="
    echo ""
}

# Check if already installed
is_installed() {
    [ -d "$APP_DIR" ] && [ -f "$APP_DIR/hsparc" ]
}

# Get installed version
get_installed_version() {
    if [ -f "$VERSION_FILE" ]; then
        python3 -c "import json; print(json.load(open('$VERSION_FILE'))['version'])" 2>/dev/null || echo "unknown"
    else
        echo "none"
    fi
}

# Backup function
backup_data() {
    local backup_name="$1"
    local backup_path="${BACKUP_DIR}/${backup_name}"
    
    echo_step "Creating backup: ${backup_name}"
    
    mkdir -p "$backup_path"
    
    # Backup database and config
    if [ -d "$DATA_DIR" ]; then
        echo_info "Backing up user data..."
        cp -r "$DATA_DIR" "${backup_path}/data"
    fi
    
    # Backup version info
    if [ -f "$VERSION_FILE" ]; then
        cp "$VERSION_FILE" "${backup_path}/version.json"
    fi
    
    # Create manifest
    cat > "${backup_path}/manifest.txt" << EOF
HSPARC Backup
Created: $(date -u +"%Y-%m-%d %H:%M:%S UTC")
Version: $(get_installed_version)
User: $KIOSK_USER
Data: $DATA_DIR
Application: $APP_DIR
EOF
    
    echo_info "Backup created: ${backup_path}"
    echo_info "Backup size: $(du -sh ${backup_path} | cut -f1)"
}

# Restore function
restore_from_backup() {
    local backup_name="$1"
    local backup_path="${BACKUP_DIR}/${backup_name}"
    
    if [ ! -d "$backup_path" ]; then
        echo_error "Backup not found: ${backup_name}"
        return 1
    fi
    
    echo_step "Restoring from backup: ${backup_name}"
    
    if [ -d "${backup_path}/data" ]; then
        echo_info "Restoring user data..."
        mkdir -p "$DATA_DIR"
        cp -r "${backup_path}/data/"* "$DATA_DIR/"
        chown -R "$KIOSK_USER:$KIOSK_USER" "$DATA_DIR"
    fi
    
    echo_info "Restore complete"
}

# List backups
list_backups() {
    if [ ! -d "$BACKUP_DIR" ]; then
        echo_info "No backups found"
        return
    fi
    
    echo_info "Available backups:"
    for backup in "$BACKUP_DIR"/*; do
        if [ -d "$backup" ]; then
            local name=$(basename "$backup")
            local size=$(du -sh "$backup" | cut -f1)
            local manifest="${backup}/manifest.txt"
            if [ -f "$manifest" ]; then
                local created=$(grep "Created:" "$manifest" | cut -d: -f2-)
                echo "  - $name (${size}, created:${created})"
            else
                echo "  - $name (${size})"
            fi
        fi
    done
}

# Install dependencies
install_dependencies() {
    echo_step "Installing system dependencies..."
    
    apt-get update -qq
    
    # Core dependencies
    PACKAGES=(
        # Window manager
        icewm
        # X utilities
        unclutter
        xdotool
        x11-xserver-utils
        # Audio
        pavucontrol
        pulseaudio
        # Development (if building from source)
        python3
        python3-pip
        python3-dev
        gcc
        g++
        # Version control
        git
    )
    
    echo_info "Installing: ${PACKAGES[*]}"
    apt-get install -y "${PACKAGES[@]}" &>/dev/null
    
    echo_info "Dependencies installed ✓"
}

# Create hsparc user
create_user() {
    echo_step "Creating hsparc user..."
    
    if id "$KIOSK_USER" &>/dev/null; then
        echo_warn "User $KIOSK_USER already exists"
    else
        # Create user with home directory
        useradd -m -s /bin/bash "$KIOSK_USER"
        
        # Set password (optional - for SSH access)
        echo_prompt "Set password for $KIOSK_USER? (y/n)"
        read -r set_password
        if [[ "$set_password" =~ ^[Yy]$ ]]; then
            passwd "$KIOSK_USER"
        fi
        
        echo_info "User created ✓"
    fi
    
    # Add to required groups
    echo_info "Adding user to required groups..."
    REQUIRED_GROUPS="video input audio"
    for group in $REQUIRED_GROUPS; do
        usermod -aG "$group" "$KIOSK_USER" 2>/dev/null || true
    done
    
    echo_info "Groups configured ✓"
}

# Configure IceWM
configure_icewm() {
    echo_step "Configuring IceWM window manager..."
    
    local icewm_dir="$KIOSK_HOME/.icewm"
    mkdir -p "$icewm_dir"
    
    # IceWM preferences for kiosk mode
    cat > "$icewm_dir/preferences" << 'EOF'
# HSPARC Kiosk Mode - IceWM Configuration

# Disable taskbar and menu
ShowTaskBar=0
ShowMenu=0

# Disable desktop icons
ShowDesktop=0

# Focus follows mouse
FocusMode=1

# Disable window decorations for fullscreen
FullscreenBorders=0

# Disable window snapping sounds
SoundPlay=""

# Workspace settings
WorkspaceNames=" "
WorkspaceCount=1

# Disable desktop switching
DesktopBackgroundCenter=0
EOF
    
    # IceWM startup
    cat > "$icewm_dir/startup" << 'EOF'
#!/usr/bin/env bash
# HSPARC IceWM Startup

# Disable screen blanking
xset s off -dpms s noblank

# Hide cursor after 3 seconds
unclutter -idle 3 -root &

# Launch HSPARC
/home/hsparc/.local/bin/hsparc-kiosk-start.sh &
EOF
    
    chmod +x "$icewm_dir/startup"
    chown -R "$KIOSK_USER:$KIOSK_USER" "$icewm_dir"
    
    echo_info "IceWM configured ✓"
}

# Install application
install_application() {
    local source_method="$1"  # "download" or "local"
    local source_path="$2"
    
    echo_step "Installing HSPARC application..."
    
    # Remove old installation if exists
    if [ -d "$APP_DIR" ]; then
        echo_info "Removing old installation..."
        rm -rf "$APP_DIR"
    fi
    
    mkdir -p "$APP_DIR"
    
    if [ "$source_method" = "download" ]; then
    if [ "$source_method" = "download" ]; then
        # Download latest release from GitHub
        echo_info "Downloading latest release..."
        
        local temp_dir=$(mktemp -d)
        local release_url="https://github.com/drjhoover/hsparc-releases/releases/download/1.0/hsparc-1.0.0-linux-x64.tar.gz"
        
        cd "$temp_dir"
        wget -q --show-progress "$release_url" -O hsparc.tar.gz
        
        if [ ! -f hsparc.tar.gz ]; then
            echo_error "Failed to download release"
            rm -rf "$temp_dir"
            return 1
        fi
        
        # Extract to APP_DIR
        echo_info "Extracting..."
        tar -xzf hsparc.tar.gz -C "$APP_DIR"
        
        rm -rf "$temp_dir"
        
        rm -rf "$temp_dir"
        
    elif [ "$source_method" = "local" ]; then
        # Install from local archive
        echo_info "Installing from: ${source_path}"
        
        if [[ "$source_path" =~ \.tar\.gz$ ]]; then
            # Extract archive
            tar -xzf "$source_path" -C "$APP_DIR" --strip-components=1
        elif [ -d "$source_path" ]; then
            # Copy directory
            cp -r "$source_path/"* "$APP_DIR/"
        else
            echo_error "Invalid source path: $source_path"
            return 1
        fi
    fi
    
    # Make binary executable
    chmod +x "$APP_DIR/hsparc"
    
    # Create wrapper script for main.py compatibility
    cat > "$APP_DIR/main.py" << 'EOF'
#!/usr/bin/env python3
"""HSPARC wrapper - launches compiled binary"""
import os
import sys

binary_path = os.path.join(os.path.dirname(__file__), 'hsparc')
os.execv(binary_path, [binary_path] + sys.argv[1:])
EOF
    chmod +x "$APP_DIR/main.py"
    
    # Verify installation
    if [ ! -f "$APP_DIR/hsparc" ]; then
        echo_error "Installation failed - binary not found"
        return 1
    fi
    
    echo_info "Application installed ✓"
    
    # Show version
    local version=$(get_installed_version)
    echo_info "Installed version: ${version}"
}

# Create kiosk launch script
create_kiosk_launcher() {
    echo_step "Creating kiosk launcher..."
    
    mkdir -p "$KIOSK_HOME/.local/bin"
    
    cat > "$KIOSK_HOME/.local/bin/hsparc-kiosk-start.sh" << 'SCRIPT_EOF'
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
log "User: $(whoami)"
log "Display: $DISPLAY"

# Wait for X server
log "Waiting for X server..."
for i in {1..60}; do
    if xset q &>/dev/null; then
        log "X server ready"
        break
    fi
    [ $i -eq 60 ] && { log "ERROR: X server timeout"; exit 1; }
    sleep 0.5
done

# Configure X
log "Configuring X settings..."
xset s off -dpms s noblank || log "WARN: xset failed"

# Hide cursor
log "Starting unclutter..."
pkill -u hsparc unclutter 2>/dev/null || true
unclutter -idle 3 -root &

# Environment
export DISPLAY="$DISPLAY"
export QT_QPA_PLATFORM=xcb
export QT_MEDIA_USE_HARDWARE_DECODER=0
export LIBVA_DRIVER_NAME=" "
export HSPARC_KIOSK=1

log "Environment configured"

# Change directory
cd /opt/hsparc || { log "ERROR: Cannot cd to /opt/hsparc"; exit 1; }

# Verify binary
if [ ! -f "/opt/hsparc/hsparc" ]; then
    log "ERROR: HSPARC binary not found"
    exit 1
fi

log "Using: /opt/hsparc/hsparc"

# Launch loop (auto-restart on crash)
while true; do
    log "======================================"
    log "Starting HSPARC..."
    log "======================================"
    
    /opt/hsparc/hsparc 2>&1 | tee -a "$LOG"
    EXIT_CODE=$?
    
    log "HSPARC exited: $EXIT_CODE"
    
    # Clean exit - don't restart
    [ $EXIT_CODE -eq 0 ] && { log "Clean exit"; break; }
    
    log "Restarting in 3 seconds..."
    sleep 3
done
SCRIPT_EOF
    
    chmod +x "$KIOSK_HOME/.local/bin/hsparc-kiosk-start.sh"
    chown -R "$KIOSK_USER:$KIOSK_USER" "$KIOSK_HOME/.local"
    
    echo_info "Kiosk launcher created ✓"
}

# Configure GDM auto-login
configure_autologin() {
    echo_step "Configuring GDM auto-login..."
    
    local GDM_CONF="/etc/gdm3/custom.conf"
    
    if [ ! -f "$GDM_CONF" ]; then
        echo_error "GDM3 config not found at $GDM_CONF"
        echo_warn "Auto-login must be configured manually"
        return 1
    fi
    
    # Backup original
    cp "$GDM_CONF" "$GDM_CONF.backup-$(date +%Y%m%d-%H%M%S)"
    
    # Check if auto-login already configured
    if grep -q "^AutomaticLogin = $KIOSK_USER" "$GDM_CONF"; then
        echo_info "Auto-login already configured ✓"
        return 0
    fi
    
    # Add/update auto-login in [daemon] section
    if grep -q "^\[daemon\]" "$GDM_CONF"; then
        # Section exists, add under it
        sed -i "/^\[daemon\]/a AutomaticLoginEnable = true\nAutomaticLogin = $KIOSK_USER" "$GDM_CONF"
    else
        # Section doesn't exist, create it
        echo "" >> "$GDM_CONF"
        echo "[daemon]" >> "$GDM_CONF"
        echo "AutomaticLoginEnable = true" >> "$GDM_CONF"
        echo "AutomaticLogin = $KIOSK_USER" >> "$GDM_CONF"
    fi
    
    # Set IceWM as default session
    mkdir -p "/var/lib/AccountsService/users"
    cat > "/var/lib/AccountsService/users/$KIOSK_USER" << EOF
[User]
Session=icewm-session
XSession=icewm-session
Icon=/var/lib/AccountsService/icons/$KIOSK_USER
SystemAccount=false
EOF
    
    echo_info "Auto-login configured ✓"
}

# OPERATION 1: Full Installation
full_install() {
    echo ""
    echo_info "=========================================="
    echo_info "   FULL INSTALLATION"
    echo_info "=========================================="
    echo ""
    
    if is_installed; then
        echo_warn "HSPARC is already installed (version $(get_installed_version))"
        echo_prompt "Continue with full installation? This will reinstall. (y/n)"
        read -r confirm
        [[ ! "$confirm" =~ ^[Yy]$ ]] && return 0
        
        # Create backup first
        backup_data "pre-install-$(date +%Y%m%d-%H%M%S)"
    fi
    
    # Steps
    install_dependencies
    create_user
    configure_icewm
    
    # Ask for installation source
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
    
    # Success message
    echo ""
    echo_info "=========================================="
    echo_info "   INSTALLATION COMPLETE!"
    echo_info "=========================================="
    echo ""
    echo_info "HSPARC v$(get_installed_version) has been installed"
    echo ""
    echo_info "Next steps:"
    echo_info "  1. Reboot the system: sudo reboot"
    echo_info "  2. System will auto-login as 'hsparc'"
    echo_info "  3. HSPARC will launch automatically in kiosk mode"
    echo ""
    echo_info "Manual testing:"
    echo_info "  sudo su - hsparc -c '/home/hsparc/.local/bin/hsparc-kiosk-start.sh'"
    echo ""
    echo_info "To disable kiosk mode:"
    echo_info "  Remove auto-login from /etc/gdm3/custom.conf"
    
    # Ask for installation source
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
    
    # Recreate launcher (in case it changed)
    create_kiosk_launcher
    
    echo ""
    echo_info "=========================================="
    echo_info "   REINSTALL COMPLETE!"
    echo_info "=========================================="
    echo ""
    echo_info "Previous version: ${current_version}"
    echo_info "New version: $(get_installed_version)"
    echo ""
    echo_info "All user data has been preserved"
    echo_info "Restart HSPARC to use the new version"
    echo ""
}

# OPERATION 3: Update App Only
update_app() {
    echo ""
    echo_info "=========================================="
    echo_info "   UPDATE APPLICATION"
    echo_info "=========================================="
    echo ""
    
    if ! is_installed; then
        echo_error "HSPARC is not installed. Use full installation instead."
        return 1
    fi
    
    local current_version=$(get_installed_version)
    echo_info "Current version: ${current_version}"
    echo ""
    
    # Check for updates
    echo_info "Checking for updates..."
    
    # Clone repo to temp location to check version
    local temp_dir=$(mktemp -d)
    if git clone --depth 1 --branch "$GIT_BRANCH" "$GIT_REPO" "$temp_dir" &>/dev/null; then
        if [ -f "${temp_dir}/version.json" ]; then
            local remote_version=$(python3 -c "import json; print(json.load(open('${temp_dir}/version.json'))['version'])" 2>/dev/null || echo "unknown")
            echo_info "Available version: ${remote_version}"
            
            if [ "$current_version" = "$remote_version" ]; then
                echo_info "You are already running the latest version"
                rm -rf "$temp_dir"
                return 0
            fi
        else
            echo_warn "Could not determine remote version"
            local remote_version="unknown"
        fi
        rm -rf "$temp_dir"
    else
        echo_error "Could not connect to repository"
        return 1
    fi
    
    echo ""
    echo_warn "Update available:"
    echo "  Current: ${current_version}"
    echo "  New:     ${remote_version}"
    echo ""
    echo_prompt "Install update? (y/n)"
    read -r confirm
    [[ ! "$confirm" =~ ^[Yy]$ ]] && return 0
    
    # Create backup
    backup_data "pre-update-${current_version}-to-${remote_version}"
    
    # Download and install
    install_application "download" ""
    
    # Recreate launcher
    create_kiosk_launcher
    
    echo ""
    echo_info "=========================================="
    echo_info "   UPDATE COMPLETE!"
    echo_info "=========================================="
    echo ""
    echo_info "Updated from ${current_version} to $(get_installed_version)"
    echo ""
    echo_info "All user data has been preserved"
    echo_info "Restart HSPARC to use the new version"
    echo ""
}

# OPERATION 4: Uninstall
uninstall_app() {
    echo ""
    echo_info "=========================================="
    echo_info "   UNINSTALL HSPARC"
    echo_info "=========================================="
    echo ""
    
    if ! is_installed; then
        echo_warn "HSPARC is not currently installed"
    fi
    
    echo_warn "This will remove:"
    echo "  âœ— HSPARC application files"
    echo "  âœ— Auto-login configuration"
    echo "  âœ— Kiosk mode scripts"
    echo ""
    
    echo_prompt "Remove user data (database, recordings)? (y/n)"
    read -r remove_data
    
    if [[ "$remove_data" =~ ^[Yy]$ ]]; then
        echo_warn "  âœ— User data (CANNOT BE RECOVERED!)"
    else
        echo_info "  ✓ User data will be preserved"
    fi
    
    echo ""
    echo_prompt "Remove hsparc user account? (y/n)"
    read -r remove_user
    
    if [[ "$remove_user" =~ ^[Yy]$ ]]; then
        echo_warn "  âœ— User account 'hsparc'"
    else
        echo_info "  ✓ User account will be preserved"
    fi
    
    echo ""
    echo_error "WARNING: This action cannot be undone!"
    echo_prompt "Type 'UNINSTALL' to confirm:"
    read -r confirm
    
    if [ "$confirm" != "UNINSTALL" ]; then
        echo_info "Uninstall cancelled"
        return 0
    fi
    
    # Create final backup
    if is_installed; then
        backup_data "pre-uninstall-$(date +%Y%m%d-%H%M%S)"
        echo_info "Final backup created in ${BACKUP_DIR}"
    fi
    
    # Remove application
    if [ -d "$APP_DIR" ]; then
        echo_info "Removing application files..."
        rm -rf "$APP_DIR"
    fi
    
    # Remove kiosk launcher
    if [ -f "$KIOSK_HOME/.local/bin/hsparc-kiosk-start.sh" ]; then
        echo_info "Removing kiosk launcher..."
        rm -f "$KIOSK_HOME/.local/bin/hsparc-kiosk-start.sh"
    fi
    
    # Remove IceWM config
    if [ -d "$KIOSK_HOME/.icewm" ]; then
        echo_info "Removing IceWM configuration..."
        rm -rf "$KIOSK_HOME/.icewm"
    fi
    
    # Remove auto-login
    echo_info "Removing auto-login configuration..."
    local GDM_CONF="/etc/gdm3/custom.conf"
    if [ -f "$GDM_CONF" ]; then
        sed -i '/AutomaticLoginEnable = true/d' "$GDM_CONF"
        sed -i "/AutomaticLogin = $KIOSK_USER/d" "$GDM_CONF"
    fi
    
    # Remove user data if requested
    if [[ "$remove_data" =~ ^[Yy]$ ]]; then
        echo_warn "Removing user data..."
        if [ -d "$DATA_DIR" ]; then
            rm -rf "$DATA_DIR"
        fi
    fi
    
    # Remove user if requested
    if [[ "$remove_user" =~ ^[Yy]$ ]]; then
        echo_warn "Removing user account..."
        userdel -r "$KIOSK_USER" 2>/dev/null || userdel "$KIOSK_USER" 2>/dev/null || true
    fi
    
    echo ""
    echo_info "=========================================="
    echo_info "   UNINSTALL COMPLETE"
    echo_info "=========================================="
    echo ""
    echo_info "HSPARC has been removed from this system"
    
    if [[ ! "$remove_data" =~ ^[Yy]$ ]] && [ -d "$DATA_DIR" ]; then
        echo ""
        echo_info "User data preserved at: ${DATA_DIR}"
    fi
    
    if [ -d "$BACKUP_DIR" ]; then
        echo_info "Backups preserved at: ${BACKUP_DIR}"
    fi
    
    echo ""
}

# Main menu
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
    echo ""
    echo "  5) List Backups         - Show available backups"
    echo "  6) Restore Backup       - Restore data from backup"
    echo ""
    echo "  0) Exit"
    echo ""
    echo -n "Enter choice [0-6]: "
}

# Main program
main() {
    while true; do
        show_menu
        read -r choice
        
        case $choice in
            1)
                full_install
                ;;
            2)
                reinstall_app
                ;;
            3)
                update_app
                ;;
            4)
                uninstall_app
                ;;
            5)
                list_backups
                echo ""
                echo_prompt "Press Enter to continue..."
                read -r
                ;;
            6)
                list_backups
                echo ""
                echo_prompt "Enter backup name to restore:"
                read -r backup_name
                if [ -n "$backup_name" ]; then
                    restore_from_backup "$backup_name"
                fi
                echo ""
                echo_prompt "Press Enter to continue..."
                read -r
                ;;
            0)
                echo ""
                echo_info "Exiting setup utility"
                exit 0
                ;;
            *)
                echo_error "Invalid choice"
                sleep 2
                ;;
        esac
    done
}

# Run main program
main
