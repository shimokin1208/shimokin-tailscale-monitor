#!/usr/bin/env python3
import json
import os
import socket
import subprocess
import threading
import time
import smtplib
from datetime import datetime
from email.message import EmailMessage
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

CONFIG_PATH = Path("/etc/shimokin-monitor/config.json")
HTML_PATH = Path(__file__).with_name("index.html")
lock = threading.RLock()
state = {
    "target": "shimokin", "status": "unknown", "failures": 0,
    "interval": 60, "last_check": None, "last_online": None,
    "last_message": "等待首次检测", "events": []
}

def now():
    return datetime.now().astimezone().isoformat(timespec="seconds")

def event(message, kind="info"):
    with lock:
        state["events"].insert(0, {"time": now(), "message": str(message), "kind": kind})
        del state["events"][100:]

def load_config():
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        cfg = json.load(f)
    cfg.setdefault("target", "shimokin")
    cfg.setdefault("interval", 60)
    cfg.setdefault("failure_threshold", 3)
    cfg.setdefault("web_port", 8765)
    cfg.setdefault("smtp", {})
    return cfg

def send_mail(cfg, subject, body):
    mail = cfg.get("smtp", {})
    if not mail.get("enabled") or not mail.get("host") or not mail.get("username") or not mail.get("password") or not mail.get("to_addrs"):
        return
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = mail.get("from_addr") or mail["username"]
    msg["To"] = ", ".join(mail["to_addrs"])
    msg.set_content(body)
    if mail.get("use_ssl", True):
        with smtplib.SMTP_SSL(mail["host"], int(mail.get("port", 465)), timeout=15) as smtp:
            smtp.login(mail["username"], mail["password"])
            smtp.send_message(msg)
    else:
        with smtplib.SMTP(mail["host"], int(mail.get("port", 587)), timeout=15) as smtp:
            smtp.starttls()
            smtp.login(mail["username"], mail["password"])
            smtp.send_message(msg)

def probe(target):
    try:
        result = subprocess.run(
            ["tailscale", "ping", "--timeout=6s", target],
            capture_output=True, text=True, timeout=9
        )
        return result.returncode == 0, (result.stdout or result.stderr).strip()[-300:]
    except Exception as exc:
        return False, str(exc)

def monitor_loop(cfg):
    target = cfg["target"]
    threshold = max(1, int(cfg["failure_threshold"]))
    interval = max(10, int(cfg["interval"]))
    with lock:
        state["target"] = target
        state["interval"] = interval
    event("监控已启动，目标设备：" + target)
    while True:
        ok, detail = probe(target)
        notification = None
        with lock:
            state["last_check"] = now()
            if ok:
                state["failures"] = 0
                state["last_online"] = state["last_check"]
                if state["status"] != "online":
                    previous = state["status"]
                    state["status"] = "online"
                    state["last_message"] = "设备在线"
                    if previous != "unknown":
                        notification = ("【shimokin】设备已恢复在线", f"设备 {target} 已恢复 Tailscale 连通。\n时间：{state['last_check']}")
                    event("设备在线" + ("（恢复连接）" if previous == "offline" else ""), "success")
            else:
                state["failures"] += 1
                state["last_message"] = "检测失败：" + (detail or "无响应")
                if state["failures"] >= threshold and state["status"] != "offline":
                    previous = state["status"]
                    state["status"] = "offline"
                    event(f"设备离线（连续失败 {state['failures']} 次）", "error")
                    if previous != "unknown":
                        notification = ("【shimokin】设备离线告警", f"设备 {target} 已连续检测失败 {state['failures']} 次。\n时间：{state['last_check']}\n详情：{detail}")
        if notification:
            try:
                send_mail(cfg, *notification)
                event("状态变化邮件已发送", "success")
            except Exception as exc:
                event("邮件发送失败：" + str(exc), "error")
        time.sleep(interval)

def get_tailscale_ip():
    while True:
        try:
            result = subprocess.run(["tailscale", "ip", "-4"], capture_output=True, text=True, timeout=5)
            ip = result.stdout.strip().splitlines()[0]
            socket.inet_aton(ip)
            return ip
        except Exception:
            event("等待 Tailscale IPv4 地址...")
            time.sleep(5)

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/status":
            with lock:
                payload = json.dumps(state, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        elif path == "/" or path == "/index.html":
            try:
                payload = HTML_PATH.read_bytes()
            except OSError:
                self.send_error(500, "Dashboard file missing")
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        else:
            self.send_error(404)
    def log_message(self, fmt, *args):
        pass

def main():
    cfg = load_config()
    ip = get_tailscale_ip()
    port = int(cfg["web_port"])
    threading.Thread(target=monitor_loop, args=(cfg,), daemon=True).start()
    server = ThreadingHTTPServer((ip, port), Handler)
    event(f"网页面板监听 http://{ip}:{port}")
    server.serve_forever()

if __name__ == "__main__":
    main()
