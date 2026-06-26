#!/bin/bash
set -euo pipefail

# VOD Clipper — Server Deployment Script
# Run on a Debian/Ubuntu server as root. Assumes the project lives at
# /opt/vod-clipper (clone or copy it there first):
#   bash deploy.sh

APP_DIR="/opt/vod-clipper"
APP_USER="vod-clipper"

echo "=================================="
echo "  VOD Clipper — Server Setup"
echo "=================================="

# 1. Install system dependencies
echo "[1/7] Installing system dependencies..."
apt-get update -qq
apt-get install -y -qq python3 python3-pip python3-venv ffmpeg git > /dev/null

# 2. Create dedicated user (no login shell)
echo "[2/7] Creating service user..."
if ! id "$APP_USER" &>/dev/null; then
    useradd --system --create-home --shell /usr/sbin/nologin "$APP_USER"
    echo "  Created user: $APP_USER"
else
    echo "  User $APP_USER already exists"
fi

# 3. Check for .env
echo "[3/7] Checking for .env file..."
if [ ! -f "$APP_DIR/.env" ]; then
    echo ""
    echo "  !! WARNING: No .env file found."
    echo "  !! Make sure to create $APP_DIR/.env before starting the service."
    echo ""
fi

# 4. Set up Python venv
echo "[4/7] Setting up Python virtual environment..."
cd "$APP_DIR"
python3 -m venv venv
./venv/bin/pip install --quiet --upgrade pip
./venv/bin/pip install --quiet -r requirements.txt

# 5. Create output directory
echo "[5/7] Creating output directory..."
mkdir -p "$APP_DIR/output/logs"
mkdir -p "$APP_DIR/output/downloads"
mkdir -p "$APP_DIR/output/clips"

# 6. Set ownership
echo "[6/7] Setting file ownership..."
chown -R "$APP_USER:$APP_USER" "$APP_DIR"

# 7. Install and enable systemd service
echo "[7/7] Installing systemd service..."
cp "$APP_DIR/vod-clipper.service" /etc/systemd/system/vod-clipper.service
systemctl daemon-reload
systemctl enable vod-clipper

echo ""
echo "=================================="
echo "  Setup complete!"
echo "=================================="
echo ""
echo "  Project:  $APP_DIR"
echo "  Service:  vod-clipper"
echo ""
echo "  Next steps:"
echo "    1. Make sure $APP_DIR/.env has all your API keys"
echo "    2. Start the service:"
echo "       sudo systemctl start vod-clipper"
echo "    3. Check status:"
echo "       sudo systemctl status vod-clipper"
echo "    4. View logs:"
echo "       journalctl -u vod-clipper -f"
echo ""
