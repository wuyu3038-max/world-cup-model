# 2026 FIFA World Cup 预测模型 — 完整系统

## 📁 项目结构

```
world-cup-model/
├── model.py                       # 核心预测模型（FIFA排名+球员统计+博彩+Poisson模拟）
├── tournament.py                  # 完整杯赛模拟（小组赛→32强→16强→8强→4强→决赛）
├── odds_refresh.py                # 实时赔率刷新（1X2/让球/大小球/BTTS）
├── news_feed.py                   # 实时新闻采集（懂球帝+ESPN+BBC+Sky Sports）
├── data/
│   ├── world_cup_players.json     # 48队×147名球员详细数据
│   ├── world_cup_players.csv      # CSV版本（pd.read_csv直接加载）
│   ├── league_stats.json          # 五大联赛+欧冠 2024-26 统计
│   ├── fifa_rankings.json         # 48队FIFA世界排名（2026年6月）
│   ├── betting_odds.json          # 博彩赔率（夺冠/小组/晋级/金靴）
│   ├── player_stats_supplement.json # 补充球员数据（33人）
│   ├── environment.json           # 16个主办城市天气/海拔/环境数据
│   ├── live_odds.json             # 实时赔率快照
│   ├── news_feed.json             # 实时新闻快照
│   └── tournament_results.json    # 完整杯赛模拟结果
└── README.md
```

## 🚀 快速开始

```bash
cd C:\Users\29746\Documents\world-cup-model

# 1. 基础分析（球员排名+球队实力+小组模拟+博彩对比）
python model.py

# 2. 完整杯赛模拟（N次蒙特卡洛→夺冠/进决赛/进四强概率）
python tournament.py 5000

# 3. 刷新实时赔率
python odds_refresh.py

# 4. 采集最新新闻
python news_feed.py --team "Spain"

# 5. 持续监控模式
python news_feed.py --watch 600       # 每10分钟刷新新闻
python odds_refresh.py --watch 300    # 每5分钟刷新赔率
```

## 📊 模型特点

| 维度 | 数据来源 | 覆盖率 |
|------|---------|--------|
| 球员统计 | Transfermarkt, Sofascore, FBref | 147名×48队 |
| FIFA排名 | FIFA官方排名 2026年6月 | 全部48队 |
| 博彩赔率 | DraftKings, FanDuel, Bet365 | 冠军/小组/晋级/金靴/大小球 |
| 新闻资讯 | 懂球帝, ESPN FC, BBC, Sky Sports | 实时采集 |
| 环境因素 | NOAA气候数据, FIFA场馆数据 | 16个城市 |
| 球员趋势 | 2024-25 → 2025-26 进球变化 | 23支球队 |

## 🔑 核心发现（1000次模拟）

- 🏆 **夺冠热门**: 西班牙 35.9%, 德国 18.4%, 英格兰 11.1%
- ⚔️ **死亡之组**: Group I (法国+挪威+塞内加尔)
- 📈 **最大黑马**: 挪威（模型PWR 18.0 vs 市场赔率 2.9%）
- 🔥 **最热场地**: 迈阿密（WBGT >30°C，极端风险）
- 🏔️ **海拔影响**: 墨西哥城 2250m（球飞行+10%，有氧-8%）
