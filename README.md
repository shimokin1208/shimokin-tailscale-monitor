# Shimokin Tailscale Monitor

通过 Tailscale ping 检测设备可达性，提供带密码保护的公网网页面板、SMTP 告警和背景轮播。

## 功能
- 每 60 秒检测目标设备，连续失败 3 次才标记离线
- 正确识别 Tailscale DERP 中继返回的 pong；中继路径不再被误判离线
- 手机适配的状态面板、最近事件
- 网页内配置 SMTP、发送测试邮件
- 上传、删除背景图片并自动轮播（JPG / PNG / WebP，单张最大 5MB）
- HTTP Basic 管理密码保护所有页面和 API
- systemd 开机启动和自动重启
- 网页监听 0.0.0.0:8765，允许公网访问；Tailscale 仍负责服务器到目标设备的探测

> 这是 Tailscale 网络可达性监控，不等同于 AstrBot / LLBot 进程健康检查。

## 安装
Debian 12/13，要求已安装并登录 Tailscale、Python 3.9+。

```bash
apt update
apt install -y git python3
git clone https://github.com/shimokin1208/shimokin-tailscale-monitor.git
cd shimokin-tailscale-monitor
bash install.sh
```

首次安装会生成随机管理密码并在终端显示一次，请妥善保存。浏览器首次访问会弹出账号密码框，用户名固定为 `admin`。

## 公网访问
在云服务器安全组添加 TCP 8765 入方向规则。建议来源限制为自己的公网 IP；确需任何网络访问才使用 0.0.0.0/0。网页有管理密码保护，但 HTTP 不加密，建议后续配置 HTTPS 反向代理。访问：

```
http://服务器公网IP:8765
```

## SMTP
登录网页后点击“设置”，填写 SMTP 服务器、端口、SSL/STARTTLS、账号、授权码、发件人和收件人。QQ 邮箱使用 smtp.qq.com:465、SSL，密码填写 SMTP 授权码。保存后可发送测试邮件。授权码保存在服务器的 /etc/shimokin-monitor/config.json，不会显示回网页。

## 背景轮播
点击“背景”上传 JPG、PNG 或 WebP 图片，单张最大 5MB。图片保存在 /var/lib/shimokin-monitor/backgrounds，重启后保留。可调整轮播间隔并删除图片。

## 管理
```bash
systemctl status shimokin-monitor
journalctl -u shimokin-monitor -n 50 --no-pager
systemctl restart shimokin-monitor
```

配置位于 /etc/shimokin-monitor/config.json，权限为 600；图片位于 /var/lib/shimokin-monitor/backgrounds。
