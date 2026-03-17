# MemePulse-4444

MemePulse-4444 是一个面向 BSC 的 meme 币监控工具，专注于发现地址后缀为 `4444` 的新代币，并在发现后自动执行风控检查与消息通知。

它包含两部分能力：

1. 链上实时监听：追踪 PancakeSwap 新交易对，分析新币安全性。
2. 舆情辅助监听：按关键词统计社媒 KOL 宣传情况并推送报告。

## 功能概览

- 监听 PancakeSwap V2 新交易对（Factory `allPairsLength` 增量扫描）。
- 过滤目标代币（支持 `4444` 后缀，或关闭后缀过滤）。
- 支持基准币：`WBNB`、`USDT`、`USDC`。
- 自动风控：
	- 初始流动性阈值检查
	- 观察期撤池检测
	- 蜜罐/高税模拟检测
	- LP 锁仓比例检测
	- 合约验证状态（可选，依赖 BscScan API）
- Telegram 实时通知。
- 每小时价格统计：比较当前价格与上一小时价格变化。
- Twitter 关键词/KOL 统计（`twitter_monitor.py`）。

## 风险声明

本项目仅用于研究和监控，不构成投资建议。meme 币波动和风险极高，请务必自行判断并控制仓位。

## 目录结构

```text
.
├── monitor.py                      # 链上监听主程序
├── twitter_monitor.py              # 社媒/KOL 关键词监听
├── monitor_settings.example.json   # 链上监听配置模板
├── twitter_settings.example.json   # Twitter 配置模板
├── requirements.txt
├── monitor.service                 # systemd 服务（链上监听）
├── twitter_monitor.service         # systemd 服务（Twitter监听）
├── DEPLOYMENT.md                   # 远端部署指南
└── QUICK_START.md                  # 快速启动指南
```

## 快速开始

1. 安装依赖

```bash
pip install -r requirements.txt
```

2. 配置链上监听

```bash
cp monitor_settings.example.json monitor_settings.json
```

按需修改：

- `ADDRESS_SUFFIX`（默认 `4444`）
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `RPC_URL`

3. 启动链上监听

```bash
python3 monitor.py
```

4. 启动 Twitter 监听（可选）

```bash
cp twitter_settings.example.json twitter_settings.json
python3 twitter_monitor.py
```

## 配置说明（核心项）

`monitor_settings.json` 关键字段：

- `ADDRESS_SUFFIX`: 地址后缀过滤，空字符串代表不过滤。
- `BASE_TOKENS`: 基准币数组（推荐保持 `WBNB/USDT/USDC`）。
- `STARTUP_BACKFILL_PAIRS`: 启动时回溯的交易对数量。
- `MIN_LIQUIDITY_BY_BASE`: 按基准币配置最低流动性。
- `OBSERVE_SECONDS`: 观察撤池时间窗口（秒）。
- `MAX_LIQUIDITY_DROP_PCT`: 观察期内允许的最大流动性下降比例。

## 服务器部署

完整步骤见：`DEPLOYMENT.md`

简版：

1. 准备 Linux VPS（Ubuntu 20.04+）。
2. 克隆项目并安装依赖。
3. 配置 `monitor_settings.json` / `twitter_settings.json`。
4. 使用 `monitor.service` 和 `twitter_monitor.service` 启动并设为开机自启。

## 版本与分支

- 默认分支：`main`
- 推荐通过 PR 或小步提交维护变更历史。

## 许可

仅供学习和个人研究使用。若用于生产环境，请自行完善审计、监控、容错与密钥管理。
