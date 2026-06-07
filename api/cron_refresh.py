"""
Vercel Cron Job — 每日8小时自动刷新数据
=========================================
由 Vercel Cron Jobs 触发，不依赖本地电脑。
只做轻量刷新（新闻+必发+合并），跳过蒙特卡洛模拟（太重）。

配置: vercel.json → crons: [{path: "/api/cron_refresh", schedule: "0 */8 * * *"}]
"""

import json
import sys
import os
from pathlib import Path
from datetime import datetime

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

DATA_DIR = Path(__file__).parent.parent / "data"


def refresh_betfair():
    """Refresh simulated Betfair index from betting odds."""
    try:
        from betfair_fetcher import fetch_betfair_index, save_betfair_index
        data = fetch_betfair_index(use_live=False)
        save_betfair_index(data)
        return True
    except Exception as e:
        print(f"  [betfair] Error: {e}")
        return False


def refresh_news():
    """Attempt to refresh news (may fail on Vercel due to network restrictions)."""
    try:
        from news_feed import fetch_all_news
        fetch_all_news()
        return True
    except Exception as e:
        print(f"  [news] Error (may be normal on Vercel): {e}")
        return False


def merge_data():
    """Merge all JSON files into all_data.json."""
    try:
        merged = {}
        for f in sorted(DATA_DIR.glob("*.json")):
            if f.name == "all_data.json":
                continue
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    merged[f.stem] = json.load(fh)
            except Exception:
                pass

        merged["_meta"] = {
            "last_merged": datetime.now().isoformat(),
            "source": "vercel_cron",
        }

        with open(DATA_DIR / "all_data.json", "w", encoding="utf-8") as f:
            json.dump(merged, f, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"  [merge] Error: {e}")
        return False


def handler(request=None):
    """Vercel serverless function entry point."""
    results = {
        "timestamp": datetime.now().isoformat(),
        "betfair": False,
        "news": False,
        "merge": False,
    }

    # 1. Betfair index (fast, always works)
    results["betfair"] = refresh_betfair()

    # 2. News (may fail on Vercel due to outbound restrictions)
    results["news"] = refresh_news()

    # 3. Merge all_data.json
    results["merge"] = merge_data()

    return {
        "statusCode": 200,
        "body": json.dumps(results, ensure_ascii=False),
        "headers": {"Content-Type": "application/json"},
    }


# For Vercel Python runtime
def lambda_handler(event, context):
    return handler(event)
