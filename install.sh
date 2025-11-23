#!/usr/bin/env bash
set -e

REPO_URL="https://github.com/The-IT-Guy/customrmm.git"
INSTALL_DIR="/opt/customrmm"

echo "========================================="
echo "      Custom RMM - Installer Script"
echo "========================================="

# Ensure we are root or have sudo
if [ "$EUID" -ne 0 ]; then
    SUDO="sudo"
else
    SUDO=""
fi

echo "[1/6] Updating apt packages..."
$SUDO apt-get update -y

echo "[2/6] Installing dependencies..."
$SUDO apt-get install -y git docker.io docker-compose-plugin

echo "[3/6] Starting Docker service..."
$SUDO systemctl enable docker || true
$SUDO systemctl start docker || true

echo "[4/6] Cloning or updating repository..."
if [ ! -d "$INSTALL_DIR/.git" ]; then
    $SUDO rm -rf "$INSTALL_DIR"
    $SUDO git clone "$REPO_URL" "$INSTALL_DIR"
else
    cd "$INSTALL_DIR"
    $SUDO git pull --ff-only || true
fi

cd "$INSTALL_DIR"

echo "[5/6] Building and launching Docker container..."
$SUDO docker compose down || true
$SUDO docker compose up -d --build

IP=$(hostname -I | awk '{print $1}')

echo ""
echo "========================================="
echo "     🎉 Custom RMM Installed Successfully"
echo "========================================="
echo " Dashboard URL:  http://$IP:8000"
echo " Login email:    admin@local"
echo " Login password: admin123"
echo "========================================="
