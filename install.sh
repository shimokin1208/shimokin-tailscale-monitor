#!/usr/bin/env bash
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "请使用 root 执行：bash install.sh"; exit 1; }
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="/opt/shimokin-monitor"
CONFIG_DIR="/etc/shimokin-monitor"
DATA_DIR="/var/lib/shimokin-monitor"
SERVICE_FILE="/etc/systemd/system/shimokin-monitor.service"
command -v tailscale >/dev/null 2>&1 || { echo "未检测到 Tailscale"; exit 1; }
tailscale status >/dev/null 2>&1 || { echo "Tailscale 未连接，请先 tailscale up"; exit 1; }
command -v python3 >/dev/null 2>&1 || { apt-get update && apt-get install -y python3; }
install -d -m 755 "$APP_DIR" "$DATA_DIR" "$DATA_DIR/backgrounds"
install -d -m 700 "$CONFIG_DIR"
install -m 644 "$REPO_DIR/monitor.py" "$APP_DIR/monitor.py"
install -m 644 "$REPO_DIR/index.html" "$APP_DIR/index.html"
if [[ ! -f "$CONFIG_DIR/config.json" ]]; then
  install -m 600 "$REPO_DIR/config.example.json" "$CONFIG_DIR/config.json"
fi
python3 - <<'PY'
import json, secrets
from pathlib import Path
p=Path("/etc/shimokin-monitor/config.json")
c=json.loads(p.read_text())
changed=False
if not c.get("admin_password"):
    c["admin_password"]=secrets.token_urlsafe(16)
    changed=True
c.setdefault("backgrounds", [])
if changed:
    p.write_text(json.dumps(c,ensure_ascii=False,indent=2)+"\n")
    p.chmod(0o600)
    print("\n首次管理密码（请立即保存）：")
    print(c["admin_password"])
PY
chmod 600 "$CONFIG_DIR/config.json"
cat > "$SERVICE_FILE" <<'UNIT'
[Unit]
Description=Shimokin Tailscale Monitor
Wants=network-online.target tailscaled.service
After=network-online.target tailscaled.service
StartLimitIntervalSec=0

[Service]
Type=simple
User=root
WorkingDirectory=/opt/shimokin-monitor
ExecStart=/usr/bin/python3 /opt/shimokin-monitor/monitor.py
Restart=always
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=full
ReadWritePaths=/etc/shimokin-monitor /var/lib/shimokin-monitor

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable shimokin-monitor
systemctl restart shimokin-monitor
echo
echo "安装完成。网页：http://服务器公网IP:8765"
echo "服务状态：systemctl status shimokin-monitor"
echo "日志：journalctl -u shimokin-monitor -n 50 --no-pager"
echo "配置：/etc/shimokin-monitor/config.json（邮箱授权码和管理密码均在此）"
