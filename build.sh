#!/usr/bin/env bash
# Build script for Render — builds both frontend and backend in one service.
set -e

echo "=== Installing backend dependencies ==="
cd backend
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
