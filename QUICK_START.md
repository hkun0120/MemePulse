# MemePulse-4444 快速部署指南

## 5分钟快速启动（仅用于本地测试）

### 1. 安装依赖
```bash
pip install -r requirements.txt
```

### 2. 配置文件
```bash
# 复制并编辑配置
cp monitor_settings.example.json monitor_settings.json
cp twitter_settings.example.json twitter_settings.json

# 编辑配置文件
nano monitor_settings.json      # 填入 Telegram Bot Token 和 Chat ID
nano twitter_settings.json      # 填入 Twitter API Key 和 Bearer Token
```

### 3. 运行脚本
```bash
# 运行监控器
python3 monitor.py

# 在另一个终端运行 Twitter 监听器
python3 twitter_monitor.py
```

---

## 完整服务器部署（15-20分钟）

### 前置条件
- [ ] 有一个 Linux VPS（Ubuntu 20.04 或更高版本）
- [ ] 获得 [Twitter Developer Account](https://developer.twitter.com) 和 **Bearer Token**
- [ ] 拥有 [Telegram Bot Token 和 Chat ID](https://core.telegram.org/bots/tutorial)

### 部署步骤

**第1步：连接到服务器**
```bash
ssh root@your_server_ip
```

**第2步：克隆项目**
```bash
git clone https://github.com/hkun0120/Limit-Sniper.git
cd Limit-Sniper
pip install -r requirements.txt
```

**第3步：配置**
```bash
# 编辑配置文件
nano monitor_settings.json
nano twitter_settings.json

# 填入：
# - TELEGRAM_BOT_TOKEN
# - TELEGRAM_CHAT_ID
# - TWITTER_BEARER_TOKEN
# - 其他 Twitter API 凭证
```

**第4步：部署为系统服务**
```bash
# 创建项目目录
sudo mkdir -p /opt/limit-sniper
sudo cp -r ~/Limit-Sniper/* /opt/limit-sniper/
sudo chown -R $USER:$USER /opt/limit-sniper

# 安装服务
sudo cp /opt/limit-sniper/monitor.service /etc/systemd/system/
sudo cp /opt/limit-sniper/twitter_monitor.service /etc/systemd/system/
sudo systemctl daemon-reload

# 启动服务
sudo systemctl start monitor
sudo systemctl start twitter_monitor

# 设置开机自启
sudo systemctl enable monitor
sudo systemctl enable twitter_monitor
```

**第5步：验证**
```bash
# 查看状态
sudo systemctl status monitor
sudo systemctl status twitter_monitor

# 查看日志
sudo journalctl -u monitor -f
sudo journalctl -u twitter_monitor -f
```

---

## 常见问题答疑

**Q: 我没有 Twitter API，能否跳过 twitter_monitor？**
A: 可以，两个脚本独立运行。只需运行 `monitor.py` 即可监控链上币。

**Q: Telegram 收不到通知？**
A: 检查 `TELEGRAM_BOT_TOKEN` 和 `TELEGRAM_CHAT_ID` 是否正确填入。可以手动测试：
```python
import requests
bot_token = "your_token"
chat_id = "your_chat_id"
requests.post(
    f"https://api.telegram.org/bot{bot_token}/sendMessage",
    json={"chat_id": chat_id, "text": "Test"}
)
```

**Q: RPC 连接超时？**
A: 公共 RPC 可能不稳定。建议使用付费 RPC：
- [QuickNode](https://quicknode.com)（$9/月起）
- [Alchemy](https://www.alchemy.com)（免费额度）
- [Infura](https://infura.io)（免费额度）

**Q: Twitter API 超速限制怎么办？**
A: 从 Free 升级到 **Elevated** 或 **Pro** 账户，或减少查询频率。

**Q: 日志文件太大？**
A: 配置日志轮换：
```bash
sudo nano /etc/logrotate.d/limit-sniper
```
内容：
```
/opt/limit-sniper/logs/*.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
}
```

**Q: 如何更新代码？**
A: 
```bash
cd /opt/limit-sniper
sudo git pull origin main
sudo systemctl restart monitor twitter_monitor
```

---

## 性能优化建议

| 配置项 | 说明 | 建议值 |
|--------|------|---------|
| `POLL_INTERVAL_SECONDS` | 轮询间隔 | 2-5秒 |
| `STARTUP_BACKFILL_PAIRS` | 启动回溯对数 | 300-1000 |
| `OBSERVE_SECONDS` | 观察期 | 60-120秒 |
| `MIN_LIQUIDITY_BNB` | 最小流动性厚度 | 0.5-2.0 |

---

## 成本预估

| 项目 | 成本 | 说明 |
|------|------|------|
| VPS（2GB RAM） | $3-8/月 | Linode/DigitalOcean |
| Twitter Elevated API | $100/月 | 按使用量计费 |
| 域名（可选） | $10/年 | 便于管理 |
| RPC（免费） | $0 | 用 BSC 公共端点 |
| **总计（最小化）** | **$3-8/月** | 用免费 API + 公共 RPC |

---

## 下一步工作

- [ ] 验证脚本正常运行
- [ ] 配置日志轮换防止磁盘满
- [ ] 设置 Systemd 的监控告警
- [ ] 考虑添加数据库持久化
- [ ] 构建 Web Dashboard 查看实时数据

---

## 技术支持

- 项目地址：https://github.com/hkun0120/Limit-Sniper
- 日志位置：`/opt/limit-sniper/logs/`
- 系统日志：`journalctl -u monitor`

有问题请提交到 GitHub Issues。
