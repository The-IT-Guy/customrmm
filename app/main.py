from __future__ import annotations
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from sqlalchemy import select
from app.settings import settings
from app.db import engine, Base, SessionLocal
from app.routers.ui import router as ui_router
from app.routers.agent_api import router as agent_router
from app.models import User, Organization, Device
from app.services.alerts import evaluate_offline_devices
from datetime import datetime, timedelta
import asyncio

app = FastAPI(title=settings.APP_NAME)

app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.include_router(ui_router)
app.include_router(agent_router)

# Create tables for alpha
Base.metadata.create_all(bind=engine)

# Attach org relationship for topbar display in templates
# (Jinja needs user.org; we can lazy-load via query in router, but keep simple here by configuring relationship loading)
# SQLAlchemy will load on access if session is still open; routers keep session open for request lifecycle.

async def offline_alerts_loop():
    # background check every 60 seconds
    while True:
        try:
            db: Session = SessionLocal()
            users_count = db.scalar(select(User.id).limit(1))
            # Only run if system is initialized
            if users_count:
                devices = list(db.scalars(select(Device)))
                evaluate_offline_devices(db, devices)
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass
        finally:
            try:
                db.close()
            except Exception:
                pass
        await asyncio.sleep(60)

@app.on_event("startup")
async def startup_event():
    # start background alert evaluator
    asyncio.create_task(offline_alerts_loop())
