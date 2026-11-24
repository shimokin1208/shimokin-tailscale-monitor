#!/usr/bin/env bash
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "请使用 root 执行：bash install.sh"
  exit 1
fi

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="/opt/shimokin-monitor"
CONFIG_DIR="/etc/shimokin-monitor"
SERVICE_FILE="/etc/systemd/system/shimokin-monitor.service"

if ! command -v tailscale >/dev/null 2>&1; then
  echo "错误：未检测到 tailscale，请先安装并登录 Tailscale。"
  exit 1
fi
if ! tailscale status >/dev/null 2>&1; then
  echo "错误：Tailscale 尚未连接，请先执行 tailscale up。"
  exit 1
fi
if ! command -v python3 >/dev/null 2>&1; then
  apt-get update
  apt-get install -y python3
fi

install -d -m 755 "$APP_DIR" "$CONFIG_DIR"
if [ "$REPO_DIR" != "$APP_DIR" ] && [ -d "$REPO_DIR/.git" ]; then
  rm -rf "$APP_DIR/.git"
  cp -a "$REPO_DIR/.git" "$APP_DIR/.git"
fi
install -m 644 "$REPO_DIR/monitor.py" "$APP_DIR/monitor.py"
install -m 644 "$REPO_DIR/index.html" "$APP_DIR/index.html"

if [ ! -f "$CONFIG_DIR/config.json" ]; then
  install -m 600 "$REPO_DIR/config.example.json" "$CONFIG_DIR/config.json"
  echo "已创建默认配置：$CONFIG_DIR/config.json"
else
  chmod 600 "$CONFIG_DIR/config.json"
  echo "保留现有配置：$CONFIG_DIR/config.json"
fi

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
ReadWritePaths=/etc/shimokin-monitor

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable --now shimokin-monitor
echo
echo "安装完成。"
echo "状态：systemctl status shimokin-monitor"
echo "日志：journalctl -u shimokin-monitor -f"
echo "配置：nano /etc/shimokin-monitor/config.json"
