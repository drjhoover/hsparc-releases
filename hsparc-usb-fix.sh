#!/usr/bin/env bash
set -euo pipefail
# HSPARC USB Mount Fix
# Adds USB auto-mount support for existing installations

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
echo_info "  HSPARC USB Mount Configuration"
echo_info "=========================================="
echo ""

# Check if hsparc user exists
if ! id "$KIOSK_USER" &>/dev/null; then
    echo_error "User '$KIOSK_USER' not found. Is HSPARC installed?"
    exit 1
fi

# Configure USB auto-mount for hsparc user
echo_step "Configuring USB auto-mount..."
mkdir -p /media/hsparc
chown "$KIOSK_USER:$KIOSK_USER" /media/hsparc

# Get hsparc user's UID/GID
HSPARC_UID=$(id -u "$KIOSK_USER")
HSPARC_GID=$(id -g "$KIOSK_USER")

echo_info "  hsparc UID: $HSPARC_UID, GID: $HSPARC_GID"

# Create mount script
echo_step "Creating mount script..."
cat > /usr/local/bin/hsparc-usb-mount.sh << EOFMOUNT
#!/bin/bash
DEVICE="\$1"
LABEL="\${2:-USB}"
MOUNT_BASE="/media/hsparc"

# Sanitize label (remove special chars)
LABEL=\$(echo "\$LABEL" | tr -cd '[:alnum:]._-' | head -c 32)
[ -z "\$LABEL" ] && LABEL="USB"

# Create mount point
MOUNT_POINT="\${MOUNT_BASE}/\${LABEL}"
mkdir -p "\$MOUNT_POINT"

# Get filesystem type
FSTYPE=\$(blkid -o value -s TYPE "\$DEVICE" 2>/dev/null)

# Mount based on filesystem type
case "\$FSTYPE" in
    vfat|exfat)
        mount -t "\$FSTYPE" -o uid=${HSPARC_UID},gid=${HSPARC_GID},umask=0002 "\$DEVICE" "\$MOUNT_POINT"
        ;;
    ntfs)
        mount -t ntfs-3g -o uid=${HSPARC_UID},gid=${HSPARC_GID},umask=0002 "\$DEVICE" "\$MOUNT_POINT"
        ;;
    *)
        mount "\$DEVICE" "\$MOUNT_POINT"
        chown ${HSPARC_UID}:${HSPARC_GID} "\$MOUNT_POINT" 2>/dev/null || true
        ;;
esac

logger "HSPARC: Mounted \$DEVICE (\$FSTYPE) at \$MOUNT_POINT"
EOFMOUNT
chmod +x /usr/local/bin/hsparc-usb-mount.sh

# Create unmount script
echo_step "Creating unmount script..."
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

# Create udev rule for USB auto-mount
echo_step "Creating udev rules..."
cat > /etc/udev/rules.d/99-hsparc-usb.rules << 'EOFUDEV'
# HSPARC USB Auto-mount Rule
# Automatically mount USB drives for hsparc user

# Mount USB storage devices when inserted
ACTION=="add", SUBSYSTEM=="block", ENV{ID_FS_USAGE}=="filesystem", ENV{ID_BUS}=="usb", RUN+="/usr/local/bin/hsparc-usb-mount.sh %E{DEVNAME} %E{ID_FS_LABEL}"

# Unmount when removed
ACTION=="remove", SUBSYSTEM=="block", ENV{ID_BUS}=="usb", RUN+="/usr/local/bin/hsparc-usb-unmount.sh %E{DEVNAME}"
EOFUDEV

# Reload udev rules
echo_step "Reloading udev rules..."
udevadm control --reload-rules
udevadm trigger

echo ""
echo_info "=========================================="
echo_info "  USB Mount Configuration Complete!"
echo_info "=========================================="
echo ""
echo_info "USB drives will now auto-mount to /media/hsparc/"
echo_info ""
echo_info "To test:"
echo_info "  1. Insert a USB drive"
echo_info "  2. Check: ls /media/hsparc/"
echo_info "  3. Remove and reinsert if already plugged in"
echo ""
