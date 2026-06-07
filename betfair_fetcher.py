"""
Betfair Exchange 必发指数采集器
===============================
使用 Betfair Developer API (免费延迟密钥) 获取:
  - 必发指数 (Betfair Index): 各结果成交量占比
  - 买卖挂单量 (Back/Lay Volume): 市场深度
  - 最后成交价 (Last Traded Price): 实时价格信号
  - 冷热指数: 大额资金流向方向

注册免费 API Key: https://docs.developer.betfair.com/
  1. 注册 Betfair 账户 (无需入金)
  2. 创建 App Key (选择 "Delayed" 免费)
  3. 将 Key 设为环境变量 BETFAIR_APP_KEY
  4. 运行: python betfair_fetcher.py

Usage:
  python betfair_fetcher.py               # 获取所有世界杯市场
  python betfair_fetcher.py --watch 300   # 每5分钟刷新
  python betfair_fetcher.py --export      # 导出到 data/betfair_index.json
"""

import json
import os
import ssl
import time
import sys
from pathlib import Path
from datetime import datetime
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

DATA_DIR = Path(__file__).parent / "data"

# ============================================================
# 1. BETFAIR API CONFIG
# ============================================================

# Betfair API endpoints
IDENTITY_URL = "https://identitysso.betfair.com/api/login"
EXCHANGE_URL = "https://api.betfair.com/exchange/betting/rest/v1.0/"

# Get from environment or set here
APP_KEY = os.environ.get("BETFAIR_APP_KEY", "")
USERNAME = os.environ.get("BETFAIR_USERNAME", "")
PASSWORD = os.environ.get("BETFAIR_PASSWORD", "")

# Session token (obtained via login)
_SESSION_TOKEN = None

# ============================================================
# 2. AUTHENTICATION
# ============================================================

def betfair_login(app_key: str = None, username: str = None, password: str = None) -> str:
    """Login to Betfair API and return session token."""
    global _SESSION_TOKEN

    ak = app_key or APP_KEY
    un = username or USERNAME
    pw = password or PASSWORD

    if not ak:
        print("  [ERROR] No Betfair App Key. Set BETFAIR_APP_KEY env var.")
        print("  Get free key at: https://docs.developer.betfair.com/")
        return ""

    headers = {
        "X-Application": ak,
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
    }

    body = f"username={un}&password={pw}"

    try:
        req = Request(IDENTITY_URL, data=body.encode(), headers=headers)
        ctx = ssl.create_default_context()
        with urlopen(req, timeout=15, context=ctx) as resp:
            data = json.loads(resp.read().decode())
            token = data.get("token", "")
            if token:
                _SESSION_TOKEN = token
                print(f"  [OK] Betfair login successful")
                return token
            else:
                print(f"  [ERROR] Login failed: {data.get('error', 'unknown')}")
                return ""
    except Exception as e:
        print(f"  [ERROR] Betfair login error: {e}")
        return ""


# ============================================================
# 3. API CALLS
# ============================================================

def _call_betfair(method: str, params: dict, app_key: str = None) -> dict:
    """Make a JSON-RPC call to Betfair Exchange API."""
    global _SESSION_TOKEN

    ak = app_key or APP_KEY
    if not _SESSION_TOKEN:
        token = betfair_login()
        if not token:
            return {"error": "Not authenticated"}

    headers = {
        "X-Application": ak,
        "X-Authentication": _SESSION_TOKEN,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    body = json.dumps({
        "jsonrpc": "2.0",
        "method": method,
        "params": params,
    })

    try:
        req = Request(EXCHANGE_URL, data=body.encode(), headers=headers)
        ctx = ssl.create_default_context()
        with urlopen(req, timeout=15, context=ctx) as resp:
            result = json.loads(resp.read().decode())
            if "error" in result:
                print(f"  [API Error] {result['error']}")
                return {"error": result["error"]}
            return result.get("result", {})
    except HTTPError as e:
        body = e.read().decode() if e.fp else ""
        print(f"  [HTTP {e.code}] {body[:200]}")
        return {"error": f"HTTP {e.code}"}
    except Exception as e:
        print(f"  [Error] {e}")
        return {"error": str(e)}


def list_world_cup_markets() -> list:
    """Find all World Cup 2026 markets on Betfair Exchange."""
    # Search for World Cup 2026 markets
    # Event type 1 = Soccer
    params = {
        "filter": {
            "eventTypeIds": [1],  # Soccer
            "marketCountries": ["GB", "US", "MX", "CA"],
            "marketTypeCodes": ["MATCH_ODDS", "WINNER", "CORRECT_SCORE"],
            "textQuery": "World Cup 2026",
            "turnInPlayEnabled": True,
        },
        "marketProjection": ["EVENT", "MARKET_START_TIME", "COMPETITION"],
        "maxResults": 200,
    }
    return _call_betfair("SportsAPING/v1.0/listMarketCatalogue", params)


def get_market_book(market_ids: list) -> list:
    """Get current prices and volumes for markets (必发指数核心)."""
    params = {
        "marketIds": market_ids,
        "priceProjection": {
            "priceData": ["EX_BEST_OFFERS", "EX_TRADED", "EX_ALL_OFFERS"],
            "virtualise": False,
        },
        "orderProjection": "ALL",
        "matchProjection": "ROLLED_UP_BY_AVG_PRICE",
    }
    result = _call_betfair("SportsAPING/v1.0/listMarketBook", params)
    return result if isinstance(result, list) else []


# ============================================================
# 4. BETTERFAIR INDEX (必发指数) COMPUTATION
# ============================================================

def compute_betfair_index(market_book: dict) -> dict:
    """
    Compute 必发指数 from Betfair market data.

    Returns per-selection:
      - betfair_index: 成交量占比 (0-1)
      - total_matched: 总成交量
      - back_price / lay_price: 最佳买卖价
      - back_volume / lay_volume: 挂单量 (市场深度)
      - last_traded: 最后成交价
      - money_flow: 资金流向 (+ = 买方主导, - = 卖方主导)
    """
    runners = market_book.get("runners", [])
    total_matched = sum(r.get("ex", {}).get("totalMatched", 0) or 0 for r in runners)

    results = {}
    for r in runners:
        selection_id = str(r.get("selectionId", ""))
        ex = r.get("ex", {}) or {}

        # Available to back (买方最佳价)
        back_prices = ex.get("availableToBack", [])
        best_back = back_prices[0] if back_prices else {}
        back_volume = sum(b.get("size", 0) for b in back_prices[:3])

        # Available to lay (卖方最佳价)
        lay_prices = ex.get("availableToLay", [])
        best_lay = lay_prices[0] if lay_prices else {}
        lay_volume = sum(l.get("size", 0) for l in lay_prices[:3])

        # Traded volume
        matched = ex.get("totalMatched", 0) or 0

        # Betfair Index = 该结果成交量 / 总成交量
        bf_index = matched / total_matched if total_matched > 0 else 0

        # Money flow: compare back volume vs lay volume
        # Back volume > Lay volume → 买方主导 (看涨)
        # Lay volume > Back volume → 卖方主导 (看跌)
        if back_volume + lay_volume > 0:
            money_flow = (back_volume - lay_volume) / (back_volume + lay_volume)
        else:
            money_flow = 0

        results[selection_id] = {
            "betfair_index": round(bf_index, 4),
            "total_matched": round(matched, 2),
            "back_price": best_back.get("price"),
            "back_size": best_back.get("size"),
            "back_volume": round(back_volume, 2),
            "lay_price": best_lay.get("price"),
            "lay_size": best_lay.get("size"),
            "lay_volume": round(lay_volume, 2),
            "last_traded": best_back.get("price"),  # proxy
            "money_flow": round(money_flow, 4),
            "status": r.get("status", ""),
        }

    return {
        "total_matched": round(total_matched, 2),
        "market_id": market_book.get("marketId", ""),
        "runners": results,
        "timestamp": datetime.now().isoformat(),
    }


# ============================================================
# 5. FALLBACK: 模拟必发指数 (无 API 密钥时)
# ============================================================

def simulate_betfair_index(betting_data: dict) -> dict:
    """
    当 Betfair API 不可用时，从现有赔率数据推算模拟必发指数。

    原理：
      1. 市场隐含概率 → 模拟成交量分配
      2. 多庄家赔率差异 → 模拟资金流向
      3. 赔率变异 → 模拟市场分歧度

    这不是真必发数据，但在无 API 时提供有限参考。
    """
    winner_odds = betting_data.get("tournament_winner_raw_odds", [])
    if not winner_odds:
        return {"error": "No betting data available", "simulated": True}

    # Normalize probabilities
    total_prob = sum(o.get("implied_prob", 0) for o in winner_odds)
    if total_prob <= 0:
        return {"error": "Invalid odds data", "simulated": True}

    # Simulate total market volume (arbitrary, relative)
    simulated_total = 100000.0  # GBP100k simulated pool

    runners = {}
    for o in winner_odds[:48]:  # All 48 teams
        team = o["team"]
        prob = o.get("implied_prob", 0.001)
        norm_prob = prob / total_prob

        # Simulated matched volume proportional to probability
        matched = round(simulated_total * norm_prob, 2)

        # Back price = 1/prob (decimal odds)
        fair_price = round(1.0 / max(prob, 0.001), 2)
        back_price = round(fair_price * 0.98, 2)  # Slightly below fair
        lay_price = round(fair_price * 1.02, 2)   # Slightly above fair

        # Simulated money flow: favorites get slightly more back volume
        money_flow = round((prob - 0.02) * 2, 4)  # Range roughly -0.04 to +0.36]

        runners[team] = {
            "betfair_index": round(norm_prob, 4),
            "total_matched": matched,
            "back_price": back_price,
            "back_size": round(matched * 0.3, 2),
            "lay_price": lay_price,
            "lay_size": round(matched * 0.2, 2),
            "money_flow": max(-1.0, min(1.0, money_flow)),
            "status": "ACTIVE",
            "simulated": True,
        }

    return {
        "total_matched": round(simulated_total, 2),
        "market_type": "WORLD_CUP_WINNER",
        "timestamp": datetime.now().isoformat(),
        "runners": runners,
        "simulated": True,
        "_note": "Simulated from bookmaker odds — NOT real Betfair data. Set BETFAIR_APP_KEY for live data.",
    }


# ============================================================
# 6. MAIN REFRESH LOGIC
# ============================================================

def fetch_betfair_index(use_live: bool = False) -> dict:
    """
    Fetch 必发指数 for World Cup 2026.

    If use_live=True and credentials available: uses real Betfair API.
    Otherwise: falls back to simulated data from betting_odds.json.
    """
    if use_live and APP_KEY:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Fetching live Betfair Exchange data...")

        # Login
        if not _SESSION_TOKEN:
            token = betfair_login()
            if not token:
                print("  Falling back to simulated data...")
                betting = json.load(open(DATA_DIR / "betting_odds.json", "r", encoding="utf-8"))
                return simulate_betfair_index(betting)

        # Find World Cup markets
        markets = list_world_cup_markets()
        if isinstance(markets, dict) and "error" in markets:
            print(f"  Falling back to simulated data...")
            betting = json.load(open(DATA_DIR / "betting_odds.json", "r", encoding="utf-8"))
            return simulate_betfair_index(betting)

        # Get winner market
        winner_markets = [m for m in markets
                          if m.get("marketName", "").lower() in ("winner", "world cup 2026 winner")]
        if not winner_markets:
            winner_markets = markets[:1]  # Take first market as fallback

        market_ids = [m["marketId"] for m in winner_markets[:5]]

        # Get market books
        books = get_market_book(market_ids)
        if not books:
            betting = json.load(open(DATA_DIR / "betting_odds.json", "r", encoding="utf-8"))
            return simulate_betfair_index(betting)

        # Compute 必发指数
        result = compute_betfair_index(books[0])
        print(f"  [OK] Betfair index computed: {len(result['runners'])} runners, "
              f"total matched: GBP{result['total_matched']:,.0f}")
        return result

    else:
        # Simulated mode
        if not APP_KEY and use_live:
            print("  [NOTE] No BETFAIR_APP_KEY set. Using simulated Betfair index.")
            print("  Get free key: https://docs.developer.betfair.com/")
        betting_path = DATA_DIR / "betting_odds.json"
        if not betting_path.exists():
            return {"error": "betting_odds.json not found", "simulated": True}
        betting = json.load(open(betting_path, "r", encoding="utf-8"))
        return simulate_betfair_index(betting)


def save_betfair_index(data: dict):
    """Save 必发指数 to JSON file for website consumption."""
    export = {
        "updated": datetime.now().isoformat(),
        "source": "betfair_exchange_live" if not data.get("simulated") else "simulated_from_bookmaker_odds",
        "betfair_index": data,
    }
    path = DATA_DIR / "betfair_index.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(export, f, indent=2, ensure_ascii=False)
    print(f"  [OK] Saved to {path}")


def watch_mode(interval: int = 300, use_live: bool = False):
    """Continuously refresh 必发指数 every `interval` seconds."""
    print(f"Watch mode: refreshing every {interval}s. Ctrl+C to stop.")
    try:
        while True:
            data = fetch_betfair_index(use_live=use_live)
            save_betfair_index(data)

            # Print summary
            runners = data.get("runners", {})
            # Sort by betfair_index descending
            sorted_runners = sorted(runners.items(),
                                    key=lambda x: x[1].get("betfair_index", 0),
                                    reverse=True)
            print(f"\n  必发指数 Top 5:")
            for team, info in sorted_runners[:5]:
                bf = info.get("betfair_index", 0)
                mf = info.get("money_flow", 0)
                mf_str = f"↑买" if mf > 0.05 else (f"↓卖" if mf < -0.05 else "—")
                print(f"    {team:<20s} 指数:{bf:>6.1%}  资金流:{mf_str}  "
                      f"成交:GBP{info.get('total_matched',0):,.0f}")

            print(f"\n  Next refresh in {interval}s...\n")
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n  Stopped.")


# ============================================================
# 7. INTEGRATION WITH MODEL
# ============================================================

def load_betfair_index() -> dict:
    """Load the most recent Betfair index snapshot."""
    path = DATA_DIR / "betfair_index.json"
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def get_team_betfair_signal(team: str) -> dict:
    """
    Get 必发指数 signal for a specific team.
    Used by model.py compute_market_sentiment().
    """
    data = load_betfair_index()
    bf = data.get("betfair_index", {})
    runners = bf.get("runners", {})

    # Search by team name in runner keys
    for key, info in runners.items():
        if isinstance(key, str) and team.lower() in key.lower():
            return info

    # Try direct lookup
    return runners.get(team, {})


# ============================================================
# 8. CLI
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("  Betfair Exchange 必发指数 — World Cup 2026")
    print("=" * 60)

    use_live = "--live" in sys.argv
    do_watch = "--watch" in sys.argv
    do_export = "--export" in sys.argv

    if do_watch:
        idx = sys.argv.index("--watch")
        interval = int(sys.argv[idx + 1]) if idx + 1 < len(sys.argv) else 300
        watch_mode(interval, use_live=use_live)
    else:
        data = fetch_betfair_index(use_live=use_live)
        save_betfair_index(data)

        # Print summary
        runners = data.get("runners", {})
        sorted_runners = sorted(runners.items(),
                                key=lambda x: x[1].get("betfair_index", 0),
                                reverse=True)
        print(f"\n  {'='*60}")
        print(f"  必发指数 (Betfair Index) Top 16 — 成交量占比 + 资金流向")
        print(f"  {'='*60}")
        print(f"  {'Team':<20s} {'BF指数':>7s} {'成交额':>10s} {'买价':>7s} {'卖价':>7s} {'资金流'}")
        print(f"  {'-'*20} {'-'*7} {'-'*10} {'-'*7} {'-'*7} {'-'*7}")
        for team, info in sorted_runners[:16]:
            bf = info.get("betfair_index", 0)
            matched = info.get("total_matched", 0)
            back = info.get("back_price", "-")
            lay = info.get("lay_price", "-")
            mf = info.get("money_flow", 0)
            mf_str = "↑" + ("+" if mf > 0 else "") if abs(mf) > 0.03 else "—"
            print(f"  {team:<20s} {bf:>6.1%}  ${matched:>8,.0f}  {str(back):>6s}  {str(lay):>6s}  {mf_str}")

        if data.get("simulated"):
            print(f"\n  [WARN] Simulated data (not live Betfair). Set BETFAIR_APP_KEY for real data.")
            print(f"  Register: https://docs.developer.betfair.com/")
        else:
            print(f"\n  [OK] Live Betfair Exchange data")
