#!/usr/bin/env python3
"""
Minimal agent (demo) that registers and sends heartbeats.

This is included for completeness; production agents should be native installers
and run as a service.

Usage:
  python3 agent.py --server http://rmm.example.com --enroll-key <key> --device-uuid demo-001

After first run, the agent stores its token in ./agent_token.txt (local file).
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import socket
import time
from urllib import request as urlrequest
from urllib.error import URLError, HTTPError

TOKEN_FILE = "agent_token.txt"

def http_json(url: str, method: str, headers: dict, body: dict | None):
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers = {**headers, "Content-Type": "application/json"}
    req = urlrequest.Request(url, data=data, method=method, headers=headers)
    with urlrequest.urlopen(req, timeout=15) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
        return resp.status, json.loads(raw) if raw else {}

def get_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return None

def read_token():
    if os.path.exists(TOKEN_FILE):
        return open(TOKEN_FILE, "r", encoding="utf-8").read().strip() or None
    return None

def write_token(tok: str):
    with open(TOKEN_FILE, "w", encoding="utf-8", newline="\n") as f:
        f.write(tok + "\n")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", required=True, help="Base URL, e.g. http://1.2.3.4 or https://rmm.example.com")
    ap.add_argument("--enroll-key", required=True)
    ap.add_argument("--device-uuid", required=True)
    ap.add_argument("--interval", type=int, default=60)
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args()

    base = args.server.rstrip("/")
    token = read_token()

    if not token:
        payload = {
            "device_uuid": args.device_uuid,
            "hostname": socket.gethostname(),
            "os": f"{platform.system()} {platform.release()}",
            "ip": get_ip(),
            "agent_version": "1.0.0",
        }
        status, resp = http_json(
            f"{base}/api/v1/register",
            "POST",
            headers={"X-ENROLL-KEY": args.enroll_key},
            body=payload,
        )
        token = resp.get("api_token")
        if not token:
            raise SystemExit(f"Register failed: status={status} resp={resp}")
        write_token(token)
        print("Registered. Token saved to agent_token.txt")

    def heartbeat():
        hb = {
            "cpu": 0,
            "mem": 0,
            "disk": 0,
            "uptime_seconds": int(time.time()),
            "ip": get_ip(),
            "hostname": socket.gethostname(),
            "os": f"{platform.system()} {platform.release()}",
            "agent_version": "1.0.0",
            "note": "agent heartbeat",
        }
        status, resp = http_json(
            f"{base}/api/v1/heartbeat",
            "POST",
            headers={"Authorization": f"Bearer {token}"},
            body=hb,
        )
        if status != 200:
            print("Heartbeat failed:", status, resp)
        else:
            print("Heartbeat ok:", resp.get("server_time"))

    heartbeat()
    if args.once:
        return
    while True:
        time.sleep(args.interval)
        heartbeat()

if __name__ == "__main__":
    main()
