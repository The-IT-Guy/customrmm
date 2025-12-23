from __future__ import annotations
from sqlalchemy.orm import Session
from app import crud, models
from app.settings import settings
from datetime import datetime, timedelta

CPU_CRITICAL = 95
CPU_WARNING = 90
RAM_CRITICAL = 95
RAM_WARNING = 90
DISK_CRITICAL = 95
DISK_WARNING = 90

def evaluate_device_metrics(db: Session, device: models.Device) -> None:
    # prevent duplicate spam: only create if last same kind within 10 minutes doesn't exist unresolved
    def recent_unresolved(kind: str) -> bool:
        # naive check: scan latest 50 alerts for device
        alerts = crud.list_alerts(db, org_id=device.org_id, device_id=device.id, limit=50)
        for a in alerts:
            if a.kind == kind and not a.is_resolved:
                # if created in last 10 min, skip
                if a.created_at and (datetime.utcnow() - a.created_at) < timedelta(minutes=10):
                    return True
        return False

    if device.cpu_percent is not None:
        if device.cpu_percent >= CPU_CRITICAL and not recent_unresolved("cpu_high"):
            crud.create_alert(db, device.org_id, device.id, "cpu_high", "critical",
                              f"CPU critical: {device.cpu_percent}%",
                              "CPU utilization exceeded critical threshold.")
        elif device.cpu_percent >= CPU_WARNING and not recent_unresolved("cpu_high"):
            crud.create_alert(db, device.org_id, device.id, "cpu_high", "warning",
                              f"CPU high: {device.cpu_percent}%",
                              "CPU utilization exceeded warning threshold.")

    if device.ram_percent is not None:
        if device.ram_percent >= RAM_CRITICAL and not recent_unresolved("ram_high"):
            crud.create_alert(db, device.org_id, device.id, "ram_high", "critical",
                              f"RAM critical: {device.ram_percent}%",
                              "Memory utilization exceeded critical threshold.")
        elif device.ram_percent >= RAM_WARNING and not recent_unresolved("ram_high"):
            crud.create_alert(db, device.org_id, device.id, "ram_high", "warning",
                              f"RAM high: {device.ram_percent}%",
                              "Memory utilization exceeded warning threshold.")

    if device.disk_percent is not None:
        if device.disk_percent >= DISK_CRITICAL and not recent_unresolved("disk_high"):
            crud.create_alert(db, device.org_id, device.id, "disk_high", "critical",
                              f"Disk critical: {device.disk_percent}%",
                              "Disk utilization exceeded critical threshold.")
        elif device.disk_percent >= DISK_WARNING and not recent_unresolved("disk_high"):
            crud.create_alert(db, device.org_id, device.id, "disk_high", "warning",
                              f"Disk high: {device.disk_percent}%",
                              "Disk utilization exceeded warning threshold.")

def evaluate_offline_devices(db: Session, devices: list[models.Device]) -> int:
    # Creates offline alerts for devices whose last_seen is older than threshold
    from app.security import minutes_ago
    cutoff = minutes_ago(settings.DEVICE_OFFLINE_MINUTES).replace(tzinfo=None)
    created = 0

    for d in devices:
        if d.last_seen_at is None:
            continue
        if d.last_seen_at < cutoff:
            # if already has unresolved offline in last hour, skip
            alerts = crud.list_alerts(db, org_id=d.org_id, device_id=d.id, limit=50)
            skip = False
            for a in alerts:
                if a.kind == "offline" and not a.is_resolved and a.created_at and (datetime.utcnow() - a.created_at) < timedelta(hours=1):
                    skip = True
                    break
            if skip:
                continue
            crud.create_alert(db, d.org_id, d.id, "offline", "critical",
                              f"Device offline: {d.hostname}",
                              f"No check-in within {settings.DEVICE_OFFLINE_MINUTES} minutes.")
            created += 1
    return created
