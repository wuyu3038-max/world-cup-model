"""
2026 FIFA World Cup Prediction Model — Enhanced Version
=======================================================
Data: world-cup-model/data/
  - world_cup_players.json   : Squad + individual player stats
  - league_stats.json        : League-level goal stats (2024-25 & 2025-26)
  - fifa_rankings.json       : FIFA World Rankings (June 2026)

Features:
  - FIFA Elo proxy via rankings
  - Player G+A weighted by league quality
  - Form trend (2024-25 → 2025-26)
  - Poisson match simulation
  - Monte Carlo group stage (1000 iterations)
"""

import json
import math
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Tuple, Optional

import numpy as np
import pandas as pd

# ============================================================
# 1. DATA LOADING
# ============================================================

DATA_DIR = Path(__file__).parent / "data"

def load_players_from_json() -> pd.DataFrame:
    """Load player data from JSON + supplement into flat DataFrame."""
    with open(DATA_DIR / "world_cup_players.json", "r", encoding="utf-8") as f:
        squads = json.load(f)

    rows = []
    for group_name, group_data in squads["groups"].items():
        for nation, team_data in group_data["teams"].items():
            for p in team_data.get("players", []):
                rows.append({
                    "nation": nation,
                    "group": group_name,
                    "player_name": p.get("name", ""),
                    "position": p.get("position", ""),
                    "age": p.get("age"),
                    "caps": p.get("caps"),
                    "club": p.get("club", ""),
                    "league": p.get("league", ""),
                    "goals_2024_25": p.get("goals_2425"),
                    "goals_2025_26": p.get("goals_2526"),
                    "assists_2025_26": p.get("assists_2526"),
                    "rating_2526": p.get("rating"),
                    "xg_2526": p.get("xg"),
                    "dribbles_2526": p.get("dribbles"),
                    "key_passes_2526": p.get("key_passes"),
                    "accurate_passes_2526": p.get("accurate_passes"),
                    "notes": p.get("notes", ""),
                })
    df = pd.DataFrame(rows)

    # Merge supplemental stats
    supp_path = DATA_DIR / "player_stats_supplement.json"
    if supp_path.exists():
        with open(supp_path, "r", encoding="utf-8") as f:
            supp = json.load(f)
        for p in supp.get("players", []):
            # Find matching player row (by name match within same nation)
            mask = (df["player_name"] == p["name"]) & (df["nation"] == p.get("nation", ""))
            if mask.any():
                idx = df[mask].index[0]
                if p.get("goals_2526") is not None:
                    df.at[idx, "goals_2025_26"] = p["goals_2526"]
                if p.get("assists_2526") is not None:
                    df.at[idx, "assists_2025_26"] = p["assists_2526"]
                if p.get("rating") is not None:
                    df.at[idx, "rating_2526"] = p["rating"]
                if p.get("goals_2425") is not None:
                    df.at[idx, "goals_2024_25"] = p["goals_2425"]
                if p.get("league") is not None:
                    df.at[idx, "league"] = p["league"]
    return df

def load_league_stats() -> dict:
    """Load league-level stats from JSON."""
    with open(DATA_DIR / "league_stats.json", "r", encoding="utf-8") as f:
        return json.load(f)

def load_fifa_rankings() -> dict:
    """Load FIFA rankings and return {team: rank} mapping."""
    with open(DATA_DIR / "fifa_rankings.json", "r", encoding="utf-8") as f:
        data = json.load(f)
    return {r["team"]: r["rank"] for r in data["rankings"]}

def load_betting_odds() -> dict:
    """Load betting odds data."""
    with open(DATA_DIR / "betting_odds.json", "r", encoding="utf-8") as f:
        return json.load(f)

def american_to_prob(odds: float) -> float:
    """Convert American odds to implied probability."""
    if odds > 0:
        return 100.0 / (odds + 100.0)
    else:
        return -odds / (-odds + 100.0)

def get_market_power(betting_data: dict) -> dict:
    """Extract market-implied team power from winner odds."""
    winner_odds = betting_data.get("tournament_winner_raw_odds", [])
    return {item["team"]: item.get("implied_prob", 0) * 100  # as percentage
            for item in winner_odds}


# ============================================================
# 2. LEAGUE QUALITY & FORM FACTORS
# ============================================================

LEAGUE_FACTORS = {
    "Premier League": 1.00,
    "La Liga": 0.95,
    "Bundesliga": 0.90,
    "Serie A": 0.85,
    "Ligue 1": 0.80,
    "MLS": 0.50,
    "Saudi Pro League": 0.55,
    "Qatar Stars League": 0.40,
    "Scottish Premiership": 0.60,
    "Serbian SuperLiga": 0.45,
    "Iraq Stars League": 0.25,
    "Eredivisie": 0.70,
    "Liga Portugal": 0.65,
}

def league_factor(league: str) -> float:
    return LEAGUE_FACTORS.get(league, 0.50)

# ============================================================
# 3. TEAM STRENGTH METRICS
# ============================================================

def compute_attack_score(players_df: pd.DataFrame, nation: str) -> float:
    """
    Attack score based on top-3 players' G+A, weighted by league quality & rating.
    Returns score normalized to ~0-100 scale.
    """
    team = players_df[players_df["nation"] == nation]
    if team.empty:
        return 0.0

    t = team.copy()
    t["goals_2025_26"] = pd.to_numeric(t["goals_2025_26"], errors="coerce").fillna(0)
    t["assists_2025_26"] = pd.to_numeric(t["assists_2025_26"], errors="coerce").fillna(0)
    t["g_a"] = t["goals_2025_26"] + t["assists_2025_26"]
    t["rating_2526"] = pd.to_numeric(t["rating_2526"], errors="coerce").fillna(6.5)
    top3 = t.nlargest(3, "g_a")
    top3 = t.nlargest(3, "g_a")

    score = 0.0
    weights = [0.5, 0.3, 0.2]  # top player weighted more
    for i, (_, row) in enumerate(top3.iterrows()):
        if i >= len(weights):
            break
        lf = league_factor(row.get("league", ""))
        rating = row.get("rating_2526") or 6.5
        score += row["g_a"] * lf * (rating / 7.0) * weights[i]

    return round(score, 2)


def compute_fifa_strength(rank: int) -> float:
    """Convert FIFA rank to a strength score (higher = stronger)."""
    # Elo-like: every ~100 ranks = ~1 standard deviation
    return max(2200 - rank * 10, 1200) / 100  # Normalized ~[3, 22]


def compute_form_bonus(players_df: pd.DataFrame, nation: str) -> float:
    """
    Compute the form trend: are key players improving or declining?
    Positive = players scoring more in 2025-26 vs 2024-25.
    """
    team = players_df[players_df["nation"] == nation]
    if team.empty:
        return 0.0

    form = 0.0
    count = 0
    for _, row in team.iterrows():
        g24 = row["goals_2024_25"]
        g25 = row["goals_2025_26"]
        if pd.notna(g24) and pd.notna(g25) and g24 > 0:
            trend = (g25 - g24) / g24  # e.g., +0.38 for a 38% increase
            form += trend
            count += 1

    return round(form / max(count, 1), 3)


def compute_team_power(players_df: pd.DataFrame, fifa_ranks: dict, nation: str) -> dict:
    """Compute comprehensive team power score."""
    attack = compute_attack_score(players_df, nation)
    rank = fifa_ranks.get(nation, 60)
    fifa_str = compute_fifa_strength(rank)
    form = compute_form_bonus(players_df, nation)

    # Handle NaN
    attack = attack if not np.isnan(attack) else 0.0
    form = form if not np.isnan(form) else 0.0

    # Combined: use FIFA as baseline, attack as bonus
    combined = attack * 0.50 + fifa_str * 0.40 + (form * 5 if not np.isnan(form) else 0)

    # Count top-league players
    team = players_df[players_df["nation"] == nation]
    elite_players = sum(1 for _, r in team.iterrows()
                        if league_factor(r.get("league", "")) >= 0.80)

    return {
        "nation": nation,
        "attack_score": round(attack, 1),
        "fifa_strength": round(fifa_str, 1),
        "form_trend": form,
        "combined": round(combined, 1),
        "elite_players": elite_players,
        "fifa_rank": rank,
    }


# ============================================================
# 4. POISSON MATCH SIMULATION
# ============================================================

def simulate_match(home_power: float, away_power: float,
                   home_advantage: float = 0.25) -> Tuple[int, int]:
    """
    Simulate a single match score using Poisson distribution.
    """
    LEAGUE_AVG = 1.40

    # Handle NaN/zero power
    hp = max(home_power, 0.01)
    ap = max(away_power, 0.01)

    home_factor = 0.3 + hp / 8
    away_factor = 0.3 + ap / 8

    home_xg = home_factor * LEAGUE_AVG + home_advantage
    away_xg = away_factor * LEAGUE_AVG

    home_goals = np.random.poisson(max(home_xg, 0.05))
    away_goals = np.random.poisson(max(away_xg, 0.05))

    return home_goals, away_goals


# ============================================================
# 5. GROUP STAGE SIMULATION (16 groups of 3)
# ============================================================

# Actual 2026 format: 16 groups × 3 teams, top 2 advance to Round of 32
GROUP_STRUCTURE_16x3 = {
    "A":  ["Mexico", "South Africa", "South Korea", "Czech Republic"],
    "B":  ["Canada", "Bosnia-Herzegovina", "Qatar", "Switzerland"],
    "C":  ["Brazil", "Morocco", "Haiti", "Scotland"],
    "D":  ["United States", "Paraguay", "Australia", "Turkey"],
    "E":  ["Germany", "Curacao", "Ivory Coast", "Ecuador"],
    "F":  ["Netherlands", "Japan", "Sweden", "Tunisia"],
    "G":  ["Belgium", "Egypt", "Iran", "New Zealand"],
    "H":  ["Spain", "Cape Verde", "Saudi Arabia", "Uruguay"],
    "I":  ["France", "Senegal", "Iraq", "Norway"],
    "J":  ["Argentina", "Algeria", "Austria", "Jordan"],
    "K":  ["Portugal", "Congo DR", "Uzbekistan", "Colombia"],
    "L":  ["England", "Croatia", "Ghana", "Panama"],
}

def simulate_group_stage(players_df: pd.DataFrame, fifa_ranks: dict,
                         n_sims: int = 1000) -> dict:
    """Simulate group stage N times and return advancement probabilities."""
    # Pre-compute team powers (ensure no NaN)
    powers = {}
    for teams in GROUP_STRUCTURE_16x3.values():
        for team in teams:
            tp = compute_team_power(players_df, fifa_ranks, team)
            p = tp["combined"]
            if np.isnan(p) or p <= 0:
                p = 0.5  # fallback for teams with no data
            powers[team] = p

    advancement = defaultdict(lambda: defaultdict(int))

    for sim in range(n_sims):
        for group_name, teams in GROUP_STRUCTURE_16x3.items():
            # Round-robin (4 teams per group for now)
            points = {t: 0 for t in teams}
            for i, t1 in enumerate(teams):
                for t2 in teams[i + 1:]:
                    # Alternate home/away
                    hg, ag = simulate_match(powers[t1], powers[t2])
                    if hg > ag:
                        points[t1] += 3
                    elif ag > hg:
                        points[t2] += 3
                    else:
                        points[t1] += 1
                        points[t2] += 1

            ranked = sorted(points.items(), key=lambda x: (-x[1], x[0]))
            advancement[group_name][ranked[0][0]] += 1
            advancement[group_name][ranked[1][0]] += 1

    # Convert to probabilities
    probs = {}
    for g, counts in advancement.items():
        probs[g] = {t: round(c / n_sims, 4) for t, c in sorted(counts.items(), key=lambda x: -x[1])}
    return probs


# ============================================================
# 6. TOURNAMENT SIMULATION (Knockout)
# ============================================================

def simulate_knockout(powers: dict, bracket: List[str],
                      n_sims: int = 1000, label: str = "") -> dict:
    """Simulate a knockout bracket and return win probabilities."""
    # For simplicity, simulate head-to-head for each pair
    pass


# ============================================================
# 7. ANALYSIS & REPORTING
# ============================================================

def analyze(players_df: pd.DataFrame, fifa_ranks: dict, betting_data: dict = None) -> None:
    """Run comprehensive analysis."""

    print("=" * 65)
    print("  2026 FIFA WORLD CUP - PREDICTION MODEL ANALYSIS")
    print("=" * 65)

    # --- A. Top Players by G+A ---
    print("\n" + "-" * 60)
    print("  [1] TOP 10 WORLD CUP PLAYERS (2025-26 G+A)")
    print("-" * 60)
    df = players_df.copy()
    df["g_a"] = df["goals_2025_26"].fillna(0) + df["assists_2025_26"].fillna(0)
    top10 = df.nlargest(10, "g_a")
    for idx, (_, r) in enumerate(top10.iterrows(), 1):
        g = int(r["goals_2025_26"]) if pd.notna(r["goals_2025_26"]) else 0
        a = int(r["assists_2025_26"]) if pd.notna(r["assists_2025_26"]) else 0
        rat = r['rating_2526'] if pd.notna(r['rating_2526']) else '--'
        club = str(r['club']) if pd.notna(r['club']) else '--'
        name = str(r['player_name'])
        nation = str(r['nation'])
        print(f"  {idx:>2}. {name:<22s} {nation:<15s} {g:>2d}G+{a:>2d}A={g+a:>2d}"
              f"  Rating:{rat!s:>4s}  [{club}]")

    # --- B. Team Power Rankings ---
    print("\n" + "-" * 60)
    print("  [2] TEAM POWER RANKINGS (Top 20)")
    print("-" * 60)
    all_powers = []
    nations = sorted(players_df["nation"].unique())
    for nat in nations:
        tp = compute_team_power(players_df, fifa_ranks, nat)
        if tp["combined"] > 0:
            all_powers.append(tp)
    all_powers.sort(key=lambda x: x["combined"], reverse=True)

    for i, tp in enumerate(all_powers[:20], 1):
        group = players_df[players_df["nation"] == tp["nation"]]["group"].iloc[0]
        bar = "#" * int(tp["combined"] * 3)
        print(f"  {i:>2}. {tp['nation']:<20s} PWR={tp['combined']:>5.1f}  "
              f"ATT={tp['attack_score']:>5.1f}  FIFA#{tp['fifa_rank']:<3d}  G.{group}  {bar}")

    # --- C. Dark Horses ---
    print("\n" + "-" * 60)
    print("  [3] DARK HORSES (Attack > FIFA rank suggests)")
    print("-" * 60)
    dark = []
    for tp in all_powers:
        expected = (100 - tp["fifa_rank"]) * 0.25
        surprise = tp["combined"] - expected
        dark.append((tp["nation"], surprise, tp))
    dark.sort(key=lambda x: x[1], reverse=True)
    for nation, surprise, tp in dark[:8]:
        print(f"  {nation:<20s}  Surprise +{surprise:.1f}  "
              f"(FIFA#{tp['fifa_rank']}, PWR={tp['combined']:.1f}, Elite={tp['elite_players']})")

    # --- D. Form Trends ---
    print("\n" + "-" * 60)
    print("  [4] FORM TRENDS (2024-25 -> 2025-26 goal change)")
    print("-" * 60)
    trends = []
    for nat in nations:
        f = compute_form_bonus(players_df, nat)
        if f != 0:
            trends.append((nat, f))
    trends.sort(key=lambda x: x[1], reverse=True)
    for nat, f in trends[:8]:
        arrow = "[UP]" if f > 0.1 else ("[DN]" if f < -0.1 else "[--]")
        print(f"  {arrow} {nat:<20s}  {f:+.0%}")
    print("  (negative = players scoring less than last season)")

    # --- E. Group Stage Simulation ---
    print("\n" + "-" * 60)
    print("  [5] GROUP STAGE SIMULATION (1000 Monte Carlo runs)")
    print("-" * 60)
    np.random.seed(42)
    probs = simulate_group_stage(players_df, fifa_ranks, n_sims=1000)

    for group_name in sorted(probs.keys()):
        team_probs = probs[group_name]
        print(f"\n  GROUP {group_name}:")
        for team, prob in sorted(team_probs.items(), key=lambda x: -x[1]):
            bar = "#" * int(prob * 40)
            print(f"    {team:<22s} {prob:>6.1%} {bar}")

    # --- F. Tournament Favorites ---
    all_advance = defaultdict(float)
    for g, team_probs in probs.items():
        for team, prob in team_probs.items():
            all_advance[team] = prob

    print("\n" + "-" * 60)
    print("  [6] TOURNAMENT FAVORITES (group advance probability)")
    print("-" * 60)
    for rank, (team, prob) in enumerate(
        sorted(all_advance.items(), key=lambda x: -x[1])[:16], 1
    ):
        bar = "#" * int(prob * 40)
        print(f"  {rank:>2}. {team:<22s} {prob:>6.1%} {bar}")

    # --- G. Group of Death ---
    print("\n" + "-" * 60)
    print("  [7] GROUP OF DEATH (highest combined power)")
    print("-" * 60)
    group_stats = {}
    for g, teams in GROUP_STRUCTURE_16x3.items():
        pwr = [next((tp["combined"] for tp in all_powers if tp["nation"] == t), 0) for t in teams]
        group_stats[g] = {"avg": np.mean(pwr), "min": min(pwr), "range": max(pwr) - min(pwr), "teams": teams}
    for g, v in sorted(group_stats.items(), key=lambda x: -x[1]["avg"]):
        print(f"  Group {g}: avg={v['avg']:.1f}  range={v['range']:.1f}  "
              f"min={v['min']:.1f}")

    # --- H. Market vs Model Comparison ---
    if betting_data:
        print("\n" + "-" * 60)
        print("  [8] MODEL vs BETTING MARKET (value detection)")
        print("-" * 60)
        market_power = get_market_power(betting_data)

        # Compare top teams
        print(f"  {'Team':<20s} {'Model':>7s} {'Market':>7s} {'Diff':>7s}  Signal")
        print(f"  {'-'*20} {'-'*7} {'-'*7} {'-'*7}  {'-'*30}")
        comparisons = []
        for tp in all_powers[:20]:
            nat = tp["nation"]
            model_p = tp["combined"]
            market_p = market_power.get(nat, 0.1)
            diff = model_p - market_p
            comparisons.append((nat, model_p, market_p, diff))

        comparisons.sort(key=lambda x: -x[3])  # sort by model over market
        for nat, m_model, m_market, diff in comparisons[:12]:
            signal = "MODEL HIGH (undervalued)" if diff > 2 else ("MARKET HIGH (overvalued)" if diff < -2 else "in line")
            print(f"  {nat:<20s} {m_model:>6.1f}  {m_market:>6.1f}  {diff:>+6.1f}  {signal}")

        # Top value bets (model says better than market)
        print(f"\n  >> VALUE BETS (Model > Market by biggest margin):")
        comparisons.sort(key=lambda x: -x[3])
        for nat, m_model, m_market, diff in comparisons[:5]:
            print(f"     {nat}: Model PWR={m_model:.1f} vs Market={m_market:.1f}")

        # Group winner odds comparison
        print(f"\n  >> GROUP WINNER MARKET FAVORITES vs MODEL:")
        group_odds = betting_data.get("group_winners_odds", {})
        for g_name in sorted(group_odds.keys()):
            gw = group_odds[g_name]
            fav = gw["favorite"]
            mkt_prob = gw.get("implied_prob", 0)
            # Find model's group advance prob for this team
            model_prob = all_advance.get(fav, 0)
            diff = model_prob - mkt_prob
            signal = "(value)" if diff > 0.05 else ("(overvalued)" if diff < -0.05 else "")
            print(f"     Group {g_name}: {fav:<18s} Market={mkt_prob:.0%}  Model={model_prob:.0%}  {signal}")

    print("\n" + "=" * 65)
    print(f"  Analysis complete. {len(all_powers)} teams evaluated.")
    print("=" * 65)


# ============================================================
# 8. ENTRY POINT
# ============================================================

if __name__ == "__main__":
    print("Loading data...")
    players = load_players_from_json()
    fifa_ranks = load_fifa_rankings()
    league = load_league_stats()
    betting = load_betting_odds()

    n_players = len(players)
    n_nations = len(players['nation'].unique())
    n_ranks = len(fifa_ranks)
    n_leagues = len(league['leagues'])
    n_odds = len(betting.get('tournament_winner_raw_odds', []))
    print(f"  [OK] {n_players} players from {n_nations} nations")
    print(f"  [OK] FIFA rankings loaded for {n_ranks} teams")
    print(f"  [OK] League stats for {n_leagues} competitions")
    print(f"  [OK] Betting odds for {n_odds} teams")

    analyze(players, fifa_ranks, betting)

    print(f"\n  Data directory: {DATA_DIR.resolve()}")
    print("  Edit model.py to customize prediction logic.")
