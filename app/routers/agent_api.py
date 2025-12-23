from __future__ import annotations
from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session
from app.db import get_db
from app import crud
from app.schemas import AgentRegisterIn, AgentRegisterOut, AgentCheckinIn, AgentCheckinOut, AgentTaskOut, AgentTaskResultIn
from app.services.alerts import evaluate_device_metrics

router = APIRouter(prefix="/api/agent", tags=["agent"])

@router.post("/register", response_model=AgentRegisterOut)
def register(payload: AgentRegisterIn, db: Session = Depends(get_db)):
    d = crud.agent_register(db, payload.enroll_token, payload.model_dump())
    if not d or not d.device_key:
        raise HTTPException(status_code=400, detail="Invalid enroll token")
    return AgentRegisterOut(device_id=d.id, device_key=d.device_key, poll_seconds=30)

@router.post("/checkin", response_model=AgentCheckinOut)
def checkin(
    payload: AgentCheckinIn,
    x_device_key: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    if not x_device_key:
        raise HTTPException(status_code=401, detail="Missing device key")
    device = crud.agent_by_key(db, x_device_key)
    if not device:
        raise HTTPException(status_code=401, detail="Invalid device key")

    device = crud.agent_checkin(db, device, payload.model_dump())
    evaluate_device_metrics(db, device)
    return AgentCheckinOut(ok=True)

@router.get("/tasks/next", response_model=AgentTaskOut | None)
def next_task(
    x_device_key: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    if not x_device_key:
        raise HTTPException(status_code=401, detail="Missing device key")
    device = crud.agent_by_key(db, x_device_key)
    if not device:
        raise HTTPException(status_code=401, detail="Invalid device key")

    t = crud.next_queued_task_for_device(db, device.id)
    if not t:
        return None
    t = crud.mark_task_dispatched(db, t)
    return AgentTaskOut(task_id=t.id, kind=t.kind, command=t.command, timeout_seconds=t.timeout_seconds)

@router.post("/tasks/result")
def task_result(
    payload: AgentTaskResultIn,
    x_device_key: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    if not x_device_key:
        raise HTTPException(status_code=401, detail="Missing device key")
    device = crud.agent_by_key(db, x_device_key)
    if not device:
        raise HTTPException(status_code=401, detail="Invalid device key")

    t = crud.get_device(db, device.org_id, device.id)  # ensure org match exists
    # fetch task by id and ensure it's for device
    from sqlalchemy import select
    from app.models import Task
    task = db.scalar(select(Task).where(Task.id == payload.task_id, Task.device_id == device.id))
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    crud.complete_task(db, task, payload.exit_code, payload.output)
    return {"ok": True}
