from __future__ import annotations
from sqlalchemy import String, Integer, DateTime, Boolean, ForeignKey, Text, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db import Base
from datetime import datetime

class Organization(Base):
    __tablename__ = "organizations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    users = relationship("User", back_populates="org", cascade="all, delete-orphan")
    clients = relationship("Client", back_populates="org", cascade="all, delete-orphan")
    devices = relationship("Device", back_populates="org", cascade="all, delete-orphan")

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(255))
    password_hash: Mapped[str] = mapped_column(String(255))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)

    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    totp_secret: Mapped[str | None] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    org = relationship("Organization", back_populates="users")

class Client(Base):
    __tablename__ = "clients"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    contact_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    org = relationship("Organization", back_populates="clients")
    devices = relationship("Device", back_populates="client", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("org_id", "name", name="uq_client_org_name"),
        Index("ix_client_org_name", "org_id", "name"),
    )

class Device(Base):
    __tablename__ = "devices"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), index=True)

    hostname: Mapped[str] = mapped_column(String(255), index=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    os: Mapped[str | None] = mapped_column(String(255), nullable=True)
    arch: Mapped[str | None] = mapped_column(String(50), nullable=True)
    agent_version: Mapped[str | None] = mapped_column(String(50), nullable=True)

    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Enrollment & auth for agent
    enroll_token: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    device_key: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    enrolled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # last reported metrics
    cpu_percent: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ram_percent: Mapped[int | None] = mapped_column(Integer, nullable=True)
    disk_percent: Mapped[int | None] = mapped_column(Integer, nullable=True)
    uptime_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    org = relationship("Organization", back_populates="devices")
    client = relationship("Client", back_populates="devices")
    alerts = relationship("Alert", back_populates="device", cascade="all, delete-orphan")
    tasks = relationship("Task", back_populates="device", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_device_org_client", "org_id", "client_id"),
    )

class Alert(Base):
    __tablename__ = "alerts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id"), index=True)

    kind: Mapped[str] = mapped_column(String(50))  # cpu_high, ram_high, disk_high, offline, task_failed, custom
    severity: Mapped[str] = mapped_column(String(20), default="warning")  # info, warning, critical
    title: Mapped[str] = mapped_column(String(255))
    message: Mapped[str | None] = mapped_column(Text, nullable=True)

    is_resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    device = relationship("Device", back_populates="alerts")

    __table_args__ = (
        Index("ix_alert_org_created", "org_id", "created_at"),
        Index("ix_alert_device_created", "device_id", "created_at"),
    )

class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id"), index=True)

    kind: Mapped[str] = mapped_column(String(50), default="shell")  # shell, powershell, python, url
    command: Mapped[str] = mapped_column(Text)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=120)

    status: Mapped[str] = mapped_column(String(30), default="queued")  # queued, dispatched, running, succeeded, failed, canceled
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    output: Mapped[str | None] = mapped_column(Text, nullable=True)
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)

    device = relationship("Device", back_populates="tasks")

    __table_args__ = (
        Index("ix_task_device_status", "device_id", "status"),
        Index("ix_task_org_created", "org_id", "created_at"),
    )
