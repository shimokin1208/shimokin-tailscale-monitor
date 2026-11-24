# shimokin-tailscale-monitor

通过 Tailscale 检测家中设备在线状态，并提供仅 Tailnet 可访问的网页面板和 SMTP 邮件告警。

## 功能

- 默认每 60 秒检测一次目标设备（默认 `shimokin`）
- 连续失败 3 次才标记离线
- 在线 / 离线状态、最后在线时间、最后检测时间、失败次数
- 状态变化时发送邮件（SMTP SSL）
- 网页每 5 秒自动刷新，保留最近 100 条运行事件
- systemd 开机启动、异常自动重启
- Web 服务只绑定服务器的 Tailscale IPv4，不监听公网网卡

> 这是 Tailscale 网络可达性监控，不等同于 AstrBot、LLBot 等应用进程健康检查。事件记录暂存在内存中，服务重启后会清空。

## 部署要求

- Debian 12/13
- 已安装并登录 Tailscale
- Python 3.9+
- 服务器和目标设备位于同一个 Tailnet

先确认服务器能看到目标设备：

```bash
tailscale status
tailscale ping shimokin
```

## 安装

```bash
apt update
apt install -y git python3
git clone https://github.com/shimokin1208/shimokin-tailscale-monitor.git
cd shimokin-tailscale-monitor
bash install.sh
```

安装脚本会把程序放到 `/opt/shimokin-monitor`，配置放到 `/etc/shimokin-monitor/config.json`，并创建 systemd 服务。

## 配置邮件

编辑配置：

```bash
nano /etc/shimokin-monitor/config.json
```

填写 SMTP 信息。QQ 邮箱示例：

- host：`smtp.qq.com`
- port：`465`
- use_ssl：`true`
- username：完整 QQ 邮箱地址
- password：QQ 邮箱 SMTP 授权码（不是网页登录密码）
- from_addr：发件邮箱
- to_addrs：收件邮箱数组

修改后重启：

```bash
systemctl restart shimokin-monitor
```

配置文件含邮箱授权码，安装时会设置为仅 root 可读写（权限 600）。不要把真实配置提交到 GitHub。

## 访问面板

在已连接同一 Tailnet 的设备浏览器访问：

```
http://服务器的Tailscale-IP:8765
```

查看服务器 Tailscale IPv4：

```bash
tailscale ip -4
```

不要在云服务器安全组开放 8765 公网入站端口。程序本身只绑定 Tailscale IPv4。

## 管理

```bash
systemctl status shimokin-monitor
journalctl -u shimokin-monitor -f
systemctl restart shimokin-monitor
systemctl stop shimokin-monitor
```

## 更新

进入最初执行 `git clone` 时生成的仓库目录（如果是在 root 终端执行，通常是 `/root/shimokin-tailscale-monitor`），再拉取更新并重新安装：

```bash
cd /root/shimokin-tailscale-monitor
git pull
bash install.sh
```

如果当初把仓库克隆到了其他目录，请将上面的路径替换为实际目录。

安装脚本不会覆盖已有的 `/etc/shimokin-monitor/config.json`。
