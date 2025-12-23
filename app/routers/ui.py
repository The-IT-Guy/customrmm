from __future__ import annotations
from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.db import get_db
from app import crud
from app.auth import get_current_user, verify_login, set_session, clear_session
from app.settings import settings
from app.rate_limit import RateLimiter
import pyotp

templates = Jinja2Templates(directory="app/templates")
router = APIRouter()

limiter = RateLimiter(settings.LOGIN_RATE_LIMIT_PER_MIN)

def require_user(db: Session, request: Request):
    user = get_current_user(db, request)
    return user

@router.get("/", response_class=HTMLResponse)
def root(request: Request, db: Session = Depends(get_db)):
    # If no users exist -> setup-admin
    if not crud.has_any_users(db):
        return RedirectResponse("/setup-admin", status_code=302)

    user = require_user(db, request)
    if not user:
        return RedirectResponse("/login", status_code=302)
    return RedirectResponse("/dashboard", status_code=302)

@router.get("/setup-admin", response_class=HTMLResponse)
def setup_admin_get(request: Request, db: Session = Depends(get_db)):
    if crud.has_any_users(db):
        return RedirectResponse("/login", status_code=302)
    return templates.TemplateResponse("setup_admin.html", {"request": request, "app_name": settings.APP_NAME, "error": None})

@router.post("/setup-admin", response_class=HTMLResponse)
def setup_admin_post(
    request: Request,
    org_name: str = Form(...),
    full_name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    if crud.has_any_users(db):
        return RedirectResponse("/login", status_code=302)

    if len(password) < settings.PASSWORD_MIN_LEN:
        return templates.TemplateResponse("setup_admin.html", {"request": request, "app_name": settings.APP_NAME, "error": f"Password must be at least {settings.PASSWORD_MIN_LEN} characters."})

    user = crud.create_org_and_admin(db, org_name, full_name, email, password)
    resp = RedirectResponse("/dashboard", status_code=302)
    set_session(resp, user.id)
    return resp

@router.get("/login", response_class=HTMLResponse)
def login_get(request: Request, db: Session = Depends(get_db)):
    if not crud.has_any_users(db):
        return RedirectResponse("/setup-admin", status_code=302)
    user = require_user(db, request)
    if user:
        return RedirectResponse("/dashboard", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request, "app_name": settings.APP_NAME, "error": None})

@router.post("/login", response_class=HTMLResponse)
def login_post(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    totp_code: str = Form(default=""),
    db: Session = Depends(get_db),
):
    ip = request.client.host if request.client else "unknown"
    if not limiter.allow(f"login:{ip}"):
        return templates.TemplateResponse("login.html", {"request": request, "app_name": settings.APP_NAME, "error": "Too many login attempts. Try again in a minute."})

    user = verify_login(db, email, password, totp_code.strip() or None)
    if not user:
        return templates.TemplateResponse("login.html", {"request": request, "app_name": settings.APP_NAME, "error": "Invalid credentials (or TOTP required)."})

    user.last_login_at = __import__("datetime").datetime.utcnow()
    db.commit()

    resp = RedirectResponse("/dashboard", status_code=302)
    set_session(resp, user.id)
    return resp

@router.get("/logout")
def logout(request: Request, db: Session = Depends(get_db)):
    resp = RedirectResponse("/login", status_code=302)
    clear_session(resp)
    return resp

@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    user = require_user(db, request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    clients = crud.list_clients(db, user.org_id)
    devices = crud.list_devices(db, user.org_id)
    alerts = crud.list_alerts(db, user.org_id, limit=20)
    tasks = crud.list_tasks(db, user.org_id, limit=10)

    # status calculation
    from datetime import datetime, timedelta
    cutoff = datetime.utcnow() - timedelta(minutes=settings.DEVICE_OFFLINE_MINUTES)
    for d in devices:
        d._status = "Online" if d.last_seen_at and d.last_seen_at >= cutoff else "Offline"

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "app_name": settings.APP_NAME,
        "user": user,
        "clients": clients,
        "devices": devices,
        "alerts": alerts,
        "tasks": tasks,
        "offline_minutes": settings.DEVICE_OFFLINE_MINUTES,
    })

@router.get("/clients", response_class=HTMLResponse)
def clients_list(request: Request, db: Session = Depends(get_db)):
    user = require_user(db, request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    clients = crud.list_clients(db, user.org_id)
    return templates.TemplateResponse("clients.html", {"request": request, "app_name": settings.APP_NAME, "user": user, "clients": clients, "error": None})

@router.post("/clients/create", response_class=HTMLResponse)
def clients_create(
    request: Request,
    name: str = Form(...),
    contact_name: str = Form(default=""),
    contact_email: str = Form(default=""),
    contact_phone: str = Form(default=""),
    notes: str = Form(default=""),
    db: Session = Depends(get_db),
):
    user = require_user(db, request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    name = name.strip()
    if len(name) < 2:
        clients = crud.list_clients(db, user.org_id)
        return templates.TemplateResponse("clients.html", {"request": request, "app_name": settings.APP_NAME, "user": user, "clients": clients, "error": "Client name must be at least 2 characters."})

    try:
        crud.create_client(db, user.org_id, {
            "name": name,
            "contact_name": contact_name.strip() or None,
            "contact_email": contact_email.strip() or None,
            "contact_phone": contact_phone.strip() or None,
            "notes": notes.strip() or None,
        })
    except Exception:
        db.rollback()
        clients = crud.list_clients(db, user.org_id)
        return templates.TemplateResponse("clients.html", {"request": request, "app_name": settings.APP_NAME, "user": user, "clients": clients, "error": "Client already exists (or database error)."})

    return RedirectResponse("/clients", status_code=302)

@router.get("/clients/{client_id}", response_class=HTMLResponse)
def client_detail(request: Request, client_id: int, db: Session = Depends(get_db)):
    user = require_user(db, request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    client = crud.get_client(db, user.org_id, client_id)
    if not client:
        return RedirectResponse("/clients", status_code=302)

    devices = crud.list_devices(db, user.org_id, client_id=client.id)
    return templates.TemplateResponse("client_detail.html", {"request": request, "app_name": settings.APP_NAME, "user": user, "client": client, "devices": devices, "error": None})

@router.post("/clients/{client_id}/update", response_class=HTMLResponse)
def client_update(
    request: Request,
    client_id: int,
    name: str = Form(...),
    contact_name: str = Form(default=""),
    contact_email: str = Form(default=""),
    contact_phone: str = Form(default=""),
    notes: str = Form(default=""),
    db: Session = Depends(get_db),
):
    user = require_user(db, request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    client = crud.get_client(db, user.org_id, client_id)
    if not client:
        return RedirectResponse("/clients", status_code=302)

    name = name.strip()
    if len(name) < 2:
        devices = crud.list_devices(db, user.org_id, client_id=client.id)
        return templates.TemplateResponse("client_detail.html", {"request": request, "app_name": settings.APP_NAME, "user": user, "client": client, "devices": devices, "error": "Client name must be at least 2 characters."})

    try:
        crud.update_client(db, client, {
            "name": name,
            "contact_name": contact_name.strip() or None,
            "contact_email": contact_email.strip() or None,
            "contact_phone": contact_phone.strip() or None,
            "notes": notes.strip() or None,
        })
    except Exception:
        db.rollback()
        devices = crud.list_devices(db, user.org_id, client_id=client.id)
        return templates.TemplateResponse("client_detail.html", {"request": request, "app_name": settings.APP_NAME, "user": user, "client": client, "devices": devices, "error": "Update failed (duplicate name or database error)."})

    return RedirectResponse(f"/clients/{client.id}", status_code=302)

@router.post("/clients/{client_id}/delete", response_class=HTMLResponse)
def client_delete(request: Request, client_id: int, db: Session = Depends(get_db)):
    user = require_user(db, request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    client = crud.get_client(db, user.org_id, client_id)
    if client:
        crud.delete_client(db, client)
    return RedirectResponse("/clients", status_code=302)

@router.get("/devices", response_class=HTMLResponse)
def devices_list(request: Request, db: Session = Depends(get_db)):
    user = require_user(db, request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    devices = crud.list_devices(db, user.org_id)
    clients = crud.list_clients(db, user.org_id)

    from datetime import datetime, timedelta
    cutoff = datetime.utcnow() - timedelta(minutes=settings.DEVICE_OFFLINE_MINUTES)
    for d in devices:
        d._status = "Online" if d.last_seen_at and d.last_seen_at >= cutoff else "Offline"

    return templates.TemplateResponse("devices.html", {"request": request, "app_name": settings.APP_NAME, "user": user, "devices": devices, "clients": clients, "error": None})

@router.post("/devices/create", response_class=HTMLResponse)
def device_create(
    request: Request,
    client_id: int = Form(...),
    hostname: str = Form(...),
    display_name: str = Form(default=""),
    db: Session = Depends(get_db),
):
    user = require_user(db, request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    client = crud.get_client(db, user.org_id, int(client_id))
    if not client:
        devices = crud.list_devices(db, user.org_id)
        clients = crud.list_clients(db, user.org_id)
        return templates.TemplateResponse("devices.html", {"request": request, "app_name": settings.APP_NAME, "user": user, "devices": devices, "clients": clients, "error": "Invalid client selected."})

    d = crud.create_device(db, user.org_id, client.id, hostname, display_name.strip() or None)
    return RedirectResponse(f"/devices/{d.id}", status_code=302)

@router.get("/devices/{device_id}", response_class=HTMLResponse)
def device_detail(request: Request, device_id: int, db: Session = Depends(get_db)):
    user = require_user(db, request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    device = crud.get_device(db, user.org_id, device_id)
    if not device:
        return RedirectResponse("/devices", status_code=302)

    client = crud.get_client(db, user.org_id, device.client_id)
    alerts = crud.list_alerts(db, user.org_id, device_id=device.id, limit=50)
    tasks = crud.list_tasks(db, user.org_id, device_id=device.id, limit=50)

    enroll_cmd = None
    if device.enroll_token:
        enroll_cmd = f"python3 agent.py --server {settings.BASE_URL} --enroll-token {device.enroll_token} --once"

    return templates.TemplateResponse("device_detail.html", {
        "request": request,
        "app_name": settings.APP_NAME,
        "user": user,
        "device": device,
        "client": client,
        "alerts": alerts,
        "tasks": tasks,
        "enroll_cmd": enroll_cmd,
        "base_url": settings.BASE_URL,
        "error": None,
    })

@router.post("/devices/{device_id}/regen-token", response_class=HTMLResponse)
def device_regen_token(request: Request, device_id: int, db: Session = Depends(get_db)):
    user = require_user(db, request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    device = crud.get_device(db, user.org_id, device_id)
    if device:
        crud.regen_enroll_token(db, device)
    return RedirectResponse(f"/devices/{device_id}", status_code=302)

@router.post("/alerts/{alert_id}/resolve", response_class=HTMLResponse)
def alert_resolve(request: Request, alert_id: int, db: Session = Depends(get_db)):
    user = require_user(db, request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    crud.resolve_alert(db, user.org_id, alert_id)
    # send back to referer
    ref = request.headers.get("referer") or "/dashboard"
    return RedirectResponse(ref, status_code=302)

@router.get("/tasks", response_class=HTMLResponse)
def tasks_list(request: Request, db: Session = Depends(get_db)):
    user = require_user(db, request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    tasks = crud.list_tasks(db, user.org_id, limit=200)
    devices = crud.list_devices(db, user.org_id)
    return templates.TemplateResponse("tasks.html", {"request": request, "app_name": settings.APP_NAME, "user": user, "tasks": tasks, "devices": devices, "error": None})

@router.post("/tasks/create", response_class=HTMLResponse)
def tasks_create(
    request: Request,
    device_id: int = Form(...),
    kind: str = Form(...),
    command: str = Form(...),
    timeout_seconds: int = Form(default=120),
    db: Session = Depends(get_db),
):
    user = require_user(db, request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    device = crud.get_device(db, user.org_id, int(device_id))
    if not device:
        tasks = crud.list_tasks(db, user.org_id, limit=200)
        devices = crud.list_devices(db, user.org_id)
        return templates.TemplateResponse("tasks.html", {"request": request, "app_name": settings.APP_NAME, "user": user, "tasks": tasks, "devices": devices, "error": "Invalid device selected."})

    kind = (kind or "shell").strip().lower()
    if kind not in ("shell", "powershell", "python", "url"):
        kind = "shell"

    crud.create_task(db, user.org_id, device.id, kind, command, int(timeout_seconds))
    return RedirectResponse("/tasks", status_code=302)

@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, db: Session = Depends(get_db)):
    user = require_user(db, request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    totp_uri = None
    if user.totp_enabled and user.totp_secret:
        totp_uri = pyotp.totp.TOTP(user.totp_secret).provisioning_uri(name=user.email, issuer_name=settings.APP_NAME)

    return templates.TemplateResponse("settings.html", {"request": request, "app_name": settings.APP_NAME, "user": user, "totp_uri": totp_uri, "error": None})

@router.post("/settings/enable-totp", response_class=HTMLResponse)
def enable_totp(request: Request, db: Session = Depends(get_db)):
    user = require_user(db, request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    if not user.totp_enabled:
        user.totp_secret = pyotp.random_base32()
        user.totp_enabled = True
        db.commit()

    return RedirectResponse("/settings", status_code=302)

@router.post("/settings/disable-totp", response_class=HTMLResponse)
def disable_totp(request: Request, totp_code: str = Form(default=""), db: Session = Depends(get_db)):
    user = require_user(db, request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    if user.totp_enabled and user.totp_secret:
        if not totp_code.strip():
            return templates.TemplateResponse("settings.html", {"request": request, "app_name": settings.APP_NAME, "user": user, "totp_uri": None, "error": "TOTP code required to disable."})
        totp = pyotp.TOTP(user.totp_secret)
        if not totp.verify(totp_code.strip(), valid_window=1):
            return templates.TemplateResponse("settings.html", {"request": request, "app_name": settings.APP_NAME, "user": user, "totp_uri": None, "error": "Invalid TOTP code."})
        user.totp_enabled = False
        user.totp_secret = None
        db.commit()

    return RedirectResponse("/settings", status_code=302)
