#!/usr/bin/env bash
set -euo pipefail

# HSPARC Update Script
# Updates existing HSPARC installation to latest version

INSTALL_DIR="/opt/hsparc"
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
    exit 0
fi

echo_warn "Update available: $CURRENT_VERSION → $LATEST_VERSION"
echo ""
read -p "Continue with update? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo_info "Update cancelled"
    exit 0
fi

# Stop HSPARC service
echo_step "Stopping HSPARC service..."
systemctl stop hsparc || true

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
chown -R hsparc:hsparc "$INSTALL_DIR"

# Start HSPARC service
echo_step "Starting HSPARC service..."
systemctl start hsparc

# Cleanup
rm -rf /tmp/hsparc-update

# Keep only last 3 backups
echo_step "Cleaning old backups..."
ls -dt ${INSTALL_DIR}.backup-* 2>/dev/null | tail -n +4 | xargs rm -rf 2>/dev/null || true

echo ""
echo_info "=========================================="
echo_info "  Update Complete!"
echo_info "=========================================="
echo ""
echo_info "Updated: $CURRENT_VERSION → $LATEST_VERSION"
echo_info "Backup: $BACKUP_DIR"
echo ""
echo_info "Check status: sudo systemctl status hsparc"
echo ""

