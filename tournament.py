"""
2026 FIFA World Cup — Full Tournament Simulator
================================================
Simulates the COMPLETE tournament from group stage through the Final.
- 16 groups × 3 teams → 32 advance to Round of 32
- Knockout bracket: R32 → R16 → QF → SF → Final
- Monte Carlo: N simulations to estimate probabilities for every stage.

Usage:
    python tournament.py          # Run with default 5000 sims
    python tournament.py 10000    # Run with 10000 sims
"""

import sys
import json
import numpy as np
from pathlib import Path
from collections import defaultdict
from model import (
    load_players_from_json, load_fifa_rankings, load_betting_odds,
    load_sponsors, load_environment, load_match_schedule,
    compute_team_power, compute_team_power_v2,
    build_venue_lookup, compute_env_factor,
    simulate_match, compute_elo_ratings, update_elo, ELO_INITIAL,
    compute_h2h_modifier
)

DATA_DIR = Path(__file__).parent / "data"

# ============================================================
# 1. GROUP STRUCTURE & BRACKET
# ============================================================

GROUPS = {
    "A": ["Mexico", "South Africa", "South Korea", "Czech Republic"],
    "B": ["Canada", "Bosnia-Herzegovina", "Qatar", "Switzerland"],
    "C": ["Brazil", "Morocco", "Haiti", "Scotland"],
    "D": ["United States", "Paraguay", "Australia", "Turkey"],
    "E": ["Germany", "Curacao", "Ivory Coast", "Ecuador"],
    "F": ["Netherlands", "Japan", "Sweden", "Tunisia"],
    "G": ["Belgium", "Egypt", "Iran", "New Zealand"],
    "H": ["Spain", "Cape Verde", "Saudi Arabia", "Uruguay"],
    "I": ["France", "Senegal", "Iraq", "Norway"],
    "J": ["Argentina", "Algeria", "Austria", "Jordan"],
    "K": ["Portugal", "Congo DR", "Uzbekistan", "Colombia"],
    "L": ["England", "Croatia", "Ghana", "Panama"],
}

# Round of 32: 8 winners-by-seed + 16 teams play R32
# R32 matches: 4th-8th group winners vs runners-up
R32_MATCHES = [
    ("1D", "2C"), ("1E", "2F"), ("1F", "2E"), ("1G", "2H"),
    ("1H", "2G"), ("1J", "2I"), ("1K", "2L"), ("1L", "2K"),
]

# Top 8 group winners (by points) get a bye to R16
# Round of 16: 8 byes + 8 R32 winners
# Bracket: winners of groups A,B,C,D,E,F,G,H,I,J,K,L seeded by points
# Simplified pairing: groups paired (A/B), (C/D), (E/F), (G/H), (I/J), (K/L)
R16_SLOTS = [
    ("group", "A"), ("group", "B"),  # 0,1 -> A vs B winner
    ("group", "C"), ("group", "D"),  # 2,3
    ("group", "E"), ("group", "F"),  # 4,5
    ("group", "G"), ("group", "H"),  # 6,7
    ("group", "I"), ("group", "J"),  # 8,9
    ("group", "K"), ("group", "L"),  # 10,11
    ("R32_W", 0), ("R32_W", 1),      # 12,13
    ("R32_W", 2), ("R32_W", 3),      # 14,15
]

# R16 pairings join these 16 slots
R16_PAIRINGS = [
    (0, 13), (1, 12), (2, 15), (3, 14),
    (4, 5), (6, 7), (8, 9), (10, 11),
]

# Quarterfinal pairings
QF_PAIRINGS = [(0, 1), (2, 3), (4, 5), (6, 7)]

# Semifinal pairings
SF_PAIRINGS = [(0, 1), (2, 3)]


# ============================================================
# 2. GROUP STAGE
# ============================================================

def play_group_stage(powers: dict, venue_map: dict = None,
                     env_data: dict = None, elo_ratings: dict = None) -> dict:
    """Simulate one group stage and return qualifying teams."""
    group_results = {}

    for g_name, teams in GROUPS.items():
        points = {t: 0 for t in teams}
        gd = {t: 0 for t in teams}

        for i, t1 in enumerate(teams):
            for t2 in teams[i + 1:]:
                # Get environmental factors for this venue
                h_env, a_env = 1.0, 1.0
                if venue_map and env_data:
                    v = venue_map.get((t1, t2), {})
                    city = v.get("city", "")
                    roof = v.get("roof", False)
                    elev = v.get("elevation_m", 0)
                    if city:
                        h_env = compute_env_factor(env_data, city, roof, elev, t1)
                        a_env = compute_env_factor(env_data, city, roof, elev, t2)

                # Head-to-head modifier
                h2h_mod = compute_h2h_modifier(t1, t2)

                # Apply h2h to home power (home gets advantage if historically dominant)
                h_power = powers.get(t1, 0.5) + h2h_mod
                a_power = powers.get(t2, 0.5)

                hg, ag = simulate_match(h_power, a_power,
                                        env_factor_home=h_env, env_factor_away=a_env)

                # Update dynamic Elo
                if elo_ratings:
                    e1 = elo_ratings.get(t1, ELO_INITIAL)
                    e2 = elo_ratings.get(t2, ELO_INITIAL)
                    if hg > ag:
                        e1_new, e2_new = update_elo(e1, e2)
                    elif ag > hg:
                        e2_new, e1_new = update_elo(e2, e1)
                    else:
                        e1_new, e2_new = update_elo(e1, e2, draw=True)
                    elo_ratings[t1] = e1_new
                    elo_ratings[t2] = e2_new

                gd[t1] += hg - ag
                gd[t2] += ag - hg
                if hg > ag:
                    points[t1] += 3
                elif ag > hg:
                    points[t2] += 3
                else:
                    points[t1] += 1
                    points[t2] += 1

        # Rank by points, then GD, then random tiebreak
        ranked = sorted(teams, key=lambda t: (points[t], gd[t], np.random.random()), reverse=True)
        group_results[g_name] = {
            "1st": ranked[0],
            "2nd": ranked[1],
            "standings": {t: {"pts": points[t], "gd": gd[t]} for t in teams},
        }

    return group_results


# ============================================================
# 3. KNOCKOUT BRACKET
# ============================================================

def play_knockout_match(powers: dict, team_a: str, team_b: str,
                        is_neutral: bool = True,
                        env_factor_a: float = 1.0,
                        env_factor_b: float = 1.0) -> str:
    """Simulate a knockout match. If draw, winner decided by power-weighted coin flip."""
    # Neutral venue: no home advantage
    home_adv = 0.0 if is_neutral else 0.25
    ga, gb = simulate_match(powers.get(team_a, 0.5), powers.get(team_b, 0.5), home_adv,
                            env_factor_home=env_factor_a, env_factor_away=env_factor_b)

    if ga > gb:
        return team_a
    elif gb > ga:
        return team_b
    else:
        # Extra time / penalties proxy: weighted by power
        pa = powers.get(team_a, 0.5)
        pb = powers.get(team_b, 0.5)
        return team_a if np.random.random() < pa / (pa + pb) else team_b


def play_tournament_knockout(powers: dict, group_results: dict) -> dict:
    """
    Full knockout from R32 through Final.
    24 teams advance from groups (top 2 each).
    Top 8 group winners get R16 bye. Remaining 16 play R32.
    """

    # Rank group winners by points → top 8 get bye
    all_winners = []
    for g_name, gr in group_results.items():
        team = gr["1st"]
        pts = gr["standings"][team]["pts"]
        gd = gr["standings"][team]["gd"]
        all_winners.append((team, g_name, pts, gd))

    all_winners.sort(key=lambda x: (-x[2], -x[3]))  # pts desc, gd desc
    bye_teams = {w[0] for w in all_winners[:8]}
    bye_groups = {w[1] for w in all_winners[:8]}
    r32_groups = {w[1] for w in all_winners[8:]}

    # R32 matches (8 matches, 16 teams)
    r32_winners = {}
    for i, (seed_a, seed_b) in enumerate(R32_MATCHES):
        # seed_a like "1D", seed_b like "2C"
        g_a, r_a = seed_a[1], seed_a[0]
        g_b, r_b = seed_b[1], seed_b[0]
        team_a = group_results[g_a]["1st"] if r_a == "1" else group_results[g_a]["2nd"]
        team_b = group_results[g_b]["1st"] if r_b == "1" else group_results[g_b]["2nd"]
        winner = play_knockout_match(powers, team_a, team_b)
        r32_winners[i] = winner

    # R16: 16 teams → 8 winners
    # Build R16 team list from R16_SLOTS
    r16_teams = []
    for slot_type, slot_id in R16_SLOTS:
        if slot_type == "group":
            # Team is the group winner (all group winners advance, bye or not)
            r16_teams.append(group_results[slot_id]["1st"])
        elif slot_type == "R32_W":
            r16_teams.append(r32_winners[slot_id])

    r16_winners = []
    for a_idx, b_idx in R16_PAIRINGS:
        winner = play_knockout_match(powers, r16_teams[a_idx], r16_teams[b_idx])
        r16_winners.append(winner)

    # Quarterfinals: 8 teams → 4
    qf_winners = []
    for a_idx, b_idx in QF_PAIRINGS:
        winner = play_knockout_match(powers, r16_winners[a_idx], r16_winners[b_idx])
        qf_winners.append(winner)

    # Semifinals: 4 teams → 2
    sf_winners = []
    sf_losers = []
    for a_idx, b_idx in SF_PAIRINGS:
        winner = play_knockout_match(powers, qf_winners[a_idx], qf_winners[b_idx])
        loser = qf_winners[b_idx] if winner == qf_winners[a_idx] else qf_winners[a_idx]
        sf_winners.append(winner)
        sf_losers.append(loser)

    # Final
    champion = play_knockout_match(powers, sf_winners[0], sf_winners[1])
    runner_up = sf_winners[1] if champion == sf_winners[0] else sf_winners[0]

    return {
        "champion": champion,
        "runner_up": runner_up,
        "semifinalists": sf_winners + sf_losers,
        "quarterfinalists": qf_winners,
        "r16": r16_winners,
        "r32": list(r32_winners.values()),
    }


# ============================================================
# 4. FULL TOURNAMENT SIMULATION
# ============================================================

def simulate_tournament(players_df, fifa_ranks: dict, n_sims: int = 5000,
                        use_v2: bool = True, betting_data: dict = None,
                        sponsors_data: dict = None, environment_data: dict = None,
                        schedule_data: dict = None):
    """Run N complete tournament simulations and return all probabilities."""
    # Pre-compute team powers + dynamic Elo
    all_teams = []
    for teams in GROUPS.values():
        all_teams.extend(teams)

    dynamic_elo = compute_elo_ratings(all_teams)

    powers = {}
    v2_details = {}
    for team in all_teams:
        if use_v2:
            tp = compute_team_power_v2(players_df, fifa_ranks, team,
                                       betting_data=betting_data,
                                       sponsors_data=sponsors_data)
        else:
            tp = compute_team_power(players_df, fifa_ranks, team)
        p = tp["combined"]
        if np.isnan(p) or p <= 0:
            p = 0.5
        powers[team] = p
        if use_v2:
            v2_details[team] = tp

    # Build venue lookup for environmental factors (group + knockout)
    venue_map = {}
    if environment_data and schedule_data:
        venue_map = build_venue_lookup(schedule_data)

    # Build knockout venue map
    ko_venues = {
        "QF1": "Kansas City", "QF2": "Miami", "QF3": "Dallas", "QF4": "Atlanta",
        "SF1": "Dallas", "SF2": "Atlanta",
        "FINAL": "New York / New Jersey",
        "3RD": "Miami",
    }

    # Counters
    champions = defaultdict(int)
    finalists = defaultdict(int)
    semifinalists = defaultdict(int)
    quarterfinalists = defaultdict(int)
    r16_count = defaultdict(int)
    r32_count = defaultdict(int)
    group_exit = defaultdict(int)
    group_1st = defaultdict(int)
    group_2nd = defaultdict(int)

    ver = "V3" if use_v2 else "V1"
    print(f"  Running {n_sims} tournament simulations [{ver}]...")

    for sim in range(n_sims):
        if (sim + 1) % max(1, n_sims // 10) == 0:
            print(f"    {sim + 1}/{n_sims} ({100*(sim+1)//n_sims}%)")

        # Reset Elo for each simulation
        sim_elo = dict(dynamic_elo)

        # Group stage (with environmental factors + h2h + dynamic Elo)
        group_results = play_group_stage(powers, venue_map=venue_map,
                                         env_data=environment_data,
                                         elo_ratings=sim_elo)

        # Track group stage outcomes
        for g_name, gr in group_results.items():
            group_1st[gr["1st"]] += 1
            group_2nd[gr["2nd"]] += 1
            for team in GROUPS[g_name]:
                if team != gr["1st"] and team != gr["2nd"]:
                    group_exit[team] += 1

        # Knockout
        ko = play_tournament_knockout(powers, group_results)

        # Track
        champions[ko["champion"]] += 1
        finalists[ko["champion"]] += 1
        finalists[ko["runner_up"]] += 1
        for t in ko["semifinalists"]:
            semifinalists[t] += 1
        for t in ko["quarterfinalists"]:
            quarterfinalists[t] += 1
        for t in ko["r16"]:
            r16_count[t] += 1
        for t in ko["r32"]:
            r32_count[t] += 1

    print(f"  Done! {n_sims} tournaments simulated.\n")

    return {
        "n_sims": n_sims,
        "version": ver,
        "champion": dict(champions),
        "finalist": dict(finalists),
        "semifinalist": dict(semifinalists),
        "quarterfinalist": dict(quarterfinalists),
        "round_of_16": dict(r16_count),
        "round_of_32": dict(r32_count),
        "group_1st": dict(group_1st),
        "group_2nd": dict(group_2nd),
        "group_exit": dict(group_exit),
        "powers": powers,
        "v2_details": v2_details if use_v2 else {},
    }


# ============================================================
# 5. REPORTING
# ============================================================

def print_results(results: dict):
    """Print comprehensive tournament simulation results."""
    n = results["n_sims"]

    def prob(count):
        return count / n

    print("=" * 70)
    print("  FULL TOURNAMENT SIMULATION RESULTS")
    print(f"  {n:,} simulations | 48 teams | 104 matches each")
    print("=" * 70)

    # Champion probabilities
    print(f"\n  [WINNER] World Cup Champion Probabilities:")
    print(f"  {'Rank':<5s} {'Team':<22s} {'Prob':>7s}  {'Odds':>8s}")
    print(f"  {'-'*5} {'-'*22} {'-'*7}  {'-'*8}")
    champs = sorted(results["champion"].items(), key=lambda x: -x[1])
    for rank, (team, count) in enumerate(champs[:16], 1):
        p = prob(count)
        fair_odds = int(100 / p) if p > 0.001 else 999999
        bar = "#" * int(p * 200)
        print(f"  {rank:>3}.  {team:<22s} {p:>6.1%}  {fair_odds:>5.0f}-1  {bar}")

    # Finalist
    print(f"\n  [FINAL] Reaching Final:")
    finals = sorted(results["finalist"].items(), key=lambda x: -x[1])
    for rank, (team, count) in enumerate(finals[:12], 1):
        p = prob(count)
        print(f"  {rank:>3}. {team:<22s} {p:>6.1%}")

    # Semifinalist
    print(f"\n  [SEMIS] Reaching Semifinals:")
    semis = sorted(results["semifinalist"].items(), key=lambda x: -x[1])
    for rank, (team, count) in enumerate(semis[:12], 1):
        p = prob(count)
        print(f"  {rank:>3}. {team:<22s} {p:>6.1%}")

    # Quarterfinalist
    print(f"\n  [QUARTERS] Reaching Quarterfinals:")
    qf = sorted(results["quarterfinalist"].items(), key=lambda x: -x[1])
    for rank, (team, count) in enumerate(qf[:16], 1):
        p = prob(count)
        print(f"  {rank:>3}. {team:<22s} {p:>6.1%}")

    # Group stage: most surprising exits
    print(f"\n  [GROUP EXITS] Most surprising (based on FIFA rank):")
    exits = sorted(results["group_exit"].items(), key=lambda x: -x[1])
    for team, count in exits[:8]:
        p = prob(count)
        if p > 0.10:
            print(f"    {team:<22s} eliminated in group: {p:.1%}")

    # Group winners
    print(f"\n  [GROUP 1st] Most dominant group winners:")
    g1 = sorted(results["group_1st"].items(), key=lambda x: -x[1])
    for team, count in g1[:12]:
        p = prob(count)
        print(f"    {team:<22s} {p:.1%}")


# ============================================================
# 6. EXPORT
# ============================================================

def export_results(results: dict, path: Path):
    """Export simulation results to JSON."""
    export = {
        "n_simulations": results["n_sims"],
        "version": results.get("version", "V1"),
        "champion_probability": {k: round(v / results["n_sims"], 4)
                                 for k, v in sorted(results["champion"].items(),
                                                    key=lambda x: -x[1])},
        "finalist_probability": {k: round(v / results["n_sims"], 4)
                                 for k, v in sorted(results["finalist"].items(),
                                                    key=lambda x: -x[1])},
        "semifinalist_probability": {k: round(v / results["n_sims"], 4)
                                     for k, v in sorted(results["semifinalist"].items(),
                                                        key=lambda x: -x[1])},
        "quarterfinalist_probability": {k: round(v / results["n_sims"], 4)
                                        for k, v in sorted(results["quarterfinalist"].items(),
                                                           key=lambda x: -x[1])},
        "round_of_16_probability": {k: round(v / results["n_sims"], 4)
                                    for k, v in sorted(results["round_of_16"].items(),
                                                       key=lambda x: -x[1])},
        "group_winner_probability": {k: round(v / results["n_sims"], 4)
                                     for k, v in sorted(results["group_1st"].items(),
                                                        key=lambda x: -x[1])},
        "group_stage_exit_probability": {k: round(v / results["n_sims"], 4)
                                         for k, v in sorted(results["group_exit"].items(),
                                                            key=lambda x: -x[1])},
        "team_powers": results.get("v2_details", {}),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(export, f, indent=2, ensure_ascii=False)
    print(f"  Results exported to: {path}")


# ============================================================
# 7. MAIN
# ============================================================

if __name__ == "__main__":
    n_sims = 10000
    use_v2 = True
    for i, arg in enumerate(sys.argv[1:], 1):
        if arg == "--v1":
            use_v2 = False
        elif arg.isdigit():
            n_sims = int(arg)

    ver = "V2 (4-factor)" if use_v2 else "V1 (original)"
    print(f"Loading data for {n_sims}-simulation tournament [{ver}]...")
    players = load_players_from_json()
    fifa_ranks = load_fifa_rankings()

    # Load new data sources for V2
    betting_data = load_betting_odds() if use_v2 else None
    sponsors_data = load_sponsors() if use_v2 else None
    environment_data = load_environment() if use_v2 else None
    schedule_data = load_match_schedule() if use_v2 else None

    if use_v2:
        print(f"  [V2] Market odds + Sponsors + Environment factors enabled")

    results = simulate_tournament(players, fifa_ranks, n_sims=n_sims,
                                  use_v2=use_v2,
                                  betting_data=betting_data,
                                  sponsors_data=sponsors_data,
                                  environment_data=environment_data,
                                  schedule_data=schedule_data)
    print_results(results)

    export_results(results, DATA_DIR / "tournament_results.json")
