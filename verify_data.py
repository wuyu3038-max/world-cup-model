import json
with open("data/world_cup_players.json", encoding="utf-8") as f:
    d = json.load(f)

checks = ["Harry Kane","Michael Olise","Kylian Mbappe","Lamine Yamal",
          "Morgan Gibbs-White","Cristiano Ronaldo","Son Heung-min","Bukayo Saka"]
for gn, gd in d["groups"].items():
    for nat, td in gd["teams"].items():
        for p in td["players"]:
            if p["name"] in checks:
                print("%-22s %-14s G=%s A=%s R=%s" % (p["name"], nat, p.get("goals_2526"), p.get("assists_2526"), p.get("rating")))
