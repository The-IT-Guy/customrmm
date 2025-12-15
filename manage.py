#!/usr/bin/env python3
"""
CustomRMM manage utility (no docker)

Examples:
  sudo -u customrmm /opt/customrmm/venv/bin/python /opt/customrmm/manage.py initdb
  sudo -u customrmm /opt/customrmm/venv/bin/python /opt/customrmm/manage.py create-admin --email admin@example.com --password 'StrongPassword123!'
  sudo -u customrmm /opt/customrmm/venv/bin/python /opt/customrmm/manage.py rotate-enroll-key
"""
from __future__ import annotations

import os
import secrets
import argparse

from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import select, func
from main import engine, SessionLocal, init_db, User, hash_password

ENV_PATH = os.getenv("ENV_PATH", "/etc/customrmm/customrmm.env")

def cmd_initdb(_args) -> None:
    init_db()
    print("DB initialized.")

def cmd_create_admin(args) -> None:
    email = args.email.strip().lower()
    password = args.password
    if len(password) < 10:
        raise SystemExit("Password must be at least 10 characters.")
    init_db()
    with SessionLocal() as db:
        exists = db.scalar(select(User).where(User.email == email))
        if exists:
            raise SystemExit("User already exists.")
        u = User(email=email, password_hash=hash_password(password), is_admin=True)
        db.add(u)
        db.commit()
        print(f"Admin created: {email}")

def cmd_rotate_enroll_key(_args) -> None:
    new_key = secrets.token_urlsafe(24)
    # Update environment file in-place (best effort)
    if not os.path.exists(ENV_PATH):
        raise SystemExit(f"Env file not found: {ENV_PATH}")
    lines = open(ENV_PATH, "r", encoding="utf-8").read().splitlines()
    out = []
    replaced = False
    for line in lines:
        if line.startswith("ENROLL_KEY="):
            out.append(f"ENROLL_KEY={new_key}")
            replaced = True
        else:
            out.append(line)
    if not replaced:
        out.append(f"ENROLL_KEY={new_key}")
    with open(ENV_PATH, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(out) + "\n")
    print("ENROLL_KEY rotated. Restart the service: systemctl restart customrmm")
    print(f"New ENROLL_KEY: {new_key}")

def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("initdb")
    s.set_defaults(func=cmd_initdb)

    s = sub.add_parser("create-admin")
    s.add_argument("--email", required=True)
    s.add_argument("--password", required=True)
    s.set_defaults(func=cmd_create_admin)

    s = sub.add_parser("rotate-enroll-key")
    s.set_defaults(func=cmd_rotate_enroll_key)

    args = p.parse_args()
    args.func(args)

if __name__ == "__main__":
    main()
