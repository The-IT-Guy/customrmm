#!/usr/bin/env python3
"""
CustomRMM Agent

- Registers with the RMM server and stores agent_id locally.
- Sends periodic heartbeats.
- Collects:
    * Hostname, OS name/version
    * IP address
    * CPU usage (if psutil available)
    * Memory usage (if psutil available)
    * Disk usage (if psutil available)
    * Basic installed software inventory (best-effort per OS)
- Sends metrics & inventory as extra fields in the heartbeat payload.
  Your current backend ignores these extras but they are ready for
  future server-side enhancements.
"""

import time
import socket
import platform
import requests
import os
import json
import subprocess
from typing import List, Dict, Any

# Optional psutil import for resource metrics
try:
    import psutil  # type: ignore
except ImportError:  # pragma: no cover
    psutil = None

# --------- Configuration ---------

SERVER = os.environ.get("RMM_SERVER_URL", "http://localhost:8000")

# Where we store agent_id and a cached inventory
AGENT_DIR = os.environ.get("RMM_AGENT_DIR", "/opt/customrmm")
AGENT_ID_FILE = os.path.join(AGENT_DIR, "agent_id.txt")
INVENTORY_CACHE_FILE = os.path.join(AGENT_DIR, "software_inventory.json")

HEARTBEAT_INTERVAL = int(os.environ.get("RMM_HEARTBEAT_INTERVAL", "60"))  # seconds
INVENTORY_REFRESH_HOURS = int(os.environ.get("RMM_INVENTORY_REFRESH_HOURS", "12"))

AGENT_VERSION = "0.2.0"


# --------- Helper Functions ---------

def get_hostname_ip() -> (str, str):
    hostname = socket.gethostname()
    try:
        ip_address = socket.gethostbyname(hostname)
    except Exception:
        ip_address = "0.0.0.0"
    return hostname, ip_address


def get_system_info() -> Dict[str, Any]:
    hostname, ip_address = get_hostname_ip()
    return {
        "hostname": hostname,
        "ip_address": ip_address,
        "os_name": platform.system(),
        "os_version": platform.release(),
        "platform": platform.platform(),
        "agent_version": AGENT_VERSION,
    }


def get_resource_usage() -> Dict[str, Any]:
    """
    Best-effort system metrics. If psutil is not installed, returns
    minimal data.
    """
    data: Dict[str, Any] = {}

    if psutil is None:
        # Minimal metrics without psutil
        data["cpu_percent"] = None
        data["memory_percent"] = None
        data["disk_percent"] = None
        return data

    try:
        data["cpu_percent"] = psutil.cpu_percent(interval=0.5)
    except Exception:
        data["cpu_percent"] = None

    try:
        mem = psutil.virtual_memory()
        data["memory_percent"] = mem.percent
        data["memory_total"] = mem.total
        data["memory_available"] = mem.available
    except Exception:
        data["memory_percent"] = None

    try:
        disk = psutil.disk_usage("/")
        data["disk_percent"] = disk.percent
        data["disk_total"] = disk.total
        data["disk_used"] = disk.used
        data["disk_free"] = disk.free
    except Exception:
        data["disk_percent"] = None

    return data


def _linux_installed_software() -> List[Dict[str, str]]:
    """
    Try dpkg then rpm. We limit to first 300 entries to keep payload small.
    """
    results: List[Dict[str, str]] = []

    # Debian/Ubuntu
    try:
        proc = subprocess.run(
            ["dpkg-query", "-W", "-f", "${Package} ${Version}\n"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
        )
        if proc.stdout:
            for line in proc.stdout.splitlines()[:300]:
                parts = line.strip().split(maxsplit=1)
                if not parts:
                    continue
                name = parts[0]
                version = parts[1] if len(parts) > 1 else ""
                results.append({"name": name, "version": version, "source": "dpkg"})
            return results
    except Exception:
        pass

    # RHEL/CentOS/Fedora
    try:
        proc = subprocess.run(
            ["rpm", "-qa", "--qf", "%{NAME} %{VERSION}-%{RELEASE}\n"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
        )
        if proc.stdout:
            for line in proc.stdout.splitlines()[:300]:
                parts = line.strip().split(maxsplit=1)
                if not parts:
                    continue
                name = parts[0]
                version = parts[1] if len(parts) > 1 else ""
                results.append({"name": name, "version": version, "source": "rpm"})
            return results
    except Exception:
        pass

    return results


def _windows_installed_software() -> List[Dict[str, str]]:
    """
    Query basic installed software via registry.
    This is not perfect but gives a decent view.
    """
    results: List[Dict[str, str]] = []
    try:
        import winreg  # type: ignore

        uninstall_keys = [
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
            r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
        ]

        for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            for subkey in uninstall_keys:
                try:
                    key = winreg.OpenKey(root, subkey)
                except OSError:
                    continue

                i = 0
                while True:
                    try:
                        subkey_name = winreg.EnumKey(key, i)
                    except OSError:
                        break
                    i += 1

                    try:
                        app_key = winreg.OpenKey(key, subkey_name)
                        name, _ = winreg.QueryValueEx(app_key, "DisplayName")
                        try:
                            version, _ = winreg.QueryValueEx(app_key, "DisplayVersion")
                        except OSError:
                            version = ""
                        results.append(
                            {
                                "name": str(name),
                                "version": str(version),
                                "source": "registry",
                            }
                        )
                    except OSError:
                        continue

        # Limit payload
        return results[:300]
    except Exception:
        return results


def _macos_installed_software() -> List[Dict[str, str]]:
    """
    Very basic: use system_profiler SPApplicationsDataType if available.
    """
    results: List[Dict[str, str]] = []
    try:
        proc = subprocess.run(
            ["system_profiler", "SPApplicationsDataType", "-json"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
        )
        if proc.stdout:
            data = json.loads(proc.stdout)
            apps = data.get("SPApplicationsDataType", [])
            for app in apps[:300]:
                name = app.get("_name", "")
                version = app.get("version", "")
                results.append({"name": name, "version": version, "source": "system_profiler"})
    except Exception:
        pass
    return results


def get_installed_software() -> List[Dict[str, str]]:
    """
    Cross-platform software inventory (best effort).
    May be slow on some systems; that's why we cache it.
    """
    os_name = platform.system().lower()
    if os_name == "linux":
        return _linux_installed_software()
    elif os_name == "windows":
        return _windows_installed_software()
    elif os_name == "darwin":
        return _macos_installed_software()
    return []


def load_cached_inventory() -> Dict[str, Any]:
    """
    Return cached inventory if it's fresh enough, else {}.
    """
    try:
        if not os.path.exists(INVENTORY_CACHE_FILE):
            return {}
        with open(INVENTORY_CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        ts = data.get("_generated_at")
        if not ts:
            return {}
        age_hours = (time.time() - ts) / 3600.0
        if age_hours > INVENTORY_REFRESH_HOURS:
            return {}
        return data
    except Exception:
        return {}


def generate_and_cache_inventory() -> Dict[str, Any]:
    sw_list = get_installed_software()
    payload = {
        "_generated_at": time.time(),
        "items": sw_list,
    }

    try:
        os.makedirs(AGENT_DIR, exist_ok=True)
        with open(INVENTORY_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f)
    except Exception:
        pass

    return payload


def get_inventory_payload() -> Dict[str, Any]:
    """
    Manage cache + regeneration.
    """
    cached = load_cached_inventory()
    if cached:
        return cached
    return generate_and_cache_inventory()


def load_agent_id() -> str | None:
    if not os.path.exists(AGENT_ID_FILE):
        return None
    try:
        with open(AGENT_ID_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return None


def save_agent_id(agent_id: str) -> None:
    os.makedirs(AGENT_DIR, exist_ok=True)
    with open(AGENT_ID_FILE, "w", encoding="utf-8") as f:
        f.write(str(agent_id))


# --------- RMM Communication ---------

def register_agent() -> str | None:
    info = get_system_info()

    data = {
        "client_name": os.environ.get("RMM_CLIENT_NAME", "Unknown"),
        "hostname": info["hostname"],
        "os_name": info["os_name"],
        "os_version": info["os_version"],
        "ip_address": info["ip_address"],
        "agent_version": AGENT_VERSION,
    }

    try:
        resp = requests.post(
            f"{SERVER}/api/agents/register",
            data=data,
            timeout=15,
        )
        resp.raise_for_status()
        agent_id = resp.json().get("agent_id")
        if agent_id:
            save_agent_id(str(agent_id))
            print(f"[agent] Registered with ID {agent_id}")
            return str(agent_id)
        else:
            print("[agent] Registration response missing agent_id")
    except Exception as exc:
        print("[agent] Registration failed:", exc)

    return None


def heartbeat(agent_id: str) -> None:
    """
    Send heartbeat with metrics & (occasionally) software inventory.
    """
    info = get_system_info()
    metrics = get_resource_usage()

    inventory_payload = get_inventory_payload()
    inventory_json = json.dumps(inventory_payload, separators=(",", ":"))

    payload = {
        "ip_address": info["ip_address"],  # required by current API
        # Extra fields for future server use:
        "hostname": info["hostname"],
        "os_name": info["os_name"],
        "os_version": info["os_version"],
        "platform": info["platform"],
        "agent_version": info["agent_version"],
        "cpu_percent": metrics.get("cpu_percent"),
        "memory_percent": metrics.get("memory_percent"),
        "disk_percent": metrics.get("disk_percent"),
        "inventory_json": inventory_json,
    }

    try:
        resp = requests.post(
            f"{SERVER}/api/agents/heartbeat/{agent_id}",
            data=payload,
            timeout=15,
        )
        resp.raise_for_status()
        print(f"[agent] Heartbeat OK for agent {agent_id}")
    except Exception as exc:
        print("[agent] Heartbeat failed:", exc)


# --------- Main Loop ---------

def main() -> None:
    print("[agent] Starting CustomRMM agent")
    agent_id = load_agent_id()

    if not agent_id:
        print("[agent] No agent_id found, attempting registration…")
        agent_id = register_agent()
        if not agent_id:
            print("[agent] Registration failed, retrying in 60 seconds…")
            time.sleep(60)
            return main()

    while True:
        heartbeat(agent_id)
        time.sleep(HEARTBEAT_INTERVAL)


if __name__ == "__main__":
    main()
