"""
必发指数一键设置脚本
==================
使用方法:
  1. 在浏览器打开: https://docs.developer.betfair.com/
  2. 点击 "Create an Application" 注册免费 Delayed App Key
     (不需要入金，选 Delayed 类型即可)
  3. 拿到 App Key 后，运行:
     python setup_betfair.py --key "你的AppKey" --user "你的用户名" --pass "你的密码"
  4. 或者手动设置环境变量后运行:
     python setup_betfair.py

此脚本会自动:
  - 测试 Betfair API 连接
  - 获取 2026 世界杯所有市场数据
  - 生成 beftair_index.json 并更新网站
"""

import os
import sys
import json
import ssl
import subprocess
from pathlib import Path
from urllib.request import Request, urlopen
from datetime import datetime

ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data"


def test_betfair_login(app_key, username, password):
    """Test Betfair API login with provided credentials."""
    print("\n" + "=" * 50)
    print("  测试 Betfair API 连接...")
    print("=" * 50)

    url = "https://identitysso.betfair.com/api/login"
    headers = {
        "X-Application": app_key,
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
    }
    body = f"username={username}&password={password}"

    try:
        ctx = ssl.create_default_context()
        req = Request(url, data=body.encode(), headers=headers)
        with urlopen(req, timeout=15, context=ctx) as resp:
            data = json.loads(resp.read().decode())
            if data.get("token"):
                print("  [OK] Betfair 登录成功!")
                print(f"  Token: {data['token'][:20]}...")
                return data["token"]
            else:
                print(f"  [FAIL] 登录失败: {data.get('error', 'unknown')}")
                print(f"  完整响应: {json.dumps(data, indent=2)}")
                return None
    except Exception as e:
        print(f"  [ERROR] 网络连接失败: {e}")
        print(f"  请检查网络是否能访问 api.betfair.com")
        print(f"  如果被墙，需要开代理后再试")
        return None


def fetch_world_cup_markets(app_key, session_token):
    """Fetch World Cup 2026 winner market from Betfair Exchange."""
    print("\n" + "=" * 50)
    print("  获取世界杯 2026 市场数据...")
    print("=" * 50)

    url = "https://api.betfair.com/exchange/betting/rest/v1.0/"
    headers = {
        "X-Application": app_key,
        "X-Authentication": session_token,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    # Step 1: Find World Cup winner market
    params = {
        "jsonrpc": "2.0",
        "method": "SportsAPING/v1.0/listMarketCatalogue",
        "params": {
            "filter": {
                "eventTypeIds": [1],
                "marketTypeCodes": ["WINNER"],
                "textQuery": "World Cup 2026",
            },
            "marketProjection": ["EVENT"],
            "maxResults": 10,
        },
    }

    try:
        ctx = ssl.create_default_context()
        req = Request(url, data=json.dumps(params).encode(), headers=headers)
        with urlopen(req, timeout=15, context=ctx) as resp:
            result = json.loads(resp.read().decode())
            markets = result.get("result", [])

            if not markets:
                print("  [WARN] 未找到 2026 世界杯市场，尝试搜索 FIFA World Cup...")
                params["params"]["filter"]["textQuery"] = "FIFA World Cup"
                req2 = Request(url, data=json.dumps(params).encode(), headers=headers)
                with urlopen(req2, timeout=15, context=ctx) as resp2:
                    result2 = json.loads(resp2.read().decode())
                    markets = result2.get("result", [])

            if markets:
                print(f"  [OK] 找到 {len(markets)} 个世界杯市场:")
                for m in markets:
                    ev = m.get("event", {})
                    print(f"    - {ev.get('name', '?')}: {m.get('marketName', '?')}")
                    print(f"      ID: {m.get('marketId', '?')}")
                return markets
            else:
                print("  [INFO] 世界杯正赛市场尚未上线（通常赛前3个月开放）")
                print("  当前使用赔率模拟的必发指数作为参考")
                return []
    except Exception as e:
        print(f"  [ERROR] {e}")
        return []


def get_market_prices(app_key, session_token, market_ids):
    """Fetch live prices and volumes from Betfair Exchange."""
    if not market_ids:
        return []

    print(f"\n  获取实时交易数据 (必发指数核心)...")

    url = "https://api.betfair.com/exchange/betting/rest/v1.0/"
    headers = {
        "X-Application": app_key,
        "X-Authentication": session_token,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    params = {
        "jsonrpc": "2.0",
        "method": "SportsAPING/v1.0/listMarketBook",
        "params": {
            "marketIds": market_ids[:5],
            "priceProjection": {
                "priceData": ["EX_BEST_OFFERS", "EX_TRADED"],
            },
        },
    }

    try:
        ctx = ssl.create_default_context()
        req = Request(url, data=json.dumps(params).encode(), headers=headers)
        with urlopen(req, timeout=15, context=ctx) as resp:
            result = json.loads(resp.read().decode())
            books = result.get("result", [])

            if books:
                print(f"  [OK] 获取 {len(books)} 个市场的实时数据")
                for b in books:
                    total_matched = sum(
                        r.get("ex", {}).get("totalMatched", 0) or 0
                        for r in b.get("runners", [])
                    )
                    print(f"    市场 {b['marketId']}: 总成交 GBP{total_matched:,.0f}")
                return books
    except Exception as e:
        print(f"  [ERROR] {e}")
    return []


def save_live_betfair_data(markets, books):
    """Save live Betfair data as betfair_index.json."""
    if not books:
        print("\n  [INFO] 无实时数据，保持当前模拟数据")
        return False

    # Build 必发指数 from real Betfair data
    runners_data = {}

    for book in books:
        total_matched = sum(
            r.get("ex", {}).get("totalMatched", 0) or 0
            for r in book.get("runners", [])
        )

        for r in book.get("runners", []):
            ex = r.get("ex", {})
            matched = ex.get("totalMatched", 0) or 0
            bf_index = matched / total_matched if total_matched > 0 else 0

            # Back/Lay prices
            back_prices = ex.get("availableToBack", [])
            lay_prices = ex.get("availableToLay", [])
            best_back = back_prices[0] if back_prices else {}
            best_lay = lay_prices[0] if lay_prices else {}

            # Money flow
            back_vol = sum(b.get("size", 0) for b in back_prices[:3])
            lay_vol = sum(l.get("size", 0) for l in lay_prices[:3])
            money_flow = (back_vol - lay_vol) / (back_vol + lay_vol) if (back_vol + lay_vol) > 0 else 0

            # We don't have team names from Betfair directly, store by selection ID
            # The runner name can be found from marketCatalogue data
            runners_data[str(r.get("selectionId", ""))] = {
                "betfair_index": round(bf_index, 4),
                "total_matched": round(matched, 2),
                "back_price": best_back.get("price"),
                "lay_price": best_lay.get("price"),
                "money_flow": round(money_flow, 4),
                "status": r.get("status", ""),
            }

    export = {
        "updated": datetime.now().isoformat(),
        "source": "betfair_exchange_live",
        "betfair_index": {
            "total_matched": round(total_matched, 2),
            "market_type": "WORLD_CUP_WINNER",
            "timestamp": datetime.now().isoformat(),
            "runners": runners_data,
            "simulated": False,
        },
    }

    path = DATA_DIR / "betfair_index.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(export, f, indent=2, ensure_ascii=False)
    print(f"\n  [OK] 实时必发数据已保存: {path}")
    return True


def main():
    print("=" * 55)
    print("  必发指数一键设置 — 2026 FIFA World Cup")
    print("=" * 55)

    # Parse command line args
    app_key = ""
    username = ""
    password = ""

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--key" and i + 1 < len(args):
            app_key = args[i + 1]
            i += 2
        elif args[i] == "--user" and i + 1 < len(args):
            username = args[i + 1]
            i += 2
        elif args[i] == "--pass" and i + 1 < len(args):
            password = args[i + 1]
            i += 2
        else:
            i += 1

    # Also check env vars
    if not app_key:
        app_key = os.environ.get("BETFAIR_APP_KEY", "")
    if not username:
        username = os.environ.get("BETFAIR_USERNAME", "")
    if not password:
        password = os.environ.get("BETFAIR_PASSWORD", "")

    if not app_key or not username or not password:
        print("""
  [INFO] 未检测到 Betfair API 密钥。

  获取免费密钥 (1分钟):
  ┌─────────────────────────────────────────────────┐
  │ 1. 浏览器打开: https://docs.developer.betfair.com │
  │ 2. 注册 Betfair 账户 (无需入金)                    │
  │ 3. 创建 App, 选择 "Delayed" 类型 (免费)            │
  │ 4. 获取 App Key                                   │
  │                                                   │
  │ 然后运行:                                         │
  │ python setup_betfair.py --key "KEY" --user "USER" --pass "PASS" │
  └─────────────────────────────────────────────────┘

  当前使用**赔率模拟必发指数**作为参考数据。
  模拟原理: 市场隐含概率 → 成交量分配 + 资金流向估计
  虽然不是实时交易所数据, 但方向性基本一致。
  """)

        # Run simulated mode
        print("  生成模拟必发指数...")
        result = subprocess.run(
            [sys.executable, str(ROOT / "betfair_fetcher.py")],
            capture_output=True, text=True, cwd=str(ROOT)
        )
        if result.returncode == 0:
            print("  [OK] 模拟必发指数已更新")

        # Also regenerate all_data.json
        print("  合并到网站数据...")
        subprocess.run(
            [sys.executable, str(ROOT / "auto_refresh.py")],
            capture_output=True, text=True, cwd=str(ROOT)
        )
        print("\n  [OK] 完成! 打开 http://localhost:8080 查看必发指数图表")
        return

    # Test connection with real credentials
    print(f"\n  使用 App Key: {app_key[:8]}...")
    token = test_betfair_login(app_key, username, password)

    if token:
        # Fetch live data
        markets = fetch_world_cup_markets(app_key, token)

        if markets:
            market_ids = [m["marketId"] for m in markets if m.get("marketId")]
            books = get_market_prices(app_key, token, market_ids)
            if save_live_betfair_data(markets, books):
                print("\n  [OK] 实时必发数据已接入网站!")
                print("  打开 http://localhost:8080 查看真实必发指数")

                # Regenerate all_data.json
                subprocess.run(
                    [sys.executable, str(ROOT / "auto_refresh.py")],
                    capture_output=True, cwd=str(ROOT)
                )
        else:
            print("\n  [INFO] 世界杯市场暂未开放，保持模拟数据")
    else:
        print("\n  [FAIL] 登录失败，请检查:")
        print("  1. App Key 是否正确")
        print("  2. 用户名/密码是否正确")
        print("  3. 网络是否能访问 api.betfair.com")
        print("  4. 如果被墙，需要代理后重试")

    print("\n" + "=" * 55)
    print(f"  数据文件: {DATA_DIR / 'betfair_index.json'}")
    print(f"  网站数据: {DATA_DIR / 'all_data.json'}")
    print("=" * 55)


if __name__ == "__main__":
    main()
