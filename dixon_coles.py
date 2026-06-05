"""
Dixon-Coles Football Prediction Model (NumPy-only, no scipy)
=============================================================
Dixon & Coles (1997) — Attack/Defence parameters + home advantage + rho correction.
Pure NumPy implementation with gradient descent fitting.
"""

import json
import math
import numpy as np
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"

# ============================================================
# 1. LIKELIHOOD
# ============================================================

def dc_neg_loglike(params, hg, ag, hi, ai, n_teams):
    home_adv = params[0]
    att = np.array(params[1:1+n_teams])
    dfn = np.array(params[1+n_teams:1+2*n_teams])
    rho = max(-1.0, min(1.0, params[-1]))

    log_lam = home_adv + att[hi] - dfn[ai]
    log_mu = att[ai] - dfn[hi]
    lam = np.exp(log_lam)
    mu = np.exp(log_mu)

    ll = (-lam + hg * log_lam - mu + ag * log_mu)
    tau = np.ones_like(hg)
    m00 = (hg == 0) & (ag == 0); m01 = (hg == 0) & (ag == 1)
    m10 = (hg == 1) & (ag == 0); m11 = (hg == 1) & (ag == 1)
    if np.any(m00): tau[m00] = 1.0 - lam[m00] * mu[m00] * rho
    if np.any(m01): tau[m01] = 1.0 + lam[m01] * rho
    if np.any(m10): tau[m10] = 1.0 + mu[m10] * rho
    if np.any(m11): tau[m11] = 1.0 - rho
    tau = np.maximum(tau, 1e-10)
    ll += np.log(tau)
    return -np.sum(ll)

# ============================================================
# 2. FITTING (gradient descent, no scipy)
# ============================================================

def fit_dixon_coles(matches, teams, lr=0.01, epochs=2000, verbose=False):
    n = len(teams)
    t2i = {t: i for i, t in enumerate(teams)}
    hg_arr, ag_arr, hi_arr, ai_arr = [], [], [], []
    for m in matches:
        h, a = m["home"], m["away"]
        if h in t2i and a in t2i:
            hg_arr.append(m["home_goals"]); ag_arr.append(m["away_goals"])
            hi_arr.append(t2i[h]); ai_arr.append(t2i[a])
    hg_arr = np.array(hg_arr, float); ag_arr = np.array(ag_arr, float)
    hi_arr = np.array(hi_arr, int); ai_arr = np.array(ai_arr, int)

    params = np.zeros(1 + 2*n + 1)
    params[0] = 0.3; params[-1] = 0.05
    eps = 1e-5; best = None; best_loss = float("inf")

    for ep in range(epochs):
        loss = dc_neg_loglike(params, hg_arr, ag_arr, hi_arr, ai_arr, n)
        grad = np.zeros_like(params)
        for i in range(len(params)):
            orig = params[i]
            params[i] = orig + eps
            lp = dc_neg_loglike(params, hg_arr, ag_arr, hi_arr, ai_arr, n)
            params[i] = orig - eps
            lm = dc_neg_loglike(params, hg_arr, ag_arr, hi_arr, ai_arr, n)
            params[i] = orig
            grad[i] = (lp - lm) / (2 * eps)
        params -= lr * grad
        params[1:1+n] -= np.mean(params[1:1+n])
        params[1+n:1+2*n] -= np.mean(params[1+n:1+2*n])
        params[-1] = max(-1.0, min(1.0, params[-1]))
        if loss < best_loss:
            best_loss = loss; best = params.copy()
        if verbose and ep % 500 == 0: print(f"  Epoch {ep}: loss={loss:.2f}")

    ha = float(best[0])
    att = {t: round(float(best[1+i]), 4) for t, i in t2i.items()}
    dfn = {t: round(float(best[1+n+i]), 4) for t, i in t2i.items()}
    return {"home_advantage": round(ha, 4), "attack": att, "defence": dfn,
            "rho": round(float(best[-1]), 4), "n_matches": len(hg_arr),
            "n_teams": n, "final_loss": round(float(best_loss), 2)}

# ============================================================
# 3. PREDICTION
# ============================================================

def predict_match_dc(model, home, away, neutral=False, max_g=10):
    att = model["attack"]; dfn = model["defence"]
    ha = 0.0 if neutral else model.get("home_advantage", 0.3)
    rho = model.get("rho", 0.0)

    ah = att.get(home, 0.0); aa = att.get(away, 0.0)
    dh = dfn.get(home, 0.0); da = dfn.get(away, 0.0)

    lam = np.exp(ha + ah - da)
    mu = np.exp(aa - dh)

    hw = dw = aw = o25 = btts = total = 0.0
    scores = {}
    for h in range(max_g+1):
        for a in range(max_g+1):
            p = (lam**h * np.exp(-lam) / math.factorial(h) *
                 mu**a * np.exp(-mu) / math.factorial(a))
            if h==0 and a==0: p *= (1 - lam*mu*rho)
            elif h==0 and a==1: p *= (1 + lam*rho)
            elif h==1 and a==0: p *= (1 + mu*rho)
            elif h==1 and a==1: p *= (1 - rho)
            p = max(p, 0.0); scores[(h,a)] = p; total += p
            if h > a: hw += p
            elif h == a: dw += p
            else: aw += p
            if h+a > 2.5: o25 += p
            if h>0 and a>0: btts += p

    if total > 0: hw /= total; dw /= total; aw /= total; o25 /= total; btts /= total
    best_score = max(scores, key=scores.get)
    return {"home_win": round(hw,4), "draw": round(dw,4), "away_win": round(aw,4),
            "expected_home_goals": round(lam,2), "expected_away_goals": round(mu,2),
            "over_2.5_pct": round(o25,4), "btts_pct": round(btts,4),
            "most_likely_score": best_score}

def simulate_match_dc(model, home, away, neutral=False):
    p = predict_match_dc(model, home, away, neutral)
    return np.random.poisson(p["expected_home_goals"]), np.random.poisson(p["expected_away_goals"])

# ============================================================
# 4. BUILD WORLD CUP MODEL
# ============================================================

def build_wc_model_from_ratings(players_df, fifa_ranks, league_stats):
    with open(DATA_DIR / "goalkeepers.json", "r", encoding="utf-8") as f:
        gk = json.load(f)
    gkr = gk.get("team_gk_rating", {}).get("ratings", {})

    from model import GROUP_STRUCTURE_16x3, compute_attack_score
    teams = []; [teams.extend(v) for v in GROUP_STRUCTURE_16x3.values()]

    att, dfn = {}, {}
    for t in teams:
        sc = compute_attack_score(players_df, t)
        if np.isnan(sc) or sc <= 0: sc = 0.1
        # Smoother scaling: log-based but clamped for realistic xG (~0.3 to 3.5)
        att[t] = round(np.log(max(sc, 0.3)) * 0.35 - 0.25, 4)
        rk = fifa_ranks.get(t, 60); gs = gkr.get(t, 50)
        dfn[t] = round(-(2200 - rk*10)/6000 - (gs-50)/400, 4)

    am = np.mean(list(att.values())); dm = np.mean(list(dfn.values()))
    for t in teams: att[t] = round(att[t]-am, 4); dfn[t] = round(dfn[t]-dm, 4)

    return {"home_advantage": 0.30, "attack": att, "defence": dfn, "rho": 0.05, "n_teams": len(teams)}

# ============================================================
# 5. TEST
# ============================================================

if __name__ == "__main__":
    print("=" * 55)
    print("  Dixon-Coles Model (NumPy only)")
    print("=" * 55)

    # Test with synthetic data
    teams = ["A", "B", "C", "D"]
    matches = [
        {"home": "A", "away": "B", "home_goals": 2, "away_goals": 1},
        {"home": "A", "away": "C", "home_goals": 3, "away_goals": 0},
        {"home": "B", "away": "A", "home_goals": 1, "away_goals": 1},
        {"home": "C", "away": "D", "home_goals": 1, "away_goals": 2},
        {"home": "B", "away": "D", "home_goals": 0, "away_goals": 0},
        {"home": "A", "away": "D", "home_goals": 4, "away_goals": 1},
        {"home": "D", "away": "C", "home_goals": 2, "away_goals": 0},
        {"home": "B", "away": "C", "home_goals": 1, "away_goals": 1},
    ]
    model = fit_dixon_coles(matches, teams, lr=0.05, epochs=3000, verbose=True)
    print(f"\n  Fitted: HA={model['home_advantage']:.2f} rho={model['rho']:.3f} loss={model['final_loss']}")
    for t in teams: print(f"    {t}: ATT={model['attack'][t]:+.3f} DEF={model['defence'][t]:+.3f}")

    p = predict_match_dc(model, "A", "B", neutral=True)
    print(f"\n  A vs B (neutral): {p['home_win']:.1%}/{p['draw']:.1%}/{p['away_win']:.1%}")
    print(f"    xG: {p['expected_home_goals']:.2f}-{p['expected_away_goals']:.2f} O2.5:{p['over_2.5_pct']:.1%}")

    # Build WC model
    print(f"\n  Building World Cup DC model...")
    from model import load_players_from_json, load_fifa_rankings, load_league_stats
    wc = build_wc_model_from_ratings(load_players_from_json(), load_fifa_rankings(), load_league_stats())
    print(f"  {wc['n_teams']} teams | Top attacks: {sorted(wc['attack'], key=wc['attack'].get, reverse=True)[:5]}")
    print(f"  Top defences: {sorted(wc['defence'], key=wc['defence'].get)[:5]}")

    print(f"\n  === KEY PREDICTIONS ===")
    for h, a, note in [
        ("France", "Senegal", "2002 rematch"), ("England", "Croatia", "2018 SF rematch"),
        ("Brazil", "Morocco", "2023 upset rematch"), ("Spain", "Uruguay", "Group H clash"),
        ("Norway", "France", "Haaland vs Mbappe"),
    ]:
        p = predict_match_dc(wc, h, a, neutral=True)
        print(f"  {h} vs {a} [{note}]: {p['home_win']:.1%}/{p['draw']:.1%}/{p['away_win']:.1%} "
              f"xG:{p['expected_home_goals']:.1f}-{p['expected_away_goals']:.1f} O2.5:{p['over_2.5_pct']:.0%}")
