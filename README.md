# Alpha MSP RMM

> **Status: Early Alpha** — Core scaffolding is in place. Agent modules and several server features are still under active development. Not production-ready.

A lightweight, self-hosted Remote Monitoring and Management (RMM) platform built for Managed Service Providers (MSPs). The server exposes a web dashboard and a REST API; agents run as system services on managed endpoints and report back via heartbeat and inventory collection.

---

## Table of Contents

- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Features](#features)
- [Project Structure](#project-structure)
- [Prerequisites](#prerequisites)
- [Server Setup](#server-setup)
- [Agent Deployment](#agent-deployment)
  - [Linux](#linux-agent)
  - [Windows](#windows-agent)
- [First Login](#first-login)
- [Configuration](#configuration)
- [Security Notes](#security-notes)
- [Roadmap](#roadmap)
- [Contributing](#contributing)

---

## Architecture

```
┌─────────────────────────────────────┐
│            RMM Server               │
│   FastAPI + SQLite + Jinja2 UI      │
│                                     │
│  /login  →  Web Dashboard           │
│  /dashboard → Device & Alert View  │
│  (REST API for agent check-ins)     │
└──────────────┬──────────────────────┘
               │  HTTPS + Agent Token
   ┌───────────┼───────────┐
   ▼           ▼           ▼
Linux Agent  Win Agent  (more platforms)
(systemd)   (service)
heartbeat + inventory → server
```

The server seeds a default admin user and a static agent token on first boot. Agents authenticate using the token, then periodically send heartbeats. Devices that have not checked in for more than 5 minutes are flagged as offline and surfaced as alerts on the dashboard.

---

## Tech Stack

| Layer      | Technology                                      |
|------------|-------------------------------------------------|
| Server     | Python 3, FastAPI, Uvicorn                      |
| Database   | SQLite (via SQLAlchemy ORM)                     |
| Auth       | JWT (python-jose), bcrypt (passlib)             |
| Templates  | Jinja2 HTML + static CSS                        |
| Agent      | Python 3 (cross-platform)                       |
| Linux svc  | systemd                                         |
| Windows svc| Python Windows service (pywin32)                |

---

## Features

**Currently implemented**
- Web-based login with JWT session cookies (8-hour expiry)
- Device registry — tracks hostname, OS, IP, and last-seen timestamp
- Online/offline status with 5-minute heartbeat threshold
- Dashboard alerts for devices that have gone silent
- Agent token authentication for endpoint check-ins
- Auto-seeded admin account and agent token on first run
- Disabled-device filtering (hidden from dashboard)

**In progress / planned**
- [ ] Agent heartbeat and inventory HTTP endpoints on the server
- [ ] Functional agent core (`agent/common/agent.py`)
- [ ] Linux agent installer (`agent/linux/install.sh`)
- [ ] Windows agent installer and service wrapper
- [ ] Multi-tenant / multi-client support
- [ ] Script execution / remote command dispatch
- [ ] Alerting integrations (email, webhook)
- [ ] Agent token management UI
- [ ] HTTPS / TLS termination guidance

---

## Project Structure

```
customrmm/
├── agent/
│   ├── common/
│   │   ├── agent.py          # Agent core (placeholder)
│   │   ├── heartbeat.py      # Heartbeat sender (placeholder)
│   │   └── inventory.py      # Inventory collector (placeholder)
│   ├── linux/
│   │   ├── install.sh        # Linux install script
│   │   └── rmm-agent.service # systemd unit file
│   └── windows/
│       ├── install.py        # Windows installer
│       └── service.py        # Windows service wrapper
└── server/
    ├── app/
    │   ├── auth.py           # JWT + bcrypt helpers
    │   ├── database.py       # SQLAlchemy engine + session
    │   ├── main.py           # FastAPI app, routes, startup seed
    │   └── models.py         # ORM models: User, AgentToken, Device
    ├── static/
    │   └── dashboard.css
    ├── templates/
    │   ├── dashboard.html
    │   └── login.html
    └── requirements.txt
```

---

## Prerequisites

- Python 3.9 or later
- `pip` (or a virtual environment tool like `venv` / `pipenv`)
- Linux agents: systemd-based distro
- Windows agents: Python 3 + pywin32

---

## Server Setup

```bash
# 1. Clone the repo
git clone https://github.com/The-IT-Guy/customrmm.git
cd customrmm/server

# 2. Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Start the server
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

The server will create `rmm.db` (SQLite) in the current directory on first run and seed the default admin account and agent token automatically.

Open `http://<server-ip>:8000` in a browser to reach the login page.

---

## Agent Deployment

### Linux Agent

```bash
# Copy the agent files to the target machine
scp -r agent/ user@target:/opt/customrmm/

# On the target machine
cd /opt/customrmm/agent/linux
sudo bash install.sh

# Enable and start the systemd service
sudo systemctl enable rmm-agent
sudo systemctl start rmm-agent
sudo systemctl status rmm-agent
```

Before deploying, edit the agent configuration to point to your server's address and set the correct agent token (see [Configuration](#configuration)).

### Windows Agent

```powershell
# Run from an elevated PowerShell prompt
python agent\windows\install.py
```

The Windows installer registers the agent as a Windows service. Ensure Python 3 and `pywin32` are installed on the target before running.

> **Note:** Windows agent functionality is a work in progress. Full service wrapping is not yet complete.

---

## First Login

Default credentials seeded on first boot:

| Field    | Value       |
|----------|-------------|
| Username | `admin`     |
| Password | `admin123`  |

**Change the password immediately after your first login.**

The default agent token is `ALPHA-AGENT-TOKEN`. Replace it with a strong random value in both the database and your agent configurations before deploying to any real environment.

---

## Configuration

All server configuration lives directly in the source for now. Key values to change before any real deployment:

### `server/app/auth.py`

```python
SECRET_KEY = "CHANGE_ME"   # Replace with a long, random secret
```

Generate a strong key:
```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

### `server/app/database.py`

```python
DATABASE_URL = "sqlite:///./rmm.db"
```

SQLite is fine for evaluation and small deployments. For production, replace this with a PostgreSQL or MySQL connection string (and install the appropriate SQLAlchemy driver).

### Agent token

The default token (`ALPHA-AGENT-TOKEN`) is seeded in `main.py` on startup. Update the `AgentToken` row in the database and set the same value in each deployed agent's configuration.

---

## Security Notes

> This project is in early alpha. The following issues **must** be addressed before exposing it to any network outside a private lab.

- **Change `SECRET_KEY`** in `auth.py` — the default is a placeholder.
- **Change the default admin password** — `admin123` is seeded for convenience only.
- **Replace the default agent token** — `ALPHA-AGENT-TOKEN` is public knowledge.
- **Run behind HTTPS** — wrap Uvicorn with an Nginx reverse proxy and a TLS certificate (Let's Encrypt or internal CA). Never expose the API over plain HTTP in production.
- **Restrict network access** — the dashboard and agent API should not be publicly reachable without authentication and ideally firewall-level controls.
- The JWT cookie is currently set without `HttpOnly` or `Secure` flags — this will be addressed in a future release.

---

## Roadmap

| Milestone | Description |
|-----------|-------------|
| v0.1 | Server scaffold, login, dashboard, device model ✅ |
| v0.2 | Working agent heartbeat + inventory endpoints |
| v0.3 | Functional Linux agent (install + service) |
| v0.4 | Functional Windows agent (install + service) |
| v0.5 | Agent token management UI |
| v1.0 | Production hardening, HTTPS guide, multi-client support |

---

## Contributing

This project is in active early development. Contributions are welcome.

1. Fork the repo and create a feature branch.
2. Keep server changes inside `server/` and agent changes inside `agent/`.
3. Open a pull request with a clear description of what the change does and why.

Please open an issue before starting large feature work so we can coordinate.

---

*Alpha MSP RMM is an independent open-source project and is not affiliated with any commercial RMM vendor.*
