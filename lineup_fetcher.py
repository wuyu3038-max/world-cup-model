"""
2026 FIFA World Cup — Starting Lineup Fetcher
===============================================
Fetches confirmed starting XIs when available (~1 hour before kickoff).

Sources:
  - FotMob API (matchDetails) — lineups, formations, bench
  - Sofascore API — match lineups (fallback)
  - Highlylightly API — free tier for lineups

Usage:
  python lineup_fetcher.py               # Fetch lineups for today's matches
  python lineup_fetcher.py --match 1     # Fetch specific match
  python lineup_fetcher.py --date 2026-06-15  # Fetch all matches on date
  python lineup_fetcher.py --all         # Refresh all pending matches
"""

import json
import sys
from pathlib import Path
from datetime import datetime
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

DATA_DIR = Path(__file__).parent / "data"

# ============================================================
# 1. FOTMOB API
# ============================================================

FOTMOB_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36",
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
}

FOTMOB_API = "https://www.fotmob.com/api"


def fetch_lineup_from_fotmob(match_id: int) -> dict:
    """
    Fetch lineup data from FotMob match details.
    Returns formatted lineup dict with formation, starting_xi, bench.
    """
    try:
        url = f"{FOTMOB_API}/matchDetails?matchId={match_id}"
        req = Request(url, headers=FOTMOB_HEADERS)
        with urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        content = data.get("content", {})
        lineup_data = content.get("lineup", {})

        result = {"home": None, "away": None}

        # FotMob returns lineups as: lineup.lineup[teamIndex][playerRows]
        lineups = lineup_data.get("lineup", [])
        benches = lineup_data.get("bench", [])

        for team_idx in range(min(2, len(lineups))):
            team_key = "home" if team_idx == 0 else "away"
            players = []

            for row in lineups[team_idx] if team_idx < len(lineups) else []:
                for player in row if isinstance(row, list) else [row]:
                    if isinstance(player, dict):
                        players.append({
                            "name": player.get("name", {}).get("fullName", ""),
                            "shirt": player.get("shirt", player.get("shirtNumber", "")),
                            "position": player.get("position", {}).get("short", ""),
                            "is_captain": player.get("captain", False),
                            "rating": player.get("rating", {}).get("num", None),
                        })

            bench_players = []
            if team_idx < len(benches):
                for player in benches[team_idx] if isinstance(benches[team_idx], list) else []:
                    if isinstance(player, dict):
                        bench_players.append(player.get("name", {}).get("fullName", ""))

            # Get formation from team sheet
            formation = lineup_data.get("formations", [])
            form_str = None
            if team_idx < len(formation) and formation[team_idx]:
                form_str = formation[team_idx]

            result[team_key] = {
                "formation": form_str,
                "starting_xi": players,
                "bench": bench_players,
                "captain": next((p["name"] for p in players if p.get("is_captain")), None),
                "confirmed": len(players) == 11,
            }

        return result

    except Exception as e:
        print(f"  [WARN] FotMob lineup fetch (match {match_id}): {e}")
        return {"home": None, "away": None}


# ============================================================
# 2. HIGHLYLIGHTLY API (free tier fallback)
# ============================================================

HIGHLYLIGHTLY_API = "https://api.highlightly.com/v1"
HIGHLYLIGHTLY_LEAGUE_ID = 1635  # World Cup 2026


def fetch_lineup_from_highlightly(match_id: int) -> dict:
    """
    Fetch lineup data from Highlylightly API.
    Free tier: 100 req/day, no credit card required.
    """
    try:
        # Highlylightly match details with lineups
        url = f"{HIGHLYLIGHTLY_API}/matches/{match_id}?include=lineups"
        req = Request(url, headers={"Accept": "application/json"})
        with urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        match_data = data.get("data", data)
        lineups = match_data.get("lineups", [])

        result = {"home": None, "away": None}

        for team_lineup in lineups:
            side = team_lineup.get("side", "").lower()
            team_key = "home" if "home" in side or side == "home" else "away"

            formation = team_lineup.get("formation")
            players = []
            for p in team_lineup.get("starting_xi", []):
                players.append({
                    "name": p.get("player_name", p.get("name", "")),
                    "shirt": p.get("shirt_number", p.get("jersey_number", "")),
                    "position": p.get("position", ""),
                    "is_captain": p.get("captain", False),
                    "rating": p.get("rating", None),
                })

            bench = [p.get("player_name", p.get("name", ""))
                     for p in team_lineup.get("substitutes", [])]

            result[team_key] = {
                "formation": formation,
                "starting_xi": players,
                "bench": bench,
                "captain": next((p["name"] for p in players if p.get("is_captain")), None),
                "confirmed": len(players) == 11,
            }

        return result

    except Exception as e:
        print(f"  [WARN] Highlylightly lineup fetch (match {match_id}): {e}")
        return {"home": None, "away": None}


# ============================================================
# 3. MATCH ID MAPPING
# ============================================================

# FotMob match IDs — updated via search/fetch when available
# These need to be populated by running fetch_fotmob_matches first
FOTMOB_MATCH_IDS = {}

# Highlylightly match IDs — discovered via league schedule endpoint
HIGHLYLIGHTLY_MATCH_IDS = {}


def discover_match_ids(date_str: str = None) -> dict:
    """
    Try to discover FotMob match IDs for World Cup matches on a given date.
    Returns {home_vs_away: fotmob_match_id} mapping.
    """
    if date_str is None:
        date_str = datetime.now().strftime("%Y%m%d")

    try:
        url = f"{FOTMOB_API}/matches?date={date_str}"
        req = Request(url, headers=FOTMOB_HEADERS)
        with urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        matches = {}
        for league in data.get("leagues", []):
            for match in league.get("matches", []):
                home = match.get("home", {}).get("name", "")
                away = match.get("away", {}).get("name", "")
                match_id = match.get("id")
                if home and away and match_id:
                    key = f"{home}_vs_{away}"
                    matches[key] = match_id
        return matches
    except Exception as e:
        print(f"  [WARN] Match ID discovery: {e}")
        return {}


# ============================================================
# 4. LINEUP FILE MANAGEMENT
# ============================================================

def load_lineups() -> dict:
    """Load current lineups.json."""
    path = DATA_DIR / "lineups.json"
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"_meta": {}, "lineups": {}}


def save_lineups(data: dict):
    """Save lineups to JSON file."""
    data["_meta"]["last_updated"] = datetime.now().isoformat()
    path = DATA_DIR / "lineups.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"  [OK] lineups.json saved")


def update_match_lineup(lineups_data: dict, match_num: int,
                        home_lineup: dict, away_lineup: dict):
    """Update lineup data for a specific match in lineups.json."""
    match_key = str(match_num)

    # Auto-create match entry if missing
    if match_key not in lineups_data.get("lineups", {}):
        from model import load_match_schedule
        schedule = load_match_schedule()
        # Find match details from schedule
        for md in ["matchday_1", "matchday_2", "matchday_3"]:
            for m in schedule.get("matches", {}).get(md, []):
                if m.get("match") == match_num:
                    lineups_data["lineups"][match_key] = {
                        "match": match_num,
                        "date": m.get("date", ""),
                        "group": m.get("group", ""),
                        "home": m.get("home", ""),
                        "away": m.get("away", ""),
                        "venue": m.get("venue", ""),
                        "status": "confirmed",
                        "home_lineup": home_lineup,
                        "away_lineup": away_lineup,
                    }
                    return lineups_data

        # Fallback: just store raw data
        lineups_data["lineups"][match_key] = {
            "match": match_num,
            "status": "confirmed",
            "home_lineup": home_lineup,
            "away_lineup": away_lineup,
        }
    else:
        match_data = lineups_data["lineups"][match_key]
        match_data["status"] = "confirmed"
        match_data["home_lineup"] = home_lineup
        match_data["away_lineup"] = away_lineup

    return lineups_data


# ============================================================
# 5. MAIN FETCH ROUTINES
# ============================================================

def fetch_today_lineups(lineups_data: dict) -> int:
    """Fetch lineups for all matches scheduled today."""
    today = datetime.now().strftime("%Y-%m-%d")
    updated = 0

    # Discover match IDs for today
    match_ids = discover_match_ids(datetime.now().strftime("%Y%m%d"))

    for match_key, match_data in lineups_data.get("lineups", {}).items():
        if match_data.get("date") != today:
            continue
        if match_data.get("status") == "confirmed":
            continue  # Already have confirmed lineup

        home = match_data.get("home", "")
        away = match_data.get("away", "")
        match_num = match_data.get("match", 0)

        # Try FotMob first
        fotmob_key = f"{home}_vs_{away}"
        fotmob_id = match_ids.get(fotmob_key)
        if fotmob_id:
            lineup = fetch_lineup_from_fotmob(fotmob_id)
        else:
            lineup = {"home": None, "away": None}

        # Fallback to Highlylightly
        hl_id = HIGHLYLIGHTLY_MATCH_IDS.get(match_num)
        if not lineup["home"] and hl_id:
            lineup = fetch_lineup_from_highlightly(hl_id)

        if lineup["home"] and lineup["away"]:
            lineups_data = update_match_lineup(
                lineups_data, match_num,
                lineup["home"], lineup["away"]
            )
            updated += 1
            print(f"  [OK] Match {match_num}: {home} vs {away} lineup confirmed")

    return updated


def fetch_specific_match(lineups_data: dict, match_num: int) -> bool:
    """Fetch lineup for a specific match by number."""
    match_key = str(match_num)
    match_data = lineups_data.get("lineups", {}).get(match_key)
    if not match_data:
        print(f"  [ERR] Match {match_num} not found in lineups.json")
        return False

    date_str = match_data.get("date", "").replace("-", "")
    if not date_str:
        date_str = datetime.now().strftime("%Y%m%d")

    match_ids = discover_match_ids(date_str)
    home = match_data.get("home", "")
    away = match_data.get("away", "")
    fotmob_key = f"{home}_vs_{away}"
    fotmob_id = match_ids.get(fotmob_key)

    if fotmob_id:
        lineup = fetch_lineup_from_fotmob(fotmob_id)
    else:
        lineup = {"home": None, "away": None}

    if not lineup["home"]:
        hl_id = HIGHLYLIGHTLY_MATCH_IDS.get(match_num)
        if hl_id:
            lineup = fetch_lineup_from_highlightly(hl_id)

    if lineup["home"]:
        lineups_data = update_match_lineup(lineups_data, match_num, lineup["home"], lineup["away"])
        print(f"  [OK] Match {match_num}: {home} vs {away} lineup fetched")
        return True
    else:
        print(f"  [INFO] Match {match_num}: lineup not yet available (usually 1h before kickoff)")
        return False


# ============================================================
# 6. ENTRY POINT
# ============================================================

if __name__ == "__main__":
    match_filter = None
    date_filter = None
    fetch_all = False

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--match" and i + 1 < len(args):
            match_filter = int(args[i + 1])
            i += 2
        elif args[i] == "--date" and i + 1 < len(args):
            date_filter = args[i + 1]
            i += 2
        elif args[i] == "--all":
            fetch_all = True
            i += 1
        else:
            i += 1

    print(f"\n{'='*55}")
    print(f"  World Cup Lineup Fetcher [{datetime.now().strftime('%Y-%m-%d %H:%M')}]")
    print(f"{'='*55}\n")

    lineups_data = load_lineups()

    if match_filter:
        print(f"[1/1] Fetching lineup for Match {match_filter}...")
        success = fetch_specific_match(lineups_data, match_filter)
        if success:
            save_lineups(lineups_data)
            # Print the lineup
            m = lineups_data["lineups"].get(str(match_filter), {})
            for side, label in [("home_lineup", m.get("home", "Home")), ("away_lineup", m.get("away", "Away"))]:
                lu = m.get(side, {})
                print(f"\n  {label} ({lu.get('formation', '?')}):")
                for i, p in enumerate(lu.get("starting_xi", []), 1):
                    cap = " (C)" if p.get("is_captain") else ""
                    print(f"    {i:>2}. {p['name']:<25s} #{p.get('shirt','?')}  {p.get('position','')}{cap}")
    elif date_filter:
        print(f"[1/1] Fetching lineups for {date_filter}...")
        match_ids = discover_match_ids(date_filter.replace("-", ""))
        print(f"  Discovered {len(match_ids)} match IDs: {match_ids}")
        # Today's lineup fetch
        today_lineups = [m for m in lineups_data.get("lineups", {}).values() if m.get("date") == date_filter]
        updated = 0
        for m in today_lineups:
            if m.get("status") != "confirmed":
                if fetch_specific_match(lineups_data, m["match"]):
                    updated += 1
        if updated > 0:
            save_lineups(lineups_data)
        print(f"  Updated {updated} lineups for {date_filter}")
    else:
        # Default: fetch today's lineups
        print(f"[1/1] Fetching lineups for today's matches...")
        updated = fetch_today_lineups(lineups_data)
        if updated > 0:
            save_lineups(lineups_data)
        print(f"  Updated {updated} lineups")
        if updated == 0:
            print(f"  (Lineups usually confirmed 1 hour before kickoff)")

    print(f"\n  Done.")
