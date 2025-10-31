#!/bin/bash
set -e
VERSION="${1:-1.0.5}"
SOURCE_DIR="/opt/hsparc"

echo "🔨 Building HSPARC v$VERSION with PyArmor Pro"

# Clean previous builds
rm -rf build dist
mkdir -p build dist

# Copy source files
echo "📦 Copying source files..."
cp -r $SOURCE_DIR/hsparc build/
cp $SOURCE_DIR/main.py build/
cp $SOURCE_DIR/requirements_current.txt build/requirements.txt

# Obfuscate with PyArmor (less aggressive for compatibility)
echo "🔐 Obfuscating with PyArmor Pro..."
cd build
pyarmor gen --enable-bcc --recursive --output ../dist/hsparc-$VERSION .
cd ..

# Copy non-Python resources AFTER obfuscation
echo "📦 Adding resources directory..."
cp -r $SOURCE_DIR/resources dist/hsparc-$VERSION/

# Add version and requirements
echo "$VERSION" > dist/hsparc-$VERSION/.version
cp build/requirements.txt dist/hsparc-$VERSION/

# Create tarball
echo "📦 Creating release package..."
cd dist
tar -czf hsparc-$VERSION.tar.gz hsparc-$VERSION/
cd ..

echo ""
echo "✅ Build complete!"
echo "📦 Release: dist/hsparc-$VERSION.tar.gz"
echo "📊 Size: $(du -h dist/hsparc-$VERSION.tar.gz | cut -f1)"
echo ""
echo "🔒 Protection: PyArmor Pro (BCC mode)"
echo "🚀 Ready to upload to GitHub!"
