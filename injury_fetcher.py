"""
2026 FIFA World Cup — Injury & Availability Tracker
=====================================================
Fetches player injury data from multiple sources and updates injuries.json.

Sources:
  - FotMob API (unofficial) — matchDetails includes injuredPlayers
  - Transfermarkt — injury table scraping
  - ESPN / BBC / Sky Sports — news-based injury detection
  - Official team announcements

Usage:
  python injury_fetcher.py              # Full fetch, update injuries.json
  python injury_fetcher.py --quick      # Only check existing injuries for status changes
  python injury_fetcher.py --team "Brazil"  # Check specific team
"""

import json
import sys
import re
import hashlib
from pathlib import Path
from datetime import datetime, timedelta
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
import xml.etree.ElementTree as ET

DATA_DIR = Path(__file__).parent / "data"

# ============================================================
# 1. FOTMOB API (unofficial)
# ============================================================

FOTMOB_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36",
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
}

# World Cup 2026 league ID on FotMob
WC_LEAGUE_ID = 44  # International > World Cup (may need updating)
FOTMOB_API = "https://www.fotmob.com/api"


def fetch_fotmob_matches(date_str: str = None) -> dict:
    """
    Fetch World Cup matches from FotMob for a given date.
    Returns match details including injuredPlayers for each match.
    """
    if date_str is None:
        date_str = datetime.now().strftime("%Y%m%d")

    try:
        url = f"{FOTMOB_API}/matches?date={date_str}"
        req = Request(url, headers=FOTMOB_HEADERS)
        with urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        # Filter for World Cup matches (league ID 44 or tournament name match)
        wc_matches = []
        for league in data.get("leagues", []):
            league_name = league.get("name", "").lower()
            league_id = league.get("id", "")
            if "world cup" in league_name or "fifa" in league_name or league_id == WC_LEAGUE_ID:
                wc_matches = league.get("matches", [])
                break

        return {"matches": wc_matches, "date": date_str}
    except Exception as e:
        print(f"  [WARN] FotMob fetch failed: {e}")
        return {"matches": [], "date": date_str, "error": str(e)}


def fetch_fotmob_match_details(match_id: int) -> dict:
    """Fetch detailed match info including lineups and injuries."""
    try:
        url = f"{FOTMOB_API}/matchDetails?matchId={match_id}"
        req = Request(url, headers=FOTMOB_HEADERS)
        with urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"  [WARN] FotMob matchDetails {match_id} failed: {e}")
        return {}


def extract_injuries_from_fotmob(match_detail: dict) -> list:
    """Extract injury data from FotMob match details response."""
    injuries = []
    try:
        content = match_detail.get("content", {})
        lineup_data = content.get("lineup", {})

        # Check injuredPlayers list in lineup
        for team_section in lineup_data.get("injuredPlayers", []):
            if isinstance(team_section, list):
                for player in team_section:
                    if isinstance(player, dict):
                        injuries.append({
                            "player": player.get("name", ""),
                            "reason": player.get("reason", ""),
                            "source": "FotMob",
                        })

        # Also check matchFacts > injuries
        match_facts = content.get("matchFacts", {})
        for team_key in ["injuries"]:
            for item in match_facts.get(team_key, []):
                if isinstance(item, dict):
                    injuries.append({
                        "player": item.get("name", item.get("playerName", "")),
                        "reason": item.get("description", item.get("reason", "")),
                        "source": "FotMob",
                    })
    except Exception:
        pass
    return injuries


# ============================================================
# 2. TRANSFERMARKT SCRAPER
# ============================================================

TM_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}

TM_WC_INJURIES_URL = "https://www.transfermarkt.com/world-cup-2026/ausfallgalerie/wettbewerb/WM26"


def fetch_transfermarkt_injuries() -> list:
    """
    Scrape Transfermarkt injury page for World Cup 2026.
    Parses the injury table rows from HTML.
    """
    injuries = []
    try:
        req = Request(TM_WC_INJURIES_URL, headers=TM_HEADERS)
        with urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8")

        # Parse injury table rows using regex
        # Transfermarkt injury rows contain: player name, nationality, injury type, expected return
        # Pattern: href="/profil/spieler/..." > Player Name < ... injury type ... return date
        player_pattern = re.compile(
            r'<a[^>]*href="[^"]*profil/spieler/\d+"[^>]*title="([^"]*)"[^>]*>.*?</a>'
            r'.*?<img[^>]*title="([^"]*)"[^>]*>',  # nationality from flag
            re.DOTALL
        )

        # Simpler approach: find all table rows with injury info
        rows = re.findall(
            r'<tr[^>]*>.*?<td[^>]*>.*?<a[^>]*title="([^"]*)"[^>]*>.*?</a>.*?</td>'
            r'.*?<td[^>]*>(.*?)</td>'
            r'.*?<td[^>]*>(.*?)</td>',
            html, re.DOTALL
        )

        for player_name, injury_type, expected_return in rows[:100]:
            name = re.sub(r'<[^>]+>', '', player_name).strip()
            injury = re.sub(r'<[^>]+>', '', injury_type).strip()
            return_date = re.sub(r'<[^>]+>', '', expected_return).strip()

            if name and injury:
                injuries.append({
                    "player": name,
                    "injury_type": injury,
                    "expected_return": return_date if return_date else None,
                    "source": "Transfermarkt",
                })
    except Exception as e:
        print(f"  [WARN] Transfermarkt scrape failed: {e}")

    return injuries


# ============================================================
# 3. NEWS-BASED INJURY DETECTION
# ============================================================

# Known team name → nation mapping for news article detection
TEAM_NEWS_MAP = {
    "Brazil": ["brazil", "brasil", "brazilian", "seleção"],
    "Argentina": ["argentina", "albiceleste"],
    "France": ["france", "french", "les bleus"],
    "Germany": ["germany", "german", "die mannschaft"],
    "Spain": ["spain", "spanish", "la roja", "españa"],
    "England": ["england", "english", "three lions"],
    "Netherlands": ["netherlands", "dutch", "oranje"],
    "Portugal": ["portugal", "portuguese"],
    "Belgium": ["belgium", "belgian", "red devils"],
    "Italy": ["italy", "italian", "azzurri"],
    "Croatia": ["croatia", "croatian"],
    "Uruguay": ["uruguay", "uruguayan"],
    "Colombia": ["colombia", "colombian"],
    "Mexico": ["mexico", "mexican", "el tri"],
    "United States": ["usa", "usmnt", "united states", "americans"],
    "Canada": ["canada", "canadian"],
    "Japan": ["japan", "japanese", "samurai blue"],
    "South Korea": ["south korea", "korea republic", "korean"],
    "Morocco": ["morocco", "moroccan"],
    "Senegal": ["senegal", "senegalese"],
    "Ghana": ["ghana", "ghanaian"],
    "Egypt": ["egypt", "egyptian"],
    "Norway": ["norway", "norwegian"],
    "Sweden": ["sweden", "swedish"],
    "Austria": ["austria", "austrian"],
    "Switzerland": ["swiss", "switzerland"],
    "Scotland": ["scotland", "scottish"],
    "Australia": ["australia", "australian", "socceroos"],
    "Paraguay": ["paraguay", "paraguayan"],
    "Ecuador": ["ecuador", "ecuadorian"],
    "Ivory Coast": ["ivory coast", "côte d'ivoire", "ivorian"],
    "Cameroon": ["cameroon", "cameroonian"],
    "Nigeria": ["nigeria", "nigerian"],
    "Tunisia": ["tunisia", "tunisian"],
    "Algeria": ["algeria", "algerian"],
    "South Africa": ["south africa", "bafana bafana"],
    "Iran": ["iran", "iranian"],
    "Saudi Arabia": ["saudi", "saudi arabia"],
    "Qatar": ["qatar", "qatari"],
    "Turkey": ["turkey", "turkish"],
    "Czech Republic": ["czech", "czech republic"],
    "Bosnia-Herzegovina": ["bosnia", "bosnian"],
}

INJURY_WORDS = [
    "injury", "injured", "ruled out", "doubt", "doubtful",
    "torn acl", "torn hamstring", "fracture", "fractured",
    "surgery", "stretchered off", "in tears", "setback",
    "misses", "will miss", "out of", "sidelined", "absent",
    "fitness test", "race to be fit", "fighting to be fit",
    "replaced by", "called up as replacement",
]


def scan_news_for_injuries(news_data: dict) -> list:
    """
    Scan news_feed.json articles for injury mentions.
    Returns list of {player, nation, injury_type, source, confidence} dicts.
    """
    findings = []
    articles = news_data.get("articles", [])

    for article in articles:
        title = (article.get("title", "") or "").lower()
        summary = (article.get("summary", "") or "").lower()
        full_text = title + " " + summary

        # Check if article mentions injuries
        has_injury = any(w in full_text for w in INJURY_WORDS)
        if not has_injury:
            continue

        # Determine which nation(s) are mentioned
        nations_found = []
        for nation, keywords in TEAM_NEWS_MAP.items():
            if any(kw in full_text for kw in keywords):
                nations_found.append(nation)

        if nations_found:
            findings.append({
                "title": article.get("title", ""),
                "nations": nations_found,
                "source": article.get("source", "unknown"),
                "url": article.get("url", ""),
                "summary": article.get("summary", "")[:200],
                "published": article.get("published_at", ""),
            })

    return findings


# ============================================================
# 4. INJURY STATUS UPDATE LOGIC
# ============================================================

def load_existing_injuries() -> dict:
    """Load current injuries.json."""
    path = DATA_DIR / "injuries.json"
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"_meta": {}, "injuries": []}


def save_injuries(data: dict):
    """Save injuries to JSON file."""
    data["_meta"]["last_updated"] = datetime.now().isoformat()
    path = DATA_DIR / "injuries.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"  [OK] injuries.json saved ({len(data.get('injuries', []))} injuries)")


def update_injury_status(injuries_data: dict) -> dict:
    """
    Update injury statuses based on time progression:
    - 'doubtful' → 'fit' if expected_return date has passed
    - 'probable' → 'fit' if expected_return date has passed + 1 day
    - Update 'since' timestamps to relative descriptions
    """
    now = datetime.now()
    updated_count = 0

    for injury in injuries_data.get("injuries", []):
        old_status = injury.get("status", "")

        # Auto-resolve based on expected_return
        expected = injury.get("expected_return")
        if expected:
            try:
                return_date = datetime.fromisoformat(expected)
                if now > return_date + timedelta(days=2):
                    if injury["status"] in ("doubtful", "questionable", "probable"):
                        injury["status"] = "fit"
                        injury["notes"] = (injury.get("notes", "") +
                                         f" [AUTO: expected return {expected} passed]").strip()
                        updated_count += 1
                elif now > return_date:
                    if injury["status"] == "probable":
                        injury["status"] = "fit"
                        updated_count += 1
                    elif injury["status"] == "doubtful":
                        injury["status"] = "questionable"
                        updated_count += 1
            except (ValueError, TypeError):
                pass

        # Update severity for resolved injuries
        if injury["status"] == "fit":
            injury["severity"] = "minor"

    if updated_count > 0:
        print(f"  [INFO] Auto-updated {updated_count} injury statuses based on timeline")

    return injuries_data


def recompute_team_summary(injuries_data: dict) -> dict:
    """Rebuild team_summary from current injuries list."""
    from collections import defaultdict

    summary = defaultdict(lambda: {
        "out": 0, "doubtful": 0, "questionable": 0, "probable": 0,
        "critical_out": [], "critical_doubtful": [], "critical_probable": [],
        "major_out": [], "major_doubtful": [],
        "moderate_out": [],
    })

    for inj in injuries_data.get("injuries", []):
        nation = inj["nation"]
        status = inj["status"]
        severity = inj["severity"]
        player = inj["player"]

        if status in ("out", "doubtful", "questionable", "probable"):
            summary[nation][status] = summary[nation].get(status, 0) + 1

        if status == "out" and severity == "critical":
            summary[nation]["critical_out"].append(player)
        elif status == "out" and severity == "major":
            summary[nation]["major_out"].append(player)
        elif status == "out" and severity == "moderate":
            summary[nation]["moderate_out"].append(player)
        elif status in ("doubtful", "questionable") and severity == "critical":
            summary[nation]["critical_doubtful"].append(player)
        elif status in ("doubtful", "questionable") and severity == "major":
            summary[nation]["major_doubtful"].append(player)
        elif status == "probable" and severity == "critical":
            summary[nation]["critical_probable"].append(player)

    injuries_data["team_summary"] = dict(summary)
    return injuries_data


# ============================================================
# 5. MAIN FETCH ROUTINE
# ============================================================

def fetch_all_injuries(quick: bool = False) -> dict:
    """Main routine: fetch injuries from all sources and merge."""
    data = load_existing_injuries()
    existing_players = {(i["player"], i["nation"]) for i in data.get("injuries", [])}
    new_count = 0

    # --- FotMob API ---
    if not quick:
        print("[1/3] FotMob API...")
        wc_matches = fetch_fotmob_matches()
        for match in wc_matches.get("matches", [])[:10]:  # limit to recent matches
            match_id = match.get("id")
            if match_id:
                details = fetch_fotmob_match_details(match_id)
                fotmob_injuries = extract_injuries_from_fotmob(details)
                for inj in fotmob_injuries:
                    key = (inj["player"], "")  # FotMob may not have nation directly
                    if key not in existing_players:
                        data["injuries"].append({
                            "player": inj["player"],
                            "nation": "",  # needs cross-referencing
                            "position": "",
                            "status": "out",
                            "injury_type": inj.get("reason", "Unknown"),
                            "since": datetime.now().strftime("%Y-%m-%d"),
                            "expected_return": None,
                            "severity": "moderate",
                            "notes": f"FotMob match data: {inj.get('reason', '')}",
                            "source": "FotMob",
                        })
                        existing_players.add(key)
                        new_count += 1
        print(f"  FotMob: {new_count} new injuries found")

    # --- Transfermarkt ---
    if not quick:
        print("[2/3] Transfermarkt...")
        tm_injuries = fetch_transfermarkt_injuries()
        tm_new = 0
        for inj in tm_injuries:
            key = (inj["player"], "")
            if key not in existing_players:
                data["injuries"].append({
                    "player": inj["player"],
                    "nation": "",
                    "position": "",
                    "status": "out",
                    "injury_type": inj.get("injury_type", "Unknown"),
                    "since": datetime.now().strftime("%Y-%m-%d"),
                    "expected_return": inj.get("expected_return"),
                    "severity": "moderate",
                    "notes": f"Transfermarkt: {inj.get('injury_type', '')}",
                    "source": "Transfermarkt",
                })
                existing_players.add(key)
                tm_new += 1
        print(f"  Transfermarkt: {tm_new} new injuries found")

    # --- News Feed Scanning ---
    print("[3/3] News Feed Scanning...")
    try:
        news_path = DATA_DIR / "news_feed.json"
        if news_path.exists():
            with open(news_path, "r", encoding="utf-8") as f:
                news_data = json.load(f)
            news_findings = scan_news_for_injuries(news_data)
            print(f"  News: {len(news_findings)} injury-related articles found")
            # Save findings for manual review
            data["_news_injury_alerts"] = news_findings[:20]
        else:
            print(f"  News: news_feed.json not found, skipping")
    except Exception as e:
        print(f"  [WARN] News scan: {e}")

    # --- Update statuses ---
    data = update_injury_status(data)

    # --- Recompute team summary ---
    data = recompute_team_summary(data)

    return data


# ============================================================
# 6. TEAM-SPECIFIC QUERY
# ============================================================

def query_team_injuries(team: str) -> list:
    """Query injuries for a specific team."""
    data = load_existing_injuries()
    return [i for i in data.get("injuries", [])
            if i["nation"].lower() == team.lower()]


# ============================================================
# 7. ENTRY POINT
# ============================================================

if __name__ == "__main__":
    quick = "--quick" in sys.argv
    team_filter = None

    for i, arg in enumerate(sys.argv):
        if arg == "--team" and i + 1 < len(sys.argv):
            team_filter = sys.argv[i + 1]

    if team_filter:
        # Query mode
        injuries = query_team_injuries(team_filter)
        print(f"\nInjuries for {team_filter}:")
        print(f"{'Player':<25s} {'Status':<12s} {'Type':<35s} {'Severity':<10s}")
        print("-" * 85)
        for inj in injuries:
            print(f"{inj['player']:<25s} {inj['status']:<12s} {inj['injury_type']:<35s} {inj['severity']:<10s}")
        if not injuries:
            print("  (no injuries found)")
    else:
        # Full fetch mode
        print(f"\n{'='*55}")
        print(f"  World Cup Injury Tracker [{datetime.now().strftime('%Y-%m-%d %H:%M')}]")
        print(f"  Mode: {'quick (status update only)' if quick else 'full fetch'}")
        print(f"{'='*55}\n")

        data = fetch_all_injuries(quick=quick)
        save_injuries(data)

        # Print summary
        summary = data.get("team_summary", {})
        print(f"\n  Team Injury Summary:")
        print(f"  {'Team':<22s} {'OUT':>4s} {'DBT':>4s} {'QST':>4s} {'PROB':>4s}  Critical OUT")
        print(f"  {'-'*22} {'-'*4} {'-'*4} {'-'*4} {'-'*4}  {'-'*30}")
        for team in sorted(summary.keys()):
            s = summary[team]
            total = s.get("out", 0) + s.get("doubtful", 0) + s.get("questionable", 0) + s.get("probable", 0)
            if total > 0:
                crit = ", ".join(s.get("critical_out", [])[:3])
                print(f"  {team:<22s} {s.get('out',0):>4} {s.get('doubtful',0):>4} {s.get('questionable',0):>4} {s.get('probable',0):>4}  {crit or '-'}")

        print(f"\n  Done. Data saved to data/injuries.json")
