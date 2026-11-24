#!/usr/bin/env python3
import base64
import json
import os
import re
import secrets
import smtplib
import socket
import subprocess
import threading
import time
from datetime import datetime
from email.message import EmailMessage
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, unquote

CONFIG_PATH = Path("/etc/shimokin-monitor/config.json")
DATA_DIR = Path("/var/lib/shimokin-monitor")
BG_DIR = DATA_DIR / "backgrounds"
HTML_PATH = Path(__file__).with_name("index.html")
lock = threading.RLock()
state = {"target": "shimokin", "status": "unknown", "failures": 0, "interval": 60,
         "last_check": None, "last_online": None, "last_message": "等待首次检测", "events": []}

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
    cfg.setdefault("admin_password", "")
    cfg.setdefault("smtp", {})
    cfg.setdefault("backgrounds", [])
    return cfg

def save_config(cfg):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(CONFIG_PATH)

def send_mail(cfg, subject, body):
    mail = cfg.get("smtp", {})
    if not mail.get("enabled") or not mail.get("host") or not mail.get("username") or not mail.get("password") or not mail.get("to_addrs"):
        raise RuntimeError("请先完整填写并启用 SMTP 配置")
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
        result = subprocess.run(["tailscale", "ping", "--c=1", "--timeout=6s", target],
                                capture_output=True, text=True, timeout=9)
        output = "\n".join(x for x in (result.stdout, result.stderr) if x).strip()
        # A pong means reachable, including when the path is relayed through DERP.
        ok = any(re.match(r"^pong from\\s+", line.strip(), re.I) for line in output.splitlines())
        return ok, output[-500:] or f"tailscale ping exit={result.returncode}"
    except Exception as exc:
        return False, str(exc)

def monitor_loop():
    while True:
        try:
            cfg = load_config()
            target = cfg["target"]
            interval = max(10, int(cfg["interval"]))
            threshold = max(1, int(cfg["failure_threshold"]))
            with lock:
                state["target"], state["interval"] = target, interval
            ok, detail = probe(target)
            notice = None
            with lock:
                state["last_check"] = now()
                if ok:
                    state["failures"] = 0
                    state["last_online"] = state["last_check"]
                    if state["status"] != "online":
                        previous = state["status"]
                        state["status"] = "online"
                        state["last_message"] = "设备在线：" + detail
                        event("设备在线" + ("（恢复连接）" if previous == "offline" else ""), "success")
                        if previous == "offline":
                            notice = ("【shimokin】设备已恢复在线", f"{target} 已恢复 Tailscale 连通。\\n时间：{state['last_check']}")
                else:
                    state["failures"] += 1
                    state["last_message"] = "检测失败：" + detail
                    if state["failures"] >= threshold and state["status"] != "offline":
                        previous = state["status"]
                        state["status"] = "offline"
                        event(f"设备离线（连续失败 {state['failures']} 次）", "error")
                        if previous == "online":
                            notice = ("【shimokin】设备离线告警", f"{target} 已连续检测失败 {state['failures']} 次。\\n时间：{state['last_check']}\\n详情：{detail}")
            if notice:
                try:
                    send_mail(cfg, *notice)
                    event("状态变化邮件已发送", "success")
                except Exception as exc:
                    event("邮件发送失败：" + str(exc), "error")
        except Exception as exc:
            event("监控循环异常：" + str(exc), "error")
        time.sleep(max(10, int(state.get("interval", 60))))

def get_tailscale_ip():
    result = subprocess.run(["tailscale", "ip", "-4"], capture_output=True, text=True, timeout=8)
    ip = result.stdout.strip().splitlines()[0]
    socket.inet_aton(ip)
    return ip

class Handler(BaseHTTPRequestHandler):
    server_version = "ShimokinMonitor/2"

    def reply(self, code, obj):
        data = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def authorized(self):
        try:
            scheme, token = self.headers.get("Authorization", "").split(" ", 1)
            user, password = base64.b64decode(token).decode().split(":", 1)
            expected = load_config().get("admin_password", "")
            return scheme.lower() == "basic" and user == "admin" and bool(expected) and secrets.compare_digest(password, expected)
        except Exception:
            return False

    def require_auth(self):
        if self.authorized():
            return True
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="Shimokin Monitor", charset="UTF-8"')
        self.send_header("Content-Length", "0")
        self.end_headers()
        return False

    def read_json(self, limit=8 * 1024 * 1024):
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > limit:
            raise ValueError("请求内容为空或超过大小限制")
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_GET(self):
        if not self.require_auth():
            return
        path = unquote(urlparse(self.path).path)
        if path == "/api/status":
            with lock:
                payload = dict(state)
                payload["events"] = list(state["events"])
            self.reply(200, payload)
        elif path == "/api/config":
            cfg = load_config()
            mail = cfg.get("smtp", {})
            self.reply(200, {"smtp": {"enabled": bool(mail.get("enabled")), "host": mail.get("host", "smtp.qq.com"),
                "port": mail.get("port", 465), "use_ssl": mail.get("use_ssl", True),
                "username": mail.get("username", ""), "from_addr": mail.get("from_addr", ""),
                "to_addrs": mail.get("to_addrs", [])}, "backgrounds": cfg.get("backgrounds", [])})
        elif path.startswith("/backgrounds/"):
            name = Path(path.rsplit("/", 1)[-1]).name
            if name not in load_config().get("backgrounds", []):
                self.send_error(404); return
            file = BG_DIR / name
            if not file.is_file():
                self.send_error(404); return
            data = file.read_bytes()
            mime = {"jpg":"image/jpeg", "jpeg":"image/jpeg", "png":"image/png", "webp":"image/webp"}.get(file.suffix.lower().lstrip("."), "application/octet-stream")
            self.send_response(200); self.send_header("Content-Type", mime)
            self.send_header("Cache-Control", "private, max-age=3600"); self.send_header("Content-Length", str(len(data)))
            self.end_headers(); self.wfile.write(data)
        elif path in ("/", "/index.html"):
            data = HTML_PATH.read_bytes()
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store"); self.send_header("Content-Length", str(len(data)))
            self.end_headers(); self.wfile.write(data)
        else:
            self.send_error(404)

    def do_POST(self):
        if not self.require_auth():
            return
        path = urlparse(self.path).path
        try:
            if path == "/api/config":
                body = self.read_json(64 * 1024)
                cfg = load_config()
                smtp = body.get("smtp", {})
                current = cfg.get("smtp", {})
                password = smtp.get("password")
                updated = {"enabled": bool(smtp.get("enabled")), "host": str(smtp.get("host", "")).strip(),
                    "port": int(smtp.get("port", 465)), "use_ssl": bool(smtp.get("use_ssl", True)),
                    "username": str(smtp.get("username", "")).strip(),
                    "password": password if password else current.get("password", ""),
                    "from_addr": str(smtp.get("from_addr", "")).strip(),
                    "to_addrs": [x.strip() for x in smtp.get("to_addrs", []) if isinstance(x, str) and x.strip()]}
                if not 1 <= updated["port"] <= 65535:
                    raise ValueError("SMTP 端口无效")
                cfg["smtp"] = updated
                save_config(cfg)
                event("网页端更新了 SMTP 配置")
                self.reply(200, {"ok": True})
            elif path == "/api/test-email":
                cfg = load_config()
                send_mail(cfg, "【Shimokin Monitor】SMTP 测试邮件", "SMTP 配置测试成功。")
                event("SMTP 测试邮件发送成功", "success")
                self.reply(200, {"ok": True, "message": "测试邮件已发送"})
            elif path == "/api/backgrounds":
                body = self.read_json(8 * 1024 * 1024)
                filename = str(body.get("filename", ""))
                match = re.search(r"\\.(jpg|jpeg|png|webp)$", filename, re.I)
                if not match:
                    raise ValueError("仅支持 JPG、PNG、WebP 图片")
                raw = body.get("data", "")
                if not isinstance(raw, str) or "," not in raw:
                    raise ValueError("图片数据格式无效")
                binary = base64.b64decode(raw.split(",", 1)[1], validate=True)
                if not binary or len(binary) > 5 * 1024 * 1024:
                    raise ValueError("图片为空或超过 5MB")
                ext = match.group(1).lower()
                name = secrets.token_hex(12) + "." + ext
                BG_DIR.mkdir(parents=True, exist_ok=True)
                (BG_DIR / name).write_bytes(binary)
                os.chmod(BG_DIR / name, 0o640)
                cfg = load_config()
                cfg["backgrounds"] = cfg.get("backgrounds", []) + [name]
                save_config(cfg)
                event("上传了背景图片：" + filename, "success")
                self.reply(200, {"ok": True, "backgrounds": cfg["backgrounds"]})
            else:
                self.send_error(404)
        except Exception as exc:
            self.reply(400, {"ok": False, "error": str(exc)})

    def do_DELETE(self):
        if not self.require_auth():
            return
        path = unquote(urlparse(self.path).path)
        if path.startswith("/api/backgrounds/"):
            name = Path(path.rsplit("/", 1)[-1]).name
            cfg = load_config()
            if name in cfg.get("backgrounds", []):
                cfg["backgrounds"].remove(name)
                save_config(cfg)
                try: (BG_DIR / name).unlink(missing_ok=True)
                except OSError: pass
                event("删除了背景图片", "info")
            self.reply(200, {"ok": True, "backgrounds": cfg.get("backgrounds", [])})
        else:
            self.send_error(404)

    def log_message(self, fmt, *args):
        pass

def main():
    cfg = load_config()
    if not cfg.get("admin_password"):
        raise SystemExit("缺少管理密码，请先运行 install.sh 初始化")
    BG_DIR.mkdir(parents=True, exist_ok=True)
    threading.Thread(target=monitor_loop, daemon=True).start()
    port = int(cfg["web_port"])
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    event(f"网页面板监听 0.0.0.0:{port}（公网/内网）")
    server.serve_forever()

if __name__ == "__main__":
    main()
