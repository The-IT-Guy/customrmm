#!/usr/bin/env bash
set -euo pipefail

#############################################
# CustomRMM Server Installer – Ubuntu 22.04
#############################################

DEFAULT_REPO_URL="https://github.com/The-IT-Guy/customrmm.git"
DEFAULT_REPO_DIR="/opt/customrmm"
DEFAULT_BRANCH="main"

echo "=== CustomRMM Server Installer ==="

if [[ "$EUID" -ne 0 ]]; then
  echo "This script must be run as root. Try: sudo bash install.sh"
  exit 1
fi

if ! grep -q "Ubuntu 22.04" /etc/os-release; then
  echo "WARNING: This script is intended for Ubuntu 22.04 LTS."
  read -rp "Continue anyway? [y/N]: " CONT
  [[ "${CONT,,}" == "y" ]] || exit 1
fi

echo
read -rp "Enter your RMM domain (e.g. rmm.example.com): " RMM_DOMAIN
[[ -n "${RMM_DOMAIN}" ]] || { echo "Domain cannot be empty"; exit 1; }

read -rp "Enter email for Let's Encrypt (for SSL): " LE_EMAIL
[[ -n "${LE_EMAIL}" ]] || { echo "Email cannot be empty"; exit 1; }

read -rp "Git repo URL [${DEFAULT_REPO_URL}]: " REPO_URL
REPO_URL="${REPO_URL:-$DEFAULT_REPO_URL}"

read -rp "Git branch [${DEFAULT_BRANCH}]: " REPO_BRANCH
REPO_BRANCH="${REPO_BRANCH:-$DEFAULT_BRANCH}"

read -rp "Install directory [${DEFAULT_REPO_DIR}]: " REPO_DIR
REPO_DIR="${REPO_DIR:-$DEFAULT_REPO_DIR}"

echo
echo "=== Summary ==="
echo "Domain:      ${RMM_DOMAIN}"
echo "LE Email:    ${LE_EMAIL}"
echo "Repo URL:    ${REPO_URL}"
echo "Branch:      ${REPO_BRANCH}"
echo "Install dir: ${REPO_DIR}"
echo
read -rp "Proceed with installation? [y/N]: " CONFIRM
[[ "${CONFIRM,,}" == "y" ]] || { echo "Cancelled."; exit 1; }

echo
echo ">>> Updating system and installing base packages..."
apt-get update -y
DEBIAN_FRONTEND=noninteractive apt-get upgrade -y

apt-get install -y \
  ca-certificates \
  curl \
  gnupg \
  lsb-release \
  git \
  ufw \
  nginx \
  python3-certbot-nginx

echo
echo ">>> Installing Docker & Docker Compose plugin..."
if ! command -v docker >/dev/null 2>&1; then
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.gpg
  chmod a+r /etc/apt/keyrings/docker.gpg

  echo \
    "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
    $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
    | tee /etc/apt/sources.list.d/docker.list >/dev/null

  apt-get update -y
  apt-get install -y \
    docker-ce \
    docker-ce-cli \
    containerd.io \
    docker-buildx-plugin \
    docker-compose-plugin

  systemctl enable --now docker
else
  echo "Docker already installed, skipping."
fi

if ! docker compose version >/dev/null 2>&1; then
  apt-get install -y docker-compose-plugin
fi

echo
echo ">>> Configuring UFW firewall..."
ufw allow OpenSSH || true
ufw allow 80/tcp || true
ufw allow 443/tcp || true
if ufw status | grep -q "Status: inactive"; then
  ufw --force enable
fi

echo
echo ">>> Cloning or updating repo at ${REPO_DIR}..."
if [[ -d "${REPO_DIR}/.git" ]]; then
  cd "${REPO_DIR}"
  git fetch --all
  git checkout "${REPO_BRANCH}"
  git pull origin "${REPO_BRANCH}"
else
  mkdir -p "${REPO_DIR}"
  git clone -b "${REPO_BRANCH}" "${REPO_URL}" "${REPO_DIR}"
  cd "${REPO_DIR}"
fi

APP_DIR="${REPO_DIR}"

echo
echo ">>> Creating .env (if missing)..."
ENV_FILE="${APP_DIR}/.env"
if [[ ! -f "${ENV_FILE}" ]]; then
  cat > "${ENV_FILE}" <<EOF
RMM_DOMAIN=${RMM_DOMAIN}
RMM_SERVER_URL=https://${RMM_DOMAIN}
RMM_DB_PATH=/app/data/customrmm.db
SECRET_KEY=$(openssl rand -hex 32)
DEBUG=false
EOF
else
  echo ".env already exists, leaving it as-is. Make sure it has:"
  echo "  RMM_SERVER_URL=https://${RMM_DOMAIN}"
  echo "  RMM_DB_PATH=/app/data/customrmm.db"
fi

echo
echo ">>> Building and starting Docker stack..."
cd "${APP_DIR}"
docker compose up -d

sleep 8
docker ps | grep -q "customrmm-app" && \
  echo "Docker app container is running." || \
  echo "WARNING: customrmm-app container not running. Check 'docker logs customrmm-app'."

echo
echo ">>> Configuring Nginx reverse proxy..."
NGINX_CONF="/etc/nginx/sites-available/customrmm.conf"
cat > "${NGINX_CONF}" <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name ${RMM_DOMAIN};

    client_max_body_size 20M;

    location / {
        proxy_pass http://127.0.0.1:8000/;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 300;
    }
}
EOF

ln -sf "${NGINX_CONF}" /etc/nginx/sites-enabled/customrmm.conf
rm -f /etc/nginx/sites-enabled/default || true

nginx -t
systemctl reload nginx

echo
echo ">>> Requesting Let's Encrypt certificate..."
certbot --nginx \
  -d "${RMM_DOMAIN}" \
  -m "${LE_EMAIL}" \
  --agree-tos \
  --non-interactive \
  --redirect || echo "Certbot failed – run it manually later if needed."

echo
echo ">>> Creating systemd service for CustomRMM..."
SERVICE_FILE="/etc/systemd/system/customrmm.service"
cat > "${SERVICE_FILE}" <<EOF
[Unit]
Description=CustomRMM Docker stack
Requires=docker.service
After=network.target docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=${APP_DIR}
ExecStart=/usr/bin/docker compose up -d
ExecStop=/usr/bin/docker compose down
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable customrmm.service
systemctl restart customrmm.service

echo
echo "=== Installation complete! ==="
echo "Dashboard: https://${RMM_DOMAIN}"
echo
echo "If something doesn't load, check:"
echo "  docker ps"
echo "  docker logs customrmm-app"
echo "  systemctl status customrmm.service"
echo "  nginx -t && journalctl -u nginx"
