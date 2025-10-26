#!/usr/bin/env bash
# HSPARC Quick Install
# One-liner: curl -fsSL https://bitbucket.org/drjhoover/hsparc/raw/main/deploy/quick-install.sh | sudo bash

set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo_info() { echo -e "${GREEN}[INFO]${NC} $*"; }
echo_warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
echo_error() { echo -e "${RED}[ERROR]${NC} $*"; }

# Check root
if [[ $EUID -ne 0 ]]; then
   echo_error "This script must be run as root"
   echo_info "Run: curl -fsSL https://bitbucket.org/drjhoover/hsparc/raw/main/deploy/quick-install.sh | sudo bash"
   exit 1
fi

echo_info "=========================================="
echo_info "   HSPARC Quick Install"
echo_info "=========================================="
echo ""

# Check if git is installed
if ! command -v git &> /dev/null; then
    echo_info "Installing git..."
    apt-get update -qq
    apt-get install -y git &>/dev/null
fi

# Download setup script
TEMP_DIR=$(mktemp -d)
cd "$TEMP_DIR"

echo_info "Downloading HSPARC setup utility..."
GIT_REPO="https://bitbucket.org/drjhoover/hsparc.git"

if ! git clone --quiet --depth 1 "$GIT_REPO" hsparc; then
    echo_error "Failed to download HSPARC"
    echo_error "Check your internet connection"
    rm -rf "$TEMP_DIR"
    exit 1
fi

# Run setup
chmod +x hsparc/deploy/setup-hsparc.sh
cd hsparc/deploy

echo ""
echo_info "Launching setup utility..."
echo ""
sleep 2

./setup-hsparc.sh

# Cleanup
cd /
rm -rf "$TEMP_DIR"

echo ""
echo_info "Quick install script complete"
echo ""
