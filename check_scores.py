import sys,io;sys.stdout=io.TextIOWrapper(sys.stdout.buffer,encoding='utf-8',errors='replace')
from model import *
players=load_players_from_json();fifa=load_fifa_rankings()
betting=load_betting_odds();sponsors=load_sponsors();injuries=load_injuries()

# Check: are powers too similar?
print("Power distribution across 48 teams:")
all_powers=[]
for nat in sorted(players["nation"].unique()):
    tp=compute_team_power_v2(players,fifa,nat,betting,sponsors,injuries)
    all_powers.append((nat,tp["combined"],tp["elo_strength"],tp["attack_score"],tp.get("defense_score",0)))

all_powers.sort(key=lambda x:-x[1])
for i,(n,c,e,a,d) in enumerate(all_powers):
    bar="█"*int(c/2)
    print(f"  {i+1:>2}. {n:<16s} {c:>5.1f} (elo={e:.1f} atk={a:.1f} def={d:.1f}) {bar}")

# Check xG diversity
print("\nxG diversity across matches:")
for home,away in [("Spain","Uruguay"),("England","Croatia"),("South Korea","Czech Republic"),
                   ("Brazil","Morocco"),("Germany","Ecuador"),("Mexico","South Africa"),
                   ("France","Senegal"),("Spain","Cape Verde"),("Brazil","Haiti"),("Germany","Curacao")]:
    hp=compute_team_power_v2(players,fifa,home,betting,sponsors,injuries)
    ap=compute_team_power_v2(players,fifa,away,betting,sponsors,injuries)
    xg_h=0.3+hp["combined"]/9.0+0.1
    xg_a=0.3+ap["combined"]/9.0
    pred=predict_match(hp["combined"],ap["combined"],home,away)

    # Dixon-Coles top 5 scores
    lam=max(xg_h,0.05);mu=max(xg_a,0.05);rho=-0.18
    scores=[]
    for h in range(11):
        for a in range(11):
            p=(lam**h*np.exp(-lam)/np.math.factorial(h))*(mu**a*np.exp(-mu)/np.math.factorial(a))
            if h==0 and a==0:p*=(1-lam*mu*rho)
            elif h==0 and a==1:p*=(1+lam*rho)
            elif h==1 and a==0:p*=(1+mu*rho)
            elif h==1 and a==1:p*=(1-rho)
            scores.append((f"{h}-{a}",max(p,0)))
    scores.sort(key=lambda x:-x[1])
    total=sum(s[1] for s in scores)
    top3=[(s,f"{c/total*100:.1f}%") for s,c in scores[:3]]

    print(f"  {home} vs {away}: xG {xg_h:.2f}-{xg_a:.2f} top3: {top3[0]} {top3[1]} {top3[2]}")
