# CustomRMM Alpha Agent

## Requirements
- Python 3.10+
- pip packages: `psutil`, `httpx`

## One-time enroll + check-in
```bash
python3 agent.py --server http://YOUR_RMM:8000 --enroll-token <TOKEN> --once
```

After enrolling, the device key is stored (Linux default: `/var/lib/customrmm/device.key`).

## Run continuously (poll tasks)
```bash
sudo python3 agent.py --server http://YOUR_RMM:8000 --enroll-token <TOKEN> --interval 30
```

## Linux systemd (example)
Create `/etc/systemd/system/customrmm-agent.service`:
```
[Unit]
Description=CustomRMM Agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 /opt/customrmm/agent.py --server http://YOUR_RMM:8000 --interval 30
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now customrmm-agent
```
