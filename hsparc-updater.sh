#!/usr/bin/env bash
# HSPARC Update Checker
# Check for and install updates manually
# Usage: sudo ./hsparc-updater.sh [--check-only]

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

# Configuration
APP_DIR="/opt/hsparc"
VERSION_FILE="$APP_DIR/version.json"
BACKUP_DIR="/var/backups/hsparc"
GIT_REPO="https://bitbucket.org/drjhoover/hsparc.git"  # UPDATE THIS
GIT_BRANCH="main"

CHECK_ONLY=false

# Parse arguments
for arg in "$@"; do
    case $arg in
        --check-only)
            CHECK_ONLY=true
            shift
            ;;
        --help)
            echo "HSPARC Update Checker"
            echo ""
            echo "Usage: sudo ./hsparc-updater.sh [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --check-only   Only check for updates, don't install"
            echo "  --help         Show this help message"
            exit 0
            ;;
    esac
done

# Check root (unless check-only)
if [ "$CHECK_ONLY" = false ] && [[ $EUID -ne 0 ]]; then
   echo_error "Update installation requires root (use sudo)"
   echo_info "Use --check-only to check without installing"
   exit 1
fi

echo_info "=========================================="
echo_info "       HSPARC Update Checker"
echo_info "=========================================="
echo ""

# Check if installed
if [ ! -f "$VERSION_FILE" ]; then
    echo_error "HSPARC is not installed"
    exit 1
fi

# Get current version
CURRENT_VERSION=$(python3 -c "import json; print(json.load(open('$VERSION_FILE'))['version'])" 2>/dev/null || echo "unknown")
CURRENT_CODENAME=$(python3 -c "import json; print(json.load(open('$VERSION_FILE'))['codename'])" 2>/dev/null || echo "")

echo_info "Current version: ${CURRENT_VERSION} '${CURRENT_CODENAME}'"
echo ""

# Check for updates
echo_info "Checking for updates..."

# Clone repo to temp location
TEMP_DIR=$(mktemp -d)
trap "rm -rf $TEMP_DIR" EXIT

if ! git clone --quiet --depth 1 --branch "$GIT_BRANCH" "$GIT_REPO" "$TEMP_DIR" 2>/dev/null; then
    echo_error "Could not connect to repository"
    echo_error "Check your internet connection or repository URL"
    exit 1
fi

if [ ! -f "${TEMP_DIR}/version.json" ]; then
    echo_error "Repository does not contain version.json"
    exit 1
fi

# Get remote version
REMOTE_VERSION=$(python3 -c "import json; print(json.load(open('${TEMP_DIR}/version.json'))['version'])" 2>/dev/null || echo "unknown")
REMOTE_CODENAME=$(python3 -c "import json; print(json.load(open('${TEMP_DIR}/version.json'))['codename'])" 2>/dev/null || echo "")
RELEASE_DATE=$(python3 -c "import json; print(json.load(open('${TEMP_DIR}/version.json'))['release_date'])" 2>/dev/null || echo "unknown")

echo_info "Latest version: ${REMOTE_VERSION} '${REMOTE_CODENAME}' (${RELEASE_DATE})"
echo ""

# Compare versions
if [ "$CURRENT_VERSION" = "$REMOTE_VERSION" ]; then
    echo_info "âœ" You are running the latest version"
    exit 0
fi

# Parse version numbers for comparison
parse_version() {
    echo "$1" | sed 's/[^0-9.]//g'
}

CURRENT_PARSED=$(parse_version "$CURRENT_VERSION")
REMOTE_PARSED=$(parse_version "$REMOTE_VERSION")

# Simple version comparison
if [ "$(printf '%s\n' "$CURRENT_PARSED" "$REMOTE_PARSED" | sort -V | head -n1)" = "$REMOTE_PARSED" ]; then
    echo_warn "âš ï¸ You are running a NEWER version than the repository"
    echo_warn "This might be a development version"
    exit 0
fi

# Update available
echo_info "=========================================="
echo_info "âœ¨ UPDATE AVAILABLE"
echo_info "=========================================="
echo ""
echo_info "Current: ${CURRENT_VERSION} '${CURRENT_CODENAME}'"
echo_info "New:     ${REMOTE_VERSION} '${REMOTE_CODENAME}'"
echo ""

# Show changelog if available
CHANGELOG=$(python3 -c "
import json
data = json.load(open('${TEMP_DIR}/version.json'))
for entry in data.get('changelog', []):
    if entry.get('version') == '${REMOTE_VERSION}':
        print('Changelog:')
        for change in entry.get('changes', []):
            print('  - ' + change)
" 2>/dev/null || echo "")

if [ -n "$CHANGELOG" ]; then
    echo "$CHANGELOG"
    echo ""
fi

# Check-only mode
if [ "$CHECK_ONLY" = true ]; then
    echo_info "Run without --check-only to install the update"
    echo_info "Command: sudo ./hsparc-updater.sh"
    exit 0
fi

# Confirm update
echo -n "Install update? (y/n): "
read -r CONFIRM

if [[ ! "$CONFIRM" =~ ^[Yy]$ ]]; then
    echo_info "Update cancelled"
    exit 0
fi

echo ""
echo_info "=========================================="
echo_info "   INSTALLING UPDATE"
echo_info "=========================================="
echo ""

# Create backup
echo_info "Creating backup..."
BACKUP_NAME="pre-update-${CURRENT_VERSION}-to-${REMOTE_VERSION}-$(date +%Y%m%d-%H%M%S)"
BACKUP_PATH="${BACKUP_DIR}/${BACKUP_NAME}"

mkdir -p "$BACKUP_PATH"

# Backup current installation
if [ -d "$APP_DIR" ]; then
    cp -r "$APP_DIR" "${BACKUP_PATH}/app"
fi

# Backup user data
KIOSK_USER="hsparc"
DATA_DIR="/home/$KIOSK_USER/.local/share/hsparc"
if [ -d "$DATA_DIR" ]; then
    cp -r "$DATA_DIR" "${BACKUP_PATH}/data"
fi

# Create manifest
cat > "${BACKUP_PATH}/manifest.txt" << EOF
HSPARC Update Backup
Created: $(date -u +"%Y-%m-%d %H:%M:%S UTC")
From Version: ${CURRENT_VERSION}
To Version: ${REMOTE_VERSION}
EOF

echo_info "Backup created: ${BACKUP_PATH}"

# Check for pre-built binary
if [ ! -f "${TEMP_DIR}/dist/hsparc" ]; then
    echo_error "No pre-built binary found in repository"
    echo_error "Please build the application first using build.sh"
    echo_error "Or download a release package"
    exit 1
fi

# Stop HSPARC if running
echo_info "Stopping HSPARC..."
pkill -u "$KIOSK_USER" hsparc 2>/dev/null || true
sleep 2

# Install update
echo_info "Installing new version..."

# Remove old binary (keep other files)
rm -f "$APP_DIR/hsparc"
rm -f "$APP_DIR/main.py"

# Copy new binary
cp "${TEMP_DIR}/dist/hsparc" "$APP_DIR/"
chmod +x "$APP_DIR/hsparc"

# Update version file
cp "${TEMP_DIR}/version.json" "$APP_DIR/"

# Copy any updated resources
if [ -d "${TEMP_DIR}/dist/resources" ]; then
    cp -r "${TEMP_DIR}/dist/resources" "$APP_DIR/" 2>/dev/null || true
fi

# Create wrapper script
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
    echo_error "Update failed - binary not found after installation"
    echo_error "Restoring from backup..."
    
    # Restore backup
    if [ -d "${BACKUP_PATH}/app" ]; then
        rm -rf "$APP_DIR"
        cp -r "${BACKUP_PATH}/app" "$APP_DIR"
        echo_info "Backup restored successfully"
    fi
    
    exit 1
fi

# Success
echo ""
echo_info "=========================================="
echo_info "   UPDATE COMPLETE!"
echo_info "=========================================="
echo ""
echo_info "Updated from ${CURRENT_VERSION} to ${REMOTE_VERSION}"
echo ""

NEW_VERSION=$(python3 -c "import json; print(json.load(open('$VERSION_FILE'))['version'])" 2>/dev/null || echo "unknown")
echo_info "Verified: Version ${NEW_VERSION} installed successfully"
echo ""
echo_info "Backup location: ${BACKUP_PATH}"
echo ""
echo_info "HSPARC will restart automatically (kiosk mode)"
echo_info "Or restart manually: sudo su - hsparc -c '/home/hsparc/.local/bin/hsparc-kiosk-start.sh &'"
echo ""
