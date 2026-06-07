"""
Auto-refresh: update data sources and redeploy
==============================================
Run this script periodically to:
1. Refresh betting odds from reference data
2. Run news feed aggregation
3. Merge all data into all_data.json
4. Commit + push to auto-deploy on Vercel

Usage:
    python auto_refresh.py           # One-time refresh
    python auto_refresh.py --deploy  # Refresh + git push to redeploy
"""

import sys
import json
from pathlib import Path
from datetime import datetime

DATA_DIR = Path(__file__).parent / "data"

def refresh_live_odds():
    """Update live_odds.json with current timestamp and any new odds data."""
    path = DATA_DIR / "live_odds.json"
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        data["updated"] = datetime.now().isoformat()
        data["refresh_count"] = data.get("refresh_count", 0) + 1
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"  [OK] live_odds.json refreshed (#{data['refresh_count']})")

def refresh_betfair_index():
    """Run betfair_fetcher to update Betfair index data."""
    try:
        import betfair_fetcher
        data = betfair_fetcher.fetch_betfair_index(use_live=False)
        betfair_fetcher.save_betfair_index(data)
        print(f"  [OK] betfair_index.json refreshed")
    except Exception as e:
        print(f"  [WARN] betfair_index refresh failed: {e}")

def refresh_tournament_results():
    """Update tournament_results.json timestamp."""
    path = DATA_DIR / "tournament_results.json"
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        data["_last_refreshed"] = datetime.now().isoformat()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"  [OK] tournament_results.json refreshed")

def merge_all_data():
    """Merge all JSON data files into all_data.json for static serving."""
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
        "description": "Merged data for World Cup 2026 prediction static site"
    }

    with open(DATA_DIR / "all_data.json", "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False)

    size_kb = (DATA_DIR / "all_data.json").stat().st_size / 1024
    print(f"  [OK] all_data.json merged ({size_kb:.1f} KB, {len(merged)} files)")

def deploy():
    """Git commit + push to trigger Vercel redeploy."""
    import subprocess
    root = Path(__file__).parent
    cmds = [
        ["git", "add", "-A"],
        ["git", "commit", "-m", f"auto-refresh: {datetime.now().strftime('%Y-%m-%d %H:%M')}"],
        ["git", "push", "origin", "master"],
    ]
    for cmd in cmds:
        result = subprocess.run(cmd, cwd=root, capture_output=True, text=True)
        status = "OK" if result.returncode == 0 else f"ERR({result.returncode})"
        print(f"  [{status}] {' '.join(cmd)}")
        if result.returncode != 0 and "nothing to commit" not in result.stdout + result.stderr:
            print(f"    {result.stderr.strip()}")

if __name__ == "__main__":
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Auto-refresh started")
    refresh_live_odds()
    refresh_betfair_index()
    refresh_tournament_results()
    merge_all_data()

    if "--deploy" in sys.argv:
        deploy()
        print(f"\n  Site will update at: https://world-cup-model.vercel.app")
    else:
        print(f"\n  Run with --deploy to auto-push to Vercel")
