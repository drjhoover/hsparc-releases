#!/usr/bin/env bash
# HSPARC Kiosk Configuration Script
# For PyArmor-obfuscated installations
# Run with: sudo ./configure-hsparc-kiosk.sh

set -euo pipefail

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

# Configuration
KIOSK_USER="hsparc"
APP_DIR="/opt/hsparc"
PYTHON_VENV="$APP_DIR/venv"
MAIN_SCRIPT="$APP_DIR/main.py"

# Check root
if [[ $EUID -ne 0 ]]; then
   echo_error "This script must be run as root (use sudo)"
   exit 1
fi

echo ""
echo_info "=========================================="
echo_info "   HSPARC Kiosk Configuration"
echo_info "   For PyArmor-based installations"
echo_info "=========================================="
echo ""

# Verify prerequisites
echo_step "Verifying prerequisites..."

if ! id "$KIOSK_USER" &>/dev/null; then
    echo_error "User '$KIOSK_USER' does not exist!"
    exit 1
fi
echo_info "✓ User '$KIOSK_USER' exists"

if [ ! -d "$APP_DIR" ]; then
    echo_error "Application directory '$APP_DIR' does not exist!"
    exit 1
fi
echo_info "✓ Application directory exists"

if [ ! -f "$MAIN_SCRIPT" ]; then
    echo_error "Main script '$MAIN_SCRIPT' does not exist!"
    exit 1
fi
echo_info "✓ Main script exists"

if [ ! -d "$PYTHON_VENV" ]; then
    echo_error "Python virtual environment '$PYTHON_VENV' does not exist!"
    exit 1
fi
echo_info "✓ Python virtual environment exists"

# Install required packages
echo_step "Installing required packages..."
apt-get update -qq
apt-get install -y \
    icewm \
    unclutter \
    x11-xserver-utils \
    libxcb-cursor0 \
    &>/dev/null
echo_info "✓ Packages installed"

# Create kiosk launcher script
echo_step "Creating kiosk launcher script..."
mkdir -p "/home/$KIOSK_USER/.local/bin"

cat > "/home/$KIOSK_USER/.local/bin/hsparc-kiosk-start.sh" << 'LAUNCHER_EOF'
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

# Hide cursor after 3 seconds
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

# Change to app directory
cd /opt/hsparc || { log "ERROR: Cannot cd to /opt/hsparc"; exit 1; }

# Verify venv and main.py
if [ ! -f "venv/bin/python3" ]; then
    log "ERROR: Python venv not found"
    exit 1
fi

if [ ! -f "main.py" ]; then
    log "ERROR: main.py not found"
    exit 1
fi

log "Using: /opt/hsparc/venv/bin/python3 /opt/hsparc/main.py"

# Launch loop (auto-restart on crash)
while true; do
    log "======================================"
    log "Starting HSPARC..."
    log "======================================"
    
    ./venv/bin/python3 main.py 2>&1 | tee -a "$LOG"
    EXIT_CODE=$?
    
    log "HSPARC exited: $EXIT_CODE"
    
    # Clean exit - don't restart
    [ $EXIT_CODE -eq 0 ] && { log "Clean exit"; break; }
    
    log "Restarting in 3 seconds..."
    sleep 3
done
LAUNCHER_EOF

chmod +x "/home/$KIOSK_USER/.local/bin/hsparc-kiosk-start.sh"
chown -R "$KIOSK_USER:$KIOSK_USER" "/home/$KIOSK_USER/.local"
echo_info "✓ Launcher script created"

# Configure IceWM
echo_step "Configuring IceWM..."
ICEWM_DIR="/home/$KIOSK_USER/.icewm"
mkdir -p "$ICEWM_DIR"

# IceWM preferences
cat > "$ICEWM_DIR/preferences" << 'ICEWM_PREFS_EOF'
# HSPARC Kiosk Mode - IceWM Configuration

# Disable taskbar and menu
ShowTaskBar=0
ShowMenu=0

# Disable desktop icons
ShowDesktop=0

# Click to focus (prevents auto-raising windows)
FocusMode=2
ClickToFocus=1
RaiseOnFocus=0
AutoRaise=0
AutoRaiseDelay=0

# Disable window decorations for fullscreen
FullscreenBorders=0

# Disable window snapping sounds
SoundPlay=""

# Workspace settings
WorkspaceNames=" "
WorkspaceCount=1

# Disable desktop switching
DesktopBackgroundCenter=0
ICEWM_PREFS_EOF

# IceWM background override
cat > "$ICEWM_DIR/prefoverride" << 'ICEWM_OVERRIDE_EOF'
# HSPARC Kiosk Mode - Desktop Background
DesktopBackgroundImage="/opt/hsparc/resources/hsparc_background.jpg"
DesktopBackgroundCenter=0
DesktopBackgroundScaled=1
ICEWM_OVERRIDE_EOF

# IceWM startup script
cat > "$ICEWM_DIR/startup" << 'ICEWM_STARTUP_EOF'
#!/usr/bin/env bash
# HSPARC IceWM Startup

# Disable screen blanking
xset s off -dpms s noblank

# Hide cursor after 3 seconds
unclutter -idle 3 -root &

# Launch HSPARC
/home/hsparc/.local/bin/hsparc-kiosk-start.sh &
ICEWM_STARTUP_EOF

chmod +x "$ICEWM_DIR/startup"
chown -R "$KIOSK_USER:$KIOSK_USER" "$ICEWM_DIR"
echo_info "✓ IceWM configured"

# Configure GDM3 auto-login
echo_step "Configuring GDM3 auto-login..."
GDM_CONF="/etc/gdm3/custom.conf"

# Backup original
if [ -f "$GDM_CONF" ]; then
    cp "$GDM_CONF" "$GDM_CONF.backup-$(date +%Y%m%d-%H%M%S)"
fi

# Remove any existing AutomaticLogin lines
sed -i '/^AutomaticLogin/d' "$GDM_CONF" 2>/dev/null || true

# Add auto-login configuration
if grep -q "^\[daemon\]" "$GDM_CONF"; then
    # [daemon] section exists, add under it
    sed -i "/^\[daemon\]/a WaylandEnable=false\nAutomaticLoginEnable=true\nAutomaticLogin=$KIOSK_USER" "$GDM_CONF"
else
    # No [daemon] section, add it
    cat >> "$GDM_CONF" << GDMEOF

[daemon]
WaylandEnable=false
AutomaticLoginEnable=true
AutomaticLogin=$KIOSK_USER
GDMEOF
fi

echo_info "✓ GDM3 auto-login configured"

# Configure AccountsService
echo_step "Configuring AccountsService..."
mkdir -p "/var/lib/AccountsService/users"
cat > "/var/lib/AccountsService/users/$KIOSK_USER" << ACCEOF
[User]
Session=icewm-session
XSession=icewm-session
Icon=/var/lib/AccountsService/icons/$KIOSK_USER
SystemAccount=false
ACCEOF
echo_info "✓ AccountsService configured"

# Set GDM3 as display manager
echo_step "Setting GDM3 as display manager..."
echo "/usr/sbin/gdm3" > /etc/X11/default-display-manager
systemctl enable gdm3 &>/dev/null || true
echo_info "✓ GDM3 enabled"

# Verification
echo ""
echo_step "Verifying configuration..."

if grep -q "^AutomaticLoginEnable.*=.*true" "$GDM_CONF" && \
   grep -q "^AutomaticLogin.*=.*$KIOSK_USER" "$GDM_CONF"; then
    echo_info "✓ GDM3 auto-login verified"
else
    echo_error "✗ GDM3 configuration verification failed!"
    exit 1
fi

if [ -f "/var/lib/AccountsService/users/$KIOSK_USER" ]; then
    echo_info "✓ AccountsService verified"
else
    echo_error "✗ AccountsService verification failed!"
    exit 1
fi

if [ -x "/home/$KIOSK_USER/.local/bin/hsparc-kiosk-start.sh" ]; then
    echo_info "✓ Launcher script verified"
else
    echo_error "✗ Launcher script verification failed!"
    exit 1
fi

if [ -x "/home/$KIOSK_USER/.icewm/startup" ]; then
    echo_info "✓ IceWM startup verified"
else
    echo_error "✗ IceWM startup verification failed!"
    exit 1
fi

# Success
echo ""
echo_info "=========================================="
echo_info "   CONFIGURATION COMPLETE!"
echo_info "=========================================="
echo ""
echo_info "Next steps:"
echo_info "  1. Reboot the system: sudo reboot"
echo_info "  2. System will auto-login as '$KIOSK_USER'"
echo_info "  3. HSPARC will launch automatically in kiosk mode"
echo ""
echo_info "Manual testing (before reboot):"
echo_info "  sudo su - $KIOSK_USER -c '/home/$KIOSK_USER/.local/bin/hsparc-kiosk-start.sh'"
echo ""
echo_info "Logs will be in: /tmp/hsparc-kiosk-*.log"
echo ""
echo_info "To disable kiosk mode:"
echo_info "  Edit /etc/gdm3/custom.conf and comment out:"
echo_info "    AutomaticLoginEnable=true"
echo_info "    AutomaticLogin=$KIOSK_USER"
echo ""
