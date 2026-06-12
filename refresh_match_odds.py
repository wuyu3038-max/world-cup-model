"""
Auto-refresh match odds before each matchday.
Called by Vercel cron or manually.

Strategy:
  - Matchday 1 (played/pending): Use real Betfair/betting odds from web
  - Matchday 2-3 (future): Generate from V5 team powers
  - Played matches: Store actual results

The odds are merged into match_odds.json which feeds into the website.
"""
import json
from pathlib import Path
from datetime import datetime

DATA_DIR = Path(__file__).parent / "data"

# Known results (update as matches complete)
MATCH_RESULTS = {
    "Mexico_vs_South_Africa": "2-0",
}


def refresh_from_team_powers():
    """Regenerate match odds for ALL unplayed matches from team powers."""
    try:
        from model import (
            load_players_from_json, load_fifa_rankings, load_betting_odds,
            load_sponsors, compute_team_power_v2, GROUP_STRUCTURE_16x3
        )

        players = load_players_from_json()
        fifa = load_fifa_rankings()
        betting = load_betting_odds()
        sponsors = load_sponsors()

        team_powers = {}
        for teams in GROUP_STRUCTURE_16x3.values():
            for team in teams:
                tp = compute_team_power_v2(players, fifa, team,
                                          betting_data=betting,
                                          sponsors_data=sponsors)
                team_powers[team] = tp["combined"]

        schedule = json.load(open(DATA_DIR / "match_schedule.json", "r", encoding="utf-8"))

        def power_to_probs(hp, ap):
            adj = (hp - ap) + 1.0
            if adj > 10: return {"home": 0.90, "draw": 0.08, "away": 0.02}
            elif adj > 7: return {"home": 0.82, "draw": 0.13, "away": 0.05}
            elif adj > 5: return {"home": 0.73, "draw": 0.18, "away": 0.09}
            elif adj > 3: return {"home": 0.63, "draw": 0.22, "away": 0.15}
            elif adj > 2: return {"home": 0.55, "draw": 0.26, "away": 0.19}
            elif adj > 1: return {"home": 0.48, "draw": 0.29, "away": 0.23}
            elif adj > 0: return {"home": 0.42, "draw": 0.31, "away": 0.27}
            elif adj > -1: return {"home": 0.35, "draw": 0.33, "away": 0.32}
            elif adj > -2: return {"home": 0.28, "draw": 0.31, "away": 0.41}
            elif adj > -3: return {"home": 0.22, "draw": 0.29, "away": 0.49}
            elif adj > -5: return {"home": 0.15, "draw": 0.24, "away": 0.61}
            elif adj > -7: return {"home": 0.09, "draw": 0.19, "away": 0.72}
            elif adj > -10: return {"home": 0.05, "draw": 0.13, "away": 0.82}
            else: return {"home": 0.02, "draw": 0.08, "away": 0.90}

        # Load existing odds
        existing = json.load(open(DATA_DIR / "match_odds.json", "r", encoding="utf-8"))
        existing_odds = existing.get("match_odds", {})

        updated = 0
        for md_key in ["matchday_1", "matchday_2", "matchday_3"]:
            for m in schedule.get("matches", {}).get(md_key, []):
                home = m["home"]
                away = m["away"]
                date = m.get("date", "")
                group = m.get("group", "")

                key = f"{home}_vs_{away}".replace(" ", "_")

                # Skip if already has real odds (matchday 1) and not yet played
                existing_match = existing_odds.get(key, {})
                has_real_odds = existing_match.get("_note", "").startswith("Real") == False
                # Always regenerate matchday 2-3 odds
                is_matchday1_real = md_key == "matchday_1" and key in existing_odds
                if is_matchday1_real and existing_match.get("_note", "") == "":
                    continue  # Keep real odds for matchday 1

                hp = team_powers.get(home, 8.0)
                ap = team_powers.get(away, 8.0)
                probs = power_to_probs(hp, ap)

                def prob_to_odds(p):
                    return round(1.0 / max(p, 0.01), 2)

                # Check if match has been played
                result = MATCH_RESULTS.get(key)

                entry = {
                    "date": date,
                    "group": group,
                    "matchday": 1 if "matchday_1" in md_key else (2 if "matchday_2" in md_key else 3),
                    "betfair_1x2": {
                        "home": prob_to_odds(probs["home"]),
                        "draw": prob_to_odds(probs["draw"]),
                        "away": prob_to_odds(probs["away"])
                    },
                    "market_probs": {
                        "home": round(probs["home"], 3),
                        "draw": round(probs["draw"], 3),
                        "away": round(probs["away"], 3)
                    },
                }
                if result:
                    entry["result"] = result

                existing_odds[key] = entry
                updated += 1

        existing["match_odds"] = existing_odds
        existing["_meta"]["updated"] = datetime.now().isoformat()
        existing["_meta"]["auto_refreshed"] = True

        with open(DATA_DIR / "match_odds.json", "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2, ensure_ascii=False)

        return updated
    except Exception as e:
        print(f"Error refreshing match odds: {e}")
        import traceback
        traceback.print_exc()
        return 0


if __name__ == "__main__":
    n = refresh_from_team_powers()
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Refreshed {n} match odds")
