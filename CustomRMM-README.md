# CustomRMM v1.0.0

A self-hosted Remote Monitoring and Management platform. One admin, many
agents, three operating systems. FastAPI + SQLite + a single-file Python
agent.

## What it does

- **Live device inventory** — hostname, OS, IPs, agent version, uptime.
- **Live metrics** — CPU / RAM / disk / network / load average every 30 s.
- **Threshold alerts** — warn/critical on CPU, memory, disk, plus offline.
- **Remote shell** — run `bash`, `sh`, `powershell`, `cmd`, or `python` on
  any agent from the dashboard.
- **Saved scripts** — keep a script library, run any saved script on any
  agent with one click.
- **Software inventory** — installed apps on each agent.
- **Patch inventory** — pending updates per agent.
- **Event collection** — recent error/critical events from the OS log.
- **Dual transport** — WebSocket for instant command delivery, HTTP
  polling as a fallback. Both run in parallel; if the WS drops, the
  agent keeps working over HTTP.

## Quick start

```bash
git clone <this-repo> customrmm
cd customrmm
sudo PUBLIC_URL=https://rmm.example.com ./install/install-server.sh
# Visit ${PUBLIC_URL}/setup-admin to create the admin account.
```

Then on each machine you want to manage, follow the one-liner shown on
the dashboard's `/install` page. The shape of those is:

| OS       | One-liner                                                                                                    |
|----------|--------------------------------------------------------------------------------------------------------------|
| Linux    | `curl -fsSL $URL/install/agent.sh \| sudo RMM_SERVER=$URL RMM_TOKEN=$TOKEN bash`                              |
| macOS    | `curl -fsSL $URL/install/agent.sh \| sudo RMM_SERVER=$URL RMM_TOKEN=$TOKEN bash`                              |
| Windows  | `powershell -c "$env:RMM_SERVER='$URL'; $env:RMM_TOKEN='$TOKEN'; iwr $URL/install/agent.ps1 -UseBasicParsing \| iex"` |

`$URL` is your `PUBLIC_URL`, `$TOKEN` is an enrollment token from
`/install`. The dashboard renders the full one-liner with both filled in.

## Repository layout

```
customrmm/
├── app/                      FastAPI server
│   ├── main.py               app + WebSocket endpoints + lifespan
│   ├── config.py             pydantic-settings
│   ├── db.py                 async SQLAlchemy
│   ├── models.py             ORM models
│   ├── schemas.py            agent <-> server protocol
│   ├── auth.py               session (user) + bearer (agent) deps
│   ├── security.py           bcrypt + token helpers
│   ├── ws.py                 WebSocket connection registry
│   ├── alerts.py             threshold alert engine
│   ├── installers.py         renders personalized install scripts
│   ├── routes/               page + API routes
│   ├── templates/            Jinja2 templates
│   └── static/               css + js
├── agent/                    Cross-platform Python agent
│   ├── customrmm_agent.py    the agent (single file)
│   ├── install-agent.sh      Linux/macOS installer
│   ├── install-agent.ps1     Windows installer
│   └── README.md             what it collects, what it doesn't
├── install/                  Server installers + deployment notes
│   ├── install-server.sh     Linux + Docker
│   ├── install-server.ps1    Windows native
│   └── README.md             TLS, backups, manual deploy
├── scripts/
│   └── generate-secret.py
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── .env.example
```

## How agents authenticate

1. The admin creates one or more **enrollment tokens** in `/install`.
2. An agent runs the installer with `RMM_TOKEN=<enrollment-token>`.
3. On first start, the agent calls `/api/agent/enroll`. The server
   validates the enrollment token, creates an `Agent` row, and returns
   a fresh per-agent **bearer token**.
4. The agent saves that bearer token in `state.json` and uses it for all
   subsequent calls (HTTP `Authorization: Bearer ...`, WS `?token=...`).
5. If you want to revoke an agent, revoke its enrollment token (no new
   agents can enroll) or delete the agent row in the database.

## Out of scope for v1 (deliberate)

- Multi-tenancy, RBAC, 2FA — single admin, single tenant.
- Email / Slack / webhook alert delivery — alerts are dashboard-only.
- Agent auto-update.
- Agent groups / tags.
- File transfer between dashboard and agent.
- Interactive PTY, VNC, or RDP.

These are reasonable v2 candidates.

## License

MIT — see `LICENSE` (placeholder; add your own).
