# CustomRMM (No Docker) — v1

This is a minimal, functional RMM server you can install on **Ubuntu 22.04+** with **no control panel**.

## What’s included
- Web UI (FastAPI + Jinja templates)
- Left sidebar navigation (Dashboard / Alerts / Devices / Clients / Scripts / Settings / Logs)
- SQLite database
- Admin setup / login
- Clients CRUD
- Devices list + detail (heartbeats + alerts)
- Agent API endpoints:
  - `POST /api/v1/register` (requires `X-ENROLL-KEY`)
  - `POST /api/v1/heartbeat` (requires `Authorization: Bearer <device_token>`)
- Background offline monitor creates "Device offline" alerts

## One-line install
After you push these files to your GitHub repo (default assumes `The-IT-Guy/customrmm`):

```bash
curl -fsSL https://raw.githubusercontent.com/The-IT-Guy/customrmm/main/install.sh | sudo bash
```

With a domain + Let's Encrypt:

```bash
curl -fsSL https://raw.githubusercontent.com/The-IT-Guy/customrmm/main/install.sh | sudo bash -s -- \
  --domain rmm.example.com --email you@example.com
```

## Service control
```bash
sudo systemctl status customrmm --no-pager
sudo journalctl -u customrmm -n 200 --no-pager
sudo systemctl restart customrmm
```

## Agent quick test (no agent needed)
1) Open **Settings** and copy ENROLL_KEY.
2) Register a device:
```bash
curl -sS -X POST http://YOUR_SERVER_IP/api/v1/register \
  -H "Content-Type: application/json" \
  -H "X-ENROLL-KEY: YOUR_ENROLL_KEY" \
  -d '{"device_uuid":"demo-001","hostname":"demo-host","os":"Linux","ip":"1.2.3.4","agent_version":"1.0.0"}'
```
The response includes `api_token`.

3) Send a heartbeat:
```bash
curl -sS -X POST http://YOUR_SERVER_IP/api/v1/heartbeat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_DEVICE_API_TOKEN" \
  -d '{"cpu":10,"mem":20,"disk":30,"uptime_seconds":1234,"note":"hello"}'
```

Refresh **Devices**.
