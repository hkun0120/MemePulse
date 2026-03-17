"""
Twitter KOL 监听脚本 - 实时监测 4444 币的推文及KOL宣传
扫描关键词、统计参与宣传的KOL、按影响力排序、每小时推送报告
"""

import tweepy
import json
import os
import logging
import requests
from datetime import datetime, timedelta
from time import sleep, time
from collections import defaultdict
import re

# ─── 配置 ───────────────────────────────────────────────
CONFIG_FILE = './twitter_settings.json'

if not os.path.exists(CONFIG_FILE):
    print(f"错误: 未找到 {CONFIG_FILE}")
    print("请先创建 twitter_settings.json，包含 Twitter API 密钥")
    exit(1)

with open(CONFIG_FILE) as f:
    config = json.load(f)

TWITTER_API_KEY = config.get("TWITTER_API_KEY", "")
TWITTER_API_SECRET = config.get("TWITTER_API_SECRET", "")
TWITTER_ACCESS_TOKEN = config.get("TWITTER_ACCESS_TOKEN", "")
TWITTER_ACCESS_TOKEN_SECRET = config.get("TWITTER_ACCESS_TOKEN_SECRET", "")
TWITTER_BEARER_TOKEN = config.get("TWITTER_BEARER_TOKEN", "")  # for Twitter API v2

TELEGRAM_BOT_TOKEN = config.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = config.get("TELEGRAM_CHAT_ID", "")

# 监听的关键词
KEYWORDS = config.get("KEYWORDS", ["4444"])  # e.g. ["4444", "Meme4444", "meme币4444"]
LANGUAGES = config.get("LANGUAGES", ["zh"])  # 只监听中文推文

# 日志
os.makedirs('./logs', exist_ok=True)
log_format = '%(levelname)s: %(asctime)s %(message)s'
logging.basicConfig(
    filename='./logs/twitter_monitor.log',
    level=logging.INFO,
    format=log_format
)

# ─── 全局变量 ───────────────────────────────────────────
kol_stats = defaultdict(lambda: {
    "user_id": "",
    "username": "",
    "name": "",
    "followers": 0,
    "tweets": [],  # [(timestamp, tweet_text, tweet_id)]
    "first_mention": None,
    "last_mention": None,
})

def ts():
    return datetime.fromtimestamp(time())


def send_telegram(message):
    """发送 Telegram 通知"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logging.warning("Telegram 未配置，跳过发送")
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }, timeout=10)
        logging.info("Telegram 发送成功")
    except Exception as e:
        logging.warning(f"Telegram 发送失败: {e}")


def get_twitter_client_v2():
    """初始化 Twitter API v2 客户端 (推荐用于最新API)"""
    if not TWITTER_BEARER_TOKEN:
        logging.error("TWITTER_BEARER_TOKEN 未配置")
        return None
    try:
        client = tweepy.Client(bearer_token=TWITTER_BEARER_TOKEN)
        return client
    except Exception as e:
        logging.error(f"初始化 Twitter 客户端失败: {e}")
        return None


def search_tweets_v2(client, keyword, max_results=100):
    """用 Twitter API v2 搜索关键词推文"""
    if not client:
        return []
    
    try:
        # 构建查询：关键词 + 中文 + 排除转推 + 在最近7天内
        query = f'{keyword} lang:zh -is:retweet'
        
        # 获取最近7天的推文（免费API只能查最近7天）
        start_time = datetime.utcnow() - timedelta(days=7)
        end_time = datetime.utcnow()
        
        tweets = client.search_recent_tweets(
            query=query,
            max_results=min(100, max_results),
            start_time=start_time,
            end_time=end_time,
            tweet_fields=['created_at', 'public_metrics', 'author_id'],
            user_fields=['username', 'name', 'public_metrics'],
            expansions=['author_id']
        )
        
        return tweets
    except Exception as e:
        logging.warning(f"搜索推文失败 (query={keyword}): {e}")
        return []


def process_tweets(tweets_response):
    """解析推文响应，提取 KOL 信息"""
    if not tweets_response or not tweets_response.data:
        return
    
    # 构建 user_id -> user_info 的映射
    user_map = {}
    if tweets_response.includes and tweets_response.includes.get('users'):
        for user in tweets_response.includes['users']:
            user_map[user.id] = user
    
    for tweet in tweets_response.data:
        try:
            user = user_map.get(tweet.author_id)
            if not user:
                continue
            
            username = user.username
            user_id = str(user.id)
            
            # 更新 KOL 信息
            if user_id not in kol_stats:
                kol_stats[user_id] = {
                    "user_id": user_id,
                    "username": username,
                    "name": user.name,
                    "followers": user.public_metrics.get('followers_count', 0),
                    "tweets": [],
                    "first_mention": datetime.fromisoformat(tweet.created_at.replace('Z', '+00:00')),
                    "last_mention": datetime.fromisoformat(tweet.created_at.replace('Z', '+00:00')),
                }
            else:
                kol_stats[user_id]['followers'] = user.public_metrics.get('followers_count', 0)
                kol_stats[user_id]['last_mention'] = datetime.fromisoformat(tweet.created_at.replace('Z', '+00:00'))
            
            # 添加推文
            kol_stats[user_id]['tweets'].append({
                "created_at": tweet.created_at,
                "text": tweet.text[:100] + "..." if len(tweet.text) > 100 else tweet.text,
                "tweet_id": tweet.id,
                "likes": tweet.public_metrics.get('like_count', 0),
                "retweets": tweet.public_metrics.get('retweet_count', 0),
            })
            
            logging.info(f"发现 KOL: @{username} ({user.name}) - 粉丝数: {user.public_metrics.get('followers_count', 'N/A')}")
        
        except Exception as e:
            logging.warning(f"处理推文出错: {e}")
            continue


def generate_hourly_report():
    """生成并发送每小时的KOL宣传报告"""
    if not kol_stats:
        logging.info("本小时无新的 KOL 宣传")
        return
    
    # 按粉丝数排序
    sorted_kols = sorted(
        kol_stats.items(),
        key=lambda x: x[1]['followers'],
        reverse=True
    )
    
    report_lines = [
        f"<b>📢 4444 币KOL宣传统计 - {ts().strftime('%Y-%m-%d %H:%M')}</b>",
        f"共发现 {len(kol_stats)} 个 KOL，{sum(len(v['tweets']) for v in kol_stats.values())} 条相关推文",
        ""
    ]
    
    for user_id, info in sorted_kols[:20]:  # 只显示前20名
        influence = "🔥" if info['followers'] > 100000 else "⭐" if info['followers'] > 10000 else "💬"
        report_lines.append(
            f"{influence} <b>@{info['username']}</b> ({info['name']})"
        )
        report_lines.append(
            f"   粉丝: {info['followers']:,} | 推文: {len(info['tweets'])} 条"
        )
        
        # 显示最近的推文
        if info['tweets']:
            latest = info['tweets'][-1]
            report_lines.append(
                f"   最近: {latest['text'][:60]}..."
            )
            report_lines.append(
                f"   互动: ❤️ {latest['likes']} 🔄 {latest['retweets']}"
            )
        
        report_lines.append("")
    
    report_lines.append(f"推文链接: https://twitter.com/search?q=4444&lang=zh")
    report_lines.append("")
    
    print("\n".join(report_lines))
    send_telegram("\n".join(report_lines))
    logging.info(f"已发送每小时报告，KOL数={len(kol_stats)}")


def hourly_monitor():
    """每小时执行一次监听和报告"""
    while True:
        try:
            print(f"\n{ts()} 开始扫描 Twitter 关键词...")
            
            client = get_twitter_client_v2()
            if not client:
                print(f"{ts()} Twitter 客户端初始化失败，{300}秒后重试")
                sleep(300)
                continue
            
            # 搜索所有关键词
            for keyword in KEYWORDS:
                print(f"{ts()} 搜索关键词: {keyword}")
                tweets_response = search_tweets_v2(client, keyword, max_results=100)
                process_tweets(tweets_response)
                sleep(2)  # 避免超出 API 速率限制
            
            # 生成报告
            generate_hourly_report()
            
            # 清空统计（准备下一小时）
            kol_stats.clear()
            
            # 等待1小时
            print(f"{ts()} 监听完成，等待1小时后再执行...")
            sleep(3600)
        
        except Exception as e:
            logging.exception(f"监听出错: {e}")
            print(f"{ts()} 出错: {e}，300秒后重试...")
            sleep(300)


if __name__ == '__main__':
    print(f"""
╔══════════════════════════════════════════════════╗
║        Twitter KOL 关键词监听脚本 - 4444币      ║
║          每小时自动扫描并统计KOL宣传              ║
╚══════════════════════════════════════════════════╝
    """)
    
    if not all([TWITTER_BEARER_TOKEN, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID]):
        print("❌ 错误: Twitter API 或 Telegram 配置不完整")
        print("请编辑 twitter_settings.json 并填入有效的配置")
        exit(1)
    
    try:
        hourly_monitor()
    except KeyboardInterrupt:
        print(f"\n{ts()} 监听已停止")
    except Exception as e:
        logging.exception(e)
        print(f"致命错误: {e}")
