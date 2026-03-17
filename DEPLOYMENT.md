# MemePulse-4444 远端部署指南

## 系统要求
- Linux 服务器（Ubuntu 20.04+ 或 CentOS 8+）
- Python 3.10+
- systemd 支持
- 能访问互联网（RPC、Twitter API、Telegram）

## 部署步骤

### 第1步：获取 Twitter API 凭证

访问 https://developer.twitter.com 申请开发者账户：

1. **创建项目** → 获得 `API Key` + `API Secret`
2. **生成 Bearer Token** → 用于 API v2（推荐）
3. **生成 Access Token** → `Access Token` + `Access Token Secret`

> 注意：需要选择 **Essential** 或更高级别，Basic 级别有速率限制

配置示例（后续会用到）：
```json
{
  "TWITTER_API_KEY": "xxxxxx",
  "TWITTER_BEARER_TOKEN": "Bearer xxxxxx",
  "TELEGRAM_BOT_TOKEN": "123456:ABCDxxxxxx",
  "TELEGRAM_CHAT_ID": "123456789"
}
```

---

### 第2步：服务器准备（以 Ubuntu 为例）

连接到服务器：
```bash
ssh root@your_server_ip
```

创建专用用户（可选但推荐）：
```bash
useradd -m -s /bin/bash limit-sniper
usermod -aG sudo limit-sniper
```

更新系统并安装依赖：
```bash
apt update && apt upgrade -y
apt install -y python3 python3-pip python3-venv git
```

---

### 第3步：克隆项目

切换到新建用户（如果创建了）：
```bash
su - limit-sniper
```

克隆项目：
```bash
git clone https://github.com/hkun0120/Limit-Sniper.git
cd Limit-Sniper
```

---

### 第4步：配置环境

创建虚拟环境：
```bash
python3 -m venv venv
source venv/bin/activate
```

安装依赖：
```bash
pip install web3==7.0.0 requests tweepy==4.14.0
```

配置监控器：
```bash
# 复制配置文件
cp monitor_settings.example.json monitor_settings.json

# 编辑配置（Vim 或 Nano）
nano monitor_settings.json
```

在编辑器中修改：
```json
{
    "ADDRESS_SUFFIX": "4444",
    "TELEGRAM_BOT_TOKEN": "你的Telegram Bot Token",
    "TELEGRAM_CHAT_ID": "你的Chat ID",
    "RPC_URL": "https://bsc-dataseed1.binance.org"
    // ... 其他配置
}
```

配置 Twitter 监听器：
```bash
# 复制配置文件
cp twitter_settings.example.json twitter_settings.json

# 编辑配置
nano twitter_settings.json
```

在编辑器中修改：
```json
{
    "TWITTER_BEARER_TOKEN": "你的Twitter Bearer Token",
    "TELEGRAM_BOT_TOKEN": "你的Telegram Bot Token",
    "TELEGRAM_CHAT_ID": "你的Chat ID",
    "KEYWORDS": ["4444", "Meme4444"]
}
```

---

### 第5步：测试脚本

测试监控器（不依赖Twitter）：
```bash
# 激活虚拟环境（如果未激活）
source venv/bin/activate

# 运行20秒测试（Ctrl+C 停止）
timeout 20 python3 monitor.py || true
```

预期输出：
```
2026-03-17 23:45:12.345678 正在连接 BSC...
2026-03-17 23:45:13.456789 BSC 连接状态: True
2026-03-17 23:45:13.567890 开始监控 PancakeSwap 新交易对...
```

测试 Twitter 监听器：
```bash
timeout 20 python3 twitter_monitor.py || true
```

预期输出：
```
开始扫描 Twitter 关键词...
搜索关键词: 4444
```

---

### 第6步：配置 Systemd 服务

将本地项目文件同步到服务器，然后：

```bash
# 创建 /opt 目录
sudo mkdir -p /opt/limit-sniper
sudo chown limit-sniper:limit-sniper /opt/limit-sniper

# 复制项目文件
sudo cp -r ~/Limit-Sniper/* /opt/limit-sniper/
sudo chown -R limit-sniper:limit-sniper /opt/limit-sniper

# 复制 systemd 服务文件
sudo cp /opt/limit-sniper/monitor.service /etc/systemd/system/
sudo cp /opt/limit-sniper/twitter_monitor.service /etc/systemd/system/

# 刷新 systemd 配置
sudo systemctl daemon-reload
```

---

### 第7步：启动服务

启动监控器：
```bash
sudo systemctl start monitor
sudo systemctl enable monitor  # 设置开机自启
```

启动 Twitter 监听器：
```bash
sudo systemctl start twitter_monitor
sudo systemctl enable twitter_monitor
```

查看状态：
```bash
sudo systemctl status monitor
sudo systemctl status twitter_monitor
```

查看日志：
```bash
# 实时查看 monitor 日志
sudo journalctl -u monitor -f

# 查看 twitter_monitor 日志
sudo journalctl -u twitter_monitor -f

# 查看程序生成的日志文件
tail -f /opt/limit-sniper/logs/monitor.log
tail -f /opt/limit-sniper/logs/twitter_monitor.log
```

---

### 第8步：管理与维护

**常用命令：**
```bash
# 重启服务
sudo systemctl restart monitor
sudo systemctl restart twitter_monitor

# 停止服务
sudo systemctl stop monitor
sudo systemctl stop twitter_monitor

# 查看服务运行状态
systemctl is-active monitor
systemctl is-active twitter_monitor

# 查看是否开机自启
systemctl is-enabled monitor
```

**更新代码：**
```bash
cd /opt/limit-sniper
sudo git pull origin main
sudo systemctl restart monitor twitter_monitor
```

**备份配置：**
```bash
# 不要备份包含敏感信息的 JSON
sudo cp /opt/limit-sniper/monitor_settings.json ~/backup/monitor_settings.json.bak
```

---

## 故障排查

**问题1：连接 BSC 失败**
```
Solution: 检查 RPC_URL 是否可访问
curl https://bsc-dataseed1.binance.org
```

**问题2：Telegram 未收到通知**
```
Solution: 检查 Bot Token 和 Chat ID
grep TELEGRAM /opt/limit-sniper/monitor_settings.json
```

**问题3：Twitter API 超速限制**
```
Solution: 升级到 Elevated 或 Pro 级别
或增加脚本中的 sleep() 时间
```

**问题4：内存或 CPU 占用过高**
```
Solution: 检查 RPC 调用频率
减少 POLL_INTERVAL_SECONDS 或 STARTUP_BACKFILL_PAIRS
```

---

## 监听器输出示例

**Monitor 报告：**
```
2026-03-18 10:30:45 发现目标代币! 地址以 '4444' 结尾
   Token: 0x812Fc5119b772c6c7a66249A559f3614623f4444
   名称: MemeToken (MEME4444)
   ...
   🟢 所有检查通过!
```

**Twitter 监听器报告：**
```
📢 4444 币KOL宣传统计 - 2026-03-18 11:00
共发现 15 个KOL，42条相关推文

🔥 @币圈大V1 (币圈大V)
   粉丝: 500,000 | 推文: 5 条
```

---

## 进一步优化

### 使用更快的 RPC
- QuickNode: https://quicknode.com （需要付费）
- Alchemy: https://www.alchemy.com
- 这些付费 RPC 可消除速率限制

### 增加数据持久化
编辑 `monitor.py`，添加发现的币到数据库（SQLite 或 PostgreSQL）

### 设置告警
在 Telegram 中@用户或发送特殊消息提醒问题

### 监控服务本身
```bash
# 使用 Systemd 的自动重启（已配置）
# 或使用 healthcheck 脚本定期检查
```

---

## 完整清单

- [ ] 获得 Twitter Developer 账户和 API key
- [ ] 获得 Telegram Bot Token 和 Chat ID
- [ ] 创建服务器（推荐 2GB RAM + 2 CPU 的轻量级 VPS）
- [ ] 安装 Python 3.10+ 和依赖
- [ ] 配置 monitor_settings.json 和 twitter_settings.json
- [ ] 测试两个脚本本地运行正常
- [ ] 部署到 /opt/limit-sniper
- [ ] 配置 systemd 服务
- [ ] 启动服务并验证日志
- [ ] 设置日志轮换（logrotate）防止磁盘满

---

## 成本估算

| 项目 | 成本 |
|------|------|
| VPS（Ubuntu, 2GB RAM） | $3-5/月 |
| Twitter API | 100-500/月（应用程度）或免费试用 |
| 域名（可选） | $10+/年 |
| 总计 | **$40-100/月左右** |

---

## 支持与反馈

如遇到问题，请检查：
1. `/opt/limit-sniper/logs/` 下的日志文件
2. `journalctl -u monitor` 的系统日志
3. Twitter API 的速率限制状态
4. RPC 连接状态

