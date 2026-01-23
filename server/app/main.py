from fastapi import FastAPI, Request, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from .database import Base, engine, SessionLocal
from .models import Device, User, AgentToken
from .auth import hash_password, verify_password, create_access_token

Base.metadata.create_all(bind=engine)
app = FastAPI()

templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

@app.on_event("startup")
def seed():
    db = SessionLocal()
    if not db.query(User).first():
        db.add(User(username="admin", password_hash=hash_password("admin123")))
        db.add(AgentToken(token="ALPHA-AGENT-TOKEN"))
        db.commit()
    db.close()

@app.get("/", response_class=HTMLResponse)
def login(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login")
def do_login(username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    u = db.query(User).filter_by(username=username).first()
    if not u or not verify_password(password, u.password_hash):
        return RedirectResponse("/", 302)
    token = create_access_token({"sub": username})
    r = RedirectResponse("/dashboard", 302)
    r.set_cookie("token", token)
    return r

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    devices = db.query(Device).filter(Device.disabled == False).all()
    now = datetime.utcnow()
    alerts = [d for d in devices if (now - d.last_seen) > timedelta(seconds=300)]
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "devices": devices,
        "alerts": alerts
    })
