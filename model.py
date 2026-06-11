"""
2026 FIFA World Cup Prediction Model — V2 (4-Factor Integrated)
================================================================
Data: world-cup-model/data/
  - world_cup_players.json   : Squad + individual player stats
  - league_stats.json        : League-level goal stats (2024-25 & 2025-26)
  - fifa_rankings.json       : FIFA World Rankings (June 2026)
  - betting_odds.json        : Tournament winner / group / match odds
  - sponsors.json            : Kit sponsors, brand power, pressure penalties
  - environment.json         : 16 host city weather / altitude / WBGT data
  - match_schedule.json      : 104-match schedule with venue mapping

Features:
  - FIFA Elo proxy via rankings
  - Player G+A weighted by league quality
  - Form trend (2024-25 → 2025-26)
  - Betting market prior (sqrt-scaled implied probability)
  - Environmental xG multiplier (heat stress × altitude × roof)
  - Sponsor brand bonus + pressure/conflict penalty
  - Market sentiment placeholder (Betfair-ready)
  - Poisson match simulation with env modifiers
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

def load_sponsors() -> dict:
    """Load kit sponsor data including brand power index and pressure penalties."""
    with open(DATA_DIR / "sponsors.json", "r", encoding="utf-8") as f:
        return json.load(f)

def load_environment() -> dict:
    """Load venue/city environmental data (temperature, elevation, WBGT, roof)."""
    with open(DATA_DIR / "environment.json", "r", encoding="utf-8") as f:
        return json.load(f)

def load_match_schedule() -> dict:
    """Load complete 104-match schedule with venue/city mappings."""
    with open(DATA_DIR / "match_schedule.json", "r", encoding="utf-8") as f:
        return json.load(f)

def load_betfair_index() -> dict:
    """Load Betfair Exchange index data (必发指数)."""
    path = DATA_DIR / "betfair_index.json"
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def load_news_feed() -> dict:
    """Load latest news feed data for sentiment analysis."""
    path = DATA_DIR / "news_feed.json"
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def load_head_to_head() -> dict:
    """Load head-to-head historical match data."""
    path = DATA_DIR / "head_to_head.json"
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def load_injuries() -> dict:
    """Load structured player injury data."""
    path = DATA_DIR / "injuries.json"
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def load_lineups() -> dict:
    """Load match lineup data (starting XI per match)."""
    path = DATA_DIR / "lineups.json"
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


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
                   home_advantage: float = 0.10,
                   env_factor_home: float = 1.0,
                   env_factor_away: float = 1.0,
                   betfair_boost: float = 1.0,
                   news_boost: float = 1.0,
                   h2h_boost: float = 1.0) -> Tuple[int, int]:
    """
    Simulate a single match score using Poisson distribution.

    Parameters:
      env_factor_home/away: xG multiplier for environmental conditions
        - 1.0 = neutral, <1.0 = adverse (heat, altitude)
      betfair_boost: xG multiplier from Betfair money flow (必发资金流)
        - Range [0.88, 1.12], default 1.0
      news_boost: xG multiplier from news sentiment (时事新闻)
        - Range [0.92, 1.08], default 1.0
      h2h_boost: xG multiplier from H2H history + common opponent analysis
        - 1.0 = neutral, >1.0 = home has historical edge
        - Range [0.95, 1.05] (direct H2H ±2.5% + common opp ±2%)
    """
    LEAGUE_AVG = 1.40

    # Handle NaN/zero power
    hp = max(home_power, 0.01)
    ap = max(away_power, 0.01)

    # xG scaling calibrated to real match data:
    # power=5 (weak) → 0.7 xG, power=10 (mid) → 1.2 xG, power=15 (top) → 1.9 xG
    # Steeper slope to differentiate strong from weak teams
    home_xg = (0.3 + hp / 9.0) + home_advantage
    away_xg = 0.3 + ap / 9.0

    # Apply all modifiers
    home_xg = home_xg * env_factor_home * betfair_boost * news_boost * h2h_boost
    away_xg = away_xg * env_factor_away

    # Dixon-Coles rho correction: adjusts low-score probabilities
    # Negative rho increases 0-0 and 1-1 (draws), decreases 1-0 and 0-1
    # Calibrated to historical draw rate of 25-29%
    DIXON_COLES_RHO = -0.18

    # Sample from Dixon-Coles adjusted distribution instead of raw Poisson
    lam = max(home_xg, 0.05)
    mu = max(away_xg, 0.05)
    rho = DIXON_COLES_RHO

    # Build probability table for scores 0-10
    probs = []
    total_p = 0.0
    for h in range(11):
        for a in range(11):
            p = (lam**h * np.exp(-lam) / math.factorial(h) *
                 mu**a * np.exp(-mu) / math.factorial(a))
            # Dixon-Coles tau adjustment for low scores
            if h == 0 and a == 0:
                p *= (1.0 - lam * mu * rho)
            elif h == 0 and a == 1:
                p *= (1.0 + lam * rho)
            elif h == 1 and a == 0:
                p *= (1.0 + mu * rho)
            elif h == 1 and a == 1:
                p *= (1.0 - rho)
            p = max(p, 0.0)
            probs.append((h, a, p))
            total_p += p

    # Normalize and sample
    if total_p > 0:
        r = np.random.random() * total_p
        cum = 0.0
        for h, a, p in probs:
            cum += p
            if r <= cum:
                return h, a
        return probs[-1][0], probs[-1][1]  # fallback
    else:
        return 0, 0


def predict_match(home_power: float, away_power: float,
                  team_home: str = "", team_away: str = "",
                  n_sims: int = 10000,
                  home_advantage: float = 0.10,
                  h2h_data: dict = None) -> dict:
    """
    Predict match outcome with H2H historical data blended in.
    This is the PRIMARY prediction function — use this, not raw simulate_match.

    Returns dict with:
      - hw, dw, aw: blended win/draw/loss probabilities
      - hw_raw, dw_raw, aw_raw: pure model probabilities (before H2H blend)
      - h2h_weight: how much H2H influenced the blend (0-0.35)
      - h2h_n: number of historical matches used
      - top_scores: most likely scorelines
      - home_xg, away_xg: expected goals
    """
    # 1. Pure model simulation
    hw_raw = dw_raw = aw_raw = 0
    scores = {}
    for _ in range(n_sims):
        hg, ag = simulate_match(home_power, away_power, home_advantage)
        if hg > ag: hw_raw += 1
        elif hg == ag: dw_raw += 1
        else: aw_raw += 1
        key = "%d-%d" % (hg, ag)
        scores[key] = scores.get(key, 0) + 1

    hw_raw /= n_sims; dw_raw /= n_sims; aw_raw /= n_sims

    # 2. Blend with H2H historical data
    if team_home and team_away and h2h_data:
        hw, dw, aw, h2h_w, h2h_n = compute_h2h_blend(
            team_home, team_away, hw_raw, dw_raw, aw_raw, h2h_data)
    else:
        hw, dw, aw = hw_raw, dw_raw, aw_raw
        h2h_w, h2h_n = 0.0, 0

    # 3. Top scorelines
    top_scores = sorted(scores.items(), key=lambda x: -x[1])[:5]
    top_scores = [(s, c/n_sims) for s, c in top_scores]

    # 4. Expected goals
    home_xg = 0.5 + home_power / 12.0 + home_advantage
    away_xg = 0.5 + away_power / 12.0

    # 5. Draw bias: when teams are evenly matched, boost draw probability
    # Close matches (gap < 0.08) → predict draw to match historical 25%+ draw rate
    gap = abs(hw - aw)
    if gap < 0.06:
        prediction = "D"
    elif hw > aw and hw > dw:
        prediction = "H"
    elif aw > hw and aw > dw:
        prediction = "A"
    else:
        prediction = "D"

    # 6. Upset check: if underdog has unusual Betfair backing
    upset_risk = _check_upset_risk(team_home, team_away, hw, aw)

    return {
        "hw": hw, "dw": dw, "aw": aw,
        "hw_raw": hw_raw, "dw_raw": dw_raw, "aw_raw": aw_raw,
        "h2h_weight": h2h_w, "h2h_n": h2h_n,
        "top_scores": top_scores,
        "home_xg": round(home_xg, 2), "away_xg": round(away_xg, 2),
        "prediction": prediction,
        "upset_risk": upset_risk,
    }


def _check_upset_risk(team_home: str, team_away: str, hw: float, aw: float) -> str:
    """
    Check if this match has upset potential based on historical patterns.
    Returns 'HIGH', 'MEDIUM', 'LOW', or 'NONE'.
    """
    if not team_home or not team_away:
        return "NONE"

    # Load upset database
    try:
        with open(DATA_DIR / "upsets.json", "r", encoding="utf-8") as f:
            upsets_db = json.load(f)
    except Exception:
        return "NONE"

    upsets = upsets_db.get("upsets", [])

    # Check if either team has been involved in historical upsets
    home_upsets = 0
    away_upsets = 0
    for u in upsets:
        if team_home in [u["favorite"], u["underdog"]]:
            home_upsets += 1
        if team_away in [u["favorite"], u["underdog"]]:
            away_upsets += 1

    # Strong favorite (hw > 55%) with history of being upset
    if hw > 0.55 and home_upsets >= 1:
        return "MEDIUM"
    if aw > 0.55 and away_upsets >= 1:
        return "MEDIUM"

    # Very strong favorite (>65%) with multiple upset history
    if hw > 0.65 and home_upsets >= 2:
        return "HIGH"
    if aw > 0.65 and away_upsets >= 2:
        return "HIGH"

    if home_upsets >= 2 or away_upsets >= 2:
        return "LOW"

    return "NONE"


def load_upsets() -> dict:
    """Load historical upsets database."""
    path = DATA_DIR / "upsets.json"
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


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
    """Simulate group stage N times and return advancement probabilities.
    Now includes H2H + common opponent modifiers per match."""
    # Pre-compute team powers (ensure no NaN)
    powers = {}
    for teams in GROUP_STRUCTURE_16x3.values():
        for team in teams:
            tp = compute_team_power(players_df, fifa_ranks, team)
            p = tp["combined"]
            if np.isnan(p) or p <= 0:
                p = 0.5
            powers[team] = p

    # Load H2H data once
    h2h_data = None
    try:
        h2h_data = load_head_to_head()
    except Exception:
        pass

    advancement = defaultdict(lambda: defaultdict(int))

    for sim in range(n_sims):
        for group_name, teams in GROUP_STRUCTURE_16x3.items():
            points = {t: 0 for t in teams}
            for i, t1 in enumerate(teams):
                for t2 in teams[i + 1:]:
                    # H2H + common opponent boost
                    h2h_mod = compute_h2h_modifier(t1, t2, h2h_data)
                    co_mod = compute_common_opponent_modifier(t1, t2, h2h_data, fifa_ranks)
                    h2h_boost = 1.0 + h2h_mod * 0.05 + co_mod * 0.02

                    hg, ag = simulate_match(powers[t1], powers[t2], h2h_boost=h2h_boost)
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

def analyze(players_df: pd.DataFrame, fifa_ranks: dict, betting_data: dict = None,
            sponsors_data: dict = None, environment_data: dict = None,
            schedule_data: dict = None) -> None:
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

    # --- I. Environmental Impact ---
    if environment_data and schedule_data:
        print("\n" + "-" * 60)
        print("  [9] ENVIRONMENTAL IMPACT — Venue Risk Assessment")
        print("-" * 60)
        cities = environment_data.get("cities", {})
        venue_map = build_venue_lookup(schedule_data)

        # Summarize risk levels
        extreme_venues = []
        high_venues = []
        altitude_venues = []
        for name, c in cities.items():
            risk = c.get("heat_risk", "LOW")
            elev = c.get("elevation_m", 0)
            if "EXTREME" in risk.upper():
                extreme_venues.append((name, c.get("wbgt_risk", "")))
            elif "HIGH" in risk.upper():
                high_venues.append(name)
            if elev >= 1500:
                altitude_venues.append((name, elev))

        print(f"\n  EXTREME HEAT VENUES (factor ~0.88):")
        for name, wbgt in extreme_venues:
            print(f"    {name:<25s} — {wbgt}")
        print(f"\n  HIGH HEAT VENUES (factor ~0.92):")
        for name in high_venues:
            c = cities[name]
            print(f"    {name:<25s} — T={c.get('avg_temp_june_c','?')}C  RH={c.get('avg_humidity_pct','?')}%  "
                  f"Roof: {'YES' if c.get('roof') else 'no'}")
        print(f"\n  ALTITUDE VENUES:")
        for name, elev in altitude_venues:
            print(f"    {name:<25s} — {elev}m "
                  f"({'MAJOR effect' if elev >= 2000 else 'MODERATE effect'})")

        # Count affected matches
        affected = sum(1 for v in venue_map.values()
                       if cities.get(v["city"], {}).get("heat_risk", "") in ("EXTREME", "HIGH")
                       and not v.get("roof", False))
        total = len(venue_map) // 2  # venue_map has both forward and reverse keys
        print(f"\n  Matches at HIGH+ heat risk (open air): ~{affected} out of ~{total}")
        print(f"  Safest venues: Vancouver, Seattle, Toronto, Los Angeles, San Francisco")

    # --- J. Sponsor Analysis ---
    if sponsors_data:
        print("\n" + "-" * 60)
        print("  [10] SPONSOR INFLUENCE — Brand Power & Pressure Penalties")
        print("-" * 60)
        kit = sponsors_data.get("kit_sponsors", {})
        brand_count = defaultdict(int)
        for team, brand in kit.items():
            brand_count[brand] += 1
        print(f"\n  Brand Distribution (48 teams):")
        for brand, count in sorted(brand_count.items(), key=lambda x: -x[1]):
            bonus = BRAND_BONUS.get(brand, 0.0)
            print(f"    {brand:<15s}: {count:>2d} teams  (bonus +{bonus:.1f})")

        pressure = sponsors_data.get("sponsor_pressure_penalty", {})
        # Filter out metadata keys (those starting with _)
        pressure_teams = {k: v for k, v in pressure.items()
                          if not k.startswith("_") and isinstance(v, (int, float))}
        if pressure_teams:
            print(f"\n  Pressure Penalties:")
            for team, penalty in sorted(pressure_teams.items(), key=lambda x: x[1]):
                print(f"    {team:<20s} {penalty:+.1f}")

        conflicts = sponsors_data.get("sponsor_conflicts", [])
        if conflicts:
            print(f"\n  Active Sponsor Conflicts:")
            for c in conflicts:
                teams = ", ".join(c.get("teams", []))
                print(f"    [{c.get('severity', '?')}] {teams}: {c.get('issue', '?')}")

    # --- K. V2 vs V1 Comparison ---
    print("\n" + "-" * 60)
    print("  [11] V2 vs V1 — Power Rankings Comparison")
    print("-" * 60)
    v1_powers = {}
    v2_powers = {}
    for nat in sorted(players_df["nation"].unique()):
        v1 = compute_team_power(players_df, fifa_ranks, nat)
        if v1["combined"] > 0:
            v1_powers[nat] = v1["combined"]
        v2 = compute_team_power_v2(players_df, fifa_ranks, nat,
                                   betting_data=betting_data,
                                   sponsors_data=sponsors_data)
        if v2["combined"] > 0:
            v2_powers[nat] = v2

    # Rank changes
    v1_ranked = sorted(v1_powers.items(), key=lambda x: -x[1])
    v1_rank_map = {team: i for i, (team, _) in enumerate(v1_ranked)}
    v2_ranked = sorted(v2_powers.items(), key=lambda x: -x[1]["combined"])
    v2_rank_map = {team: i for i, (team, _) in enumerate(v2_ranked)}

    # Teams with biggest rank change
    rank_changes = []
    for team in v1_rank_map:
        if team in v2_rank_map:
            delta = v1_rank_map[team] - v2_rank_map[team]  # positive = moved up in V2
            rank_changes.append((team, delta, v1_rank_map[team] + 1, v2_rank_map[team] + 1,
                                 v2_powers[team]))
    rank_changes.sort(key=lambda x: abs(x[1]), reverse=True)

    print(f"  Top 10 ranking changes (V1 → V2):")
    print(f"  {'Team':<20s} {'V1 Rank':>7s} {'V2 Rank':>7s} {'Δ':>5s}  {'V2 Factors'}")
    print(f"  {'-'*20} {'-'*7} {'-'*7} {'-'*5}  {'-'*30}")
    for team, delta, r1, r2, v2 in rank_changes[:10]:
        arrow = "↑" if delta > 0 else ("↓" if delta < 0 else "—")
        factors = f"ELO={v2.get('elo_strength',v2.get('fifa_strength',0)):.1f} ATK={v2['attack_score']:.1f} MKT={v2['market_power']:.1f} SP={v2['sponsor_adj']:+.1f} NEWS={v2.get('news_sentiment',0):+.2f} CCH={v2.get('coach_bonus',0):+.1f}"
        print(f"  {team:<20s} {r1:>4d}   {r2:>4d}   {arrow}{abs(delta):>3d}  {factors}")

    # V2 top 20 with decomposition
    print(f"\n  V3 Top 10 — 8-Factor Power Decomposition:")
    print(f"  {'Rank':<5s} {'Team':<18s} {'Comb':>5s} {'Elo':>5s} {'Atk':>5s} {'Mkt':>5s} {'Sp':>4s} {'Nws':>4s} {'Cch':>4s} {'Dpt':>4s}")
    print(f"  {'-'*5} {'-'*18} {'-'*5} {'-'*5} {'-'*5} {'-'*5} {'-'*4} {'-'*4} {'-'*4} {'-'*4}")
    for i, (team, v2) in enumerate(v2_ranked[:10], 1):
        print(f"  {i:>3}.  {team:<18s} {v2['combined']:>5.1f} {v2.get('elo_strength',0):>5.1f} "
              f"{v2['attack_score']:>5.1f} {v2['market_power']:>5.1f} {v2['sponsor_adj']:>+4.1f} "
              f"{v2.get('news_sentiment',0):>+4.1f} {v2.get('coach_bonus',0):>+4.1f} {v2.get('squad_depth',0):>4.1f}")

    print("\n" + "=" * 65)
    print(f"  Analysis complete. {len(v2_powers)} teams evaluated (V1+V2).")
    print("=" * 65)


# ============================================================
# 8. MATCH-VENUE LOOKUP
# ============================================================

# City name mapping: schedule uses short names, environment uses full names
CITY_NAME_MAP = {
    "Boston": "Boston / Foxborough",
    "Los Angeles": "Los Angeles / Inglewood",
    "San Francisco": "San Francisco / Santa Clara",
    "New York / New Jersey": "New York / New Jersey",
}


def build_venue_lookup(schedule_data: dict) -> dict:
    """
    Build a lookup table mapping (home_team, away_team) -> venue info.
    Match schedule JSON already includes city, roof, elevation_m per match.
    Returns dict with both forward and reverse keys for flexible lookup.

    Handles city name mismatches between schedule (short names) and
    environment.json (full names like 'Boston / Foxborough').
    """
    venue_map = {}
    matches = schedule_data.get("matches", {})

    for md_key in ["matchday_1", "matchday_2", "matchday_3"]:
        for match in matches.get(md_key, []):
            home = match.get("home", "")
            away = match.get("away", "")
            if not home or not away:
                continue
            city = match.get("city", "")
            # Map schedule city name to environment city name
            env_city = CITY_NAME_MAP.get(city, city)
            info = {
                "city": env_city,
                "roof": match.get("roof", False),
                "elevation_m": match.get("elevation_m", 0),
                "group": match.get("group", ""),
                "match_num": match.get("match", 0),
            }
            venue_map[(home, away)] = info
            # Also store reverse for lookup flexibility
            venue_map[(away, home)] = info

    return venue_map


# ============================================================
# 9. ENVIRONMENTAL FACTOR COMPUTATION
# ============================================================

# Acclimatized teams: nations with high-altitude home venues or experience
ALTITUDE_TEAMS = {
    "Mexico": 1.00,      # Full acclimatization (2250m home)
    "Ecuador": 0.80,     # Strong acclimatization (Quito ~2850m)
    "Colombia": 0.50,    # Partial acclimatization (Bogota ~2640m)
    "Bolivia": 1.00,     # (not in WC but kept for completeness)
}

# Module-level cache for city env factors
_ENV_CACHE: dict = {}


def _heat_factor(heat_risk: str) -> float:
    """Convert FIFA heat_risk category to xG multiplier."""
    risk = (heat_risk or "").upper()
    if "EXTREME" in risk:
        return 0.88
    elif "HIGH" in risk:
        return 0.92
    elif "MODERATE" in risk:
        return 0.96
    else:
        return 1.00  # LOW or unknown


def _altitude_factor(elevation_m: float, team: str) -> float:
    """Altitude xG multiplier for a given team at a given elevation."""
    if elevation_m < 1000:
        return 1.00
    elif elevation_m < 1800:
        # Guadalajara level: 2-4% VO2max loss
        base = 0.95
    else:
        # Mexico City level: 5-8% VO2max loss
        base = 0.90

    # Acclimatized teams get partial or full compensation
    acclimatization = ALTITUDE_TEAMS.get(team, 0.0)
    if acclimatization > 0:
        # Recover up to 60% of the altitude penalty based on acclimatization level
        recovery = (1.0 - base) * 0.60 * acclimatization
        base = base + recovery

    return base


def compute_env_factor(environment_data: dict, city_name: str,
                       roof: bool, elevation_m: float,
                       team: str) -> float:
    """
    Compute environmental xG multiplier for a team at a specific venue.

    Returns float in ~[0.85, 1.00] range:
      1.00 = neutral/indoor/no adverse conditions
      <1.00 = adverse conditions reduce expected goals

    Factors multiply: heat_factor × altitude_factor
    Roof=true eliminates heat penalty (climate controlled).
    Results are cached per (city, roof, team) tuple.
    """
    cache_key = (city_name, roof, team)
    if cache_key in _ENV_CACHE:
        return _ENV_CACHE[cache_key]

    # If roof is closed, heat risk is eliminated
    if roof:
        heat_f = 1.00
    else:
        city_data = environment_data.get("cities", {}).get(city_name, {})
        heat_risk = city_data.get("heat_risk", "LOW")
        heat_f = _heat_factor(heat_risk)

    alt_f = _altitude_factor(elevation_m, team)

    result = round(heat_f * alt_f, 4)
    _ENV_CACHE[cache_key] = result
    return result


# ============================================================
# 10. SPONSOR FACTOR COMPUTATION
# ============================================================

# Brand power bonus based on historical World Cup performance
BRAND_BONUS = {
    "Adidas": 1.2,
    "Nike": 1.0,
    "Puma": 0.6,
}

# Conflict severity penalty
SEVERITY_PENALTY = {"HIGH": -0.5, "MEDIUM": -0.3, "LOW": -0.1}


def compute_sponsor_factor(sponsors_data: dict, team: str) -> float:
    """
    Compute sponsor/brand influence on team power (~-1.3 to +1.2 range).

    Components:
      1. Brand bonus: Adidas (+1.2) > Nike (+1.0) > Puma (+0.6) > Other (0)
      2. Pressure penalty: direct lookup from sponsor_pressure_penalty
      3. Conflict penalty: from sponsor_conflicts list
    """
    if not sponsors_data:
        return 0.0

    kit_sponsors = sponsors_data.get("kit_sponsors", {})
    brand = kit_sponsors.get(team, "Other")

    # 1. Brand bonus
    brand_bonus = BRAND_BONUS.get(brand, 0.0)

    # 2. Pressure penalty (skip metadata keys)
    pressure_dict = sponsors_data.get("sponsor_pressure_penalty", {})
    pressure = pressure_dict.get(team, 0.0)
    if not isinstance(pressure, (int, float)):
        pressure = 0.0

    # 3. Conflict penalty
    conflict_penalty = 0.0
    for conflict in sponsors_data.get("sponsor_conflicts", []):
        if team in conflict.get("teams", []):
            severity = conflict.get("severity", "LOW")
            conflict_penalty += SEVERITY_PENALTY.get(severity, 0.0)

    return round(brand_bonus + pressure + conflict_penalty, 2)


# ============================================================
# 11. MARKET POWER FROM BETTING ODDS
# ============================================================

def compute_market_power(betting_data: dict, team: str) -> float:
    """
    Convert tournament winner implied probability to model power scale.
    Uses sqrt scaling to compress differences at the top:
      market_power = sqrt(implied_prob * 100) * 2.5

    Range: ~0.8 (Cape Verde 0.1%) to ~10.7 (Spain 18.2%)
    Falls back to group odds or 0.001 for unlisted teams.
    """
    if not betting_data:
        return 0.0

    # Name mapping: betting odds JSON uses short names, players use full names
    NAME_MAP = {
        "USA": "United States",
        "South Korea": "Korea Republic",  # for safety
    }
    lookup_names = {team}
    if team in NAME_MAP:
        lookup_names.add(NAME_MAP[team])
    # Also check reverse mapping
    for short, full in NAME_MAP.items():
        if full == team:
            lookup_names.add(short)

    # 1. Try tournament winner odds
    winner_odds = betting_data.get("tournament_winner_raw_odds", [])
    for item in winner_odds:
        if item.get("team") in lookup_names:
            prob = item.get("implied_prob", 0.001)
            return round(math.sqrt(max(prob, 0.0001) * 100) * 2.5, 1)

    # 2. Try group winner odds
    group_odds = betting_data.get("group_winners_odds", {})
    for g_name, gw in group_odds.items():
        if gw.get("favorite") == team:
            return round(math.sqrt(max(gw.get("implied_prob", 0.02), 0.0001) * 100) * 2.5, 1)
        others = gw.get("others", {})
        if team in others:
            prob = others[team]
            return round(math.sqrt(max(prob, 0.0001) * 100) * 2.5, 1)

    # 3. Fallback
    return round(math.sqrt(0.1) * 2.5, 1)  # ~0.8 for unlisted teams


# ============================================================
# 12. MARKET SENTIMENT (BETFAIR PLACEHOLDER)
# ============================================================

def compute_market_sentiment(live_odds_data: dict = None,
                             betting_data: dict = None,
                             team_a: str = "", team_b: str = "") -> float:
    """
    Estimate market sentiment / money flow direction.

    V2: Uses Betfair Exchange 必发指数 from betfair_index.json.
    Falls back to 0.0 if no data available.

    Range: ~-1 to +1 scale.
      + = positive sentiment toward team_a (资金流入team_a)
      - = positive sentiment toward team_b (资金流入team_b)

    Data source: betfair_index.json (generated by betfair_fetcher.py)
    """
    try:
        import json
        from pathlib import Path
        bf_path = Path(__file__).parent / "data" / "betfair_index.json"
        if not bf_path.exists():
            return 0.0

        with open(bf_path, "r", encoding="utf-8") as f:
            bf_data = json.load(f)

        bf_index = bf_data.get("betfair_index", {})
        runners = bf_index.get("runners", {})

        # Get money_flow for each team from Betfair runners
        mf_a = 0.0
        mf_b = 0.0
        for key, info in runners.items():
            if isinstance(key, str):
                if team_a.lower() in key.lower():
                    mf_a = info.get("money_flow", 0)
                if team_b.lower() in key.lower():
                    mf_b = info.get("money_flow", 0)

        # Net sentiment = team_a money flow - team_b money flow
        return round(mf_a - mf_b, 4)
    except Exception:
        return 0.0


# ============================================================
# 13a. BETFAIR MONEY FLOW BOOST (必发资金流 — per-match xG multiplier)
# ============================================================

def compute_betfair_boost(team_a: str, team_b: str,
                          betfair_data: dict = None) -> float:
    """
    Compute per-match xG multiplier from Betfair money flow difference.

    Mirrors website dcPredict() logic:
      netFlow = money_flow_home - money_flow_away
      bfBoost = 1.0 + netFlow * 0.15
      Clamped to [0.88, 1.12]

    Boost > 1.0 = money chasing team_a (home), increases home xG.
    """
    if not betfair_data:
        return 1.0

    runners = betfair_data.get("betfair_index", {}).get("runners", {})
    if not runners:
        return 1.0

    mf_a = 0.0
    mf_b = 0.0
    for key, info in runners.items():
        if isinstance(key, str):
            key_lower = key.lower()
            if team_a.lower() in key_lower:
                mf_a = info.get("money_flow", 0)
            if team_b.lower() in key_lower:
                mf_b = info.get("money_flow", 0)

    net_flow = mf_a - mf_b
    boost = 1.0 + net_flow * 0.15
    return max(0.88, min(1.12, boost))  # clamp ±12%


# ============================================================
# 13b. NEWS SENTIMENT BOOST (时事新闻 — per-match xG multiplier)
# ============================================================

# Positive/negative keyword lists matching website dcPredict()
NEWS_POS_WORDS = ['win', 'victory', 'confident', 'star', 'fit', 'return',
                  'boost', 'hat-trick', 'record', 'top', 'best',
                  'favorite', 'triumph']
NEWS_NEG_WORDS = ['injury', 'injured', 'doubt', 'loss', 'defeat', 'out',
                  'suspended', 'struggle', 'disappointing', 'blow',
                  'setback', 'worry', 'crisis']

# Team keywords for news matching (sync with website TEAM_KW)
NEWS_TEAM_KEYWORDS = {
    'Spain': ['spain', 'españa', 'yamal', 'rodri', 'pedri'],
    'France': ['france', 'mbappé', 'mbappe', 'olise'],
    'England': ['england', 'kane', 'bellingham', 'saka'],
    'Brazil': ['brazil', 'brasil', 'neymar', 'vinícius'],
    'Argentina': ['argentina', 'messi', 'lautaro'],
    'Portugal': ['portugal', 'ronaldo', 'bruno'],
    'Germany': ['germany', 'musiala', 'wirtz'],
    'Netherlands': ['netherlands', 'van dijk', 'gakpo'],
    'Norway': ['norway', 'haaland', 'odegaard'],
    'United States': ['usa', 'united states', 'pulisic'],
    'Mexico': ['mexico', 'méxico', 'el tri'],
    'Japan': ['japan', 'mitoma', 'kubo'],
    'South Korea': ['south korea', 'son heung'],
    'Croatia': ['croatia', 'modrić', 'modric'],
    'Belgium': ['belgium', 'de bruyne', 'lukaku'],
    'Senegal': ['senegal', 'mané', 'mane'],
    'Morocco': ['morocco', 'hakimi'],
    'Colombia': ['colombia', 'luis díaz'],
    'Uruguay': ['uruguay', 'valverde', 'núñez'],
    'Sweden': ['sweden', 'isak', 'gyökeres'],
    'Egypt': ['egypt', 'salah', 'marmoush'],
    'Canada': ['canada', 'davies'],
    'Scotland': ['scotland', 'mctominay', 'robertson'],
}


def _team_news_sentiment(articles: list, team: str) -> float:
    """Compute per-team news sentiment (-1 to +1) from articles."""
    if not articles:
        return 0.0

    kw = NEWS_TEAM_KEYWORDS.get(team, [team.lower()])
    pos_count = 0
    neg_count = 0
    total = 0

    for a in articles:
        text = ((a.get('title', '') or '') + ' ' +
                (a.get('summary', '') or '')).lower()
        # Check if article mentions this team
        if any(k.lower() in text for k in kw):
            total += 1
            pc = sum(1 for w in NEWS_POS_WORDS if w in text)
            nc = sum(1 for w in NEWS_NEG_WORDS if w in text)
            if nc > pc:
                neg_count += 1
            elif pc > nc:
                pos_count += 1

    if total == 0:
        return 0.0
    return (pos_count - neg_count) / total


def compute_news_boost(team_a: str, team_b: str,
                       news_data: dict = None) -> float:
    """
    Compute per-match xG multiplier from news sentiment difference.

    Mirrors website dcPredict() logic:
      newsH = sentiment(team_a), newsA = sentiment(team_b)
      newsBoost = 1.0 + (newsH - newsA) * 0.06
      Clamped to [0.92, 1.08]

    Boost > 1.0 = positive news for team_a relative to team_b.
    """
    if not news_data:
        return 1.0

    articles = news_data.get('articles', [])
    if not articles:
        return 1.0

    sent_h = _team_news_sentiment(articles, team_a)
    sent_a = _team_news_sentiment(articles, team_b)

    boost = 1.0 + (sent_h - sent_a) * 0.06
    return max(0.92, min(1.08, boost))  # clamp ±8%


# ============================================================
# 13. DYNAMIC ELO RATINGS (FIFA-rank-based with experience bonus)
# ============================================================

# Standard Elo K-factor
ELO_K = 32
ELO_INITIAL = 1500

def compute_elo_ratings(teams: list) -> dict:
    """
    Compute Elo ratings primarily from FIFA rankings (current strength),
    with a small bonus from international tournament experience (caps).

    FIFA rank → Elo base:
      rank 1  → 2100
      rank 10 → 1980
      rank 25 → 1800
      rank 50 → 1500
      rank 100→ 1200

    Experience bonus: up to +80 for teams with many veteran players (caps).
    This rewards tournament-tested squads without over-weighting career totals.

    Returns {team: elo_rating} with ~1200-2180 range.
    """
    elo = {}

    # 1. PRIMARY: FIFA ranking → Elo (current strength, not career totals)
    try:
        fifa = load_fifa_rankings()
        for team in teams:
            rank = fifa.get(team, 60)
            # Linear: rank 1=2100, rank 50=1500, rank 100=1200
            elo[team] = round(2100 - (rank - 1) * 12)
            elo[team] = max(1200, min(2180, elo[team]))
    except Exception:
        for team in teams:
            elo[team] = ELO_INITIAL

    # 2. SECONDARY: Small experience bonus from international caps
    try:
        with open(DATA_DIR / "international_stats.json", "r", encoding="utf-8") as f:
            intl = json.load(f)

        wc_players = intl.get("world_cup_players_international", {})
        for team in teams:
            players = wc_players.get(team, [])
            if players:
                total_caps = sum(p.get("caps", 0) for p in players)
                # Experience bonus: up to +80 for veteran-heavy squads
                exp_bonus = min(80, total_caps * 0.3)
                elo[team] = elo.get(team, ELO_INITIAL) + round(exp_bonus)
                elo[team] = min(2180, elo[team])
    except Exception:
        pass

    return elo


def elo_strength(elo_rating: float) -> float:
    """Convert Elo rating to model strength scale with wider separation (~8-28)."""
    # Scale: Elo 1400→8.0, 1700→15.0, 2100→28.0
    # Creates meaningful gaps between top (France 2100) and mid (1700) teams
    return max(elo_rating - 1000, 100) / 40.0


def update_elo(winner_elo: float, loser_elo: float, k: float = ELO_K,
               draw: bool = False) -> tuple:
    """Update Elo ratings after a match result."""
    expected = 1.0 / (1.0 + 10 ** ((loser_elo - winner_elo) / 400))
    actual = 0.5 if draw else 1.0
    delta = k * (actual - expected)
    return winner_elo + delta, loser_elo - delta


# ============================================================
# 14. HEAD-TO-HEAD / COACH / SQUAD DEPTH MODIFIERS
# ============================================================

def _find_h2h_match(h2h: dict, team_a: str, team_b: str) -> dict:
    """Find H2H data for any pair, trying both key orderings."""
    key1 = f"{team_a}_vs_{team_b}"
    if key1 in h2h:
        return h2h[key1]
    key2 = f"{team_b}_vs_{team_a}"
    if key2 in h2h:
        return h2h[key2]
    # Try with underscores (teams with spaces use _ in keys)
    key1u = team_a.replace(" ", "_") + "_vs_" + team_b.replace(" ", "_")
    key2u = team_b.replace(" ", "_") + "_vs_" + team_a.replace(" ", "_")
    if key1u in h2h:
        return h2h[key1u]
    if key2u in h2h:
        return h2h[key2u]
    return {}


# Mapping from full team name to 3-letter H2H key code
TEAM_CODE_MAP = {
    "Mexico": "mex", "South Africa": "rsa", "South Korea": "kor",
    "Czech Republic": "cze", "Canada": "can", "Bosnia-Herzegovina": "bih",
    "Qatar": "qat", "Switzerland": "sui", "Brazil": "bra", "Morocco": "mar",
    "Haiti": "hai", "Scotland": "sco", "United States": "usa", "Paraguay": "par",
    "Australia": "aus", "Turkey": "tur", "Germany": "ger", "Curacao": "cuw",
    "Ivory Coast": "civ", "Ecuador": "ecu", "Netherlands": "ned", "Japan": "jpn",
    "Sweden": "swe", "Tunisia": "tun", "Belgium": "bel", "Egypt": "egy",
    "Iran": "irn", "New Zealand": "nzl", "Spain": "esp", "Cape Verde": "cpv",
    "Saudi Arabia": "ksa", "Uruguay": "uru", "France": "fra", "Senegal": "sen",
    "Iraq": "irq", "Norway": "nor", "Argentina": "arg", "Algeria": "alg",
    "Austria": "aut", "Jordan": "jor", "Portugal": "por", "Congo DR": "cod",
    "Uzbekistan": "uzb", "Colombia": "col", "England": "eng", "Croatia": "cro",
    "Ghana": "gha", "Panama": "pan",
}


def _get_winrate(h2h_match: dict, team: str) -> float:
    """Extract win rate for a specific team from an H2H match dict."""
    total = h2h_match.get("total", 0)
    if total <= 0:
        return 0.5  # neutral

    # Try lookup using known team code mapping
    code = TEAM_CODE_MAP.get(team)
    if code:
        wins = h2h_match.get(f"{code}_wins", -1)
        if wins >= 0:
            return wins / total

    # Fallback: try full name
    team_key = team.lower().replace(" ", "_")
    wins = h2h_match.get(f"{team_key}_wins", -1)
    if wins >= 0:
        return wins / total

    # Last resort: compute from total - other_wins - draws
    draws = h2h_match.get("draws", 0)
    all_wins = sum(v for k, v in h2h_match.items() if k.endswith("_wins"))
    # Our team's wins = total - opponent_wins - draws
    opp_wins = all_wins  # only one other _wins key besides ours (which we can't find)
    # Actually this is circular. Just return 0.5 if we couldn't find it.
    return 0.5


def compute_h2h_modifier(team_a: str, team_b: str,
                         h2h_data: dict = None) -> float:
    """
    Head-to-head modifier based on historical matchups.
    Returns ~-0.5 to +0.5 (positive = team_a has historical edge).

    If h2h_data is not provided, loads from file (cached across calls).
    """
    if h2h_data is None:
        if not hasattr(compute_h2h_modifier, "_cache"):
            try:
                with open(DATA_DIR / "head_to_head.json", "r", encoding="utf-8") as f:
                    compute_h2h_modifier._cache = json.load(f)
            except Exception:
                compute_h2h_modifier._cache = {}
        h2h_data = compute_h2h_modifier._cache

    h2h = h2h_data.get("head_to_head", {}) if isinstance(h2h_data, dict) else {}
    match = _find_h2h_match(h2h, team_a, team_b)

    if not match or match.get("total", 0) <= 0:
        return 0.0

    wr_a = _get_winrate(match, team_a)
    # winrate - 0.5 → range [-0.5, +0.5]
    return round((wr_a - 0.5) * 1.0, 3)


def compute_h2h_blend(team_home: str, team_away: str,
                      model_hw: float, model_dw: float, model_aw: float,
                      h2h_data: dict = None) -> tuple:
    """
    Blend model predictions with historical H2H win rates.
    Uses YOUR head_to_head.json data directly.

    Blend weight = min(0.35, N/25) — up to 35% H2H influence for 9+ match samples.

    Returns: (blended_hw, blended_dw, blended_aw, h2h_weight_used, h2h_sample_size)
    """
    if h2h_data is None:
        if not hasattr(compute_h2h_blend, "_cache"):
            try:
                with open(DATA_DIR / "head_to_head.json", "r", encoding="utf-8") as f:
                    compute_h2h_blend._cache = json.load(f)
            except Exception:
                compute_h2h_blend._cache = {}
        h2h_data = compute_h2h_blend._cache

    h2h = h2h_data.get("head_to_head", {}) if isinstance(h2h_data, dict) else {}
    match = _find_h2h_match(h2h, team_home, team_away)

    if not match:
        return model_hw, model_dw, model_aw, 0.0, 0

    total = match.get("total", 0)
    if total < 3:
        return model_hw, model_dw, model_aw, 0.0, total

    # Extract historical win rates
    h_code = TEAM_CODE_MAP.get(team_home, "")
    a_code = TEAM_CODE_MAP.get(team_away, "")
    h_wins = match.get(f"{h_code}_wins", 0)
    a_wins = match.get(f"{a_code}_wins", 0)
    draws = match.get("draws", 0)

    if h_wins + a_wins + draws == 0:
        return model_hw, model_dw, model_aw, 0.0, total

    h_hist = h_wins / total
    d_hist = draws / total
    a_hist = a_wins / total

    # Blend weight: more matches = more trust in history
    w = min(0.35, total / 25.0)

    # Blend model with history
    blended_hw = model_hw * (1 - w) + h_hist * w
    blended_dw = model_dw * (1 - w) + d_hist * w
    blended_aw = model_aw * (1 - w) + a_hist * w

    return blended_hw, blended_dw, blended_aw, w, total


def compute_common_opponent_modifier(team_a: str, team_b: str,
                                     h2h_data: dict = None,
                                     fifa_ranks: dict = None) -> float:
    """
    Find common opponents both teams have played and compare performance.

    For each team C that both A and B have played:
      - Compare A's win rate vs C to B's win rate vs C
      - Weight by C's strength (higher FIFA rank = more meaningful comparison)
      - Aggregate into a normalized modifier

    Returns ~-1.0 to +1.0:
      + = team_a performed better against common opponents
      - = team_b performed better against common opponents
      0 = no common opponents found or equal performance
    """
    if h2h_data is None:
        if not hasattr(compute_common_opponent_modifier, "_h2h_cache"):
            try:
                with open(DATA_DIR / "head_to_head.json", "r", encoding="utf-8") as f:
                    compute_common_opponent_modifier._h2h_cache = json.load(f)
            except Exception:
                compute_common_opponent_modifier._h2h_cache = {}
        h2h_data = compute_common_opponent_modifier._h2h_cache

    h2h = h2h_data.get("head_to_head", {}) if isinstance(h2h_data, dict) else {}
    if not h2h:
        return 0.0

    # Build opponent sets for both teams
    def get_opponents(team):
        opponents = {}
        for key, match in h2h.items():
            if not isinstance(key, str):
                continue
            teams = key.replace("_vs_", "|").split("|")
            if len(teams) != 2:
                continue
            if team.replace(" ", "_") == teams[0].replace(" ", "_"):
                other = teams[1].replace("_", " ")
                opponents[other] = _get_winrate(match, team)
            elif team.replace(" ", "_") == teams[1].replace(" ", "_"):
                other = teams[0].replace("_", " ")
                opponents[other] = _get_winrate(match, team)
        return opponents

    opp_a = get_opponents(team_a)
    opp_b = get_opponents(team_b)

    # Find common opponents
    common = set(opp_a.keys()) & set(opp_b.keys())
    if not common:
        return 0.0

    # Weighted comparison
    if fifa_ranks is None:
        fifa_ranks = {}
    max_rank = max(fifa_ranks.values()) if fifa_ranks else 200
    total_weight = 0.0
    weighted_diff = 0.0

    for c in common:
        diff = opp_a[c] - opp_b[c]
        # Weight: stronger opponents (lower rank number) get higher weight
        rank = fifa_ranks.get(c, 100) if fifa_ranks else 100
        weight = 1.0 - (rank / (max_rank + 50))  # ~0.2 to ~0.9
        if weight < 0.1:
            weight = 0.2  # minimum weight for any common opponent

        weighted_diff += diff * weight
        total_weight += weight

    if total_weight <= 0:
        return 0.0

    modifier = weighted_diff / total_weight
    # Clamp to ±1.0
    return max(-1.0, min(1.0, round(modifier, 4)))


def compute_coach_bonus(team: str) -> float:
    """Coach tournament experience bonus. Range ~-0.5 to +0.8."""
    try:
        with open(DATA_DIR / "managers.json", "r", encoding="utf-8") as f:
            mgr_data = json.load(f)

        managers = mgr_data.get("managers", {})
        mgr = managers.get(team, {})
        if not mgr:
            return 0.0

        exp = (mgr.get("exp", "") + " " + mgr.get("strength", "")).lower()
        bonus = 0.0

        # Tournament winners
        if "wc winner" in exp or "world cup winner" in exp:
            bonus += 0.8
        elif "wc final" in exp or "wc semi-final" in exp:
            bonus += 0.5
        elif "wc" in exp and ("qf" in exp or "r16" in exp or "knockout" in exp):
            bonus += 0.3

        # Continental champions
        if "euro" in exp and "winner" in exp:
            bonus += 0.4
        elif "copa" in exp and ("winner" in exp or "golden boot" in exp):
            bonus += 0.4
        elif "afcon" in exp and "winner" in exp:
            bonus += 0.3

        # UCL winner (club level, transfers to big-game management)
        if "ucl winner" in exp or "champions league winner" in exp:
            bonus += 0.3

        return round(bonus, 2)
    except Exception:
        return 0.0


def compute_squad_depth(players_df: pd.DataFrame, team: str) -> float:
    """
    Squad depth score based on:
      - Number of elite players (top-5 league)
      - Average rating of top-11 players
      - Bench strength (players 12-23 quality)
    Range: ~0 to 3
    """
    squad = players_df[players_df["nation"] == team]
    if squad.empty:
        return 0.0

    # Count elite players
    elite = sum(1 for _, r in squad.iterrows()
                if league_factor(r.get("league", "")) >= 0.80)

    # Average rating of all squad players
    ratings = pd.to_numeric(squad["rating_2526"], errors="coerce").dropna()
    avg_rating = ratings.mean() if len(ratings) > 0 else 6.5

    # Depth = elite count bonus + rating bonus
    depth = (elite * 0.3) + (avg_rating - 6.0) * 0.5
    return round(max(0, depth), 2)


def compute_defense_score(players_df: pd.DataFrame, team: str,
                          gk_data: dict = None) -> float:
    """
    Compute defensive strength to balance attack-heavy teams (e.g., Norway).

    Uses:
      - Goalkeeper rating (team_gk_rating)
      - Top defenders' league quality (CBs, DMs from top leagues)
      - Number of elite defenders in the squad

    Range: ~0 to 15 (comparable to attack_score scale).
    Balances teams like Norway (high attack, weak defense) vs France (high both).
    """
    squad = players_df[players_df["nation"] == team]
    if squad.empty:
        return 0.0

    # 1. GK rating contribution
    gk_score = 0.0
    if gk_data:
        gk_ratings = gk_data.get("team_gk_rating", {}).get("ratings", {})
        gk = gk_ratings.get(team, 50)
        gk_score = (gk - 50) / 50 * 3  # Range: -3 to +3

    # 2. Defender quality
    defenders = squad[squad["position"].isin(["DF", "GK"])]
    if len(defenders) == 0:
        defenders = squad  # fallback if no position data

    def_quality = 0.0
    def_count = 0
    for _, r in defenders.iterrows():
        lf = league_factor(r.get("league", ""))
        if lf >= 0.50:  # Only count players from decent leagues
            rating = r.get("rating_2526")
            if pd.isna(rating) or rating is None:
                rating = 6.5
            def_quality += float(rating) * lf
            def_count += 1

    # Average defender quality — scale to 0-10 range
    if def_count > 0:
        avg_def_rating = def_quality / def_count  # ~6.0-7.5
        def_quality = (avg_def_rating - 5.5) * min(def_count, 8) * 0.35
        def_quality = max(0, def_quality)
    else:
        def_quality = 2.0  # fallback

    # 3. DM (defensive midfielders) bonus — scale to 0-5 range
    dms = squad[squad["position"] == "MF"]
    dm_bonus = 0.0
    dm_count = 0
    for _, r in dms.iterrows():
        lf = league_factor(r.get("league", ""))
        if lf >= 0.80:  # Top league DMs
            rating = r.get("rating_2526")
            if pd.isna(rating) or rating is None:
                rating = 6.5
            dm_bonus += (float(rating) - 6.0) * lf
            dm_count += 1
    dm_bonus = max(0, dm_bonus) * 0.5

    return round(gk_score + def_quality + dm_bonus, 2)


# ============================================================
# 15. INJURY PENALTY — Structured injury impact on team power
# ============================================================

# Severity weight: how much each injury level reduces team power
INJURY_SEVERITY_WEIGHTS = {
    "critical": 1.00,   # Star player / captain
    "major": 0.55,      # Key starter
    "moderate": 0.25,   # Rotation player
    "minor": 0.08,      # Bench/depth player
}

# Status multiplier: how much the severity weight is applied based on status
INJURY_STATUS_MULTIPLIER = {
    "out": 1.00,        # Full penalty — player is absent
    "doubtful": 0.70,   # 70% of penalty — unlikely to play
    "questionable": 0.40,  # 40% — may play, uncertainty
    "probable": 0.15,   # 15% — expected to play, slight concern
    "fit": 0.0,         # No penalty
}

# Max penalty cap per team (prevents excessive stacking)
MAX_INJURY_PENALTY = 2.5


def compute_injury_penalty(team: str, injuries_data: dict = None) -> float:
    """
    Compute injury penalty for a team based on structured injuries.json data.

    Formula:
      penalty = sum(severity_weight × status_multiplier) for each injured player
      Capped at MAX_INJURY_PENALTY to prevent excessive impact from stacking injuries.

    Returns float in range [0, MAX_INJURY_PENALTY]:
      0 = fully fit squad
      2.5 = multiple critical players out (severe impact)

    Examples:
      Spain: no critical OUT → ~0.15 (Merino doubtful + Yamal probable)
      Brazil: Rodrygo (critical OUT) + Militão (major OUT) + Neymar (critical doubtful)
            → 1.0×1.0 + 0.55×1.0 + 1.0×0.70 = 2.25
      Argentina: Romero (critical doubtful) + Molina (major doubtful) + Messi (critical probable)
               → 1.0×0.70 + 0.55×0.70 + 1.0×0.15 = 1.235
    """
    if not injuries_data:
        return 0.0

    injuries = injuries_data.get("injuries", [])
    if not injuries:
        return 0.0

    penalty = 0.0
    for inj in injuries:
        if inj.get("nation", "") != team:
            continue

        status = inj.get("status", "fit")
        severity = inj.get("severity", "moderate")

        sev_weight = INJURY_SEVERITY_WEIGHTS.get(severity, 0.25)
        status_mult = INJURY_STATUS_MULTIPLIER.get(status, 0.0)

        penalty += sev_weight * status_mult

    return round(min(penalty, MAX_INJURY_PENALTY), 3)


def get_team_injury_summary(team: str, injuries_data: dict = None) -> dict:
    """
    Get a human-readable summary of a team's injury situation.
    Returns {out_players, doubtful_players, total_penalty, status_text}
    """
    if not injuries_data:
        return {"out": [], "doubtful": [], "probable": [], "penalty": 0.0, "status": "✅ Clean bill of health"}

    injuries = injuries_data.get("injuries", [])
    out_players = []
    doubtful_players = []
    probable_players = []

    for inj in injuries:
        if inj.get("nation", "") != team:
            continue
        info = f"{inj['player']} ({inj.get('injury_type','?')})"
        if inj["status"] == "out":
            out_players.append(info)
        elif inj["status"] in ("doubtful", "questionable"):
            doubtful_players.append(info)
        elif inj["status"] == "probable":
            probable_players.append(info)

    penalty = compute_injury_penalty(team, injuries_data)

    if penalty >= 2.0:
        status = "[CRISIS] — multiple key players out"
    elif penalty >= 1.0:
        status = "[SIGNIFICANT] — key absences affecting strength"
    elif penalty >= 0.3:
        status = "[MINOR] — some concerns but core intact"
    elif penalty > 0:
        status = "[MOSTLY FIT] — minor issues only"
    else:
        status = "[CLEAN] — Clean bill of health"

    return {
        "out": out_players,
        "doubtful": doubtful_players,
        "probable": probable_players,
        "penalty": penalty,
        "status": status,
    }


# ============================================================
# 16. LINEUP-BASED ATTACK SCORE ADJUSTMENT
# ============================================================

def compute_lineup_attack_score(players_df: pd.DataFrame, team: str,
                                lineup_data: dict = None,
                                match_num: int = None) -> float:
    """
    Compute attack score based on CONFIRMED starting XI instead of full squad top-3.

    When lineups are available (~1h before kickoff), this replaces the generic
    compute_attack_score() which uses the best 3 players from the entire squad.

    If no lineup available, falls back to the standard squad-based attack_score.
    """
    # Fallback to standard attack score if no lineup data
    if not lineup_data or not match_num:
        return compute_attack_score(players_df, team)

    match_key = str(match_num)
    match_lineups = lineup_data.get("lineups", {}).get(match_key)
    if not match_lineups or match_lineups.get("status") != "confirmed":
        return compute_attack_score(players_df, team)

    # Determine which side (home/away) this team is
    is_home = match_lineups.get("home") == team
    side_key = "home_lineup" if is_home else "away_lineup"
    lineup = match_lineups.get(side_key, {})

    starting_xi = lineup.get("starting_xi", [])
    if not starting_xi or len(starting_xi) < 7:  # Need at least 7 names
        return compute_attack_score(players_df, team)

    # Match starting XI names against player database
    player_names = [p.get("name", "") for p in starting_xi]

    squad = players_df[players_df["nation"] == team]
    matched_players = squad[squad["player_name"].isin(player_names)]

    if len(matched_players) < 3:
        # Not enough players matched — fall back to squad-based
        return compute_attack_score(players_df, team)

    # Compute attack score from matched starting XI players
    t = matched_players.copy()
    t["goals_2025_26"] = pd.to_numeric(t["goals_2025_26"], errors="coerce").fillna(0)
    t["assists_2025_26"] = pd.to_numeric(t["assists_2025_26"], errors="coerce").fillna(0)
    t["g_a"] = t["goals_2025_26"] + t["assists_2025_26"]
    t["rating_2526"] = pd.to_numeric(t["rating_2526"], errors="coerce").fillna(6.5)

    top3 = t.nlargest(3, "g_a")

    score = 0.0
    weights = [0.5, 0.3, 0.2]
    for i, (_, row) in enumerate(top3.iterrows()):
        if i >= len(weights):
            break
        lf = league_factor(row.get("league", ""))
        rating = row.get("rating_2526") or 6.5
        score += row["g_a"] * lf * (rating / 7.0) * weights[i]

    return round(score, 2)


# ============================================================
# 15. BRIER SCORE CALIBRATION
# ============================================================

def brier_score(probabilities: list, outcomes: list) -> float:
    """Brier Score: lower = better calibration. Range [0, 1]."""
    if len(probabilities) != len(outcomes) or len(probabilities) == 0:
        return 1.0
    return sum((p - o) ** 2 for p, o in zip(probabilities, outcomes)) / len(probabilities)


# ============================================================
# 16. NEWS SENTIMENT (时事新闻情感)
# ============================================================

def compute_news_sentiment(team: str) -> float:
    """
    Get team news sentiment score from latest news_feed.json.
    Range: -1.0 (all negative news) to +1.0 (all positive news).
    Returns 0.0 if no news data available.

    Sentiment is computed by:
      (positive_articles - negative_articles) / total_articles
    using keyword-based scoring from news_feed.py.
    """
    try:
        import json
        from pathlib import Path

        news_path = Path(__file__).parent / "data" / "news_feed.json"
        if not news_path.exists():
            return 0.0

        with open(news_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Check if data already has sentiment for this team
        if data.get("team_filter") == team and "team_sentiment" in data:
            sent = data["team_sentiment"]
            total = sent.get("total", 1) or 1
            return round((sent["positive"] - sent["negative"]) / total, 3)

        # Otherwise compute on the fly
        articles = data.get("articles", [])
        if not articles:
            return 0.0

        # Simple keyword-based sentiment matching
        from news_feed import filter_team_news, extract_news_sentiment, TEAM_KEYWORDS

        team_articles = filter_team_news(articles, team)
        sent = extract_news_sentiment(team_articles)
        total = sent.get("total", 1) or 1
        return round((sent["positive"] - sent["negative"]) / total, 3)

    except Exception:
        return 0.0


# ============================================================
# 14. UNIFIED TEAM POWER V2
# ============================================================

def compute_team_power_v2(players_df: pd.DataFrame, fifa_ranks: dict,
                          nation: str, betting_data: dict = None,
                          sponsors_data: dict = None,
                          injuries_data: dict = None,
                          lineups_data: dict = None,
                          match_num: int = None) -> dict:
    """
    Compute comprehensive team power with all factors integrated.

    V5 Weights (calibrated against Opta/betting market consensus):
      elo_strength    × 0.30   (~30% — FIFA-rank-based Elo, primary factor)
      attack_score    × 0.22   (~22% — attacking talent, capped at 25)
      defense_score   × 0.15   (~12% — GK + defenders quality)
      form_trend      × 2.0    (~4% — form momentum)
      market_power    × 0.10   (~8% — betting market wisdom)
      sponsor_adj     × 0.04   (~2% — brand/sponsor effects)
      news_sent       × 0.03   (~1% — real-time news sentiment)
      coach_bonus     × 0.05   (~3% — manager tournament experience)
      squad_depth     × 0.03   (~1% — bench strength)
      injury_penalty  × -0.10  (~-1-3% — player injuries, moderated)

    Targets: Spain ~18%, France ~17%, England ~13%, Brazil ~10%, Argentina ~9%
    """
    # Use lineup-based attack score if available, otherwise squad-based
    if lineups_data and match_num:
        attack = compute_lineup_attack_score(players_df, nation, lineups_data, match_num)
    else:
        attack = compute_attack_score(players_df, nation)

    form = compute_form_bonus(players_df, nation)

    # NaN safety
    attack = attack if not np.isnan(attack) else 0.0
    form = form if not np.isnan(form) else 0.0

    # Core factors
    market_power = compute_market_power(betting_data, nation) if betting_data else 0.0
    sponsor_adj = compute_sponsor_factor(sponsors_data, nation) if sponsors_data else 0.0
    news_sent = compute_news_sentiment(nation)
    coach_bonus = compute_coach_bonus(nation)
    squad_depth = compute_squad_depth(players_df, nation)

    # Defense score (NEW V5)
    defense = compute_defense_score(players_df, nation)

    # Injury penalty
    if injuries_data:
        injury_penalty = compute_injury_penalty(nation, injuries_data)
    else:
        injury_penalty = 0.0

    # Dynamic Elo (computed once, cached at module level)
    if not hasattr(compute_team_power_v2, "_elo_cache"):
        all_teams = players_df["nation"].unique().tolist()
        compute_team_power_v2._elo_cache = compute_elo_ratings(all_teams)
    elo_rating = compute_team_power_v2._elo_cache.get(nation, ELO_INITIAL)
    elo_str = elo_strength(elo_rating)

    # Cap attack score to prevent outlier dominance (Norway, Sweden, etc.)
    attack_capped = min(attack, 25.0)

    # Combined formula — V5 weights (backtest-calibrated for match prediction accuracy)
    # Higher Elo weight = wider gap between strong and weak = better differentiation
    combined = (elo_str * 0.38 +
                attack_capped * 0.18 +
                defense * 0.15 +
                form * 1.5 +
                market_power * 0.12 +
                sponsor_adj * 0.04 +
                news_sent * 0.03 +
                coach_bonus * 0.05 +
                squad_depth * 0.03 -
                injury_penalty * 0.10)

    # Count top-league players
    team = players_df[players_df["nation"] == nation]
    elite_players = sum(1 for _, r in team.iterrows()
                        if league_factor(r.get("league", "")) >= 0.80)

    # Injury summary for display
    injury_summary = get_team_injury_summary(nation, injuries_data) if injuries_data else {}

    return {
        "nation": nation,
        "elo_rating": elo_rating,
        "elo_strength": round(elo_str, 1),
        "attack_score": round(attack, 1),
        "defense_score": round(defense, 2),
        "form_trend": form,
        "market_power": round(market_power, 1),
        "sponsor_adj": round(sponsor_adj, 2),
        "news_sentiment": round(news_sent, 3),
        "coach_bonus": round(coach_bonus, 2),
        "squad_depth": round(squad_depth, 2),
        "injury_penalty": round(injury_penalty, 3),
        "injury_summary": injury_summary,
        "combined": round(combined, 1),
        "elite_players": elite_players,
        "fifa_rank": int(elo_rating),
        "version": "v5",
    }


# ============================================================
# 14. ENTRY POINT
# ============================================================

if __name__ == "__main__":
    print("Loading data...")
    players = load_players_from_json()
    fifa_ranks = load_fifa_rankings()
    league = load_league_stats()
    betting = load_betting_odds()
    sponsors = load_sponsors()
    environment = load_environment()
    schedule = load_match_schedule()

    n_players = len(players)
    n_nations = len(players['nation'].unique())
    n_ranks = len(fifa_ranks)
    n_leagues = len(league['leagues'])
    n_odds = len(betting.get('tournament_winner_raw_odds', []))
    n_sponsors = len(sponsors.get('kit_sponsors', {}))
    n_cities = len(environment.get('cities', {}))
    n_group_matches = sum(len(schedule.get('matches', {}).get(k, []))
                          for k in ['matchday_1', 'matchday_2', 'matchday_3'])
    print(f"  [OK] {n_players} players from {n_nations} nations")
    print(f"  [OK] FIFA rankings loaded for {n_ranks} teams")
    print(f"  [OK] League stats for {n_leagues} competitions")
    print(f"  [OK] Betting odds for {n_odds} teams")
    print(f"  [OK] Sponsor data for {n_sponsors} teams")
    print(f"  [OK] Environment data for {n_cities} cities")
    print(f"  [OK] Match schedule: {n_group_matches} group matches")

    analyze(players, fifa_ranks, betting, sponsors, environment, schedule)

    print(f"\n  Data directory: {DATA_DIR.resolve()}")
    print("  Edit model.py to customize prediction logic.")
