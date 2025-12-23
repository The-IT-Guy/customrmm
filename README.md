# CustomRMM (Alpha)

This repository is a working alpha build of a self-hosted RMM dashboard + agent check-in system.

## What works in this alpha
- One-time **Setup Admin** flow (creates first org + admin user)
- Session-based login/logout
- Optional TOTP per user (enable in Settings)
- Multi-tenant data model (Organization -> Users, Clients, Devices)
- Client CRUD (UI + server-side validation)
- Device enrollment tokens, agent registration, device keys
- Agent check-in with metrics (CPU, RAM, disk, uptime, IP, OS)
- Device status (Online/Offline by last seen)
- Alerts (basic threshold + offline) stored in DB and shown in UI
- Remote Tasking (create task, agent polls, returns output, UI shows results)

## Quick start (Docker)
1) Copy env file and set secrets:
```bash
cp .env.example .env
# edit .env (set SECRET_KEY at minimum)
```

2) Start:
```bash
docker compose up -d --build
```

3) Open:
- http://YOUR_SERVER:8000/setup-admin (only if no users exist yet)

## Linux host (no Docker)
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
mkdir -p data
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Agent
Alpha agent is a single Python file in `/agent/agent.py`.
- It can run as a service (systemd) or scheduled task.
- It enrolls once with an enrollment token and then checks in on an interval.

See `/agent/README.md` and `/scripts/` for installers.

## Notes
- This alpha uses `create_all()` on startup (no Alembic). For beta, switch to Alembic migrations.
- Notifications are stubbed (email/SMS config placeholders are included).
