from __future__ import annotations
import secrets
from datetime import datetime, timedelta, timezone
from passlib.context import CryptContext
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from app.settings import settings

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
_serializer = URLSafeTimedSerializer(settings.SECRET_KEY, salt="customrmm-session")

def hash_password(password: str) -> str:
    return _pwd.hash(password)

def verify_password(password: str, password_hash: str) -> bool:
    return _pwd.verify(password, password_hash)

def new_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)

def sign_session(payload: dict) -> str:
    return _serializer.dumps(payload)

def unsign_session(token: str, max_age_seconds: int = 60 * 60 * 12) -> dict | None:
    try:
        return _serializer.loads(token, max_age=max_age_seconds)
    except (BadSignature, SignatureExpired):
        return None

def utcnow() -> datetime:
    return datetime.now(timezone.utc)

def minutes_ago(m: int) -> datetime:
    return utcnow() - timedelta(minutes=m)
