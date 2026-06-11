"""
Auto-refresh: full data pipeline for World Cup prediction
==========================================================
Run periodically (every 8h recommended) to:
1. Refresh betting odds & Betfair index
2. Run news feed aggregation
3. Re-run full tournament simulation (5000 MC)
4. Merge all data into all_data.json
5. Optional: git push to deploy on Vercel

Usage:
    python auto_refresh.py              # Full refresh
    python auto_refresh.py --quick      # Skip tournament sim (fast)
    python auto_refresh.py --deploy     # Full refresh + git push
"""

import sys
import json
from pathlib import Path
from datetime import datetime

DATA_DIR = Path(__file__).parent / "data"


def refresh_live_odds():
    """Update live_odds.json timestamp."""
    path = DATA_DIR / "live_odds.json"
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        data["updated"] = datetime.now().isoformat()
        data["refresh_count"] = data.get("refresh_count", 0) + 1
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"  [OK] live_odds.json (#{data['refresh_count']})")


def refresh_betfair_index():
    """Update Betfair index from bookmaker odds."""
    try:
        import betfair_fetcher
        data = betfair_fetcher.fetch_betfair_index(use_live=False)
        betfair_fetcher.save_betfair_index(data)
        print(f"  [OK] betfair_index.json")
    except Exception as e:
        print(f"  [WARN] betfair_index: {e}")


def refresh_news():
    """Run news_feed.py scraper."""
    try:
        import subprocess
        result = subprocess.run(
            ["python", "news_feed.py"],
            cwd=Path(__file__).parent, capture_output=True, text=True, timeout=120
        )
        if result.returncode == 0:
            print(f"  [OK] news_feed.json ({len(json.loads(Path(DATA_DIR/'news_feed.json').read_text(encoding='utf-8')).get('articles',[]))} articles)")
        else:
            print(f"  [WARN] news_feed: {result.stderr.strip()[:100]}")
    except Exception as e:
        print(f"  [WARN] news_feed: {e}")


def refresh_injuries():
    """Run injury_fetcher.py to update injury data."""
    try:
        import subprocess
        result = subprocess.run(
            ["python", "injury_fetcher.py", "--quick"],
            cwd=Path(__file__).parent, capture_output=True, text=True, timeout=120
        )
        if result.returncode == 0:
            with open(DATA_DIR / "injuries.json", "r", encoding="utf-8") as f:
                n = len(json.load(f).get("injuries", []))
            print(f"  [OK] injuries.json ({n} injuries)")
        else:
            print(f"  [WARN] injuries: {result.stderr.strip()[:100]}")
    except Exception as e:
        print(f"  [WARN] injuries: {e}")


def refresh_lineups():
    """Run lineup_fetcher.py to update starting XIs."""
    try:
        import subprocess
        result = subprocess.run(
            ["python", "lineup_fetcher.py"],
            cwd=Path(__file__).parent, capture_output=True, text=True, timeout=120
        )
        if result.returncode == 0:
            with open(DATA_DIR / "lineups.json", "r", encoding="utf-8") as f:
                n = sum(1 for m in json.load(f).get("lineups", {}).values() if m.get("status") == "confirmed")
            print(f"  [OK] lineups.json ({n} confirmed)")
        else:
            print(f"  [WARN] lineups: {result.stderr.strip()[:100]}")
    except Exception as e:
        print(f"  [WARN] lineups: {e}")


def run_tournament_simulation():
    """Re-run full 5000-simulation Monte Carlo tournament."""
    try:
        import subprocess
        print(f"  Running tournament simulation (5000 MC)...")
        result = subprocess.run(
            ["python", "tournament.py", "5000"],
            cwd=Path(__file__).parent, capture_output=True, text=True, timeout=300
        )
        if result.returncode == 0:
            # Extract champion name from output
            for line in result.stdout.split("\n"):
                if "Spain" in line and "%" in line and "1." in line:
                    print(f"  [OK] tournament ({line.strip()[:60]})")
                    break
            else:
                print(f"  [OK] tournament_results.json updated")
        else:
            print(f"  [WARN] tournament sim failed: {result.stderr.strip()[:150]}")
    except Exception as e:
        print(f"  [WARN] tournament sim: {e}")


def merge_all_data():
    """Merge all JSON data files into all_data.json."""
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
        "description": "World Cup 2026 prediction — auto-refreshed"
    }

    with open(DATA_DIR / "all_data.json", "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False)

    size_kb = (DATA_DIR / "all_data.json").stat().st_size / 1024
    n = len(merged)
    print(f"  [OK] all_data.json ({size_kb:.0f}KB, {n} files)")


def deploy():
    """Git commit + push to Vercel."""
    import subprocess
    root = Path(__file__).parent
    cmds = [
        ["git", "add", "-A"],
        ["git", "commit", "-m", f"auto-refresh: {datetime.now().strftime('%Y-%m-%d %H:%M')}"],
        ["git", "push", "origin", "master"],
    ]
    for cmd in cmds:
        result = subprocess.run(cmd, cwd=root, capture_output=True, text=True)
        ok = result.returncode == 0
        tag = "OK" if ok else f"ERR({result.returncode})"
        print(f"  [{tag}] {' '.join(cmd)}")
        if not ok and "nothing to commit" not in result.stdout + result.stderr:
            print(f"    {result.stderr.strip()[:200]}")


if __name__ == "__main__":
    quick = "--quick" in sys.argv
    do_deploy = "--deploy" in sys.argv
    merge_only = "--merge-only" in sys.argv

    if merge_only:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Merge only")
        merge_all_data()
        if do_deploy:
            deploy()
        sys.exit(0)

    print(f"\n{'='*55}")
    print(f"  World Cup Auto-Refresh [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]")
    print(f"  Mode: {'quick (no sim)' if quick else 'full'}")
    print(f"{'='*55}")

    print("\n[1/6] Odds & Betfair")
    refresh_live_odds()
    refresh_betfair_index()

    print("\n[2/6] News Feed")
    refresh_news()

    print("\n[3/6] Injuries & Lineups")
    refresh_injuries()
    refresh_lineups()

    if not quick:
        print("\n[4/6] Tournament Simulation")
        run_tournament_simulation()
    else:
        print("\n[4/6] Tournament Simulation  [SKIP]")

    print("\n[5/6] Merge all_data.json")
    merge_all_data()

    if do_deploy:
        print("\n[6/6] Deploy to Vercel")
        deploy()
        print(f"\n  ▶ https://world-cup-model.vercel.app")

    print(f"\n  Done. Next refresh: +8h\n")
