#!/bin/bash
# HSPARC Update Script
# Usage: curl -fsSL https://raw.githubusercontent.com/drjhoover/hsparc-releases/main/update.sh | bash -s -- VERSION

set -e

VERSION="$1"

if [ -z "$VERSION" ]; then
    echo "Error: Version required"
    echo "Usage: curl -fsSL https://raw.githubusercontent.com/drjhoover/hsparc-releases/main/update.sh | bash -s -- VERSION"
    echo "Example: curl -fsSL https://raw.githubusercontent.com/drjhoover/hsparc-releases/main/update.sh | bash -s -- 1.0.7"
    exit 1
fi

echo "=========================================="
echo "HSPARC Update Script"
echo "Version: $VERSION"
echo "=========================================="
echo ""

# Check if HSPARC is installed
if [ ! -d "/opt/hsparc" ]; then
    echo "Error: HSPARC not found at /opt/hsparc"
    echo "Use install script for fresh installation"
    exit 1
fi

# Create temp directory
TEMP_DIR=$(mktemp -d)
cd "$TEMP_DIR"

echo "📥 Downloading HSPARC v$VERSION..."
TARBALL_URL="https://github.com/drjhoover/hsparc-releases/releases/download/v${VERSION}/hsparc-${VERSION}.tar.gz"

if ! curl -fsSL -o "hsparc-${VERSION}.tar.gz" "$TARBALL_URL"; then
    echo "❌ Error: Failed to download v$VERSION"
    echo "URL: $TARBALL_URL"
    rm -rf "$TEMP_DIR"
    exit 1
fi

echo "📦 Extracting archive..."
tar -xzf "hsparc-${VERSION}.tar.gz"

# Backup database before update
echo "💾 Backing up database..."
if [ -f "/opt/hsparc/hsparc.db" ]; then
    sudo cp /opt/hsparc/hsparc.db /opt/hsparc/hsparc.db.backup-$(date +%Y%m%d-%H%M%S)
    echo "✓ Database backed up"
fi

# Backup settings
if [ -f "/opt/hsparc/settings.json" ]; then
    sudo cp /opt/hsparc/settings.json /opt/hsparc/settings.json.backup-$(date +%Y%m%d-%H%M%S)
    echo "✓ Settings backed up"
fi

echo "🔄 Updating HSPARC..."

# Stop HSPARC if running (for systemd service)
if systemctl is-active --quiet hsparc 2>/dev/null; then
    echo "⏸️  Stopping HSPARC service..."
    sudo systemctl stop hsparc
fi

# Update code (preserve database and settings)
cd "hsparc-${VERSION}"
sudo cp -r hsparc /opt/hsparc/
sudo cp -r pyarmor_runtime_* /opt/hsparc/ 2>/dev/null || true
sudo cp main.py /opt/hsparc/
sudo cp requirements.txt /opt/hsparc/
sudo cp -r resources /opt/hsparc/ 2>/dev/null || true

# Update dependencies
echo "📚 Updating dependencies..."
cd /opt/hsparc
sudo ./venv/bin/pip install -r requirements.txt --break-system-packages

# Install python-docx if not present (required for v1.0.7+)
if ! ./venv/bin/pip show python-docx > /dev/null 2>&1; then
    echo "📦 Installing python-docx..."
    sudo ./venv/bin/pip install python-docx --break-system-packages
fi

# Restart service if it was running
if systemctl is-active --quiet hsparc 2>/dev/null; then
    echo "▶️  Starting HSPARC service..."
    sudo systemctl start hsparc
fi

# Cleanup
cd /
rm -rf "$TEMP_DIR"

echo ""
echo "=========================================="
echo "✅ Update Complete!"
echo "=========================================="
echo "HSPARC v$VERSION installed at /opt/hsparc"
echo ""
echo "Database migration will run automatically on first launch."
echo ""
echo "To start HSPARC:"
echo "  cd /opt/hsparc && ./venv/bin/python3 main.py"
echo ""
