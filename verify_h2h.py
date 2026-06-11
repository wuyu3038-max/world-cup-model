"""Verify model after calibration to match historical patterns."""
import sys,io; sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
from model import *
import numpy as np
np.random.seed(42)

players = load_players_from_json()
fifa = load_fifa_rankings()
betting = load_betting_odds()
sponsors = load_sponsors()
injuries = load_injuries()

# Test ALL group matches and compute aggregate draw rate + avg goals
schedule = load_match_schedule()
all_hw = []; all_dw = []; all_aw = []
all_goals_h = []; all_goals_a = []

for md in ["matchday_1", "matchday_2", "matchday_3"]:
    for m in schedule["matches"][md]:
        home, away = m["home"], m["away"]
        hp = compute_team_power_v2(players, fifa, home, betting, sponsors, injuries)
        ap = compute_team_power_v2(players, fifa, away, betting, sponsors, injuries)

        hw = dw = aw = 0; h_goals = 0; a_goals = 0
        for _ in range(2000):
            hg, ag = simulate_match(hp['combined'], ap['combined'])
            h_goals += hg; a_goals += ag
            if hg > ag: hw += 1
            elif hg == ag: dw += 1
            else: aw += 1
        all_hw.append(hw/2000); all_dw.append(dw/2000); all_aw.append(aw/2000)
        all_goals_h.append(h_goals/2000); all_goals_a.append(a_goals/2000)

avg_draw = np.mean(all_dw)
avg_goals = np.mean(all_goals_h) + np.mean(all_goals_a)
avg_home_win = np.mean(all_hw)

print("Model calibration vs H2H historical data:")
print("  Historical draw rate: 25.4%%")
print("  Model draw rate:      %.1f%%" % (avg_draw*100))
print("  Historical goals/match: 2.88")
print("  Model goals/match:      %.2f" % avg_goals)
print("  Historical home win%:   ~45%% (neutral-ish)")
print("  Model home win%:        %.1f%%" % (avg_home_win*100))

# Check the biggest H2H mismatches from backtest
print("\nRe-checking mismatches with corrected home advantage:")
tests = [
    ("Scotland", "Brazil"),  # real 0%, was 33%
    ("Japan", "Sweden"),      # real 17%, was 39%
    ("Uruguay", "Spain"),     # real 10%, was 33%
    ("Norway", "France"),     # real 25%, was 40%
]
for home, away in tests:
    hp = compute_team_power_v2(players, fifa, home, betting, sponsors, injuries)
    ap = compute_team_power_v2(players, fifa, away, betting, sponsors, injuries)
    hw = dw = aw = 0
    for _ in range(5000):
        hg, ag = simulate_match(hp['combined'], ap['combined'])
        if hg > ag: hw += 1
        elif hg == ag: dw += 1
        else: aw += 1
    print("  %s vs %s: HW=%.1f%% (was ~33%%) D=%.1f%% AW=%.1f%%" % (home, away, hw/50, dw/50, aw/50))

# Check key match predictions with new calibration
print("\nKey match predictions:")
for home, away in [("South Korea","Czech Republic"),("Brazil","Morocco"),("Spain","Uruguay"),("England","Croatia")]:
    hp = compute_team_power_v2(players, fifa, home, betting, sponsors, injuries)
    ap = compute_team_power_v2(players, fifa, away, betting, sponsors, injuries)
    hw = dw = aw = 0
    scores = {}
    for _ in range(5000):
        hg, ag = simulate_match(hp['combined'], ap['combined'])
        if hg > ag: hw += 1
        elif hg == ag: dw += 1
        else: aw += 1
        scores["%d-%d"%(hg,ag)] = scores.get("%d-%d"%(hg,ag),0)+1
    top = sorted(scores.items(), key=lambda x:-x[1])[:3]
    print("  %s vs %s: W%.1f%% D%.1f%% L%.1f%%  top: %s(%.1f%%) %s(%.1f%%)" % (
        home, away, hw/50, dw/50, aw/50, top[0][0], top[0][1]/50, top[1][0], top[1][1]/50))
