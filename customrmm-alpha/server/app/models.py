from sqlalchemy import Column, Integer, String, DateTime, Boolean
from datetime import datetime
from .database import Base

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True)
    password_hash = Column(String)

class AgentToken(Base):
    __tablename__ = "agent_tokens"
    id = Column(Integer, primary_key=True)
    token = Column(String, unique=True)
    active = Column(Boolean, default=True)

class Device(Base):
    __tablename__ = "devices"
    id = Column(Integer, primary_key=True)
    device_id = Column(String, unique=True)
    hostname = Column(String)
    os = Column(String)
    ip = Column(String)
    cpu = Column(String)
    ram = Column(String)
    disk = Column(String)
    uptime = Column(String)
    last_seen = Column(DateTime, default=datetime.utcnow)
    online = Column(Boolean, default=False)
    disabled = Column(Boolean, default=False)
    agent_version = Column(String, default="0.1.0")
