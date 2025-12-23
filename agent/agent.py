#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
import os
import platform
import socket
import sys
import time
from dataclasses import dataclass

import httpx
import psutil

AGENT_VERSION = "0.1.0-alpha"
DEFAULT_POLL_SECONDS = 30

def hostname() -> str:
    try:
        return socket.gethostname()
    except Exception:
        return platform.node() or "unknown"

def primary_ip() -> str | None:
    # best-effort without external calls
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return None

def get_metrics() -> dict:
    cpu = int(psutil.cpu_percent(interval=0.5))
    vm = psutil.virtual_memory()
    ram = int(vm.percent)
    disk = psutil.disk_usage(os.path.abspath(os.sep))
    diskp = int(disk.percent)

    # uptime
    boot = psutil.boot_time()
    uptime = int(time.time() - boot)

    return {
        "cpu_percent": cpu,
        "ram_percent": ram,
        "disk_percent": diskp,
        "uptime_seconds": uptime,
        "ip_address": primary_ip(),
        "os": f"{platform.system()} {platform.release()}",
        "arch": platform.machine(),
        "agent_version": AGENT_VERSION,
    }

@dataclass
class AgentState:
    server: str
    enroll_token: str | None
    device_key_path: str
    device_key: str | None = None

    def load_key(self):
        if os.path.exists(self.device_key_path):
            try:
                self.device_key = open(self.device_key_path, "r", encoding="utf-8").read().strip()
            except Exception:
                self.device_key = None

    def save_key(self, key: str):
        os.makedirs(os.path.dirname(self.device_key_path) or ".", exist_ok=True)
        with open(self.device_key_path, "w", encoding="utf-8") as f:
            f.write(key.strip())
        self.device_key = key.strip()

def post_register(state: AgentState) -> tuple[int, str]:
    if not state.enroll_token:
        return (1, "Missing enroll token. Provide --enroll-token on first run.")
    payload = {
        "enroll_token": state.enroll_token,
        "hostname": hostname(),
        "os": f"{platform.system()} {platform.release()}",
        "arch": platform.machine(),
        "agent_version": AGENT_VERSION,
        "ip_address": primary_ip(),
    }
    url = state.server.rstrip("/") + "/api/agent/register"
    with httpx.Client(timeout=15) as client:
        r = client.post(url, json=payload)
        if r.status_code != 200:
            return (2, f"Register failed: {r.status_code} {r.text}")
        data = r.json()
        key = data.get("device_key")
        if not key:
            return (3, "Register response missing device_key")
        state.save_key(key)
        return (0, "Registered OK")

def post_checkin(state: AgentState) -> tuple[int, str]:
    if not state.device_key:
        return (1, "Missing device key. Enroll first.")
    payload = get_metrics()
    url = state.server.rstrip("/") + "/api/agent/checkin"
    headers = {"X-Device-Key": state.device_key}
    with httpx.Client(timeout=15) as client:
        r = client.post(url, json=payload, headers=headers)
        if r.status_code != 200:
            return (2, f"Check-in failed: {r.status_code} {r.text}")
        return (0, "Check-in OK")

def poll_task(state: AgentState) -> dict | None:
    url = state.server.rstrip("/") + "/api/agent/tasks/next"
    headers = {"X-Device-Key": state.device_key}
    with httpx.Client(timeout=15) as client:
        r = client.get(url, headers=headers)
        if r.status_code != 200:
            return None
        if r.text.strip() in ("null", ""):
            return None
        data = r.json()
        return data if data else None

def run_task(task: dict) -> tuple[int, str]:
    # Alpha task runner: shell/python/url (best-effort cross-platform)
    kind = (task.get("kind") or "shell").lower()
    cmd = task.get("command") or ""
    timeout = int(task.get("timeout_seconds") or 120)

    if kind == "url":
        try:
            with httpx.Client(timeout=timeout) as client:
                r = client.get(cmd)
                return (0 if r.status_code < 400 else 1, f"HTTP {r.status_code}\n{r.text[:5000]}")
        except Exception as e:
            return (1, f"URL task failed: {e}")

    import subprocess
    try:
        if kind == "powershell" and platform.system().lower().startswith("win"):
            p = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", cmd],
                               capture_output=True, text=True, timeout=timeout)
        elif kind == "python":
            p = subprocess.run([sys.executable, "-c", cmd], capture_output=True, text=True, timeout=timeout)
        else:
            # shell
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, shell=True)
        out = (p.stdout or "") + (("\n" + p.stderr) if p.stderr else "")
        return (int(p.returncode), out[:100000])
    except subprocess.TimeoutExpired:
        return (124, f"Task timed out after {timeout}s")
    except Exception as e:
        return (1, f"Task execution failed: {e}")

def post_task_result(state: AgentState, task_id: int, exit_code: int, output: str):
    url = state.server.rstrip("/") + "/api/agent/tasks/result"
    headers = {"X-Device-Key": state.device_key}
    payload = {"task_id": task_id, "exit_code": int(exit_code), "output": output}
    with httpx.Client(timeout=15) as client:
        client.post(url, json=payload, headers=headers)

def main():
    ap = argparse.ArgumentParser(description="CustomRMM Alpha Agent")
    ap.add_argument("--server", required=True, help="Server base URL, e.g. http://rmm.example.com:8000")
    ap.add_argument("--enroll-token", default=None, help="Enrollment token (first run only)")
    ap.add_argument("--device-key-path", default=None, help="Where to store device key")
    ap.add_argument("--interval", type=int, default=DEFAULT_POLL_SECONDS, help="Seconds between loops")
    ap.add_argument("--once", action="store_true", help="Enroll/check-in once and exit")
    args = ap.parse_args()

    # default key path by OS
    if args.device_key_path:
        key_path = args.device_key_path
    else:
        if platform.system().lower().startswith("win"):
            key_path = os.path.join(os.environ.get("PROGRAMDATA", "C:\\ProgramData"), "customrmm", "device.key")
        else:
            key_path = "/var/lib/customrmm/device.key"

    state = AgentState(server=args.server, enroll_token=args.enroll_token, device_key_path=key_path)
    state.load_key()

    if not state.device_key:
        code, msg = post_register(state)
        print(msg)
        if code != 0:
            sys.exit(code)

    code, msg = post_checkin(state)
    print(msg)
    if code != 0:
        sys.exit(code)

    if args.once:
        sys.exit(0)

    # loop: checkin + task poll
    while True:
        try:
            post_checkin(state)
            task = poll_task(state)
            if task and task.get("task_id"):
                task_id = int(task["task_id"])
                exit_code, output = run_task(task)
                post_task_result(state, task_id, exit_code, output)
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"loop error: {e}", file=sys.stderr)
        time.sleep(max(5, int(args.interval)))

if __name__ == "__main__":
    main()
