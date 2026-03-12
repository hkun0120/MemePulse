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
BSCSCAN_API_KEY = config.get("BSCSCAN_API_KEY", "")
TELEGRAM_BOT_TOKEN = config.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = config.get("TELEGRAM_CHAT_ID", "")
RPC_URL = config.get("RPC_URL", "https://bsc-dataseed1.binance.org")

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

factoryContract = client.eth.contract(address=FACTORY_ADDRESS, abi=factoryAbi)
routerContract = client.eth.contract(address=ROUTER_ADDRESS, abi=routerAbi)

# PairCreated 事件签名
PAIR_CREATED_TOPIC = Web3.keccak(text="PairCreated(address,address,address,uint256)").hex()

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


def check_liquidity(pair_address, token_address):
    """检查流动性池中的 BNB 数量"""
    try:
        pair_contract = client.eth.contract(address=Web3.to_checksum_address(pair_address), abi=lpAbi)
        reserves = pair_contract.functions.getReserves().call()
        token0 = pair_contract.functions.token0().call()

        if token0.lower() == WBNB.lower():
            bnb_reserve = reserves[0]
        else:
            bnb_reserve = reserves[1]

        bnb_amount = Web3.from_wei(bnb_reserve, 'ether')
        return float(bnb_amount)
    except Exception as e:
        logging.warning(f"检查流动性失败 {pair_address}: {e}")
        return 0.0


def check_honeypot(token_address):
    """
    模拟买卖检测蜜罐:
    用 getAmountsOut 模拟买入0.01BNB，再模拟用得到的token卖出
    如果卖出时 revert 或税率过高则判定为蜜罐
    """
    try:
        buy_amount = Web3.to_wei(0.01, 'ether')

        # 模拟买入
        amounts_out = routerContract.functions.getAmountsOut(
            buy_amount, [WBNB, Web3.to_checksum_address(token_address)]
        ).call()
        tokens_bought = amounts_out[-1]

        if tokens_bought == 0:
            return True, "买入返回0", 0

        # 模拟卖出
        amounts_back = routerContract.functions.getAmountsOut(
            tokens_bought, [Web3.to_checksum_address(token_address), WBNB]
        ).call()
        bnb_back = amounts_back[-1]

        # 计算来回税率
        tax_rate = 1 - (bnb_back / buy_amount)
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
        return lock_pct > 50, lock_pct

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


def analyze_token(token_address, pair_address, block_number):
    """对发现的代币执行全套安全检查并输出报告"""

    print("\n" + "=" * 70)
    print(f"🎯 发现目标代币! 地址以 '{ADDRESS_SUFFIX}' 结尾")
    print(f"   Token:  {token_address}")
    print(f"   Pair:   {pair_address}")
    print(f"   区块:   {block_number}")
    print(f"   BscScan: https://bscscan.com/address/{token_address}")
    print("-" * 70)

    report_lines = [
        f"<b>🎯 发现目标代币!</b>",
        f"地址以 <code>{ADDRESS_SUFFIX}</code> 结尾",
        f"Token: <code>{token_address}</code>",
        f"区块: {block_number}",
        f"BscScan: https://bscscan.com/address/{token_address}",
        ""
    ]

    # 1. 代币基本信息
    info = get_token_info(token_address)
    if info:
        print(f"   名称:   {info['name']} ({info['symbol']})")
        print(f"   精度:   {info['decimals']}")
        print(f"   总供应: {info['total_supply']:,.0f}")
        report_lines.append(f"名称: {info['name']} ({info['symbol']})")
        report_lines.append(f"总供应: {info['total_supply']:,.0f}")
    else:
        print("   ⚠️ 无法获取代币信息")
        report_lines.append("⚠️ 无法获取代币信息")

    # 2. 流动性检查
    liquidity_bnb = check_liquidity(pair_address, token_address)
    liq_status = "✅" if liquidity_bnb >= MIN_LIQUIDITY_BNB else "❌"
    print(f"   {liq_status} 流动性: {liquidity_bnb:.4f} BNB (最低要求: {MIN_LIQUIDITY_BNB} BNB)")
    report_lines.append(f"{liq_status} 流动性: {liquidity_bnb:.4f} BNB")

    if liquidity_bnb < MIN_LIQUIDITY_BNB:
        print(f"   ⛔ 流动性不足，跳过后续检查")
        report_lines.append("⛔ 流动性不足")
        print("=" * 70)
        report_lines.append("")
        send_telegram("\n".join(report_lines))
        return

    # 3. 蜜罐检测
    is_honeypot, hp_msg, tax_pct = check_honeypot(token_address)
    hp_status = "❌ 蜜罐!" if is_honeypot else "✅ 非蜜罐"
    print(f"   {hp_status} - {hp_msg}")
    report_lines.append(f"{'❌ 蜜罐' if is_honeypot else '✅ 非蜜罐'} - {hp_msg}")

    # 4. LP 锁定检查
    is_locked, lock_pct = check_lp_locked(pair_address)
    lock_status = "✅" if is_locked else "⚠️"
    print(f"   {lock_status} LP锁定: {lock_pct}%")
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
        liquidity_bnb >= MIN_LIQUIDITY_BNB,
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


# ─── 主监控循环 ─────────────────────────────────────────

def monitor():
    last_block = client.eth.block_number
    print(f"\n{ts()} 开始监控 PancakeSwap 新交易对...")
    print(f"{ts()} 过滤条件: 代币地址以 '{ADDRESS_SUFFIX}' 结尾")
    print(f"{ts()} 最低流动性: {MIN_LIQUIDITY_BNB} BNB")
    print(f"{ts()} 起始区块: {last_block}")
    print(f"{ts()} 轮询间隔: {POLL_INTERVAL}秒")
    print(f"{ts()} Telegram 通知: {'已配置' if TELEGRAM_BOT_TOKEN else '未配置'}")
    print("-" * 70)

    while True:
        try:
            current_block = client.eth.block_number

            if current_block <= last_block:
                sleep(POLL_INTERVAL)
                continue

            # 每50个块打印一次心跳
            if (current_block - last_block) == 1 and current_block % 50 == 0:
                print(f"{ts()} 监控中... 当前区块: {current_block}")

            # 拉取 PairCreated 事件日志
            try:
                logs = client.eth.get_logs({
                    'fromBlock': last_block + 1,
                    'toBlock': current_block,
                    'address': FACTORY_ADDRESS,
                    'topics': [PAIR_CREATED_TOPIC]
                })
            except Exception as e:
                logging.warning(f"获取日志失败: {e}")
                sleep(POLL_INTERVAL)
                continue

            for log in logs:
                # 解析 PairCreated(token0, token1, pair, uint)
                token0 = Web3.to_checksum_address('0x' + log['topics'][1].hex()[-40:])
                token1 = Web3.to_checksum_address('0x' + log['topics'][2].hex()[-40:])
                pair_address = Web3.to_checksum_address('0x' + log['data'].hex()[26:66])

                # 判断哪个是新代币（排除 WBNB 侧）
                target_token = None
                if token0.lower() != WBNB.lower() and token0.lower().endswith(ADDRESS_SUFFIX):
                    target_token = token0
                elif token1.lower() != WBNB.lower() and token1.lower().endswith(ADDRESS_SUFFIX):
                    target_token = token1

                if target_token:
                    try:
                        analyze_token(target_token, pair_address, log['blockNumber'])
                    except Exception as e:
                        logging.exception(f"分析代币出错: {target_token}: {e}")
                        print(f"  ⚠️ 分析出错: {e}")

            last_block = current_block

        except Exception as e:
            logging.exception(f"监控循环出错: {e}")
            print(f"{ts()} 出错: {e}，{POLL_INTERVAL}秒后重试...")

        sleep(POLL_INTERVAL)


if __name__ == '__main__':
    print(f"""
╔══════════════════════════════════════════════════╗
║     BSC 新币监控器 - PancakeSwap PairCreated     ║
║     过滤地址后缀: {ADDRESS_SUFFIX:>8s}                       ║
╚══════════════════════════════════════════════════╝
    """)
    try:
        monitor()
    except KeyboardInterrupt:
        print(f"\n{ts()} 监控已停止")
    except Exception as e:
        logging.exception(e)
        print(f"致命错误: {e}")