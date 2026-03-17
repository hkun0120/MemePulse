"""
BSC 新币监控器 - 监控 PancakeSwap 上地址以指定后缀结尾的新代币
监听 Factory PairCreated 事件，执行安全检查，控制台 + Telegram 通知
"""

from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware
from time import sleep, time
import json
import os
import logging
import requests
from datetime import datetime

# ─── 配置 ───────────────────────────────────────────────
CONFIG_FILE = './monitor_settings.json'

with open(CONFIG_FILE) as f:
    config = json.load(f)

ADDRESS_SUFFIX = config.get("ADDRESS_SUFFIX", "4444").lower()
MIN_LIQUIDITY_BNB = float(config.get("MIN_LIQUIDITY_BNB", 1.0))
POLL_INTERVAL = int(config.get("POLL_INTERVAL_SECONDS", 2))
OBSERVE_SECONDS = int(config.get("OBSERVE_SECONDS", 90))
MAX_LIQUIDITY_DROP_PCT = float(config.get("MAX_LIQUIDITY_DROP_PCT", 50.0))
MIN_LP_LOCK_PCT = float(config.get("MIN_LP_LOCK_PCT", 80.0))
BASE_TOKENS = config.get("BASE_TOKENS", ["WBNB", "USDT", "USDC"])
STARTUP_BACKFILL_PAIRS = int(config.get("STARTUP_BACKFILL_PAIRS", 1000))
MIN_LIQUIDITY_BY_BASE = config.get("MIN_LIQUIDITY_BY_BASE", {"WBNB": MIN_LIQUIDITY_BNB, "USDT": 3000, "USDC": 3000})
TEST_BUY_AMOUNT_BY_BASE = config.get("TEST_BUY_AMOUNT_BY_BASE", {"WBNB": 0.01, "USDT": 50, "USDC": 50})
BSCSCAN_API_KEY = config.get("BSCSCAN_API_KEY", "")
TELEGRAM_BOT_TOKEN = config.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = config.get("TELEGRAM_CHAT_ID", "")
RPC_URL = config.get("RPC_URL", "https://bsc-dataseed1.binance.org")
MONITOR_ALL_NEW_TOKENS = ADDRESS_SUFFIX == ""

MIN_LIQUIDITY_BY_BASE = {k.upper(): float(v) for k, v in MIN_LIQUIDITY_BY_BASE.items()}
TEST_BUY_AMOUNT_BY_BASE = {k.upper(): float(v) for k, v in TEST_BUY_AMOUNT_BY_BASE.items()}

# ─── 日志 ───────────────────────────────────────────────
os.makedirs('./logs', exist_ok=True)
log_format = '%(levelname)s: %(asctime)s %(message)s'
logging.basicConfig(
    filename='./logs/monitor.log',
    level=logging.INFO,
    format=log_format
)

# ─── ABI 加载 ───────────────────────────────────────────
with open('./abi/standard.json') as f:
    standardAbi = json.load(f)
with open('./abi/lp.json') as f:
    lpAbi = json.load(f)
with open('./abi/factory2.json') as f:
    factoryAbi = json.load(f)
with open('./abi/router.json') as f:
    routerAbi = json.load(f)

# ─── Web3 连接 ──────────────────────────────────────────
def ts():
    return datetime.fromtimestamp(time())

print(f"{ts()} 正在连接 BSC...")
client = Web3(Web3.HTTPProvider(RPC_URL))
client.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
print(f"{ts()} BSC 连接状态: {client.is_connected()}")

# PancakeSwap V2 合约
FACTORY_ADDRESS = Web3.to_checksum_address("0xcA143Ce32Fe78f1f7019d7d551a6402fC5350c73")
ROUTER_ADDRESS = Web3.to_checksum_address("0x10ED43C718714eb63d5aA57B78B54704E256024E")
WBNB = Web3.to_checksum_address("0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c")
USDT = Web3.to_checksum_address("0x55d398326f99059fF775485246999027B3197955")
USDC = Web3.to_checksum_address("0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d")

BASE_TOKEN_ADDRESS_BY_SYMBOL = {
    "WBNB": WBNB,
    "USDT": USDT,
    "USDC": USDC,
}

ACTIVE_BASE_TOKEN_SYMBOLS = [s.upper() for s in BASE_TOKENS if s.upper() in BASE_TOKEN_ADDRESS_BY_SYMBOL]
if not ACTIVE_BASE_TOKEN_SYMBOLS:
    ACTIVE_BASE_TOKEN_SYMBOLS = ["WBNB"]

ACTIVE_BASE_TOKEN_ADDRESSES = {
    BASE_TOKEN_ADDRESS_BY_SYMBOL[s].lower() for s in ACTIVE_BASE_TOKEN_SYMBOLS
}

BASE_TOKEN_SYMBOL_BY_ADDRESS = {
    v.lower(): k for k, v in BASE_TOKEN_ADDRESS_BY_SYMBOL.items()
}

TOKEN_DECIMALS_CACHE = {}

factoryContract = client.eth.contract(address=FACTORY_ADDRESS, abi=factoryAbi)
routerContract = client.eth.contract(address=ROUTER_ADDRESS, abi=routerAbi)

# 已知锁仓合约地址 (PinkLock, Unicrypt, Team.Finance 等)
LOCK_CONTRACTS = {
    "0x7ee058420e5937496f5a2096f04caa7721cf70cc",  # PinkLock V1
    "0x407993575c91ce7643a4d4ccacc9a98c36ee1bbe",  # PinkLock V2
    "0xc765bddb93b0d1c1a88282ba0fa6b2d00e3e0c83",  # Unicrypt V2
    "0x663a5c229c09b049e36dcc11a9b0d4a8eb9db214",  # DxLock
    "0xe2fe530c047f2d85298b07d9333c05d6e0aed57f",  # Team.Finance
}

# ─── 工具函数 ───────────────────────────────────────────

def send_telegram(message):
    """发送 Telegram 通知"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }, timeout=10)
    except Exception as e:
        logging.warning(f"Telegram 发送失败: {e}")


def get_token_info(token_address):
    """获取代币名称、符号、精度"""
    try:
        contract = client.eth.contract(address=token_address, abi=standardAbi)
        name = contract.functions.name().call()
        symbol = contract.functions.symbol().call()
        decimals = contract.functions.decimals().call()
        total_supply = contract.functions.totalSupply().call()
        return {
            "name": name,
            "symbol": symbol,
            "decimals": decimals,
            "total_supply": total_supply / (10 ** decimals)
        }
    except Exception as e:
        logging.warning(f"获取代币信息失败 {token_address}: {e}")
        return None


def get_token_decimals(token_address):
    """读取并缓存代币精度"""
    addr = Web3.to_checksum_address(token_address)
    key = addr.lower()
    if key in TOKEN_DECIMALS_CACHE:
        return TOKEN_DECIMALS_CACHE[key]

    contract = client.eth.contract(address=addr, abi=standardAbi)
    decimals = contract.functions.decimals().call()
    TOKEN_DECIMALS_CACHE[key] = decimals
    return decimals


def check_liquidity(pair_address, base_token_address):
    """检查流动性池中的基准币数量"""
    try:
        pair_contract = client.eth.contract(address=Web3.to_checksum_address(pair_address), abi=lpAbi)
        reserves = pair_contract.functions.getReserves().call()
        token0 = pair_contract.functions.token0().call().lower()
        token1 = pair_contract.functions.token1().call().lower()
        base = Web3.to_checksum_address(base_token_address).lower()

        if token0 == base:
            base_reserve = reserves[0]
        elif token1 == base:
            base_reserve = reserves[1]
        else:
            return 0.0

        decimals = get_token_decimals(base_token_address)
        return float(base_reserve / (10 ** decimals))
    except Exception as e:
        logging.warning(f"检查流动性失败 {pair_address}: {e}")
        return 0.0


def check_honeypot(token_address, base_token_address, base_symbol):
    """
    模拟买卖检测蜜罐:
    用 getAmountsOut 模拟买入基准币，再模拟用得到的token卖出
    如果卖出时 revert 或税率过高则判定为蜜罐
    """
    try:
        base_symbol = base_symbol.upper()
        buy_amount_human = TEST_BUY_AMOUNT_BY_BASE.get(base_symbol, TEST_BUY_AMOUNT_BY_BASE.get("WBNB", 0.01))

        if base_symbol == "WBNB":
            buy_amount = Web3.to_wei(buy_amount_human, 'ether')
        else:
            base_decimals = get_token_decimals(base_token_address)
            buy_amount = int(buy_amount_human * (10 ** base_decimals))

        base_token = Web3.to_checksum_address(base_token_address)
        token = Web3.to_checksum_address(token_address)

        # 模拟买入
        amounts_out = routerContract.functions.getAmountsOut(
            buy_amount, [base_token, token]
        ).call()
        tokens_bought = amounts_out[-1]

        if tokens_bought == 0:
            return True, "买入返回0", 0

        # 模拟卖出
        amounts_back = routerContract.functions.getAmountsOut(
            tokens_bought, [token, base_token]
        ).call()
        base_back = amounts_back[-1]

        # 计算来回税率
        tax_rate = 1 - (base_back / buy_amount)
        tax_pct = round(tax_rate * 100, 1)

        if tax_pct > 50:
            return True, f"买卖税率过高: {tax_pct}%", tax_pct
        return False, f"买卖税率: {tax_pct}%", tax_pct

    except Exception as e:
        return True, f"模拟交易失败(可能是蜜罐): {e}", 100


def check_lp_locked(pair_address):
    """检查 LP token 是否发送到了已知锁仓合约"""
    try:
        pair_contract = client.eth.contract(address=Web3.to_checksum_address(pair_address), abi=standardAbi)
        total_supply = pair_contract.functions.totalSupply().call()
        if total_supply == 0:
            return False, 0.0

        locked = 0
        for lock_addr in LOCK_CONTRACTS:
            try:
                balance = pair_contract.functions.balanceOf(Web3.to_checksum_address(lock_addr)).call()
                locked += balance
            except Exception:
                pass

        # 也检查 dead address
        dead = "0x000000000000000000000000000000000000dEaD"
        try:
            locked += pair_contract.functions.balanceOf(Web3.to_checksum_address(dead)).call()
        except Exception:
            pass

        lock_pct = round((locked / total_supply) * 100, 1) if total_supply > 0 else 0
        return lock_pct >= MIN_LP_LOCK_PCT, lock_pct

    except Exception as e:
        logging.warning(f"检查LP锁定失败: {e}")
        return False, 0.0


def check_contract_verified(token_address):
    """通过 BscScan API 检查合约是否已验证"""
    if not BSCSCAN_API_KEY:
        return None  # 无API key，跳过
    try:
        url = (
            f"https://api.bscscan.com/api?module=contract&action=getsourcecode"
            f"&address={token_address}&apikey={BSCSCAN_API_KEY}"
        )
        resp = requests.get(url, timeout=10).json()
        result = resp.get('result', [{}])
        if result and result[0].get('ABI') != 'Contract source code not verified':
            return True
        return False
    except Exception as e:
        logging.warning(f"BscScan 查询失败: {e}")
        return None


def get_pair_tokens(pair_address):
    """读取交易对中的 token0 / token1"""
    try:
        pair_contract = client.eth.contract(address=Web3.to_checksum_address(pair_address), abi=lpAbi)
        token0 = pair_contract.functions.token0().call()
        token1 = pair_contract.functions.token1().call()
        return Web3.to_checksum_address(token0), Web3.to_checksum_address(token1)
    except Exception as e:
        logging.warning(f"读取交易对代币失败 {pair_address}: {e}")
        return None, None


def analyze_token(token_address, pair_address, block_number, base_token_address, base_symbol):
    """对发现的代币执行全套安全检查并输出报告"""

    mode_text = "监控全部新币" if MONITOR_ALL_NEW_TOKENS else f"地址以 '{ADDRESS_SUFFIX}' 结尾"

    print("\n" + "=" * 70)
    print(f"🎯 发现目标代币! {mode_text}")
    print(f"   Token:  {token_address}")
    print(f"   Pair:   {pair_address}")
    print(f"   Base:   {base_symbol}")
    print(f"   区块:   {block_number}")
    print(f"   BscScan: https://bscscan.com/address/{token_address}")
    print("-" * 70)

    report_lines = [
        f"<b>🎯 发现目标代币!</b>",
        "监控模式: 全部新币" if MONITOR_ALL_NEW_TOKENS else f"地址以 <code>{ADDRESS_SUFFIX}</code> 结尾",
        f"Token: <code>{token_address}</code>",
        f"Base: {base_symbol}",
        f"区块: {block_number}",
        f"BscScan: https://bscscan.com/address/{token_address}",
        ""
    ]

    # 1. 代币基本信息
    info = get_token_info(token_address)
    if info:
        # 过滤：名称或符号必须含中文字符
        combined = info['name'] + info['symbol']
        if not any('\u4e00' <= c <= '\u9fff' for c in combined):
            print(f"{ts()} [跳过] {token_address} 原因: 非中文代币 (name={info['name']}, symbol={info['symbol']})")
            return
        print(f"   名称:   {info['name']} ({info['symbol']})")
        print(f"   精度:   {info['decimals']}")
        print(f"   总供应: {info['total_supply']:,.0f}")
        report_lines.append(f"名称: {info['name']} ({info['symbol']})")
        report_lines.append(f"总供应: {info['total_supply']:,.0f}")
    else:
        print("   ⚠️ 无法获取代币信息")
        report_lines.append("⚠️ 无法获取代币信息")

    # 2. 流动性检查
    min_liquidity = MIN_LIQUIDITY_BY_BASE.get(base_symbol.upper(), MIN_LIQUIDITY_BY_BASE.get("WBNB", MIN_LIQUIDITY_BNB))
    liquidity_base = check_liquidity(pair_address, base_token_address)
    initial_liquidity_base = liquidity_base
    liq_status = "✅" if liquidity_base >= min_liquidity else "❌"
    print(f"   {liq_status} 初始流动性: {liquidity_base:.4f} {base_symbol} (最低要求: {min_liquidity} {base_symbol})")
    report_lines.append(f"{liq_status} 流动性: {liquidity_base:.4f} {base_symbol}")

    if liquidity_base < min_liquidity:
        print(f"   ⛔ 流动性不足，跳过后续检查")
        report_lines.append("⛔ 流动性不足")
        print("=" * 70)
        report_lines.append("")
        send_telegram("\n".join(report_lines))
        return

    # 2.1 上线后观察流动性是否瞬间被抽走
    if OBSERVE_SECONDS > 0:
        print(f"   ⏳ 观察期: {OBSERVE_SECONDS}秒，检测是否瞬间撤池")
        sleep(OBSERVE_SECONDS)
        liquidity_base = check_liquidity(pair_address, base_token_address)
        drop_pct = 0.0
        if initial_liquidity_base > 0:
            drop_pct = round((initial_liquidity_base - liquidity_base) / initial_liquidity_base * 100, 1)

        print(f"   观察后流动性: {liquidity_base:.4f} {base_symbol} (下降 {drop_pct}%)")
        report_lines.append(f"观察后流动性: {liquidity_base:.4f} {base_symbol} (下降 {drop_pct}%)")

        if liquidity_base <= 0 or drop_pct >= MAX_LIQUIDITY_DROP_PCT:
            print(f"   ❌ 高风险: 观察期内疑似撤池 (下降阈值: {MAX_LIQUIDITY_DROP_PCT}%)")
            report_lines.append(f"❌ 高风险: 观察期内疑似撤池 (下降阈值: {MAX_LIQUIDITY_DROP_PCT}%)")
            report_lines.append("🔴 强烈不建议买入")
            print("=" * 70)
            report_lines.append("")
            send_telegram("\n".join(report_lines))
            return

    # 3. 蜜罐检测
    is_honeypot, hp_msg, tax_pct = check_honeypot(token_address, base_token_address, base_symbol)
    hp_status = "❌ 蜜罐!" if is_honeypot else "✅ 非蜜罐"
    print(f"   {hp_status} - {hp_msg}")
    report_lines.append(f"{'❌ 蜜罐' if is_honeypot else '✅ 非蜜罐'} - {hp_msg}")

    # 4. LP 锁定检查
    is_locked, lock_pct = check_lp_locked(pair_address)
    lock_status = "✅" if is_locked else "⚠️"
    print(f"   {lock_status} LP锁定: {lock_pct}% (阈值: {MIN_LP_LOCK_PCT}%)")
    report_lines.append(f"{lock_status} LP锁定: {lock_pct}%")

    # 5. 合约验证检查
    verified = check_contract_verified(token_address)
    if verified is True:
        print(f"   ✅ 合约已验证")
        report_lines.append("✅ 合约已验证")
    elif verified is False:
        print(f"   ⚠️ 合约未验证")
        report_lines.append("⚠️ 合约未验证")
    else:
        print(f"   ⏭️ 合约验证检查跳过(无API Key)")

    # 6. 综合评估
    print("-" * 70)
    safe_count = sum([
        liquidity_base >= min_liquidity,
        not is_honeypot,
        is_locked,
        verified is True
    ])
    total_checks = 4
    if verified is None:
        total_checks = 3

    print(f"   安全评分: {safe_count}/{total_checks}")
    report_lines.append(f"\n安全评分: {safe_count}/{total_checks}")

    if safe_count == total_checks:
        print(f"   🟢 所有检查通过!")
        report_lines.append("🟢 所有检查通过!")
    elif safe_count >= total_checks - 1:
        print(f"   🟡 基本安全，建议小心")
        report_lines.append("🟡 基本安全，建议小心")
    else:
        print(f"   🔴 高风险，不建议买入")
        report_lines.append("🔴 高风险，不建议买入")

    print("=" * 70)
    report_lines.append("")

    send_telegram("\n".join(report_lines))
    logging.info(f"分析完成: {token_address} 评分={safe_count}/{total_checks}")


def analyze_pair_index(pair_index, block_number, is_backfill=False):
    """按交易对索引分析目标代币"""
    pair_address = Web3.to_checksum_address(factoryContract.functions.allPairs(pair_index).call())
    token0, token1 = get_pair_tokens(pair_address)

    if token0 is None or token1 is None:
        print(f"{ts()} [跳过] index={pair_index} 原因: 无法读取交易对代币")
        return

    token0_l = token0.lower()
    token1_l = token1.lower()
    target_token = None
    base_token_address = None
    base_symbol = None

    if token0_l in ACTIVE_BASE_TOKEN_ADDRESSES and token1_l not in ACTIVE_BASE_TOKEN_ADDRESSES:
        target_token = token1
        base_token_address = token0
    elif token1_l in ACTIVE_BASE_TOKEN_ADDRESSES and token0_l not in ACTIVE_BASE_TOKEN_ADDRESSES:
        target_token = token0
        base_token_address = token1

    if not target_token:
        if not is_backfill:
            print(f"{ts()} [跳过] index={pair_index} pair={pair_address} 原因: 非基准币对 (token0=...{token0_l[-6:]} token1=...{token1_l[-6:]})")
        return

    if not MONITOR_ALL_NEW_TOKENS and not target_token.lower().endswith(ADDRESS_SUFFIX):
        base_sym = BASE_TOKEN_SYMBOL_BY_ADDRESS.get(base_token_address.lower(), "BASE")
        print(f"{ts()} [跳过] index={pair_index} ...{target_token[-10:]} 原因: 地址不以 '{ADDRESS_SUFFIX}' 结尾 (base={base_sym})")
        return

    base_symbol = BASE_TOKEN_SYMBOL_BY_ADDRESS.get(base_token_address.lower(), "BASE")
    if is_backfill:
        print(f"{ts()} [回溯命中] index={pair_index} pair={pair_address}")

    analyze_token(target_token, pair_address, block_number, base_token_address, base_symbol)


# ─── 主监控循环 ─────────────────────────────────────────

def monitor():
    last_block = client.eth.block_number
    last_pair_count = factoryContract.functions.allPairsLength().call()
    idle_rounds = 0
    print(f"\n{ts()} 开始监控 PancakeSwap 新交易对...")
    if MONITOR_ALL_NEW_TOKENS:
        print(f"{ts()} 过滤条件: 关闭后缀过滤，监控所有新币")
    else:
        print(f"{ts()} 过滤条件: 代币地址以 '{ADDRESS_SUFFIX}' 结尾")
    print(f"{ts()} 基准币: {', '.join(ACTIVE_BASE_TOKEN_SYMBOLS)}")
    print(f"{ts()} 最低流动性阈值: {MIN_LIQUIDITY_BY_BASE}")
    print(f"{ts()} 观察期: {OBSERVE_SECONDS}秒 (撤池下降阈值: {MAX_LIQUIDITY_DROP_PCT}%)")
    print(f"{ts()} LP锁定阈值: {MIN_LP_LOCK_PCT}%")
    print(f"{ts()} 启动回溯: 最近 {STARTUP_BACKFILL_PAIRS} 个新池")
    print(f"{ts()} 起始区块: {last_block}")
    print(f"{ts()} 当前交易对总数: {last_pair_count}")
    print(f"{ts()} 轮询间隔: {POLL_INTERVAL}秒")
    print(f"{ts()} Telegram 通知: {'已配置' if TELEGRAM_BOT_TOKEN else '未配置'}")
    print("-" * 70)

    if STARTUP_BACKFILL_PAIRS > 0:
        backfill_start = max(0, last_pair_count - STARTUP_BACKFILL_PAIRS)
        total_bf = last_pair_count - backfill_start
        print(f"{ts()} 执行启动回溯: index {backfill_start} -> {last_pair_count - 1} (共{total_bf}个)")
        for idx, pair_index in enumerate(range(backfill_start, last_pair_count)):
            if idx > 0 and idx % 500 == 0:
                print(f"{ts()} 回溯进度: {idx}/{total_bf}")
            try:
                analyze_pair_index(pair_index, last_block, is_backfill=True)
            except Exception as e:
                logging.exception(f"回溯分析出错 index={pair_index}: {e}")
                print(f"{ts()} 回溯分析出错 index={pair_index}: {e}")
        print(f"{ts()} 启动回溯完成")
        print("-" * 70)

    while True:
        try:
            current_block = client.eth.block_number

            if current_block <= last_block:
                sleep(POLL_INTERVAL)
                continue

            # 每10个块打印一次心跳，方便确认程序在持续运行
            if current_block % 10 == 0:
                print(f"{ts()} 监控中... 当前区块: {current_block}")

            try:
                current_pair_count = factoryContract.functions.allPairsLength().call()
            except Exception as e:
                logging.warning(f"读取交易对总数失败: {e}")
                print(f"{ts()} 读取交易对总数失败: {e}")
                sleep(POLL_INTERVAL)
                continue

            if current_pair_count > last_pair_count:
                new_pairs = current_pair_count - last_pair_count
                print(f"{ts()} 检测到 {new_pairs} 个新交易对 (总数: {current_pair_count})")
                idle_rounds = 0

                for pair_index in range(last_pair_count, current_pair_count):
                    try:
                        analyze_pair_index(pair_index, current_block, is_backfill=False)
                    except Exception as e:
                        logging.exception(f"分析新交易对出错 index={pair_index}: {e}")
                        print(f"{ts()} 分析新交易对出错 index={pair_index}: {e}")

                last_pair_count = current_pair_count
            else:
                idle_rounds += 1
                if idle_rounds % 30 == 0:
                    print(f"{ts()} 暂无新交易对 (总数: {current_pair_count})")

            last_block = current_block

        except Exception as e:
            logging.exception(f"监控循环出错: {e}")
            print(f"{ts()} 出错: {e}，{POLL_INTERVAL}秒后重试...")

        sleep(POLL_INTERVAL)


if __name__ == '__main__':
    mode_display = "ALL" if MONITOR_ALL_NEW_TOKENS else ADDRESS_SUFFIX
    print(f"""
╔══════════════════════════════════════════════════╗
║     BSC 新币监控器 - PancakeSwap PairCreated     ║
║     过滤地址后缀: {mode_display:>8s}                       ║
╚══════════════════════════════════════════════════╝
    """)
    try:
        monitor()
    except KeyboardInterrupt:
        print(f"\n{ts()} 监控已停止")
    except Exception as e:
        logging.exception(e)
        print(f"致命错误: {e}")