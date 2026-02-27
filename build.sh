#!/usr/bin/env bash
# Build script for Render — builds both frontend and backend in one service.
set -e

echo "=== Installing system dependencies ==="
# Install LibreDWG build dependencies for DWG file support
if ! command -v dwg2dxf &> /dev/null; then
  echo "Building LibreDWG for DWG support..."
  apt-get update -qq && apt-get install -y -qq --no-install-recommends \
    build-essential git autoconf automake libtool texinfo 2>/dev/null || true
  if command -v git &> /dev/null; then
    git clone --depth 1 https://github.com/LibreDWG/libredwg.git /tmp/libredwg 2>/dev/null || true
    if [ -d /tmp/libredwg ]; then
      cd /tmp/libredwg
      autoreconf -fi 2>/dev/null
      ./configure --prefix=/usr/local --disable-bindings --disable-write 2>/dev/null
      make -j$(nproc) -C src 2>/dev/null
      make -j$(nproc) -C programs 2>/dev/null
      make install -C src 2>/dev/null
      make install -C programs 2>/dev/null
      ldconfig 2>/dev/null || true
      cd /
      rm -rf /tmp/libredwg
      echo "LibreDWG installed: $(dwg2dxf --version 2>&1 | head -1)"
    fi
  fi
else
  echo "dwg2dxf already available: $(dwg2dxf --version 2>&1 | head -1)"
fi

echo "=== Installing backend dependencies ==="
cd /opt/render/project/src/backend 2>/dev/null || cd "$(dirname "$0")/backend"
pip install -r requirements.txt

echo "=== Installing frontend dependencies ==="
cd ../frontend
npm ci

echo "=== Building React frontend ==="
npm run build

echo "=== Copying build to backend/static ==="
rm -rf ../backend/static
cp -r build ../backend/static

echo "=== Build complete ==="
