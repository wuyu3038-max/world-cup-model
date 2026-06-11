"""Backtest model against 2022 World Cup matches only."""
import sys, io, json, csv
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
import numpy as np

DATA = "data"

# Load 2022 World Cup matches
matches = []
with open(f"{DATA}/results.csv", "r", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    for row in reader:
        if row["tournament"] == "FIFA World Cup" and row["date"] >= "2022-11-20" and row["date"] <= "2022-12-18":
            matches.append({
                "date": row["date"],
                "home": row["home_team"],
                "away": row["away_team"],
                "hg": int(row["home_score"]),
                "ag": int(row["away_score"]),
                "neutral": True,
                "stage": "Group" if "Group" in row.get("city","") or int(row["date"][8:10]) <= 2 else "Knockout",
            })

print(f"2022 World Cup matches found: {len(matches)}")

# Load model
from model import *
players = load_players_from_json()
fifa = load_fifa_rankings()
betting = load_betting_odds()
sponsors = load_sponsors()
injuries = load_injuries()

# Name mapping
NAME_MAP_2022 = {
    "United States": "United States", "Korea Republic": "South Korea",
    "Iran": "Iran", "Qatar": "Qatar", "Ecuador": "Ecuador",
    "Senegal": "Senegal", "Netherlands": "Netherlands", "England": "England",
    "Wales": None, "Argentina": "Argentina", "Saudi Arabia": "Saudi Arabia",
    "Mexico": "Mexico", "Poland": None, "France": "France",
    "Australia": "Australia", "Denmark": None, "Tunisia": "Tunisia",
    "Spain": "Spain", "Costa Rica": None, "Germany": "Germany",
    "Japan": "Japan", "Belgium": "Belgium", "Canada": "Canada",
    "Morocco": "Morocco", "Croatia": "Croatia", "Brazil": "Brazil",
    "Serbia": None, "Switzerland": "Switzerland", "Cameroon": None,
    "Portugal": "Portugal", "Ghana": "Ghana", "Uruguay": "Uruguay",
    "South Korea": "South Korea",
}

# Pre-compute powers
team_powers = {}
for team in set(players["nation"].unique()):
    tp = compute_team_power_v2(players, fifa, team, betting, sponsors, injuries)
    team_powers[team] = tp["combined"]

# Run predictions
print("\nRunning predictions...")
results = []
correct = 0
correct_group = 0; total_group = 0
correct_ko = 0; total_ko = 0
score_exact = 0
brier_total = 0

for m in matches:
    h_raw = m["home"]; a_raw = m["away"]
    home = NAME_MAP_2022.get(h_raw, h_raw)
    away = NAME_MAP_2022.get(a_raw, a_raw)
    if home is None or away is None:
        continue

    hp = team_powers.get(home, 5.0)
    ap = team_powers.get(away, 5.0)
    if home not in team_powers: hp = 5.0
    if away not in team_powers: ap = 5.0

    # Predict
    hw = dw = aw = 0
    scores = {}
    for _ in range(5000):
        hg, ag = simulate_match(hp, ap, home_advantage=0.0)  # neutral
        if hg > ag: hw += 1
        elif hg == ag: dw += 1
        else: aw += 1
        scores[f"{hg}-{ag}"] = scores.get(f"{hg}-{ag}", 0) + 1
    hw /= 5000; dw /= 5000; aw /= 5000
    top_score = max(scores, key=scores.get)
    top_pct = scores[top_score] / 5000 * 100

    # Actual
    hg_real, ag_real = m["hg"], m["ag"]
    if hg_real > ag_real: actual = "H"
    elif hg_real == ag_real: actual = "D"
    else: actual = "A"

    # Model pick
    if hw > aw and hw > dw: pred = "H"
    elif aw > hw and aw > dw: pred = "A"
    else: pred = "D"

    is_correct = (pred == actual)
    if is_correct: correct += 1

    # Exact score
    if top_score == f"{hg_real}-{ag_real}": score_exact += 1

    # Brier
    if actual == "H": brier = (hw-1)**2 + dw**2 + aw**2
    elif actual == "D": brier = hw**2 + (dw-1)**2 + aw**2
    else: brier = hw**2 + dw**2 + (aw-1)**2
    brier_total += brier

    is_group = m["hg"] + m["ag"] < 20  # knockouts have ET
    if pred != "D" or actual != "D":
        if hg_real != ag_real:
            if is_group:
                total_group += 1
                if is_correct: correct_group += 1
            else:
                total_ko += 1
                if is_correct: correct_ko += 1

    results.append({
        "match": f"{home} vs {away}",
        "score": f"{hg_real}-{ag_real}",
        "pred": pred, "actual": actual, "correct": is_correct,
        "hw": hw, "dw": dw, "aw": aw,
        "top_score": top_score, "top_pct": top_pct,
        "brier": brier, "power_gap": abs(hp - ap),
    })

# ============================================
# RESULTS
# ============================================
n = len(results)
acc = correct / n * 100
avg_brier = brier_total / n

print(f"\n{'='*60}")
print(f" 2022 WORLD CUP BACKTEST — {n} matches")
print(f"{'='*60}")
print(f"Direction accuracy: {correct}/{n} = {acc:.1f}%")
print(f"Exact score: {score_exact}/{n} = {score_exact/n*100:.1f}%")
print(f"Brier score: {avg_brier:.4f}")

# By outcome
for label, name in [("H","Home"),("D","Draw"),("A","Away")]:
    subset = [r for r in results if r["actual"] == label]
    c = sum(1 for r in subset if r["correct"])
    if subset:
        print(f"  {name}: {c}/{len(subset)} = {c/len(subset)*100:.1f}%")

# Calibration
avg_hw = np.mean([r["hw"] for r in results])
avg_dw = np.mean([r["dw"] for r in results])
avg_aw = np.mean([r["aw"] for r in results])
act_hw = sum(1 for r in results if r["actual"]=="H") / n
act_dw = sum(1 for r in results if r["actual"]=="D") / n
act_aw = sum(1 for r in results if r["actual"]=="A") / n
print(f"\nCalibration:")
print(f"  Home: pred={avg_hw:.1%} actual={act_hw:.1%}")
print(f"  Draw: pred={avg_dw:.1%} actual={act_dw:.1%}")
print(f"  Away: pred={avg_aw:.1%} actual={act_aw:.1%}")

# Group vs Knockout
if total_group > 0:
    print(f"\nGroup stage: {correct_group}/{total_group} = {correct_group/total_group*100:.1f}%")
if total_ko > 0:
    print(f"Knockout: {correct_ko}/{total_ko} = {correct_ko/total_ko*100:.1f}%")

# All matches detail
print(f"\n{'─'*80}")
print(f"{'Match':<35s} {'Score':>6s} {'Pred':>4s} {'Act':>4s} {'OK':>4s} {'HW':>6s} {'DW':>6s} {'AW':>6s} {'TopSc':>6s}")
print(f"{'─'*80}")
for r in results:
    ok = "✓" if r["correct"] else "✗"
    print(f"{r['match']:<35s} {r['score']:>6s} {r['pred']:>4s} {r['actual']:>4s} {ok:>4s} {r['hw']:>5.1%} {r['dw']:>5.1%} {r['aw']:>5.1%} {r['top_score']:>6s}")

# Biggest errors
print(f"\n{'─'*80}")
print(f"Biggest misses:")
errors = [r for r in results if not r["correct"]]
errors.sort(key=lambda r: r["brier"], reverse=True)
for r in errors[:8]:
    print(f"  {r['match']} ({r['score']}): pred={r['pred']} HW={r['hw']:.1%} DW={r['dw']:.1%} AW={r['aw']:.1%} gap={r['power_gap']:.1f}")
