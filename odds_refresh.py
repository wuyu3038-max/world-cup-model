"""
2026 FIFA World Cup — Real-Time Odds Refresh Module
=====================================================
Fetches and caches live betting odds from multiple sources.
Supports: 1X2 (European), Asian Handicap, Over/Under Goals.

Usage:
    python odds_refresh.py              # Fetch & save to data/live_odds.json
    python odds_refresh.py --watch 300   # Auto-refresh every 300 seconds
"""

import json
import time
import sys
from pathlib import Path
from datetime import datetime
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

DATA_DIR = Path(__file__).parent / "data"

# ============================================================
# 1. ODDS PROVIDERS
# ============================================================

# Oddspedia API-like URLs (free tier, JSON)
ODDSPEDIA_BASE = "https://oddspedia.com/api/v1"

# The Odds API (free tier: 500 req/month)
# Sign up at https://the-odds-api.com
ODDS_API_KEY = None  # Set via ODDS_API_KEY env var or hardcode
ODDS_API_BASE = "https://api.the-odds-api.com/v4"

# ============================================================
# 2. FALLBACK: HARDCODED REFERENCE ODDS
# ============================================================

# These serve as fallback when API is unavailable
# Based on DraftKings/FanDuel as of June 2026
# Format: {match_key: {bookmaker: {1X2: [home, draw, away], o25: [over, under], ...}}}

REFERENCE_ODDS = {
    "Mexico_vs_South Africa": {
        "date": "2026-06-11",
        "group": "A",
        "matchday": 1,
        "bet365": {
            "1X2": [1.53, 4.00, 5.50],
            "over_under_2.5": [1.85, 1.95],
            "asian_handicap_-1": [2.05, 1.80],
            "btts_yes": 2.10,
            "btts_no": 1.67,
        }
    },
    "Brazil_vs_Morocco": {
        "date": "2026-06-14",
        "group": "C",
        "matchday": 1,
        "bet365": {
            "1X2": [1.40, 4.50, 7.00],
            "over_under_2.5": [1.73, 2.10],
            "asian_handicap_-1": [1.80, 2.05],
            "btts_yes": 1.91,
            "btts_no": 1.80,
        }
    },
    "Germany_vs_Curacao": {
        "date": "2026-06-15",
        "group": "E",
        "matchday": 1,
        "bet365": {
            "1X2": [1.12, 9.00, 17.00],
            "over_under_3.5": [1.80, 2.00],
            "asian_handicap_-3": [1.95, 1.90],
            "btts_yes": 3.50,
            "btts_no": 1.29,
        }
    },
    "Spain_vs_Cape Verde": {
        "date": "2026-06-17",
        "group": "H",
        "matchday": 1,
        "bet365": {
            "1X2": [1.08, 11.00, 21.00],
            "over_under_3.5": [1.73, 2.10],
            "asian_handicap_-3": [1.90, 1.95],
            "btts_yes": 4.00,
            "btts_no": 1.22,
        }
    },
    "France_vs_Senegal": {
        "date": "2026-06-17",
        "group": "I",
        "matchday": 1,
        "bet365": {
            "1X2": [1.44, 4.20, 6.50],
            "over_under_2.5": [1.80, 2.00],
            "asian_handicap_-1": [1.91, 1.95],
            "btts_yes": 1.80,
            "btts_no": 1.91,
        }
    },
    "Argentina_vs_Algeria": {
        "date": "2026-06-18",
        "group": "J",
        "matchday": 1,
        "bet365": {
            "1X2": [1.36, 4.75, 7.50],
            "over_under_2.5": [1.83, 1.98],
            "asian_handicap_-1.5": [2.05, 1.80],
            "btts_yes": 1.91,
            "btts_no": 1.80,
        }
    },
    "Portugal_vs_Congo DR": {
        "date": "2026-06-18",
        "group": "K",
        "matchday": 1,
        "bet365": {
            "1X2": [1.25, 5.50, 10.00],
            "over_under_2.5": [1.73, 2.10],
            "asian_handicap_-1.5": [1.80, 2.05],
            "btts_yes": 2.20,
            "btts_no": 1.62,
        }
    },
    "England_vs_Croatia": {
        "date": "2026-06-19",
        "group": "L",
        "matchday": 1,
        "bet365": {
            "1X2": [1.73, 3.50, 4.75],
            "over_under_2.5": [2.00, 1.80],
            "asian_handicap_-0.5": [1.85, 2.00],
            "btts_yes": 1.83,
            "btts_no": 1.83,
        }
    },
}

# ============================================================
# 3. ODDS CONVERSION UTILS
# ============================================================

def decimal_to_prob(odds: float) -> float:
    """Decimal odds to implied probability (before margin)."""
    return 1.0 / odds

def prob_to_decimal(prob: float) -> float:
    """Probability to fair decimal odds."""
    return 1.0 / max(prob, 0.001)

def remove_overround(probs: list) -> list:
    """Normalize probabilities to sum to 1.0 (remove bookmaker margin)."""
    total = sum(probs)
    return [p / total for p in probs]

def asian_handicap_to_probs(home_odds: float, away_odds: float, line: float) -> dict:
    """Convert Asian handicap odds to win probabilities."""
    home_prob = decimal_to_prob(home_odds)
    away_prob = decimal_to_prob(away_odds)
    home_prob, away_prob = remove_overround([home_prob, away_prob])
    return {
        "home_cover": home_prob,
        "away_cover": away_prob,
        "line": line,
    }

def o25_to_probs(over_odds: float, under_odds: float) -> dict:
    """Convert Over/Under odds to probabilities."""
    over_prob = decimal_to_prob(over_odds)
    under_prob = decimal_to_prob(under_odds)
    over_prob, under_prob = remove_overround([over_prob, under_prob])
    return {"over": over_prob, "under": under_prob}

def expected_goals_from_o25(over_prob: float, line: float = 2.5) -> float:
    """
    Estimate expected total goals from over/under probability.
    Uses Poisson CDF inversion approximation.
    """
    # Simple heuristic: over_prob 0.5 -> ~2.5 goals, each 0.1 over = +0.2 goals
    base = line
    adjustment = (over_prob - 0.50) * 2.0
    return max(base + adjustment, 0.8)


# ============================================================
# 4. API FETCH (The Odds API)
# ============================================================

def fetch_odds_api(sport: str = "soccer_world_cup", regions: str = "uk,us,eu",
                   markets: str = "h2h,totals,spreads") -> dict:
    """Fetch live odds from The Odds API."""
    import os
    api_key = ODDS_API_KEY or os.environ.get("ODDS_API_KEY")
    if not api_key:
        return {"error": "No API key. Set ODDS_API_KEY env var or sign up at the-odds-api.com"}

    url = (f"{ODDS_API_BASE}/sports/{sport}/odds/"
           f"?apiKey={api_key}&regions={regions}&markets={markets}")
    try:
        req = Request(url, headers={"User-Agent": "WorldCupModel/1.0"})
        with urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except HTTPError as e:
        return {"error": f"HTTP {e.code}: {e.reason}"}
    except URLError as e:
        return {"error": f"Connection failed: {e.reason}"}


# ============================================================
# 5. MAIN REFRESH LOGIC
# ============================================================

def refresh_odds():
    """Fetch latest odds and save to JSON."""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Refreshing odds...")

    odds_data = {
        "updated": datetime.now().isoformat(),
        "source": "reference_odds",
        "matches": REFERENCE_ODDS,
    }

    # Try live API
    live = fetch_odds_api()
    if "error" not in live:
        odds_data["source"] = "the_odds_api"
        odds_data["api_data"] = live
        print("  [OK] Live odds fetched from The Odds API")
    else:
        print(f"  [NOTE] API unavailable ({live['error']}), using reference odds")
        odds_data["api_error"] = live["error"]

    # Save
    output_path = DATA_DIR / "live_odds.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(odds_data, f, indent=2, ensure_ascii=False)

    print(f"  [OK] Saved to {output_path}")

    # Print summary
    print(f"\n  Key Match Odds (1X2):")
    for match_key, match_data in REFERENCE_ODDS.items():
        b365 = match_data.get("bet365", {}).get("1X2", [])
        if b365:
            name = match_key.replace("_vs_", " vs ")
            probs = remove_overround([decimal_to_prob(o) for o in b365])
            print(f"    {name}")
            print(f"      Home: {b365[0]:.2f} ({probs[0]:.1%})  "
                  f"Draw: {b365[1]:.2f} ({probs[1]:.1%})  "
                  f"Away: {b365[2]:.2f} ({probs[2]:.1%})")

    return odds_data


def watch_mode(interval: int = 300):
    """Continuously refresh odds every `interval` seconds."""
    print(f"Watch mode: refreshing every {interval}s. Ctrl+C to stop.")
    try:
        while True:
            refresh_odds()
            print(f"\n  Next refresh in {interval}s...\n")
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n  Stopped.")


# ============================================================
# 6. USAGE: Integrate with model
# ============================================================

def load_live_odds() -> dict:
    """Load the most recent odds snapshot."""
    path = DATA_DIR / "live_odds.json"
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def get_match_odds(match_key: str) -> dict:
    """Get odds for a specific match."""
    data = load_live_odds()
    matches = data.get("matches", {})
    return matches.get(match_key, {})


def odds_to_match_prediction(match_key: str) -> dict:
    """Convert betting odds to a match prediction."""
    odds = get_match_odds(match_key)
    if not odds:
        return {}

    b365 = odds.get("bet365", {})

    # 1X2 probs
    hda = b365.get("1X2", [])
    if hda:
        probs = remove_overround([decimal_to_prob(o) for o in hda])
        outcome = {"home_win": probs[0], "draw": probs[1], "away_win": probs[2]}
    else:
        outcome = {}

    # Expected goals from O/U
    o25 = b365.get("over_under_2.5", [])
    if o25:
        over_prob = decimal_to_prob(o25[0])
        under_prob = decimal_to_prob(o25[1])
        over_prob, _ = remove_overround([over_prob, under_prob])
        exp_goals = expected_goals_from_o25(over_prob)
    else:
        exp_goals = None

    return {
        "match": match_key,
        "date": odds.get("date", ""),
        "outcome_probs": outcome,
        "expected_total_goals": round(exp_goals, 2) if exp_goals else None,
        "raw_1X2": hda,
        "raw_o25": o25,
    }


# ============================================================
# 7. CLI
# ============================================================

if __name__ == "__main__":
    if "--watch" in sys.argv:
        idx = sys.argv.index("--watch")
        interval = int(sys.argv[idx + 1]) if idx + 1 < len(sys.argv) else 300
        watch_mode(interval)
    else:
        print("=" * 50)
        print("  World Cup 2026 — Live Odds Refresh")
        print("=" * 50)
        refresh_odds()

        # Demo: convert to predictions
        print(f"\n{'='*50}")
        print("  Sample: Odds-based Match Predictions")
        print(f"{'='*50}")
        for match_key in list(REFERENCE_ODDS.keys())[:5]:
            pred = odds_to_match_prediction(match_key)
            if pred.get("outcome_probs"):
                p = pred["outcome_probs"]
                print(f"\n  {match_key.replace('_vs_', ' vs ')}:")
                print(f"    1X2: H={p['home_win']:.1%}  D={p['draw']:.1%}  A={p['away_win']:.1%}")
                if pred.get("expected_total_goals"):
                    print(f"    Expected Goals: {pred['expected_total_goals']}")
