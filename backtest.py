"""
BACKTEST: Use ONLY provided data to validate and calibrate the model.
1. Analyze H2H historical patterns
2. Compare model predictions to historical outcomes
3. Adjust model weights based on historical accuracy
"""
import json, sys, io, math
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
import numpy as np
from collections import defaultdict

DATA = "data"

# ============================================
# 1. LOAD ALL PROVIDED DATA
# ============================================
with open(f"{DATA}/head_to_head.json", encoding="utf-8") as f:
    h2h = json.load(f)
with open(f"{DATA}/international_stats.json", encoding="utf-8") as f:
    intl = json.load(f)
with open(f"{DATA}/match_schedule.json", encoding="utf-8") as f:
    schedule = json.load(f)
with open(f"{DATA}/world_cup_players.json", encoding="utf-8") as f:
    wp = json.load(f)

# ============================================
# 2. ANALYZE H2H DATA — what patterns exist?
# ============================================
print("=" * 60)
print(" H2H DATA ANALYSIS")
print("=" * 60)

h2h_pairs = h2h.get("head_to_head", {})
total_matches = 0
total_wins_home = 0  # "home" = first team in key
total_draws = 0
total_wins_away = 0
score_dist = defaultdict(int)
win_rate_by_elo_gap = []

for key, data in h2h_pairs.items():
    if not isinstance(key, str) or "_vs_" not in key:
        continue
    teams = key.split("_vs_")
    if len(teams) != 2:
        continue
    t1, t2 = teams[0].replace("_"," "), teams[1].replace("_"," ")
    total_m = data.get("total", 0)
    draws = data.get("draws", 0)

    # Find win counts
    wins_t1 = 0
    wins_t2 = 0
    for k, v in data.items():
        if k.endswith("_wins") and isinstance(v, (int, float)):
            code = k.replace("_wins", "")
            if code in [t1[:3].lower(), t2[:3].lower()]:
                pass  # Can't easily map without team codes

    total_matches += total_m

print(f"Total H2H pairs: {len(h2h_pairs)}")
print(f"Total matches in database: {total_matches}")

# Count by total matches (how many pairs have decent sample size)
sample_sizes = defaultdict(int)
for key, data in h2h_pairs.items():
    n = data.get("total", 0)
    if n <= 3: sample_sizes["1-3"] += 1
    elif n <= 10: sample_sizes["4-10"] += 1
    elif n <= 20: sample_sizes["11-20"] += 1
    else: sample_sizes["20+"] += 1
print(f"Sample sizes: {dict(sample_sizes)}")

# ============================================
# 3. EXTRACT WIN/LOSS PATTERNS FROM H2H
# ============================================
print("\n" + "=" * 60)
print(" WIN/LOSS PATTERNS FROM H2H")
print("=" * 60)

# For each pair, calculate win rates using known team codes
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

# Analyze win rates for group-stage matchups
group_predictions = []
for md_key in ["matchday_1", "matchday_2", "matchday_3"]:
    for match in schedule.get("matches", {}).get(md_key, []):
        home = match.get("home", "")
        away = match.get("away", "")
        if not home or not away:
            continue

        # Find H2H data
        h2h_key = None
        for k in [f"{home}_vs_{away}", f"{away}_vs_{home}",
                  home.replace(" ","_") + "_vs_" + away.replace(" ","_"),
                  away.replace(" ","_") + "_vs_" + home.replace(" ","_")]:
            if k in h2h_pairs:
                h2h_key = k
                break

        h2h_data = h2h_pairs.get(h2h_key, {}) if h2h_key else {}
        total = h2h_data.get("total", 0)

        if total >= 2:
            h_code = TEAM_CODE_MAP.get(home, "")
            a_code = TEAM_CODE_MAP.get(away, "")
            h_wins = h2h_data.get(f"{h_code}_wins", -1)
            a_wins = h2h_data.get(f"{a_code}_wins", -1)
            draws = h2h_data.get("draws", 0)

            if h_wins >= 0 and a_wins >= 0:
                h_wr = h_wins / total
                a_wr = a_wins / total
                d_rate = draws / total
                group_predictions.append((home, away, h_wr, d_rate, a_wr, total, match.get("group","?")))

# Show matches with strongest H2H signals
group_predictions.sort(key=lambda x: abs(x[2] - 0.5), reverse=True)
print("\nGroup matches with significant H2H history:")
print("%-30s %3s  %6s %6s %6s %6s" % ("Matchup", "Grp", "Home%", "Draw%", "Away%", "N"))
for home, away, hw, dw, aw, n, grp in group_predictions[:20]:
    if abs(hw - 0.5) > 0.2:  # Only show meaningful edges
        print("%-30s %3s  %5.1f%% %5.1f%% %5.1f%% %4d" % (f"{home} vs {away}", grp, hw*100, dw*100, aw*100, n))

# ============================================
# 4. HISTORICAL SCORE DISTRIBUTION (from H2H goals data)
# ============================================
print("\n" + "=" * 60)
print(" HISTORICAL SCORE PATTERNS (from H2H goal data)")
print("=" * 60)

# Collect all goal totals from H2H data
all_gf = []
all_ga = []
for key, data in h2h_pairs.items():
    gf = data.get("gf", 0)
    ga = data.get("ga", 0)
    total = data.get("total", 0)
    if total > 0:
        avg_gf = gf / total  # avg goals for first team
        avg_ga = ga / total  # avg goals against first team
        all_gf.append(avg_gf)
        all_ga.append(avg_ga)

if all_gf:
    print(f"Average goals scored (team1): {np.mean(all_gf):.2f}")
    print(f"Average goals conceded (team1): {np.mean(all_ga):.2f}")
    print(f"Average total goals per match: {np.mean(all_gf) + np.mean(all_ga):.2f}")
    print(f"Range: {min(all_gf):.2f}-{max(all_gf):.2f} scored, {min(all_ga):.2f}-{max(all_ga):.2f} conceded")

# ============================================
# 5. VALIDATE MODEL AGAINST H2H
# ============================================
print("\n" + "=" * 60)
print(" MODEL vs H2H VALIDATION")
print("=" * 60)

from model import *

players = load_players_from_json()
fifa = load_fifa_rankings()
betting = load_betting_odds()
sponsors = load_sponsors()
injuries = load_injuries()

# For each H2H pair with sufficient data, compare model prediction to historical
validated = 0
correct = 0
brier_sum = 0
results = []

for home, away, hw_real, dw_real, aw_real, n, grp in group_predictions:
    if n < 5:
        continue

    hp = compute_team_power_v2(players, fifa, home, betting, sponsors, injuries)
    ap = compute_team_power_v2(players, fifa, away, betting, sponsors, injuries)

    # Model prediction
    hw_mod = dw_mod = aw_mod = 0
    for _ in range(5000):
        hg, ag = simulate_match(hp['combined'], ap['combined'])
        if hg > ag: hw_mod += 1
        elif hg == ag: dw_mod += 1
        else: aw_mod += 1
    hw_mod /= 5000; dw_mod /= 5000; aw_mod /= 5000

    # Compare
    model_favors_home = hw_mod > aw_mod
    real_favors_home = hw_real > aw_real
    if model_favors_home == real_favors_home:
        correct += 1

    # Brier score component
    brier = (hw_mod - hw_real)**2 + (dw_mod - dw_real)**2 + (aw_mod - aw_real)**2
    brier_sum += brier

    validated += 1
    results.append((home, away, hw_real, hw_mod, abs(hw_real - hw_mod)))

results.sort(key=lambda x: -x[4])  # Sort by prediction error

print(f"Validated against {validated} H2H matchups (N>=5)")
if validated > 0:
    print(f"Direction accuracy: {correct}/{validated} = {correct/validated*100:.1f}%")
    print(f"Brier score: {brier_sum/validated:.4f} (lower=better, 0=perfect, 1=always wrong)")

    print("\nBiggest prediction errors:")
    for home, away, real, pred, err in results[:5]:
        print(f"  {home} vs {away}: real HW%={real:.1%} model HW%={pred:.1%} error={err:.1%}")

# ============================================
# 6. CALIBRATION: ADJUST MODEL TO MATCH HISTORICAL REALITY
# ============================================
print("\n" + "=" * 60)
print(" CALIBRATION ANALYSIS")
print("=" * 60)

# What does the historical data tell us about football?
# 1. Home advantage in World Cups (neutral-ish venues but some have real home advantage)
# 2. Score distributions
# 3. Upset frequency

# From H2H data: calculate real draw rate
total_draws_h2h = sum(data.get("draws", 0) for data in h2h_pairs.values())
total_all = sum(data.get("total", 0) for data in h2h_pairs.values())
if total_all > 0:
    real_draw_rate = total_draws_h2h / total_all
    print(f"Historical draw rate: {real_draw_rate:.1%} ({total_draws_h2h}/{total_all})")

# Calculate model's draw rate for same matches
if validated > 0:
    model_draws = sum(1 for r in results if r[3] > 0.2)  # approximate
    print(f"Note: Real football has ~25% draws. Model should be calibrated to match.")

# Upset rate: in H2H, how often does the team with fewer wins still win?
upsets = 0
total_upset_opps = 0
for key, data in h2h_pairs.items():
    total = data.get("total", 0)
    if total < 5:
        continue
    # Find win counts for both sides
    win_keys = [k for k in data if k.endswith("_wins")]
    if len(win_keys) == 2:
        w1 = data[win_keys[0]]
        w2 = data[win_keys[1]]
        total_upset_opps += 1
        # "Upset" = the team with fewer historical wins won more recently
        # (can't determine from aggregate data alone)

print(f"\nHistorical data is aggregate only (no individual match results).")
print(f"Can validate direction, not individual score distributions.")

print("\n" + "=" * 60)
print(" CONCLUSIONS")
print("=" * 60)
print(f"""
Based on YOUR provided data ({len(h2h_pairs)} H2H pairs, {total_all} total matches):

1. Historical draw rate: ~{real_draw_rate:.0%} (model should target this)
2. Average total goals per match: ~{np.mean(all_gf)+np.mean(all_ga):.1f}
3. H2H validation accuracy: {correct}/{validated} correct direction

Data limitations:
- H2H data is aggregate (win/draw/loss counts), not match-by-match
- Cannot back-test score distributions without individual match data
- Cannot validate xG levels against historical data (no xG in H2H)
""")
