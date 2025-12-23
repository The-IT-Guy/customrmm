from __future__ import annotations
from pydantic import BaseModel, Field, EmailStr
from typing import Optional, Literal

class SetupAdminIn(BaseModel):
    org_name: str = Field(min_length=2, max_length=200)
    full_name: str = Field(min_length=2, max_length=255)
    email: EmailStr
    password: str = Field(min_length=10, max_length=200)

class LoginIn(BaseModel):
    email: EmailStr
    password: str
    totp_code: Optional[str] = None

class ClientIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    contact_name: Optional[str] = Field(default=None, max_length=200)
    contact_email: Optional[EmailStr] = None
    contact_phone: Optional[str] = Field(default=None, max_length=50)
    notes: Optional[str] = None

class DeviceCreateIn(BaseModel):
    client_id: int
    hostname: str = Field(min_length=1, max_length=255)
    display_name: Optional[str] = Field(default=None, max_length=255)

class DeviceEnrollOut(BaseModel):
    device_id: int
    enroll_token: str
    enroll_command: str

class AgentRegisterIn(BaseModel):
    enroll_token: str
    hostname: str
    os: Optional[str] = None
    arch: Optional[str] = None
    agent_version: Optional[str] = None
    ip_address: Optional[str] = None

class AgentRegisterOut(BaseModel):
    device_id: int
    device_key: str
    poll_seconds: int = 30

class AgentCheckinIn(BaseModel):
    cpu_percent: int = Field(ge=0, le=100)
    ram_percent: int = Field(ge=0, le=100)
    disk_percent: int = Field(ge=0, le=100)
    uptime_seconds: int = Field(ge=0)
    ip_address: Optional[str] = None
    os: Optional[str] = None
    arch: Optional[str] = None
    agent_version: Optional[str] = None

class AgentCheckinOut(BaseModel):
    ok: bool = True

class TaskCreateIn(BaseModel):
    device_id: int
    kind: Literal["shell", "powershell", "python", "url"] = "shell"
    command: str = Field(min_length=1)
    timeout_seconds: int = Field(default=120, ge=5, le=3600)

class AgentTaskOut(BaseModel):
    task_id: int
    kind: str
    command: str
    timeout_seconds: int

class AgentTaskResultIn(BaseModel):
    task_id: int
    exit_code: int
    output: Optional[str] = None
