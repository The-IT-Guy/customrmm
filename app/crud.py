from __future__ import annotations
from sqlalchemy.orm import Session
from sqlalchemy import select, func
from app import models
from app.security import hash_password, new_token
from datetime import datetime

def has_any_users(db: Session) -> bool:
    return db.scalar(select(func.count(models.User.id))) > 0

def create_org_and_admin(db: Session, org_name: str, full_name: str, email: str, password: str) -> models.User:
    org = models.Organization(name=org_name.strip())
    db.add(org)
    db.flush()

    user = models.User(
        org_id=org.id,
        email=email.lower().strip(),
        full_name=full_name.strip(),
        password_hash=hash_password(password),
        is_admin=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user

def get_user_by_email(db: Session, email: str) -> models.User | None:
    return db.scalar(select(models.User).where(models.User.email == email.lower().strip()))

def get_user(db: Session, user_id: int) -> models.User | None:
    return db.get(models.User, user_id)

def list_clients(db: Session, org_id: int):
    return list(db.scalars(select(models.Client).where(models.Client.org_id == org_id).order_by(models.Client.name)))

def get_client(db: Session, org_id: int, client_id: int) -> models.Client | None:
    return db.scalar(select(models.Client).where(models.Client.org_id == org_id, models.Client.id == client_id))

def create_client(db: Session, org_id: int, data: dict) -> models.Client:
    c = models.Client(org_id=org_id, **data)
    db.add(c)
    db.commit()
    db.refresh(c)
    return c

def update_client(db: Session, client: models.Client, data: dict) -> models.Client:
    for k, v in data.items():
        setattr(client, k, v)
    db.commit()
    db.refresh(client)
    return client

def delete_client(db: Session, client: models.Client) -> None:
    db.delete(client)
    db.commit()

def list_devices(db: Session, org_id: int, client_id: int | None = None):
    q = select(models.Device).where(models.Device.org_id == org_id)
    if client_id is not None:
        q = q.where(models.Device.client_id == client_id)
    q = q.order_by(models.Device.hostname)
    return list(db.scalars(q))

def get_device(db: Session, org_id: int, device_id: int) -> models.Device | None:
    return db.scalar(select(models.Device).where(models.Device.org_id == org_id, models.Device.id == device_id))

def create_device(db: Session, org_id: int, client_id: int, hostname: str, display_name: str | None):
    d = models.Device(org_id=org_id, client_id=client_id, hostname=hostname.strip(), display_name=(display_name or None))
    # create enrollment token on creation
    d.enroll_token = new_token(24)
    db.add(d)
    db.commit()
    db.refresh(d)
    return d

def regen_enroll_token(db: Session, device: models.Device) -> models.Device:
    device.enroll_token = new_token(24)
    device.device_key = None
    device.enrolled_at = None
    db.commit()
    db.refresh(device)
    return device

def agent_register(db: Session, enroll_token: str, payload: dict) -> models.Device | None:
    d = db.scalar(select(models.Device).where(models.Device.enroll_token == enroll_token))
    if not d:
        return None
    # set device key
    d.device_key = new_token(32)
    d.enrolled_at = datetime.utcnow()
    d.hostname = payload.get("hostname") or d.hostname
    d.os = payload.get("os") or d.os
    d.arch = payload.get("arch") or d.arch
    d.agent_version = payload.get("agent_version") or d.agent_version
    d.ip_address = payload.get("ip_address") or d.ip_address
    d.last_seen_at = datetime.utcnow()
    db.commit()
    db.refresh(d)
    return d

def agent_by_key(db: Session, device_key: str) -> models.Device | None:
    return db.scalar(select(models.Device).where(models.Device.device_key == device_key))

def agent_checkin(db: Session, device: models.Device, payload: dict) -> models.Device:
    device.cpu_percent = int(payload["cpu_percent"])
    device.ram_percent = int(payload["ram_percent"])
    device.disk_percent = int(payload["disk_percent"])
    device.uptime_seconds = int(payload["uptime_seconds"])
    device.ip_address = payload.get("ip_address") or device.ip_address
    device.os = payload.get("os") or device.os
    device.arch = payload.get("arch") or device.arch
    device.agent_version = payload.get("agent_version") or device.agent_version
    device.last_seen_at = datetime.utcnow()
    db.commit()
    db.refresh(device)
    return device

def create_alert(db: Session, org_id: int, device_id: int, kind: str, severity: str, title: str, message: str | None):
    a = models.Alert(org_id=org_id, device_id=device_id, kind=kind, severity=severity, title=title, message=message)
    db.add(a)
    db.commit()
    db.refresh(a)
    return a

def list_alerts(db: Session, org_id: int, device_id: int | None = None, limit: int = 200):
    q = select(models.Alert).where(models.Alert.org_id == org_id)
    if device_id is not None:
        q = q.where(models.Alert.device_id == device_id)
    q = q.order_by(models.Alert.created_at.desc()).limit(limit)
    return list(db.scalars(q))

def resolve_alert(db: Session, org_id: int, alert_id: int) -> models.Alert | None:
    a = db.scalar(select(models.Alert).where(models.Alert.org_id == org_id, models.Alert.id == alert_id))
    if not a:
        return None
    a.is_resolved = True
    a.resolved_at = datetime.utcnow()
    db.commit()
    db.refresh(a)
    return a

def create_task(db: Session, org_id: int, device_id: int, kind: str, command: str, timeout_seconds: int):
    t = models.Task(
        org_id=org_id,
        device_id=device_id,
        kind=kind,
        command=command,
        timeout_seconds=timeout_seconds,
        status="queued",
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return t

def list_tasks(db: Session, org_id: int, device_id: int | None = None, limit: int = 200):
    q = select(models.Task).where(models.Task.org_id == org_id)
    if device_id is not None:
        q = q.where(models.Task.device_id == device_id)
    q = q.order_by(models.Task.created_at.desc()).limit(limit)
    return list(db.scalars(q))

def next_queued_task_for_device(db: Session, device_id: int):
    return db.scalar(
        select(models.Task)
        .where(models.Task.device_id == device_id, models.Task.status == "queued")
        .order_by(models.Task.created_at.asc())
        .limit(1)
    )

def mark_task_dispatched(db: Session, task: models.Task):
    task.status = "dispatched"
    task.dispatched_at = datetime.utcnow()
    db.commit()
    db.refresh(task)
    return task

def complete_task(db: Session, task: models.Task, exit_code: int, output: str | None):
    task.exit_code = int(exit_code)
    task.output = output
    task.completed_at = datetime.utcnow()
    task.status = "succeeded" if exit_code == 0 else "failed"
    db.commit()
    db.refresh(task)
    return task
