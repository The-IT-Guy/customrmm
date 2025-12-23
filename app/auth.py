from __future__ import annotations
from fastapi import Request
from sqlalchemy.orm import Session
from app.security import sign_session, unsign_session, verify_password
from app import crud
import pyotp

SESSION_MAX_AGE_SECONDS = 60 * 60 * 12

def set_session(response, user_id: int):
    token = sign_session({"user_id": user_id})
    response.set_cookie(
        key="session",
        value=token,
        httponly=True,
        samesite="lax",
        secure=False,
        max_age=SESSION_MAX_AGE_SECONDS,
        path="/",
    )

def clear_session(response):
    response.delete_cookie(key="session", path="/")

def get_current_user(db: Session, request: Request):
    token = request.cookies.get("session")
    if not token:
        return None
    data = unsign_session(token, max_age_seconds=SESSION_MAX_AGE_SECONDS)
    if not data:
        return None
    user = crud.get_user(db, int(data.get("user_id")))
    return user

def verify_login(db: Session, email: str, password: str, totp_code: str | None):
    user = crud.get_user_by_email(db, email)
    if not user:
        return None
    if not verify_password(password, user.password_hash):
        return None
    if user.totp_enabled:
        if not user.totp_secret or not totp_code:
            return None
        totp = pyotp.TOTP(user.totp_secret)
        if not totp.verify(totp_code, valid_window=1):
            return None
    return user
