import os, socket, platform, time, requests

SERVER = "http://159.198.44.119:8000"
API_KEY = "ALPHA_RMM_KEY_2026"
STATE_DIR = "/var/lib/customrmm"
ID_FILE = f"{STATE_DIR}/agent_id"

os.makedirs(STATE_DIR, exist_ok=True)

def get_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(("8.8.8.8", 80))
    ip = s.getsockname()[0]
    s.close()
    return ip

def get_machine_id():
    return open("/etc/machine-id").read().strip()

headers = {"X-API-Key": API_KEY}

if os.path.exists(ID_FILE):
    agent_id = open(ID_FILE).read().strip()
else:
    r = requests.post(
        f"{SERVER}/agent/register",
        json={
            "machine_id": get_machine_id(),
            "hostname": socket.gethostname(),
            "os": platform.system(),
            "ip": get_ip(),
        },
        headers=headers,
    )
    agent_id = r.json()["agent_id"]
    open(ID_FILE, "w").write(agent_id)

while True:
    try:
        requests.post(
            f"{SERVER}/agent/heartbeat/{agent_id}",
            headers=headers,
        )
    except Exception:
        pass
    time.sleep(60)
