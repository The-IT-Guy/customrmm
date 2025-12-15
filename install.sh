#!/usr/bin/env bash
set -euo pipefail

# CustomRMM No-Docker One-Line Installer (Ubuntu 22.04+)
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/The-IT-Guy/customrmm/main/install.sh | sudo bash -s -- --domain rmm.example.com --email you@example.com
#
# Options:
#   --domain <fqdn>         Optional. If set, nginx will use this as server_name. Certbot will be attempted.
#   --email <email>         Required only if --domain is used (for Let's Encrypt).
#   --repo <git_url>        Repo URL to clone (default: https://github.com/The-IT-Guy/customrmm.git)
#   --branch <name>         Branch to clone (default: main)
#   --admin-email <email>   Optional. If not provided, prompted.
#   --admin-pass <pass>     Optional. If not provided, generated and printed.
#   --port <port>           App port behind nginx (default: 8000)
#   --offline-minutes <n>   Minutes to consider a device offline (default: 5)
#   --non-interactive       Do not prompt (requires admin-email; admin-pass optional)
#
# Notes:
# - This installer sets up:
#   - /opt/customrmm (app + venv)
#   - /etc/customrmm/customrmm.env (config)
#   - /var/lib/customrmm/customrmm.db (SQLite DB)
#   - systemd service "customrmm"
#   - nginx reverse proxy (HTTP; HTTPS attempted if domain is provided)
#
# Uninstall:
#   systemctl disable --now customrmm
#   rm -f /etc/systemd/system/customrmm.service
#   rm -rf /opt/customrmm /etc/customrmm /var/lib/customrmm
#   rm -f /etc/nginx/sites-enabled/customrmm /etc/nginx/sites-available/customrmm
#   systemctl daemon-reload
#   nginx -t && systemctl reload nginx

APP_USER="customrmm"
APP_DIR="/opt/customrmm"
ENV_DIR="/etc/customrmm"
ENV_FILE="${ENV_DIR}/customrmm.env"
DATA_DIR="/var/lib/customrmm"
LOG_DIR="/var/log/customrmm"
NGINX_SITE_AVAIL="/etc/nginx/sites-available/customrmm"
NGINX_SITE_ENABLED="/etc/nginx/sites-enabled/customrmm"
SYSTEMD_SERVICE="/etc/systemd/system/customrmm.service"

REPO_URL_DEFAULT="https://github.com/The-IT-Guy/customrmm.git"
BRANCH_DEFAULT="main"

DOMAIN=""
LE_EMAIL=""
REPO_URL="$REPO_URL_DEFAULT"
BRANCH="$BRANCH_DEFAULT"
ADMIN_EMAIL=""
ADMIN_PASS=""
APP_PORT="8000"
OFFLINE_MINUTES="5"
NON_INTERACTIVE="0"

log() { echo -e "[customrmm] $*"; }
die() { echo -e "[customrmm] ERROR: $*" >&2; exit 1; }

need_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    die "Run as root (use sudo)."
  fi
}

detect_ubuntu() {
  if [[ ! -f /etc/os-release ]]; then
    die "Cannot detect OS."
  fi
  . /etc/os-release
  if [[ "${ID}" != "ubuntu" ]]; then
    die "This installer is for Ubuntu. Detected: ${ID}"
  fi
  ver="${VERSION_ID%%.*}"
  if [[ "${ver}" -lt 22 ]]; then
    die "Ubuntu 22.04+ required. Detected: ${VERSION_ID}"
  fi
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --domain) DOMAIN="${2:-}"; shift 2 ;;
      --email) LE_EMAIL="${2:-}"; shift 2 ;;
      --repo) REPO_URL="${2:-}"; shift 2 ;;
      --branch) BRANCH="${2:-}"; shift 2 ;;
      --admin-email) ADMIN_EMAIL="${2:-}"; shift 2 ;;
      --admin-pass) ADMIN_PASS="${2:-}"; shift 2 ;;
      --port) APP_PORT="${2:-}"; shift 2 ;;
      --offline-minutes) OFFLINE_MINUTES="${2:-}"; shift 2 ;;
      --non-interactive) NON_INTERACTIVE="1"; shift 1 ;;
      -h|--help)
        sed -n '1,120p' "$0"; exit 0 ;;
      *)
        die "Unknown option: $1"
        ;;
    esac
  done
}

prompt_if_needed() {
  if [[ "${NON_INTERACTIVE}" == "1" ]]; then
    [[ -n "${ADMIN_EMAIL}" ]] || die "--admin-email is required with --non-interactive"
    return
  fi

  if [[ -z "${DOMAIN}" ]]; then
    read -r -p "Domain (optional; press Enter to skip and use IP): " DOMAIN || true
  fi
  if [[ -n "${DOMAIN}" && -z "${LE_EMAIL}" ]]; then
    read -r -p "Email for Let's Encrypt (required if using a domain): " LE_EMAIL || true
  fi
  if [[ -z "${ADMIN_EMAIL}" ]]; then
    read -r -p "Admin email: " ADMIN_EMAIL || true
  fi
}

rand_pass() {
  # 20 chars; avoids problematic shell chars
  tr -dc 'A-Za-z0-9!@#%^_+=-' </dev/urandom | head -c 20
}

apt_install() {
  export DEBIAN_FRONTEND=noninteractive
  log "Updating apt..."
  apt-get update -y
  log "Installing dependencies..."
  apt-get install -y --no-install-recommends \
    ca-certificates curl git nginx \
    python3 python3-venv python3-pip \
    certbot python3-certbot-nginx \
    ufw
}

create_user_and_dirs() {
  log "Creating user and directories..."
  if ! id "${APP_USER}" >/dev/null 2>&1; then
    useradd --system --home "${APP_DIR}" --shell /usr/sbin/nologin "${APP_USER}"
  fi
  mkdir -p "${APP_DIR}" "${ENV_DIR}" "${DATA_DIR}" "${LOG_DIR}"
  chown -R "${APP_USER}:${APP_USER}" "${APP_DIR}" "${DATA_DIR}" "${LOG_DIR}"
  chmod 750 "${ENV_DIR}"
}

clone_or_update_repo() {
  log "Fetching app code..."
  if [[ -d "${APP_DIR}/.git" ]]; then
    log "Repo exists. Pulling updates..."
    cd "${APP_DIR}"
    sudo -u "${APP_USER}" git fetch --all --prune
    sudo -u "${APP_USER}" git checkout "${BRANCH}"
    sudo -u "${APP_USER}" git pull --ff-only origin "${BRANCH}"
  else
    rm -rf "${APP_DIR:?}/"* || true
    sudo -u "${APP_USER}" git clone --branch "${BRANCH}" --depth 1 "${REPO_URL}" "${APP_DIR}"
  fi

  # Ensure expected files exist
  [[ -f "${APP_DIR}/main.py" ]] || die "main.py not found in ${APP_DIR}. Did you push the code to the repo?"
  [[ -f "${APP_DIR}/requirements.txt" ]] || die "requirements.txt not found in ${APP_DIR}."
}

setup_venv() {
  log "Setting up Python venv..."
  if [[ ! -d "${APP_DIR}/venv" ]]; then
    sudo -u "${APP_USER}" python3 -m venv "${APP_DIR}/venv"
  fi
  sudo -u "${APP_USER}" "${APP_DIR}/venv/bin/pip" install --upgrade pip wheel setuptools
  sudo -u "${APP_USER}" "${APP_DIR}/venv/bin/pip" install -r "${APP_DIR}/requirements.txt"
}

write_env() {
  log "Writing environment file..."
  local session_secret enroll_key
  session_secret="$(python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(48))
PY
)"
  enroll_key="$(python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(24))
PY
)"

  # If admin pass not provided, generate
  if [[ -z "${ADMIN_PASS}" ]]; then
    ADMIN_PASS="$(rand_pass)"
  fi

  cat > "${ENV_FILE}" <<EOF
# CustomRMM runtime config
APP_NAME=CustomRMM
BASE_URL=${DOMAIN:+https://${DOMAIN}}
DATA_DIR=${DATA_DIR}
DB_PATH=${DATA_DIR}/customrmm.db
DATABASE_URL=sqlite:///${DATA_DIR}/customrmm.db

APP_PORT=${APP_PORT}

SESSION_SECRET=${session_secret}
SESSION_HTTPS_ONLY=false

ENROLL_KEY=${enroll_key}

OFFLINE_MINUTES=${OFFLINE_MINUTES}
OFFLINE_CHECK_EVERY_SECONDS=60
EOF

  chmod 640 "${ENV_FILE}"
}

init_db_and_admin() {
  log "Initializing database and creating admin user..."
  # Ensure app files are readable to service user
  chown -R "${APP_USER}:${APP_USER}" "${APP_DIR}" "${DATA_DIR}" "${LOG_DIR}"

  # Run DB init and create admin
  sudo -u "${APP_USER}" -H "${APP_DIR}/venv/bin/python" "${APP_DIR}/manage.py" initdb
  sudo -u "${APP_USER}" -H "${APP_DIR}/venv/bin/python" "${APP_DIR}/manage.py" create-admin --email "${ADMIN_EMAIL}" --password "${ADMIN_PASS}" || true
}

write_systemd_service() {
  log "Installing systemd service..."
  cat > "${SYSTEMD_SERVICE}" <<EOF
[Unit]
Description=CustomRMM (No-Docker)
After=network.target

[Service]
Type=simple
User=${APP_USER}
Group=${APP_USER}
WorkingDirectory=${APP_DIR}
EnvironmentFile=${ENV_FILE}
ExecStart=${APP_DIR}/venv/bin/uvicorn main:app --host 127.0.0.1 --port ${APP_PORT}
Restart=always
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=true
ReadWritePaths=${DATA_DIR} ${LOG_DIR}
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
EOF

  systemctl daemon-reload
  systemctl enable --now customrmm
}

write_nginx_site() {
  log "Configuring nginx reverse proxy..."
  local server_name
  if [[ -n "${DOMAIN}" ]]; then
    server_name="${DOMAIN}"
  else
    server_name="_"
  fi

  cat > "${NGINX_SITE_AVAIL}" <<EOF
server {
  listen 80;
  listen [::]:80;
  server_name ${server_name};

  client_max_body_size 10m;

  location /static/ {
    alias ${APP_DIR}/static/;
    access_log off;
    expires 7d;
  }

  location / {
    proxy_pass http://127.0.0.1:${APP_PORT};
    proxy_http_version 1.1;
    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;
    proxy_set_header Connection "";
    proxy_buffering off;
  }
}
EOF

  ln -sf "${NGINX_SITE_AVAIL}" "${NGINX_SITE_ENABLED}"

  # disable default site if present
  if [[ -e /etc/nginx/sites-enabled/default ]]; then
    rm -f /etc/nginx/sites-enabled/default
  fi

  nginx -t
  systemctl enable --now nginx
  systemctl reload nginx
}

try_certbot() {
  if [[ -z "${DOMAIN}" ]]; then
    log "No domain provided; skipping Let's Encrypt."
    return
  fi
  if [[ -z "${LE_EMAIL}" ]]; then
    log "No email provided; skipping Let's Encrypt."
    return
  fi

  log "Attempting Let's Encrypt (certbot)..."
  set +e
  certbot --nginx -d "${DOMAIN}" -m "${LE_EMAIL}" --agree-tos --non-interactive --redirect
  local rc=$?
  set -e

  if [[ $rc -ne 0 ]]; then
    log "Certbot failed (exit code: ${rc}). Leaving HTTP enabled. You can re-run later:"
    log "  sudo certbot --nginx -d ${DOMAIN} -m ${LE_EMAIL} --agree-tos --redirect"
    return
  fi

  # Now that HTTPS is active, set secure cookies.
  log "HTTPS enabled. Updating SESSION_HTTPS_ONLY=true"
  sed -i 's/^SESSION_HTTPS_ONLY=.*/SESSION_HTTPS_ONLY=true/' "${ENV_FILE}"
  systemctl restart customrmm
}

setup_firewall() {
  log "Configuring UFW..."
  ufw allow OpenSSH >/dev/null 2>&1 || true
  ufw allow 'Nginx Full' >/dev/null 2>&1 || true
  ufw --force enable >/dev/null 2>&1 || true
}

print_finish() {
  log "Install complete."
  if [[ -n "${DOMAIN}" ]]; then
    echo
    echo "URL: https://${DOMAIN}/"
  else
    echo
    echo "URL: http://<SERVER_IP>/"
  fi
  echo "Admin email: ${ADMIN_EMAIL}"
  echo "Admin password: ${ADMIN_PASS}"
  echo
  echo "Agent enrollment key (ENROLL_KEY): $(grep '^ENROLL_KEY=' "${ENV_FILE}" | cut -d= -f2-)"
  echo
  echo "Service:"
  echo "  systemctl status customrmm --no-pager"
  echo
  echo "Logs:"
  echo "  journalctl -u customrmm -n 200 --no-pager"
  echo
}

main() {
  need_root
  detect_ubuntu
  parse_args "$@"
  prompt_if_needed

  if [[ -n "${DOMAIN}" && -z "${LE_EMAIL}" ]]; then
    die "--email is required when --domain is provided"
  fi
  if [[ -z "${ADMIN_EMAIL}" ]]; then
    die "Admin email is required."
  fi

  apt_install
  create_user_and_dirs
  clone_or_update_repo
  setup_venv
  write_env
  init_db_and_admin
  write_systemd_service
  write_nginx_site
  setup_firewall
  try_certbot
  print_finish
}

main "$@"
