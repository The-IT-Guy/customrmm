# CustomRMM

A self-hosted Remote Monitoring and Management platform. One admin, many agents, three operating systems. FastAPI + SQLite + a single-file Python agent.

## Features

- **Live device inventory** — hostname, OS, IPs, agent version, uptime
- **Live metrics** — CPU, RAM, disk, network, and load average every 30s
- **Threshold alerts** — warn/critical on CPU, memory, disk, plus offline detection
- **Remote shell** — run `bash`, `sh`, `powershell`, `cmd`, or `python` on any agent from the dashboard
- **Saved scripts** — script library; run any saved script on any agent with one click
- **Software inventory** — installed apps per agent
- **Patch inventory** — pending updates per agent
- **Event collection** — recent error/critical events from the OS log
- **Dual transport** — WebSocket for instant command delivery, HTTP polling as fallback; if the WS drops, the agent keeps working over HTTP

## Quick Start

```bash
git clone <this-repo> customrmm
cd customrmm
sudo PUBLIC_URL=https://rmm.example.com ./install/install-server.sh
```

Visit `${PUBLIC_URL}/setup-admin` to create the admin account.

## Agent Install

From the dashboard's `/install` page, copy the one-liner for the target OS:

| OS | One-liner |
|---|---|
| Linux | `curl -fsSL $URL/install/agent.sh \| sudo RMM_SERVER=$URL RMM_TOKEN=$TOKEN bash` |
| macOS | `curl -fsSL $URL/install/agent.sh \| sudo RMM_SERVER=$URL RMM_TOKEN=$TOKEN bash` |
| Windows | `powershell -c "$env:RMM_SERVER='$URL'; $env:RMM_TOKEN='$TOKEN'; iwr $URL/install/agent.ps1 -UseBasicParsing \| iex"` |

## Tech Stack

| Layer | Tech |
|---|---|
| Server | FastAPI + SQLite (async SQLAlchemy) |
| Auth | bcrypt sessions (users) + bearer tokens (agents) |
| Realtime | WebSocket + HTTP polling fallback |
| Agent | Single-file Python (`customrmm_agent.py`) |
| Installer | Bash (Linux/macOS) + PowerShell (Windows) |
| Container | Docker + docker-compose |

## Project Structure

```
customrmm/
├── app/
│   ├── main.py               # App + WebSocket endpoints + lifespan
│   ├── config.py             # Pydantic settings
│   ├── db.py                 # Async SQLAlchemy
│   ├── models.py             # ORM models
│   ├── schemas.py            # Agent ↔ server protocol
│   ├── auth.py               # Session + bearer auth deps
│   ├── security.py           # bcrypt + token helpers
│   ├── ws.py                 # WebSocket connection registry
│   ├── alerts.py             # Threshold alert engine
│   ├── installers.py         # Personalized install script renderer
│   ├── routes/               # Page + API routes
│   ├── templates/            # Jinja2 templates
│   └── static/               # CSS + JS
├── agent/
│   ├── customrmm_agent.py    # Cross-platform agent (single file)
│   ├── install-agent.sh      # Linux/macOS installer
│   ├── install-agent.ps1     # Windows installer
│   └── README.md
├── install/
│   ├── install-server.sh     # Linux + Docker server installer
│   ├── install-server.ps1    # Windows native server installer
│   └── README.md
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── .env.example
```

## Agent Authentication

1. Admin creates an **enrollment token** in `/install`
2. Agent installer runs with `RMM_TOKEN=<enrollment-token>`
3. On first start, agent calls `/api/agent/enroll` — server validates the token, creates an `Agent` row, and returns a per-agent **bearer token**
4. Agent saves the bearer token in `state.json` and uses it for all subsequent HTTP and WebSocket calls
5. Revoke access by deleting the enrollment token or the agent row

## v1 Scope

Deliberately out of scope for v1:

- Multi-tenancy, RBAC, 2FA
- Email / Slack / webhook alert delivery (dashboard-only in v1)
- Agent auto-update
- Agent groups / tags
- File transfer
- Interactive PTY, VNC, or RDP

## License

MIT
