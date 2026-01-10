#!/bin/bash
set -e

VERSION="${1:-1.2.7}"
SOURCE_DIR="/opt/hsparc"

echo "🔨 Building HSPARC v$VERSION (plain Python - no obfuscation)"

# Clean previous builds
rm -rf build dist
mkdir -p build dist/hsparc-$VERSION

# Copy source files directly (no obfuscation)
echo "📦 Copying source files..."
cp -r $SOURCE_DIR/hsparc dist/hsparc-$VERSION/
cp $SOURCE_DIR/main.py dist/hsparc-$VERSION/
cp $SOURCE_DIR/requirements_current.txt dist/hsparc-$VERSION/requirements.txt

# Copy resources
echo "📦 Adding resources directory..."
cp -r $SOURCE_DIR/resources dist/hsparc-$VERSION/

# Add version
echo "$VERSION" > dist/hsparc-$VERSION/.version

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
echo "⚠️  NO OBFUSCATION - source code visible"
echo "🚀 Ready to upload to GitHub!"
