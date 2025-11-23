#!/usr/bin/env python3

import time
import socket
import platform
import requests
import os

SERVER = os.environ.get("RMM_SERVER_URL", "http://localhost:8000")

AGENT_ID_FILE = "/opt/customrmm/agent_id.txt"
HEARTBEAT_INTERVAL = 60  # seconds


def register_agent():
    hostname = socket.gethostname()
    os_name = platform.system()
    os_version = platform.release()

    try:
        ip_address = socket.gethostbyname(hostname)
    except Exception:
        ip_address = "0.0.0.0"

    data = {
        "client_name": os.environ.get("RMM_CLIENT_NAME", "Unknown"),
        "hostname": hostname,
        "os_name": os_name,
        "os_version": os_version,
        "ip_address": ip_address,
        "agent_version": "0.1.0",
    }

    try:
        response = requests.post(f"{SERVER}/api/agents/register", data=data, timeout=10)
        response.raise_for_status()
        agent_id = response.json().get("agent_id")
        if agent_id:
            os.makedirs(os.path.dirname(AGENT_ID_FILE), exist_ok=True)
            with open(AGENT_ID_FILE, "w") as f:
                f.write(str(agent_id))
            print(f"Agent registered with ID {agent_id}")
            return agent_id
    except Exception as e:
        print("Registration failed:", e)

    return None


def load_agent_id():
    if not os.path.exists(AGENT_ID_FILE):
        return None
    try:
        with open(AGENT_ID_FILE, "r") as f:
            return f.read().strip()
    except Exception:
        return None


def heartbeat(agent_id):
    try:
        hostname = socket.gethostname()
        ip_address = socket.gethostbyname(hostname)
    except Exception:
        ip_address = "0.0.0.0"

    try:
        data = {"ip_address": ip_address}
        response = requests.post(
            f"{SERVER}/api/agents/heartbeat/{agent_id}", data=data, timeout=10
        )
        response.raise_for_status()
        print(f"Heartbeat OK for agent {agent_id}")
    except Exception as e:
        print("Heartbeat failed:", e)


def main():
    agent_id = load_agent_id()

    if not agent_id:
        agent_id = register_agent()
        if not agent_id:
            print("Retrying registration in 60 seconds…")
            time.sleep(60)
            return main()

    while True:
        heartbeat(agent_id)
        time.sleep(HEARTBEAT_INTERVAL)


if __name__ == "__main__":
    main()