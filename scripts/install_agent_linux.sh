#!/usr/bin/env bash
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Run as root: sudo bash install_agent_linux.sh <SERVER_URL> <ENROLL_TOKEN>"
  exit 1
fi

SERVER_URL="${1:-}"
ENROLL_TOKEN="${2:-}"
if [[ -z "$SERVER_URL" || -z "$ENROLL_TOKEN" ]]; then
  echo "Usage: sudo bash install_agent_linux.sh <SERVER_URL> <ENROLL_TOKEN>"
  exit 1
fi

INSTALL_DIR="/opt/customrmm"
DATA_DIR="/var/lib/customrmm"
SERVICE_FILE="/etc/systemd/system/customrmm-agent.service"

mkdir -p "$INSTALL_DIR" "$DATA_DIR"
cp -f "$(dirname "$0")/../agent/agent.py" "$INSTALL_DIR/agent.py"

python3 -m pip install --upgrade pip >/dev/null 2>&1 || true
python3 -m pip install --upgrade psutil httpx >/dev/null 2>&1

cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=CustomRMM Agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 $INSTALL_DIR/agent.py --server $SERVER_URL --enroll-token $ENROLL_TOKEN --interval 30
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now customrmm-agent
echo "Installed and started customrmm-agent."
