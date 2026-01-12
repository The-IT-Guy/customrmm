#!/bin/bash
set -e

BASE_URL="https://raw.githubusercontent.com/The-IT-Guy/customrmm/main/customrmm-gold-alpha"
INSTALL_DIR="/opt/customrmm"

apt update
apt install -y python3 python3-venv python3-pip curl git openssl

mkdir -p $INSTALL_DIR
cd $INSTALL_DIR

mkdir -p server/templates server/static/linux server/static/windows

curl -fsSL $BASE_URL/server/main.py -o server/main.py
curl -fsSL $BASE_URL/server/requirements.txt -o server/requirements.txt

curl -fsSL $BASE_URL/server/templates/login.html -o server/templates/login.html
curl -fsSL $BASE_URL/server/templates/dashboard.html -o server/templates/dashboard.html

curl -fsSL $BASE_URL/server/static/linux/agent.py -o server/static/linux/agent.py
curl -fsSL $BASE_URL/server/static/linux/customrmm-agent.service -o server/static/linux/customrmm-agent.service
curl -fsSL $BASE_URL/server/static/windows/agent.ps1 -o server/static/windows/agent.ps1

curl -fsSL $BASE_URL/systemd/customrmm.service -o /etc/systemd/system/customrmm.service

python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r server/requirements.txt

if [ ! -f /etc/customrmm.env ]; then
  echo "RMM_SESSION_SECRET=$(openssl rand -hex 32)" > /etc/customrmm.env
  chmod 600 /etc/customrmm.env
fi

systemctl daemon-reload
systemctl enable --now customrmm

echo "✅ CustomRMM server installed"
echo "🌐 http://$(hostname -I | awk '{print $1}'):8000"
