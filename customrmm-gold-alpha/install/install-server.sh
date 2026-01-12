#!/bin/bash
set -e

INSTALL_DIR="/opt/customrmm"

apt update
apt install -y python3 python3-venv python3-pip curl unzip

mkdir -p $INSTALL_DIR
cd $INSTALL_DIR

unzip customrmm-gold-alpha.zip

python3 -m venv venv
source venv/bin/activate
pip install -r server/requirements.txt

echo "RMM_SESSION_SECRET=$(openssl rand -hex 32)" > /etc/customrmm.env

cp systemd/customrmm.service /etc/systemd/system/customrmm.service
systemctl daemon-reload
systemctl enable --now customrmm

echo "RMM Server Installed"
