from fastapi import FastAPI, Depends, HTTPException, status, Request, Form
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    Boolean,
    DateTime,
    ForeignKey,
    Text,
)
from sqlalchemy.orm import sessionmaker, declarative_base, relationship, Session

from passlib.hash import pbkdf2_sha256
from datetime import datetime
from typing import Optional
import os


# ============ Database Setup ============

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB_PATH = os.path.join(BASE_DIR, "customrmm.db")
DB_PATH = os.environ.get("RMM_DB_PATH", DEFAULT_DB_PATH)

DB_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(DB_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


# ============ FastAPI App ============

app = FastAPI(title="Custom RMM")

templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

static_dir = os.path.join(BASE_DIR, "static")
os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")


SERVER_URL = os.environ.get("RMM_SERVER_URL", "http://localhost:8000")


# ============ Models ============

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    name = Column(String(255))
    email = Column(String(255), unique=True)
    password_hash = Column(String(255))
    role = Column(String(50), default="admin")
    is_active = Column(Boolean, default=True)

    def verify(self, password):
        return pbkdf2_sha256.verify(password, self.password_hash)


class Client(Base):
    __tablename__ = "clients"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), unique=True)
    contact_name = Column(String(255))
    contact_email = Column(String(255))
    contact_phone = Column(String(50))
    notes = Column(Text)

    agents = relationship("Agent", back_populates="client", cascade="all, delete")
    tickets = relationship("Ticket", back_populates="client", cascade="all, delete")


class Agent(Base):
    __tablename__ = "agents"

    id = Column(Integer, primary_key=True)
    client_id = Column(Integer, ForeignKey("clients.id"))
    hostname = Column(String(255))
    os_name = Column(String(255))
    os_version = Column(String(255))
    ip_address = Column(String(255))
    last_seen = Column(DateTime, default=datetime.utcnow)
    status = Column(String(50), default="offline")
    agent_version = Column(String(50))

    client = relationship("Client", back_populates="agents")
    tickets = relationship("Ticket", back_populates="agent")


class Ticket(Base):
    __tablename__ = "tickets"

    id = Column(Integer, primary_key=True)
    client_id = Column(Integer, ForeignKey("clients.id"))
    agent_id = Column(Integer, ForeignKey("agents.id"))
    title = Column(String(255))
    description = Column(Text)
    status = Column(String(50), default="open")
    priority = Column(String(50), default="medium")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

    client = relationship("Client", back_populates="tickets")
    agent = relationship("Agent", back_populates="tickets")


# ============ Database Init ============

def init_db():
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    if not db.query(User).filter_by(email="admin@local").first():
        admin = User(
            name="Admin",
            email="admin@local",
            password_hash=pbkdf2_sha256.hash("admin123"),
        )
        db.add(admin)
        db.commit()

    db.close()


init_db()


# ============ Dependencies ============

SESSION_COOKIE = "rmm_session"

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def current_user(request: Request, db: Session = Depends(get_db)):
    email = request.cookies.get(SESSION_COOKIE)
    if not email:
        raise HTTPException(status_code=401)

    user = db.query(User).filter_by(email=email).first()
    if not user:
        raise HTTPException(status_code=401)

    return user


# ============ UI Pages ============

@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    try:
        user = current_user(request, db)
    except:
        return RedirectResponse("/login")

    clients = db.query(Client).order_by(Client.name).all()
    agents = db.query(Agent).order_by(Agent.id.desc()).all()
    tickets = db.query(Ticket).order_by(Ticket.created_at.desc()).all()

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "clients": clients,
            "agents": agents,
            "tickets": tickets,
        },
    )


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@app.post("/login")
def login(email: str = Form(), password: str = Form(), db: Session = Depends(get_db)):
    user = db.query(User).filter_by(email=email).first()
    if not user or not user.verify(password):
        return RedirectResponse("/login", status_code=302)

    resp = RedirectResponse("/", status_code=302)
    resp.set_cookie(SESSION_COOKIE, email, httponly=True)
    return resp


@app.get("/logout")
def logout():
    resp = RedirectResponse("/login", status_code=302)
    resp.delete_cookie(SESSION_COOKIE)
    return resp


# ============ Client Management ============

@app.post("/clients/add")
def add_client(
    name: str = Form(...),
    contact_name: str = Form(""),
    contact_email: str = Form(""),
    contact_phone: str = Form(""),
    notes: str = Form(""),
    request: Request = None,
    db: Session = Depends(get_db),
):
    current_user(request, db)

    if db.query(Client).filter_by(name=name).first():
        raise HTTPException(400, "Client exists")

    c = Client(
        name=name,
        contact_name=contact_name,
        contact_email=contact_email,
        contact_phone=contact_phone,
        notes=notes,
    )
    db.add(c)
    db.commit()

    return RedirectResponse("/", status_code=302)


@app.post("/clients/delete/{client_id}")
def delete_client(client_id: int, request: Request, db: Session = Depends(get_db)):
    current_user(request, db)

    c = db.query(Client).get(client_id)
    if not c:
        raise HTTPException(404)

    db.delete(c)
    db.commit()
    return RedirectResponse("/", status_code=302)


# ============ Ticketing ============

@app.post("/tickets/add")
def add_ticket(
    title: str = Form(...),
    description: str = Form(...),
    client_id: Optional[int] = Form(None),
    agent_id: Optional[int] = Form(None),
    priority: str = Form("medium"),
    request: Request = None,
    db: Session = Depends(get_db),
):
    current_user(request, db)

    t = Ticket(
        title=title,
        description=description,
        client_id=client_id,
        agent_id=agent_id,
        priority=priority,
    )
    db.add(t)
    db.commit()
    return RedirectResponse("/", status_code=302)


# ============ Agent API ============

@app.post("/api/agents/register")
def agent_register(
    client_name: str,
    hostname: str,
    os_name: str,
    os_version: str,
    ip_address: str,
    agent_version: str = "0.1.0",
    db: Session = Depends(get_db),
):
    client = db.query(Client).filter_by(name=client_name).first()
    if not client:
        raise HTTPException(404)

    a = Agent(
        client_id=client.id,
        hostname=hostname,
        os_name=os_name,
        os_version=os_version,
        ip_address=ip_address,
        status="online",
        last_seen=datetime.utcnow(),
        agent_version=agent_version,
    )
    db.add(a)
    db.commit()

    return {"agent_id": a.id}


@app.post("/api/agents/heartbeat/{agent_id}")
def agent_heartbeat(agent_id: int, ip_address: str, db: Session = Depends(get_db)):
    a = db.query(Agent).get(agent_id)
    if not a:
        raise HTTPException(404)

    a.ip_address = ip_address
    a.last_seen = datetime.utcnow()
    a.status = "online"
    db.commit()

    return {"status": "ok"}


# ============ Installers ============

@app.get("/install/windows/{client_name}", response_class=PlainTextResponse)
def windows_installer(client_name: str):
    script = f"""# Windows RMM Installer
$server = "{SERVER_URL}"
$client = "{client_name}"

# Install Python if missing (future)
# Download agent
$dest = "$env:ProgramData\\CustomRMM"
New-Item -ItemType Directory -Force -Path $dest | Out-Null
Invoke-WebRequest -Uri "$server/static/agent.py" -OutFile "$dest\\agent.py"

# Register
"""
    return script


@app.get("/install/linux/{client_name}", response_class=PlainTextResponse)
def linux_installer(client_name: str):
    script = f"""#!/usr/bin/env bash
SERVER="{SERVER_URL}"
CLIENT="{client_name}"

sudo mkdir -p /opt/customrmm
sudo curl -sS "$SERVER/static/agent.py" -o /opt/customrmm/agent.py
sudo chmod +x /opt/customrmm/agent.py

echo "Linux installer done."
"""
    return script


# ============ Health Check ============

@app.get("/health")
def health():

    return "ok"
