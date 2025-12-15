#!/usr/bin/env python3
"""
CustomRMM (No-Docker) - minimal functional RMM server (Ubuntu 22.04+)

Features (v1):
- Admin/user auth (cookie session)
- Clients CRUD
- Devices list + device detail
- Agent API: register + heartbeat
- Alerts + acknowledge
- Offline monitor (creates alerts when a device stops checking in)
- Left sidebar navigation (updated UI)

This is intentionally "small but real": a working baseline you can extend.
"""
from __future__ import annotations

import os
import secrets
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any, Tuple

from dotenv import load_dotenv
from fastapi import FastAPI, Request, Form, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from sqlalchemy import (
    create_engine, String, Integer, DateTime, Boolean, ForeignKey, Text, select, func, Index
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker, Session

from passlib.context import CryptContext
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

###############################################################################
# Config
###############################################################################

def utcnow() -> datetime:
    return datetime.now(timezone.utc)

def env_bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "y", "on")

load_dotenv()  # loads local .env if present (systemd uses EnvironmentFile)

APP_NAME = os.getenv("APP_NAME", "CustomRMM")
BASE_URL = os.getenv("BASE_URL", "")  # optional, shown in UI
DATA_DIR = os.getenv("DATA_DIR", "/var/lib/customrmm")
DB_PATH = os.getenv("DB_PATH", os.path.join(DATA_DIR, "customrmm.db"))
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DB_PATH}")

SESSION_SECRET = os.getenv("SESSION_SECRET") or secrets.token_urlsafe(48)
SESSION_HTTPS_ONLY = env_bool("SESSION_HTTPS_ONLY", False)

# How long until a device is considered offline (minutes)
OFFLINE_MINUTES = int(os.getenv("OFFLINE_MINUTES", "5"))
OFFLINE_CHECK_EVERY_SECONDS = int(os.getenv("OFFLINE_CHECK_EVERY_SECONDS", "60"))

# Agent enrollment key (used only for initial register call)
ENROLL_KEY = os.getenv("ENROLL_KEY") or secrets.token_urlsafe(24)

###############################################################################
# Database
###############################################################################

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

class Client(Base):
    __tablename__ = "clients"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    devices: Mapped[List["Device"]] = relationship(back_populates="client")

class Device(Base):
    __tablename__ = "devices"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # stable identifier from agent
    device_uuid: Mapped[str] = mapped_column(String(64), unique=True, index=True)

    # API token for heartbeats
    api_token: Mapped[str] = mapped_column(String(96), unique=True, index=True)

    client_id: Mapped[Optional[int]] = mapped_column(ForeignKey("clients.id"), nullable=True)

    hostname: Mapped[str] = mapped_column(String(255), default="unknown")
    os: Mapped[str] = mapped_column(String(255), default="unknown")
    ip: Mapped[Optional[str]] = mapped_column(String(64), default=None)
    agent_version: Mapped[Optional[str]] = mapped_column(String(64), default=None)

    last_seen: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=None, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    tags: Mapped[Optional[str]] = mapped_column(String(512), default=None)  # comma-separated
    status: Mapped[str] = mapped_column(String(32), default="new")  # new/online/offline

    client: Mapped[Optional[Client]] = relationship(back_populates="devices")
    heartbeats: Mapped[List["Heartbeat"]] = relationship(back_populates="device", cascade="all, delete-orphan")
    alerts: Mapped[List["Alert"]] = relationship(back_populates="device", cascade="all, delete-orphan")

Index("ix_devices_client_status", Device.client_id, Device.status)

class Heartbeat(Base):
    __tablename__ = "heartbeats"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id"), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    cpu_load: Mapped[Optional[float]] = mapped_column(Integer, nullable=True)  # percent 0-100 (stored as int)
    mem_used: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)    # percent 0-100
    disk_used: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)   # percent 0-100
    uptime_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    note: Mapped[Optional[str]] = mapped_column(String(255), default=None)

    device: Mapped[Device] = relationship(back_populates="heartbeats")

Index("ix_heartbeats_device_ts", Heartbeat.device_id, Heartbeat.ts)

class Alert(Base):
    __tablename__ = "alerts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id"), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    level: Mapped[str] = mapped_column(String(16), default="warning")  # info/warning/critical
    title: Mapped[str] = mapped_column(String(255))
    details: Mapped[Optional[str]] = mapped_column(Text, default=None)

    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    acknowledged_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), default=None, nullable=True)
    acknowledged_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=None, nullable=True)

    device: Mapped[Device] = relationship(back_populates="alerts")

Index("ix_alerts_ack_ts", Alert.acknowledged, Alert.ts)

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

def init_db() -> None:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    Base.metadata.create_all(bind=engine)

def db_session() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

###############################################################################
# Auth
###############################################################################

pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password: str) -> str:
    return pwd.hash(password)

def verify_password(password: str, password_hash: str) -> bool:
    return pwd.verify(password, password_hash)

def get_user_by_email(db: Session, email: str) -> Optional[User]:
    return db.scalar(select(User).where(User.email == email))

def get_user(db: Session, user_id: int) -> Optional[User]:
    return db.get(User, user_id)

def require_user(request: Request, db: Session = Depends(db_session)) -> User:
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    user = get_user(db, int(user_id))
    if not user:
        request.session.clear()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    return user

def html_require_user(request: Request, db: Session = Depends(db_session)) -> User:
    try:
        return require_user(request, db)
    except HTTPException:
        raise RedirectToLogin()

class RedirectToLogin(Exception):
    pass

###############################################################################
# App + templates + sidebar
###############################################################################

app = FastAPI(title=APP_NAME)
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET, https_only=SESSION_HTTPS_ONLY)
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=os.getenv("TRUSTED_HOSTS", "*").split(",") if os.getenv("TRUSTED_HOSTS") else ["*"],
)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

SIDEBAR = [
    {"label": "Overview", "items": [
        {"name": "Dashboard", "href": "/dashboard", "icon": "home"},
        {"name": "Alerts", "href": "/alerts", "icon": "bell"},
    ]},
    {"label": "Management", "items": [
        {"name": "Devices", "href": "/devices", "icon": "monitor"},
        {"name": "Clients", "href": "/clients", "icon": "building"},
        {"name": "Scripts", "href": "/scripts", "icon": "terminal"},
    ]},
    {"label": "Platform", "items": [
        {"name": "Settings", "href": "/settings", "icon": "cog"},
        {"name": "Logs", "href": "/logs", "icon": "list"},
    ]},
]

ICON_SVGS = {
    "home": """<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 10.5 12 3l9 7.5V21a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1z"/></svg>""",
    "bell": """<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 22a2.5 2.5 0 0 0 2.45-2h-4.9A2.5 2.5 0 0 0 12 22Zm7-6V11a7 7 0 1 0-14 0v5L3 18v2h18v-2z"/></svg>""",
    "monitor": """<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 5a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2h-5v2h3v2H6v-2h3v-2H6a2 2 0 0 1-2-2z"/></svg>""",
    "building": """<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 22V2h12v6h4v14H4zm2-2h2v-2H6v2zm0-4h2v-2H6v2zm0-4h2v-2H6v2zm0-4h2V6H6v2zm4 12h2v-2h-2v2zm0-4h2v-2h-2v2zm0-4h2v-2h-2v2zm0-4h2V6h-2v2zm4 12h2v-2h-2v2zm0-4h2v-2h-2v2z"/></svg>""",
    "terminal": """<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 5h16a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2zm2 4 4 3-4 3v-2l2-1-2-1V9zm6 6h6v-2h-6v2z"/></svg>""",
    "cog": """<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M19.14 12.94a7.96 7.96 0 0 0 .06-.94 7.96 7.96 0 0 0-.06-.94l2.03-1.58a.5.5 0 0 0 .12-.64l-1.92-3.32a.5.5 0 0 0-.6-.22l-2.39.96a7.36 7.36 0 0 0-1.63-.94l-.36-2.54A.5.5 0 0 0 13.9 1h-3.8a.5.5 0 0 0-.49.42l-.36 2.54c-.58.23-1.12.53-1.63.94l-2.39-.96a.5.5 0 0 0-.6.22L2.71 7.02a.5.5 0 0 0 .12.64l2.03 1.58c-.04.31-.06.63-.06.94 0 .31.02.63.06.94L2.83 14.52a.5.5 0 0 0-.12.64l1.92 3.32a.5.5 0 0 0 .6.22l2.39-.96c.5.41 1.05.72 1.63.94l.36 2.54a.5.5 0 0 0 .49.42h3.8a.5.5 0 0 0 .49-.42l.36-2.54c.58-.23 1.12-.53 1.63-.94l2.39.96a.5.5 0 0 0 .6-.22l1.92-3.32a.5.5 0 0 0-.12-.64l-2.03-1.58zM12 15.5A3.5 3.5 0 1 1 12 8a3.5 3.5 0 0 1 0 7.5z"/></svg>""",
    "list": """<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 6h2v2H4V6zm4 0h12v2H8V6zM4 11h2v2H4v-2zm4 0h12v2H8v-2zM4 16h2v2H4v-2zm4 0h12v2H8v-2z"/></svg>""",
}

def render(request: Request, name: str, ctx: Dict[str, Any]) -> HTMLResponse:
    path = request.url.path
    ctx = {
        **ctx,
        "request": request,
        "app_name": APP_NAME,
        "base_url": BASE_URL,
        "sidebar": SIDEBAR,
        "icons": ICON_SVGS,
        "active_path": path,
    }
    return templates.TemplateResponse(name, ctx)

def redirect(path: str) -> RedirectResponse:
    return RedirectResponse(url=path, status_code=status.HTTP_303_SEE_OTHER)

###############################################################################
# Helpers
###############################################################################

def device_is_online(last_seen: Optional[datetime]) -> bool:
    if not last_seen:
        return False
    return (utcnow() - last_seen) <= timedelta(minutes=OFFLINE_MINUTES)

def get_counts(db: Session) -> Dict[str, int]:
    total_clients = db.scalar(select(func.count()).select_from(Client)) or 0
    total_devices = db.scalar(select(func.count()).select_from(Device)) or 0
    total_alerts_open = db.scalar(select(func.count()).select_from(Alert).where(Alert.acknowledged == False)) or 0
    return {"clients": total_clients, "devices": total_devices, "alerts_open": total_alerts_open}

###############################################################################
# Startup: init DB + background offline monitor
###############################################################################

@app.on_event("startup")
async def startup() -> None:
    init_db()
    app.state.offline_task = asyncio.create_task(offline_monitor_loop())

@app.on_event("shutdown")
async def shutdown() -> None:
    task: asyncio.Task = getattr(app.state, "offline_task", None)
    if task:
        task.cancel()

async def offline_monitor_loop() -> None:
    # Background task that marks devices offline and creates alerts.
    while True:
        try:
            with SessionLocal() as db:
                cutoff = utcnow() - timedelta(minutes=OFFLINE_MINUTES)
                devices = db.scalars(select(Device)).all()
                for d in devices:
                    online = device_is_online(d.last_seen)
                    new_status = "online" if online else "offline"
                    if d.status != new_status and d.last_seen is not None:
                        d.status = new_status
                        if new_status == "offline":
                            # Create an alert if no unacked offline alert exists
                            existing = db.scalar(
                                select(Alert).where(
                                    Alert.device_id == d.id,
                                    Alert.acknowledged == False,
                                    Alert.title == "Device offline",
                                ).limit(1)
                            )
                            if not existing:
                                db.add(Alert(
                                    device_id=d.id,
                                    level="warning",
                                    title="Device offline",
                                    details=f"Last seen: {d.last_seen.isoformat()}",
                                ))
                db.commit()
        except Exception:
            # Intentionally swallow errors to keep loop alive.
            pass
        await asyncio.sleep(OFFLINE_CHECK_EVERY_SECONDS)

###############################################################################
# Public endpoints
###############################################################################

@app.get("/healthz", response_class=PlainTextResponse)
def healthz() -> str:
    return "ok"

@app.get("/", response_class=HTMLResponse)
def root(request: Request):
    # If logged in, go to dashboard, otherwise login/setup
    with SessionLocal() as db:
        any_user = db.scalar(select(func.count()).select_from(User)) or 0
    if request.session.get("user_id"):
        return redirect("/dashboard")
    if any_user == 0:
        return redirect("/setup-admin")
    return redirect("/login")

###############################################################################
# Setup admin (first-run)
###############################################################################

@app.get("/setup-admin", response_class=HTMLResponse)
def setup_admin_get(request: Request):
    with SessionLocal() as db:
        any_user = db.scalar(select(func.count()).select_from(User)) or 0
    if any_user > 0:
        return redirect("/login")
    return render(request, "setup_admin.html", {"error": None})

@app.post("/setup-admin", response_class=HTMLResponse)
def setup_admin_post(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
):
    with SessionLocal() as db:
        any_user = db.scalar(select(func.count()).select_from(User)) or 0
        if any_user > 0:
            return redirect("/login")
        email_norm = email.strip().lower()
        if len(password) < 10:
            return render(request, "setup_admin.html", {"error": "Password must be at least 10 characters."})
        user = User(email=email_norm, password_hash=hash_password(password), is_admin=True)
        db.add(user)
        db.commit()
        db.refresh(user)
        request.session["user_id"] = user.id
    return redirect("/dashboard")

###############################################################################
# Login/logout
###############################################################################

@app.get("/login", response_class=HTMLResponse)
def login_get(request: Request):
    # If no users yet, redirect to setup
    with SessionLocal() as db:
        any_user = db.scalar(select(func.count()).select_from(User)) or 0
    if any_user == 0:
        return redirect("/setup-admin")
    if request.session.get("user_id"):
        return redirect("/dashboard")
    return render(request, "login.html", {"error": None})

@app.post("/login", response_class=HTMLResponse)
def login_post(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
):
    with SessionLocal() as db:
        user = get_user_by_email(db, email.strip().lower())
        if not user or not verify_password(password, user.password_hash):
            return render(request, "login.html", {"error": "Invalid email or password."})
        request.session["user_id"] = user.id
    return redirect("/dashboard")

@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return redirect("/login")

###############################################################################
# Dashboard
###############################################################################

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, user: User = Depends(html_require_user)):
    with SessionLocal() as db:
        counts = get_counts(db)
        recent_alerts = db.scalars(
            select(Alert).order_by(Alert.ts.desc()).limit(10)
        ).all()
        devices = db.scalars(select(Device).order_by(Device.last_seen.desc().nullslast()).limit(10)).all()

    return render(request, "dashboard.html", {
        "user": user,
        "counts": counts,
        "recent_alerts": recent_alerts,
        "recent_devices": devices,
        "offline_minutes": OFFLINE_MINUTES,
        "enroll_key_hint": ENROLL_KEY[:6] + "..." if ENROLL_KEY else "",
    })

###############################################################################
# Clients CRUD
###############################################################################

@app.get("/clients", response_class=HTMLResponse)
def clients_list(request: Request, user: User = Depends(html_require_user)):
    with SessionLocal() as db:
        clients = db.scalars(select(Client).order_by(Client.name.asc())).all()
        device_counts = dict(db.execute(select(Device.client_id, func.count()).group_by(Device.client_id)).all())
    return render(request, "clients.html", {
        "user": user,
        "clients": clients,
        "device_counts": device_counts,
    })

@app.get("/clients/new", response_class=HTMLResponse)
def clients_new_get(request: Request, user: User = Depends(html_require_user)):
    return render(request, "client_form.html", {"user": user, "mode": "new", "client": None, "error": None})

@app.post("/clients/new", response_class=HTMLResponse)
def clients_new_post(
    request: Request,
    user: User = Depends(html_require_user),
    name: str = Form(...),
    notes: str = Form(""),
):
    name = name.strip()
    if not name:
        return render(request, "client_form.html", {"user": user, "mode": "new", "client": None, "error": "Name is required."})
    with SessionLocal() as db:
        exists = db.scalar(select(Client).where(Client.name == name))
        if exists:
            return render(request, "client_form.html", {"user": user, "mode": "new", "client": None, "error": "Client already exists."})
        c = Client(name=name, notes=(notes.strip() or None))
        db.add(c)
        db.commit()
    return redirect("/clients")

@app.get("/clients/{client_id}/edit", response_class=HTMLResponse)
def clients_edit_get(request: Request, client_id: int, user: User = Depends(html_require_user)):
    with SessionLocal() as db:
        c = db.get(Client, client_id)
        if not c:
            return redirect("/clients")
    return render(request, "client_form.html", {"user": user, "mode": "edit", "client": c, "error": None})

@app.post("/clients/{client_id}/edit", response_class=HTMLResponse)
def clients_edit_post(
    request: Request,
    client_id: int,
    user: User = Depends(html_require_user),
    name: str = Form(...),
    notes: str = Form(""),
):
    name = name.strip()
    if not name:
        with SessionLocal() as db:
            c = db.get(Client, client_id)
        return render(request, "client_form.html", {"user": user, "mode": "edit", "client": c, "error": "Name is required."})
    with SessionLocal() as db:
        c = db.get(Client, client_id)
        if not c:
            return redirect("/clients")
        # prevent name collision
        other = db.scalar(select(Client).where(Client.name == name, Client.id != client_id))
        if other:
            return render(request, "client_form.html", {"user": user, "mode": "edit", "client": c, "error": "Another client already has that name."})
        c.name = name
        c.notes = (notes.strip() or None)
        db.commit()
    return redirect("/clients")

@app.post("/clients/{client_id}/delete")
def clients_delete(client_id: int, user: User = Depends(html_require_user)):
    with SessionLocal() as db:
        c = db.get(Client, client_id)
        if c:
            # Detach devices rather than deleting them
            for d in db.scalars(select(Device).where(Device.client_id == client_id)).all():
                d.client_id = None
            db.delete(c)
            db.commit()
    return redirect("/clients")

###############################################################################
# Devices
###############################################################################

@app.get("/devices", response_class=HTMLResponse)
def devices_list(
    request: Request,
    user: User = Depends(html_require_user),
    client_id: Optional[int] = None,
    status_filter: Optional[str] = None,
    q: str = "",
):
    q = (q or "").strip().lower()
    with SessionLocal() as db:
        clients = db.scalars(select(Client).order_by(Client.name.asc())).all()

        stmt = select(Device).order_by(Device.last_seen.desc().nullslast(), Device.hostname.asc())
        if client_id:
            stmt = stmt.where(Device.client_id == client_id)
        if status_filter in ("online", "offline", "new"):
            stmt = stmt.where(Device.status == status_filter)
        if q:
            stmt = stmt.where(
                func.lower(Device.hostname).contains(q) |
                func.lower(Device.os).contains(q) |
                func.lower(func.coalesce(Device.ip, "")).contains(q)
            )

        devices = db.scalars(stmt).all()

        # enrich with client names (avoid lazy load)
        client_map = {c.id: c.name for c in clients}
        enriched = []
        for d in devices:
            enriched.append({
                "id": d.id,
                "device_uuid": d.device_uuid,
                "hostname": d.hostname,
                "os": d.os,
                "ip": d.ip,
                "agent_version": d.agent_version,
                "last_seen": d.last_seen,
                "status": "online" if device_is_online(d.last_seen) else ("new" if d.last_seen is None else "offline"),
                "client_id": d.client_id,
                "client_name": client_map.get(d.client_id) if d.client_id else None,
            })

    return render(request, "devices.html", {
        "user": user,
        "devices": enriched,
        "clients": clients,
        "filters": {"client_id": client_id, "status": status_filter, "q": q},
        "offline_minutes": OFFLINE_MINUTES,
    })

@app.get("/devices/{device_id}", response_class=HTMLResponse)
def device_detail(request: Request, device_id: int, user: User = Depends(html_require_user)):
    with SessionLocal() as db:
        d = db.get(Device, device_id)
        if not d:
            return redirect("/devices")
        clients = db.scalars(select(Client).order_by(Client.name.asc())).all()
        heartbeats = db.scalars(
            select(Heartbeat).where(Heartbeat.device_id == device_id).order_by(Heartbeat.ts.desc()).limit(50)
        ).all()
        alerts = db.scalars(
            select(Alert).where(Alert.device_id == device_id).order_by(Alert.ts.desc()).limit(20)
        ).all()

        status_str = "online" if device_is_online(d.last_seen) else ("new" if d.last_seen is None else "offline")

    return render(request, "device_detail.html", {
        "user": user,
        "device": d,
        "device_status": status_str,
        "clients": clients,
        "heartbeats": heartbeats,
        "alerts": alerts,
        "offline_minutes": OFFLINE_MINUTES,
    })

@app.post("/devices/{device_id}/assign")
def device_assign(device_id: int, user: User = Depends(html_require_user), client_id: Optional[int] = Form(None)):
    with SessionLocal() as db:
        d = db.get(Device, device_id)
        if d:
            d.client_id = int(client_id) if client_id else None
            db.commit()
    return redirect(f"/devices/{device_id}")

@app.post("/devices/{device_id}/delete")
def device_delete(device_id: int, user: User = Depends(html_require_user)):
    with SessionLocal() as db:
        d = db.get(Device, device_id)
        if d:
            db.delete(d)
            db.commit()
    return redirect("/devices")

###############################################################################
# Alerts
###############################################################################

@app.get("/alerts", response_class=HTMLResponse)
def alerts_list(request: Request, user: User = Depends(html_require_user), show: str = "open"):
    with SessionLocal() as db:
        stmt = select(Alert).order_by(Alert.ts.desc())
        if show == "open":
            stmt = stmt.where(Alert.acknowledged == False)
        alerts = db.scalars(stmt.limit(200)).all()

        # device name map
        dev_ids = list({a.device_id for a in alerts})
        dev_map = {}
        if dev_ids:
            for d in db.scalars(select(Device).where(Device.id.in_(dev_ids))).all():
                dev_map[d.id] = d
    enriched = []
    for a in alerts:
        d = dev_map.get(a.device_id)
        enriched.append({
            "id": a.id,
            "ts": a.ts,
            "level": a.level,
            "title": a.title,
            "details": a.details,
            "acknowledged": a.acknowledged,
            "device_id": a.device_id,
            "device_hostname": d.hostname if d else "unknown",
        })

    return render(request, "alerts.html", {"user": user, "alerts": enriched, "show": show})

@app.post("/alerts/{alert_id}/ack")
def alert_ack(alert_id: int, user: User = Depends(html_require_user)):
    with SessionLocal() as db:
        a = db.get(Alert, alert_id)
        if a and not a.acknowledged:
            a.acknowledged = True
            a.acknowledged_by = user.id
            a.acknowledged_at = utcnow()
            db.commit()
    return redirect("/alerts")

###############################################################################
# Stub pages (Scripts, Settings, Logs)
###############################################################################

@app.get("/scripts", response_class=HTMLResponse)
def scripts_page(request: Request, user: User = Depends(html_require_user)):
    return render(request, "stub.html", {"user": user, "title": "Scripts", "message": "Script library and execution will be added next."})

@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, user: User = Depends(html_require_user)):
    # Show server-side config hints safely
    return render(request, "settings.html", {
        "user": user,
        "offline_minutes": OFFLINE_MINUTES,
        "enroll_key": ENROLL_KEY,
        "db_path": DB_PATH,
        "https_only": SESSION_HTTPS_ONLY,
    })

@app.get("/logs", response_class=HTMLResponse)
def logs_page(request: Request, user: User = Depends(html_require_user)):
    return render(request, "stub.html", {"user": user, "title": "Logs", "message": "Add log viewer (systemd journal + app logs) next."})

###############################################################################
# Agent API (No auth cookie; token-based)
###############################################################################

def require_enroll_key(request: Request) -> None:
    provided = request.headers.get("X-ENROLL-KEY", "")
    if not provided or provided != ENROLL_KEY:
        raise HTTPException(status_code=401, detail="Invalid enroll key")

def get_device_by_token(db: Session, token: str) -> Optional[Device]:
    return db.scalar(select(Device).where(Device.api_token == token))

@app.post("/api/v1/register")
async def api_register(request: Request, payload: Dict[str, Any], db: Session = Depends(db_session)):
    """
    First call from an agent:
    Headers: X-ENROLL-KEY: <ENROLL_KEY>
    Body:
      {
        "device_uuid": "...",
        "hostname": "...",
        "os": "...",
        "ip": "...",
        "agent_version": "1.0.0"
      }
    Returns:
      { "device_id": 123, "api_token": "..." }
    """
    require_enroll_key(request)
    device_uuid = (payload.get("device_uuid") or "").strip()
    if not device_uuid or len(device_uuid) > 64:
        raise HTTPException(400, detail="device_uuid required")
    hostname = (payload.get("hostname") or "unknown").strip()[:255]
    os_name = (payload.get("os") or "unknown").strip()[:255]
    ip = (payload.get("ip") or None)
    agent_version = (payload.get("agent_version") or None)

    d = db.scalar(select(Device).where(Device.device_uuid == device_uuid))
    if not d:
        d = Device(
            device_uuid=device_uuid,
            api_token=secrets.token_urlsafe(32),
            hostname=hostname,
            os=os_name,
            ip=ip,
            agent_version=agent_version,
            status="new",
            last_seen=None,
        )
        db.add(d)
        db.commit()
        db.refresh(d)
    else:
        # update metadata; keep existing api_token
        d.hostname = hostname
        d.os = os_name
        d.ip = ip
        d.agent_version = agent_version
        db.commit()

    return {"device_id": d.id, "api_token": d.api_token}

@app.post("/api/v1/heartbeat")
async def api_heartbeat(request: Request, payload: Dict[str, Any], db: Session = Depends(db_session)):
    """
    Heartbeat call:
    Header: Authorization: Bearer <api_token>
    Body:
      {
        "cpu": 23, "mem": 61, "disk": 52,
        "uptime_seconds": 12345,
        "ip": "x.x.x.x",
        "hostname": "pc-01",
        "os": "Windows 11",
        "agent_version": "1.0.0",
        "note": "optional"
      }
    """
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(401, detail="Missing bearer token")
    token = auth.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(401, detail="Missing bearer token")
    d = get_device_by_token(db, token)
    if not d:
        raise HTTPException(401, detail="Invalid device token")

    cpu = payload.get("cpu")
    mem = payload.get("mem")
    disk = payload.get("disk")
    uptime_seconds = payload.get("uptime_seconds")
    note = (payload.get("note") or None)

    # update metadata
    d.ip = payload.get("ip") or d.ip
    d.hostname = (payload.get("hostname") or d.hostname)[:255]
    d.os = (payload.get("os") or d.os)[:255]
    d.agent_version = (payload.get("agent_version") or d.agent_version)
    d.last_seen = utcnow()
    d.status = "online"

    hb = Heartbeat(
        device_id=d.id,
        cpu_load=int(cpu) if isinstance(cpu, (int, float)) else None,
        mem_used=int(mem) if isinstance(mem, (int, float)) else None,
        disk_used=int(disk) if isinstance(disk, (int, float)) else None,
        uptime_seconds=int(uptime_seconds) if isinstance(uptime_seconds, (int, float)) else None,
        note=(str(note)[:255] if note else None),
    )
    db.add(hb)
    db.commit()

    return {"ok": True, "server_time": utcnow().isoformat(), "device_id": d.id}

@app.get("/api/v1/ping")
def api_ping() -> Dict[str, Any]:
    return {"ok": True, "name": APP_NAME, "time": utcnow().isoformat()}

###############################################################################
# Error handling (redirect unauthenticated HTML routes)
###############################################################################

@app.exception_handler(RedirectToLogin)
def handle_redirect_to_login(request: Request, exc: RedirectToLogin):
    return redirect("/login")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=int(os.getenv("APP_PORT", "8000")), reload=True)
