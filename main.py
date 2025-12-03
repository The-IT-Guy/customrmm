import os
import secrets
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

from fastapi import (
    FastAPI,
    Request,
    Depends,
    Form,
    HTTPException,
    status,
)
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    DateTime,
    Text,
    ForeignKey,
    Boolean,
)
from sqlalchemy.orm import sessionmaker, declarative_base, relationship, Session

from passlib.context import CryptContext
import pyotp

# ---------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE_URL = f"sqlite:///{os.path.join(BASE_DIR, 'rmm.db')}"

SESSION_TTL_HOURS = 8
LOGIN_MAX_ATTEMPTS = 5
LOGIN_WINDOW_MINUTES = 15

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# in-memory login rate limiter: ip -> {"count": int, "first": datetime}
login_attempts: Dict[str, Dict[str, Any]] = {}

# ---------------------------------------------------------------------
# FastAPI + DB setup
# ---------------------------------------------------------------------

engine = create_engine(
    DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

app = FastAPI(title="Nexivo RMM")

static_dir = os.path.join(BASE_DIR, "static")
templates_dir = os.path.join(BASE_DIR, "templates")

os.makedirs(static_dir, exist_ok=True)
os.makedirs(templates_dir, exist_ok=True)

app.mount("/static", StaticFiles(directory=static_dir), name="static")
templates = Jinja2Templates(directory=templates_dir)


# ---------------------------------------------------------------------
# DB Models
# ---------------------------------------------------------------------


class AdminUser(Base):
    __tablename__ = "admin_users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    totp_secret = Column(String(64), nullable=True)
    is_totp_enabled = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

    sessions = relationship(
        "Session",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    reset_tokens = relationship(
        "PasswordResetToken",
        back_populates="user",
        cascade="all, delete-orphan",
    )


class Session(Base):
    __tablename__ = "sessions"

    id = Column(Integer, primary_key=True, index=True)
    token = Column(String(255), unique=True, index=True, nullable=False)
    user_id = Column(Integer, ForeignKey("admin_users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)

    user = relationship("AdminUser", back_populates="sessions")


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("admin_users.id"), nullable=False)
    token = Column(String(255), unique=True, index=True, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("AdminUser", back_populates="reset_tokens")


class Client(Base):
    __tablename__ = "clients"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)
    company = Column(String(200), nullable=True)
    email = Column(String(200), nullable=True)
    phone = Column(String(100), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

    agents = relationship(
        "Agent", back_populates="client", cascade="all, delete-orphan"
    )


class Agent(Base):
    __tablename__ = "agents"

    id = Column(Integer, primary_key=True, index=True)
    hostname = Column(String(200), nullable=False, index=True)
    username = Column(String(200), nullable=True)
    os_name = Column(String(200), nullable=True)
    os_version = Column(String(200), nullable=True)
    ip_address = Column(String(100), nullable=True)

    cpu_model = Column(String(300), nullable=True)
    cpu_cores = Column(Integer, nullable=True)
    total_ram_gb = Column(String(50), nullable=True)
    total_disk_gb = Column(String(50), nullable=True)
    free_disk_gb = Column(String(50), nullable=True)
    gpu_name = Column(String(300), nullable=True)

    status = Column(String(50), default="offline")
    last_checkin = Column(DateTime, default=datetime.utcnow)

    agent_tag = Column(String(200), nullable=True)
    notes = Column(Text, nullable=True)

    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True)
    client = relationship("Client", back_populates="agents")


Base.metadata.create_all(bind=engine)


# ---------------------------------------------------------------------
# Dependencies & helpers
# ---------------------------------------------------------------------


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def mark_agent_status(agent: Agent):
    if not agent.last_checkin:
        agent.status = "offline"
        return
    if agent.last_checkin < datetime.utcnow() - timedelta(minutes=5):
        agent.status = "offline"
    else:
        agent.status = "online"


def get_client_or_404(db: Session, client_id: int) -> Client:
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    return client


def get_agent_or_404(db: Session, agent_id: int) -> Agent:
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


def cleanup_expired_sessions(db: Session):
    now = datetime.utcnow()
    db.query(Session).filter(Session.expires_at < now).delete()
    db.commit()


def get_current_user(
    request: Request, db: Session = Depends(get_db)
) -> Optional[AdminUser]:
    cleanup_expired_sessions(db)
    token = request.cookies.get("session_token")
    if not token:
        return None
    session = (
        db.query(Session)
        .filter(Session.token == token, Session.expires_at > datetime.utcnow())
        .first()
    )
    if not session:
        return None
    return session.user


def require_login(
    current_user: Optional[AdminUser] = Depends(get_current_user),
):
    if current_user is None:
        # redirect to login
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/login"},
        )
    return current_user


def get_client_ip(request: Request) -> str:
    # simple best-effort
    ip = request.client.host if request.client else "unknown"
    return ip or "unknown"


def check_login_rate_limit(ip: str) -> bool:
    now = datetime.utcnow()
    window = timedelta(minutes=LOGIN_WINDOW_MINUTES)
    entry = login_attempts.get(ip)
    if not entry or entry["first"] < now - window:
        login_attempts[ip] = {"first": now, "count": 0}
        entry = login_attempts[ip]
    entry["count"] += 1
    return entry["count"] <= LOGIN_MAX_ATTEMPTS


# ---------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------


@app.get("/login", response_class=HTMLResponse)
async def login_page(
    request: Request, db: Session = Depends(get_db), reset: Optional[str] = None
):
    user = get_current_user(request, db)
    if user:
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)

    error = None
    if reset == "1":
        error = None  # could pass a success message via separate variable if you update template

    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "error": error,
            "email": "admin@local",
            "password_placeholder": "admin123",
        },
    )


@app.post("/login", response_class=HTMLResponse)
async def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    totp_code: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    ip = get_client_ip(request)
    if not check_login_rate_limit(ip):
        # too many attempts
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "error": "Too many login attempts. Please try again in a few minutes.",
                "email": email,
                "password_placeholder": "",
            },
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        )

    user = db.query(AdminUser).filter(AdminUser.email == email).first()

    if not user or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "error": "Invalid email or password.",
                "email": email,
                "password_placeholder": "",
            },
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    # If TOTP is enabled, require a valid code
    if user.is_totp_enabled and user.totp_secret:
        if not totp_code:
            return templates.TemplateResponse(
                "login.html",
                {
                    "request": request,
                    "error": "2FA code required.",
                    "email": email,
                    "password_placeholder": "",
                },
                status_code=status.HTTP_401_UNAUTHORIZED,
            )
        totp = pyotp.TOTP(user.totp_secret)
        if not totp.verify(totp_code.strip()):
            return templates.TemplateResponse(
                "login.html",
                {
                    "request": request,
                    "error": "Invalid 2FA code.",
                    "email": email,
                    "password_placeholder": "",
                },
                status_code=status.HTTP_401_UNAUTHORIZED,
            )

    # Successful login: create session
    token = secrets.token_urlsafe(32)
    now = datetime.utcnow()
    expires_at = now + timedelta(hours=SESSION_TTL_HOURS)

    session = Session(token=token, user_id=user.id, created_at=now, expires_at=expires_at)
    db.add(session)
    db.commit()

    response = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        "session_token",
        token,
        max_age=SESSION_TTL_HOURS * 3600,
        httponly=True,
        secure=False,  # set True if behind HTTPS
        samesite="lax",
    )
    return response


@app.get("/logout")
async def logout(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get("session_token")
    if token:
        db.query(Session).filter(Session.token == token).delete()
        db.commit()

    response = RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie("session_token")
    return response


@app.get("/setup-admin", response_class=HTMLResponse)
async def setup_admin_page(request: Request, db: Session = Depends(get_db)):
    existing = db.query(AdminUser).count()
    if existing > 0:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    return templates.TemplateResponse(
        "setup_admin.html",
        {"request": request, "error": None, "email": ""},
    )


@app.post("/setup-admin", response_class=HTMLResponse)
async def setup_admin_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
    db: Session = Depends(get_db),
):
    existing = db.query(AdminUser).count()
    if existing > 0:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    if password != password_confirm:
        return templates.TemplateResponse(
            "setup_admin.html",
            {
                "request": request,
                "error": "Passwords do not match.",
                "email": email,
            },
        )

    if db.query(AdminUser).filter(AdminUser.email == email).first():
        return templates.TemplateResponse(
            "setup_admin.html",
            {
                "request": request,
                "error": "An admin with that email already exists.",
                "email": email,
            },
        )

    user = AdminUser(
        email=email.strip(),
        password_hash=get_password_hash(password),
    )
    db.add(user)
    db.commit()

    return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/forgot-password", response_class=HTMLResponse)
async def forgot_password_page(request: Request):
    return templates.TemplateResponse(
        "forgot_password.html",
        {"request": request, "message": None, "email": ""},
    )


@app.post("/forgot-password", response_class=HTMLResponse)
async def forgot_password_submit(
    request: Request,
    email: str = Form(...),
    db: Session = Depends(get_db),
):
    user = db.query(AdminUser).filter(AdminUser.email == email).first()
    reset_link = None

    if user:
        token_str = secrets.token_urlsafe(32)
        expires_at = datetime.utcnow() + timedelta(hours=1)
        prt = PasswordResetToken(
            user_id=user.id,
            token=token_str,
            expires_at=expires_at,
        )
        db.add(prt)
        db.commit()
        reset_link = f"/reset-password?token={token_str}"

    # For now, we show the link on-screen (dev mode).
    message = (
        "If that email exists, a reset link has been generated."
        + (f" Reset URL: {reset_link}" if reset_link else "")
    )

    return templates.TemplateResponse(
        "forgot_password.html",
        {"request": request, "message": message, "email": email},
    )


@app.get("/reset-password", response_class=HTMLResponse)
async def reset_password_page(
    request: Request,
    token: Optional[str] = None,
    db: Session = Depends(get_db),
):
    if not token:
        raise HTTPException(status_code=400, detail="Missing token")

    prt = (
        db.query(PasswordResetToken)
        .filter(PasswordResetToken.token == token)
        .first()
    )
    error = None
    if (
        not prt
        or prt.used_at is not None
        or prt.expires_at < datetime.utcnow()
    ):
        error = "This reset link is invalid or has expired."

    return templates.TemplateResponse(
        "reset_password.html",
        {"request": request, "error": error, "token": token},
    )


@app.post("/reset-password", response_class=HTMLResponse)
async def reset_password_submit(
    request: Request,
    token: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
    db: Session = Depends(get_db),
):
    prt = (
        db.query(PasswordResetToken)
        .filter(PasswordResetToken.token == token)
        .first()
    )
    if (
        not prt
        or prt.used_at is not None
        or prt.expires_at < datetime.utcnow()
    ):
        return templates.TemplateResponse(
            "reset_password.html",
            {
                "request": request,
                "error": "This reset link is invalid or has expired.",
                "token": token,
            },
        )

    if password != password_confirm:
        return templates.TemplateResponse(
            "reset_password.html",
            {
                "request": request,
                "error": "Passwords do not match.",
                "token": token,
            },
        )

    user = db.query(AdminUser).filter(AdminUser.id == prt.user_id).first()
    if not user:
        return templates.TemplateResponse(
            "reset_password.html",
            {
                "request": request,
                "error": "User not found.",
                "token": token,
            },
        )

    user.password_hash = get_password_hash(password)
    user.updated_at = datetime.utcnow()
    prt.used_at = datetime.utcnow()
    db.commit()

    return RedirectResponse(url="/login?reset=1", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/account/totp/setup", response_class=HTMLResponse)
async def totp_setup_page(
    request: Request,
    current_user: AdminUser = Depends(require_login),
):
    otpauth_url = None
    secret = current_user.totp_secret

    if secret:
        totp = pyotp.TOTP(secret)
        otpauth_url = totp.provisioning_uri(
            name=current_user.email, issuer_name="Nexivo RMM"
        )

    return templates.TemplateResponse(
        "totp_setup.html",
        {
            "request": request,
            "totp_secret": secret,
            "otpauth_url": otpauth_url,
            "message": None,
        },
    )


@app.post("/account/totp/setup", response_class=HTMLResponse)
async def totp_setup_submit(
    request: Request,
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_login),
):
    user = db.query(AdminUser).filter(AdminUser.id == current_user.id).first()
    if not user:
        raise HTTPException(status_code=400, detail="User not found")

    message = None
    if not user.totp_secret:
        secret = pyotp.random_base32()
        user.totp_secret = secret
        user.is_totp_enabled = True
        user.updated_at = datetime.utcnow()
        db.commit()
        message = "2FA secret generated. Add it to your authenticator app."
    else:
        message = "2FA is already configured for your account."

    otpauth_url = None
    if user.totp_secret:
        totp = pyotp.TOTP(user.totp_secret)
        otpauth_url = totp.provisioning_uri(
            name=user.email, issuer_name="Nexivo RMM"
        )

    return templates.TemplateResponse(
        "totp_setup.html",
        {
            "request": request,
            "totp_secret": user.totp_secret,
            "otpauth_url": otpauth_url,
            "message": message,
        },
    )


# ---------------------------------------------------------------------
# Dashboard + Client/Agent CRUD (HTML)
# ---------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_login),
):
    clients = db.query(Client).order_by(Client.created_at.desc()).all()
    agents = db.query(Agent).order_by(Agent.last_checkin.desc()).all()
    for a in agents:
        mark_agent_status(a)

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "clients": clients,
            "agents": agents,
            "current_user": current_user,
        },
    )


@app.get("/clients/new", response_class=HTMLResponse)
async def new_client(
    request: Request,
    current_user: AdminUser = Depends(require_login),
):
    return templates.TemplateResponse(
        "client_form.html",
        {
            "request": request,
            "mode": "create",
            "client": None,
            "current_user": current_user,
        },
    )


@app.post("/clients/create")
async def create_client(
    request: Request,
    name: str = Form(...),
    company: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_login),
):
    client = Client(
        name=name.strip(),
        company=company.strip() or None,
        email=email.strip() or None,
        phone=phone.strip() or None,
        notes=notes.strip() or None,
    )
    db.add(client)
    db.commit()
    db.refresh(client)

    return RedirectResponse(
        url=f"/clients/{client.id}", status_code=status.HTTP_303_SEE_OTHER
    )


@app.get("/clients/{client_id}", response_class=HTMLResponse)
async def client_detail(
    client_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_login),
):
    client = get_client_or_404(db, client_id)
    for a in client.agents:
        mark_agent_status(a)

    return templates.TemplateResponse(
        "client_detail.html",
        {
            "request": request,
            "client": client,
            "current_user": current_user,
        },
    )


@app.get("/clients/{client_id}/edit", response_class=HTMLResponse)
async def edit_client(
    client_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_login),
):
    client = get_client_or_404(db, client_id)
    return templates.TemplateResponse(
        "client_form.html",
        {
            "request": request,
            "mode": "edit",
            "client": client,
            "current_user": current_user,
        },
    )


@app.post("/clients/{client_id}/update")
async def update_client(
    client_id: int,
    request: Request,
    name: str = Form(...),
    company: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_login),
):
    client = get_client_or_404(db, client_id)

    client.name = name.strip()
    client.company = company.strip() or None
    client.email = email.strip() or None
    client.phone = phone.strip() or None
    client.notes = notes.strip() or None
    client.updated_at = datetime.utcnow()

    db.commit()

    return RedirectResponse(
        url=f"/clients/{client.id}", status_code=status.HTTP_303_SEE_OTHER
    )


@app.post("/clients/{client_id}/delete")
async def delete_client(
    client_id: int,
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_login),
):
    client = get_client_or_404(db, client_id)
    db.delete(client)
    db.commit()
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/agents/new", response_class=HTMLResponse)
async def new_agent(
    request: Request,
    client_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_login),
):
    client = None
    if client_id:
        client = db.query(Client).filter(Client.id == client_id).first()

    return templates.TemplateResponse(
        "agent_form.html",
        {
            "request": request,
            "mode": "create",
            "agent": None,
            "client": client,
            "clients": db.query(Client).all(),
            "current_user": current_user,
        },
    )


@app.post("/agents/create")
async def create_agent(
    request: Request,
    hostname: str = Form(...),
    username: str = Form(""),
    agent_tag: str = Form(""),
    notes: str = Form(""),
    client_id: Optional[int] = Form(None),
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_login),
):
    agent = Agent(
        hostname=hostname.strip(),
        username=username.strip() or None,
        agent_tag=agent_tag.strip() or None,
        notes=notes.strip() or None,
        client_id=client_id or None,
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)
    return RedirectResponse(
        url=f"/agents/{agent.id}", status_code=status.HTTP_303_SEE_OTHER
    )


@app.get("/agents/{agent_id}", response_class=HTMLResponse)
async def agent_detail(
    agent_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_login),
):
    agent = get_agent_or_404(db, agent_id)
    mark_agent_status(agent)

    return templates.TemplateResponse(
        "agent_detail.html",
        {
            "request": request,
            "agent": agent,
            "current_user": current_user,
        },
    )


@app.get("/agents/{agent_id}/edit", response_class=HTMLResponse)
async def edit_agent(
    agent_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_login),
):
    agent = get_agent_or_404(db, agent_id)
    clients = db.query(Client).all()
    return templates.TemplateResponse(
        "agent_form.html",
        {
            "request": request,
            "mode": "edit",
            "agent": agent,
            "client": agent.client,
            "clients": clients,
            "current_user": current_user,
        },
    )


@app.post("/agents/{agent_id}/update")
async def update_agent(
    agent_id: int,
    request: Request,
    hostname: str = Form(...),
    username: str = Form(""),
    agent_tag: str = Form(""),
    notes: str = Form(""),
    client_id: Optional[int] = Form(None),
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_login),
):
    agent = get_agent_or_404(db, agent_id)

    agent.hostname = hostname.strip()
    agent.username = username.strip() or None
    agent.agent_tag = agent_tag.strip() or None
    agent.notes = notes.strip() or None
    agent.client_id = client_id or None

    db.commit()

    return RedirectResponse(
        url=f"/agents/{agent.id}", status_code=status.HTTP_303_SEE_OTHER
    )


@app.post("/agents/{agent_id}/delete")
async def delete_agent(
    agent_id: int,
    db: Session = Depends(get_db),
    current_user: AdminUser = Depends(require_login),
):
    agent = get_agent_or_404(db, agent_id)
    db.delete(agent)
    db.commit()
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)


# ---------------------------------------------------------------------
# Agent API – checkin
# ---------------------------------------------------------------------


@app.post("/api/agents/checkin")
async def agent_checkin(payload: dict, db: Session = Depends(get_db)):
    """
    Agent posts a JSON payload with system info.
    If 'agent_id' is present, update that agent; otherwise find/create by hostname.
    """
    agent_id = payload.get("agent_id")
    hostname = payload.get("hostname")
    if not hostname:
        raise HTTPException(status_code=400, detail="hostname is required")

    if agent_id:
        agent = db.query(Agent).filter(Agent.id == agent_id).first()
    else:
        agent = (
            db.query(Agent)
            .filter(Agent.hostname == hostname)
            .order_by(Agent.id.asc())
            .first()
        )

    if not agent:
        agent = Agent(hostname=hostname)

    agent.username = payload.get("username") or agent.username
    agent.os_name = payload.get("os_name") or agent.os_name
    agent.os_version = payload.get("os_version") or agent.os_version
    agent.ip_address = payload.get("ip_address") or agent.ip_address

    agent.cpu_model = payload.get("cpu_model") or agent.cpu_model
    agent.cpu_cores = payload.get("cpu_cores") or agent.cpu_cores
    agent.total_ram_gb = payload.get("total_ram_gb") or agent.total_ram_gb
    agent.total_disk_gb = payload.get("total_disk_gb") or agent.total_disk_gb
    agent.free_disk_gb = payload.get("free_disk_gb") or agent.free_disk_gb
    agent.gpu_name = payload.get("gpu_name") or agent.gpu_name

    agent.last_checkin = datetime.utcnow()
    agent.status = "online"

    db.add(agent)
    db.commit()
    db.refresh(agent)

    return {
        "agent_id": agent.id,
        "status": "ok",
    }


# ---------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------


@app.get("/health")
async def health():
    return {"status": "ok", "time": datetime.utcnow().isoformat()}


# ---------------------------------------------------------------------
# Uvicorn entry point
# ---------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
