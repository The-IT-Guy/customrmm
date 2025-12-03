import os
from datetime import datetime, timedelta

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
)
from sqlalchemy.orm import sessionmaker, declarative_base, relationship, Session

# ---------------------------------------------------------------------
# FastAPI + DB setup
# ---------------------------------------------------------------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE_URL = f"sqlite:///{os.path.join(BASE_DIR, 'rmm.db')}"

engine = create_engine(
    DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

app = FastAPI(title="Nexivo RMM")

# Static + templates
static_dir = os.path.join(BASE_DIR, "static")
templates_dir = os.path.join(BASE_DIR, "templates")

if not os.path.isdir(static_dir):
    os.makedirs(static_dir, exist_ok=True)
if not os.path.isdir(templates_dir):
    os.makedirs(templates_dir, exist_ok=True)

app.mount("/static", StaticFiles(directory=static_dir), name="static")
templates = Jinja2Templates(directory=templates_dir)


# ---------------------------------------------------------------------
# DB Models
# ---------------------------------------------------------------------


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

    agent_tag = Column(String(200), nullable=True)  # for grouping or friendly name
    notes = Column(Text, nullable=True)

    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True)
    client = relationship("Client", back_populates="agents")


Base.metadata.create_all(bind=engine)


# ---------------------------------------------------------------------
# Dependency
# ---------------------------------------------------------------------


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------


def mark_agent_status(agent: Agent):
    """Set agent.online/offline based on last_checkin."""
    if not agent.last_checkin:
        agent.status = "offline"
        return

    # If we haven’t seen it for 5 minutes, call it offline
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


# ---------------------------------------------------------------------
# Dashboard routes (HTML)
# ---------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db)):
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
        },
    )


# ---------------------------------------------------------------------
# Client CRUD (HTML)
# ---------------------------------------------------------------------


@app.get("/clients/new", response_class=HTMLResponse)
async def new_client(request: Request):
    return templates.TemplateResponse(
        "client_form.html",
        {
            "request": request,
            "mode": "create",
            "client": None,
        },
    )


@app.post("/clients/create")
async def create_client(
    name: str = Form(...),
    company: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
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
    client_id: int, request: Request, db: Session = Depends(get_db)
):
    client = get_client_or_404(db, client_id)
    for a in client.agents:
        mark_agent_status(a)

    return templates.TemplateResponse(
        "client_detail.html",
        {
            "request": request,
            "client": client,
        },
    )


@app.get("/clients/{client_id}/edit", response_class=HTMLResponse)
async def edit_client(
    client_id: int, request: Request, db: Session = Depends(get_db)
):
    client = get_client_or_404(db, client_id)
    return templates.TemplateResponse(
        "client_form.html",
        {
            "request": request,
            "mode": "edit",
            "client": client,
        },
    )


@app.post("/clients/{client_id}/update")
async def update_client(
    client_id: int,
    name: str = Form(...),
    company: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
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
async def delete_client(client_id: int, db: Session = Depends(get_db)):
    client = get_client_or_404(db, client_id)
    db.delete(client)
    db.commit()
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)


# ---------------------------------------------------------------------
# Agent CRUD (HTML)
# ---------------------------------------------------------------------


@app.get("/agents/new", response_class=HTMLResponse)
async def new_agent(
    request: Request,
    client_id: int | None = None,
    db: Session = Depends(get_db),
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
        },
    )


@app.post("/agents/create")
async def create_agent(
    hostname: str = Form(...),
    username: str = Form(""),
    agent_tag: str = Form(""),
    notes: str = Form(""),
    client_id: int | None = Form(None),
    db: Session = Depends(get_db),
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
    agent_id: int, request: Request, db: Session = Depends(get_db)
):
    agent = get_agent_or_404(db, agent_id)
    mark_agent_status(agent)

    return templates.TemplateResponse(
        "agent_detail.html",
        {
            "request": request,
            "agent": agent,
        },
    )


@app.get("/agents/{agent_id}/edit", response_class=HTMLResponse)
async def edit_agent(
    agent_id: int, request: Request, db: Session = Depends(get_db)
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
        },
    )


@app.post("/agents/{agent_id}/update")
async def update_agent(
    agent_id: int,
    hostname: str = Form(...),
    username: str = Form(""),
    agent_tag: str = Form(""),
    notes: str = Form(""),
    client_id: int | None = Form(None),
    db: Session = Depends(get_db),
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
async def delete_agent(agent_id: int, db: Session = Depends(get_db)):
    agent = get_agent_or_404(db, agent_id)
    db.delete(agent)
    db.commit()
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)


# ---------------------------------------------------------------------
# Agent API – “Step 2” beefed-up check-in endpoint
# ---------------------------------------------------------------------


@app.post("/api/agents/checkin")
async def agent_checkin(payload: dict, db: Session = Depends(get_db)):
    """
    Agent posts a JSON payload with system info.
    If 'agent_id' is present, update that agent.
    Otherwise, find/create by hostname.
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
# Simple health check
# ---------------------------------------------------------------------


@app.get("/health")
async def health():
    return {"status": "ok", "time": datetime.utcnow().isoformat()}


# ---------------------------------------------------------------------
# Uvicorn entry point for bare-metal runs
# (Docker still uses: uvicorn main:app --host 0.0.0.0 --port 8000)
# ---------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
