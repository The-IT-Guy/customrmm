from fastapi import FastAPI, Request, Form, Header, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
import sqlite3, uuid, time, os

API_KEY = "ALPHA_RMM_KEY_2026"

SESSION_SECRET = os.environ.get("RMM_SESSION_SECRET")
if not SESSION_SECRET:
    raise RuntimeError("RMM_SESSION_SECRET not set")

DB_PATH = "rmm.db"

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET)

templates = Jinja2Templates(directory="server/templates")
app.mount("/static", StaticFiles(directory="server/static"), name="static")

def db():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

@app.on_event("startup")
def init():
    c = db()
    cur = c.cursor()
    cur.execute("PRAGMA journal_mode=WAL;")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS agents (
            id TEXT PRIMARY KEY,
            machine_id TEXT UNIQUE,
            hostname TEXT,
            os TEXT,
            ip TEXT,
            last_seen INTEGER
        )
    """)
    c.commit()

def verify_agent(key: str = Header(None, alias="X-API-Key")):
    if key != API_KEY:
        raise HTTPException(status_code=403)

@app.get("/", response_class=HTMLResponse)
def login(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login")
def do_login(request: Request, username: str = Form(...), password: str = Form(...)):
    if username == "admin" and password == "admin":
        request.session["auth"] = True
        return RedirectResponse("/dashboard", status_code=302)
    return RedirectResponse("/", status_code=302)

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    if not request.session.get("auth"):
        return RedirectResponse("/", status_code=302)

    cur = db().cursor()
    cur.execute("SELECT hostname, os, ip, last_seen FROM agents")
    agents = cur.fetchall()

    return templates.TemplateResponse(
        "dashboard.html",
        {"request": request, "agents": agents, "now": int(time.time())}
    )

@app.post("/agent/register")
def register_agent(data: dict, key: str = Header(None, alias="X-API-Key")):
    verify_agent(key)
    c = db()
    cur = c.cursor()

    cur.execute("SELECT id FROM agents WHERE machine_id=?", (data["machine_id"],))
    row = cur.fetchone()
    if row:
        return {"agent_id": row[0]}

    agent_id = str(uuid.uuid4())
    cur.execute(
        "INSERT INTO agents VALUES (?,?,?,?,?,?)",
        (
            agent_id,
            data["machine_id"],
            data["hostname"],
            data["os"],
            data["ip"],
            int(time.time()),
        ),
    )
    c.commit()
    return {"agent_id": agent_id}

@app.post("/agent/heartbeat/{agent_id}")
def heartbeat(agent_id: str, key: str = Header(None, alias="X-API-Key")):
    verify_agent(key)
    c = db()
    c.execute(
        "UPDATE agents SET last_seen=? WHERE id=?",
        (int(time.time()), agent_id),
    )
    c.commit()
    return {"status": "ok"}
