"""
2026 FIFA World Cup — Real-Time News & Information Module
===========================================================
Multi-source news aggregator for World Cup predictions.
Sources: 懂球帝 (Dongqiudi CN), ESPN FC, BBC Sport, Sky Sports.

Usage:
    python news_feed.py                  # Fetch latest news, save to JSON
    python news_feed.py --team "Spain"   # Filter news for specific team
    python news_feed.py --watch 600      # Auto-refresh every 10 min
"""

import json
import time
import sys
import re
import hashlib
from pathlib import Path
from datetime import datetime, timedelta
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
import xml.etree.ElementTree as ET

DATA_DIR = Path(__file__).parent / "data"

# ============================================================
# 1. 懂球帝 (Dongqiudi) — Chinese Football News
# ============================================================

DONGQIUDI_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
    "Referer": "https://www.dongqiudi.com/",
}

# World Cup / 世界杯 related tags and search
DONGQIUDI_ARTICLES_URL = "https://www.dongqiudi.com/api/v2/articles"
DONGQIUDI_SEARCH_URL = "https://api.dongqiudi.com/search/v3/search"


def fetch_dongqiudi_news(keyword: str = "世界杯", limit: int = 20) -> list:
    """
    Fetch latest news from Dongqiudi.
    Uses their unofficial JSON API (publicly accessible).
    """
    articles = []
    try:
        # Try the main articles feed with world cup tag
        url = f"{DONGQIUDI_ARTICLES_URL}?page=1&size={limit}"
        req = Request(url, headers=DONGQIUDI_HEADERS)
        with urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        for item in data.get("data", {}).get("articles", [])[:limit]:
            title = item.get("title", "")
            if keyword.lower() in title.lower():
                articles.append({
                    "id": item.get("id"),
                    "title": title,
                    "url": item.get("url", f"https://www.dongqiudi.com/articles/{item.get('id')}"),
                    "published_at": item.get("published_at", ""),
                    "source": "dongqiudi",
                    "language": "zh",
                    "summary": item.get("description", "")[:200],
                })
    except (URLError, HTTPError, json.JSONDecodeError, KeyError) as e:
        # Fallback: try search endpoint
        try:
            search_url = f"{DONGQIUDI_SEARCH_URL}?keyword={keyword}&type=article&size={limit}"
            req = Request(search_url, headers=DONGQIUDI_HEADERS)
            with urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            for item in data.get("data", {}).get("articles", [])[:limit]:
                articles.append({
                    "id": item.get("id"),
                    "title": item.get("title", ""),
                    "url": f"https://www.dongqiudi.com/articles/{item.get('id')}",
                    "published_at": item.get("published_at", ""),
                    "source": "dongqiudi",
                    "language": "zh",
                })
        except Exception:
            pass

    return articles


# ============================================================
# 2. International RSS Feeds
# ============================================================

RSS_SOURCES = {
    "espn_fc": {
        "name": "ESPN FC",
        "url": "https://www.espn.com/espn/rss/soccer/news",
        "language": "en",
    },
    "bbc_sport": {
        "name": "BBC Sport Football",
        "url": "https://feeds.bbci.co.uk/sport/football/rss.xml",
        "language": "en",
    },
    "sky_sports": {
        "name": "Sky Sports Football",
        "url": "https://www.skysports.com/rss/12040",
        "language": "en",
    },
    "goal_com": {
        "name": "Goal.com World Cup",
        "url": "https://www.goal.com/en/feeds/world-cup-2026/news",
        "language": "en",
    },
}


def fetch_rss_feed(source_key: str) -> list:
    """Fetch and parse an RSS feed."""
    source = RSS_SOURCES.get(source_key)
    if not source:
        return []

    articles = []
    try:
        req = Request(source["url"], headers={"User-Agent": "WorldCupModel/1.0"})
        with urlopen(req, timeout=15) as resp:
            xml_data = resp.read().decode("utf-8", errors="replace")

        root = ET.fromstring(xml_data)
        channel = root.find("channel")
        if channel is None:
            return articles

        for item in channel.findall("item")[:25]:
            title = item.findtext("title", "")
            link = item.findtext("link", "")
            desc = item.findtext("description", "")[:300]
            pub_date = item.findtext("pubDate", "")

            # Only include World Cup 2026 related
            wc_keywords = ["world cup", "2026", "fifa", "qualifier", "squad",
                           "group", "team news", "injury", "lineup"]
            title_lower = title.lower()
            if any(kw in title_lower for kw in wc_keywords):
                articles.append({
                    "id": hashlib.sha256(link.encode()).hexdigest()[:12],
                    "title": title,
                    "url": link,
                    "published_at": pub_date,
                    "source": source["name"],
                    "language": source["language"],
                    "summary": re.sub(r"<[^>]+>", "", desc)[:200],
                })
    except (URLError, HTTPError, ET.ParseError, UnicodeDecodeError) as e:
        pass  # Source unavailable, skip

    return articles


# ============================================================
# 3. Team-Specific News Filtering
# ============================================================

# Mapping: team name → search keywords in multiple languages
TEAM_KEYWORDS = {
    "Spain": ["spain", "españa", "西班牙", "yamal", "rodri", "pedri", "nico williams", "furia roja"],
    "France": ["france", "francia", "法国", "mbappé", "mbappe", "dembélé", "olise", "les bleus"],
    "England": ["england", "inglaterra", "英格兰", "kane", "bellingham", "saka", "three lions"],
    "Brazil": ["brazil", "brasil", "巴西", "neymar", "vinícius", "vinicius", "raphinha", "seleção"],
    "Argentina": ["argentina", "阿根廷", "messi", "lautaro", "albiceleste"],
    "Portugal": ["portugal", "葡萄牙", "ronaldo", "bruno fernandes", "bernardo silva", "seleção"],
    "Germany": ["germany", "alemania", "德国", "musiala", "wirtz", "kimmich", "die mannschaft"],
    "Netherlands": ["netherlands", "holland", "荷兰", "van dijk", "gakpo", "oranje"],
    "Norway": ["norway", "noruega", "挪威", "haaland", "ødegaard", "odegaard"],
    "USA": ["usa", "united states", "美国", "pulisic", "usmnt"],
    "Mexico": ["mexico", "méxico", "墨西哥", "ochoa", "giménez", "el tri"],
    "Japan": ["japan", "japón", "日本", "samurai blue", "mitoma", "kubo", "endo"],
    "South Korea": ["south korea", "korea", "韩国", "son heung", "kim min", "taegeuk"],
    "Croatia": ["croatia", "croacia", "克罗地亚", "modrić", "modric", "gvardiol"],
    "Belgium": ["belgium", "bélgica", "比利时", "de bruyne", "lukaku", "doku", "red devils"],
    "Senegal": ["senegal", "塞内加尔", "mané", "mane", "koulibaly"],
    "Morocco": ["morocco", "marruecos", "摩洛哥", "hakimi", "atlas lions"],
    "Colombia": ["colombia", "哥伦比亚", "luis díaz", "james"],
    "Uruguay": ["uruguay", "乌拉圭", "valverde", "darwin", "núñez", "celeste"],
    "Sweden": ["sweden", "suecia", "瑞典", "isak", "gyökeres", "elanga"],
    "Egypt": ["egypt", "egipto", "埃及", "salah", "marmoush"],
    "Canada": ["canada", "canadá", "加拿大", "davies", "david"],
    "Scotland": ["scotland", "escocia", "苏格兰", "mctominay", "robertson", "tartan army"],
}

# Generic World Cup keywords (match all)
WC_GENERAL_KEYWORDS = [
    "world cup", "world cup 2026", "fifa world cup", "世界杯", "2026世界杯",
    "fifa 2026", "group stage", "小组赛", "knockout", "淘汰赛", "squad", "injury",
    "starting xi", "lineup", "首发", "伤病", "transfer", "转会",
]


def filter_team_news(all_articles: list, team: str) -> list:
    """Filter articles relevant to a specific team."""
    keywords = TEAM_KEYWORDS.get(team, [team.lower()])
    filtered = []
    for article in all_articles:
        text = (article.get("title", "") + " " + article.get("summary", "")).lower()
        if any(kw.lower() in text for kw in keywords):
            filtered.append(article)
    return filtered


def extract_news_sentiment(articles: list) -> dict:
    """
    Simple keyword-based sentiment analysis.
    Returns counts of positive/negative/neutral articles.
    """
    positive_words = ["win", "victory", "confident", "star", "fit", "return", "boost",
                      "hat-trick", "record", "top", "best", "favorite", "triumph",
                      "胜", "赢", "回归", "进球", "帽子戏法", "纪录", "最佳"]
    negative_words = ["injury", "injured", "doubt", "loss", "defeat", "out", "suspended",
                      "struggle", "disappointing", "blow", "setback", "worry",
                      "伤", "输", "缺阵", "停赛", "低迷", "失利", "危机", "淘汰"]

    result = {"positive": 0, "negative": 0, "neutral": 0, "total": len(articles),
              "highlights": []}
    for article in articles:
        text = (article.get("title", "") + " " + article.get("summary", "")).lower()
        pos_count = sum(1 for w in positive_words if w in text)
        neg_count = sum(1 for w in negative_words if w in text)
        if neg_count > pos_count:
            result["negative"] += 1
            if neg_count >= 3:
                result["highlights"].append(f"[!] NEG: {article['title'][:80]}")
        elif pos_count > neg_count:
            result["positive"] += 1
        else:
            result["neutral"] += 1
    return result


# ============================================================
# 4. Environment / Weather Impact Analysis
# ============================================================

def load_environment() -> dict:
    """Load environment data."""
    path = DATA_DIR / "environment.json"
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def get_match_environment(city_name: str) -> dict:
    """Get environmental factors for a match venue."""
    env = load_environment()
    cities = env.get("cities", {})
    return cities.get(city_name, {})


def env_impact_score(city: str, team_power: float) -> float:
    """
    Calculate environmental impact on team performance.
    Returns a modifier to expected goals (-0.3 to +0.0).
    """
    env = get_match_environment(city)
    if not env:
        return 0.0

    impact = 0.0

    # Heat penalty: WBGT >26 = fatigue, slower play
    wbgt_risk = env.get("wbgt_risk", "")
    if ">30" in wbgt_risk or "EXTREME" in wbgt_risk:
        impact -= 0.25  # severe
    elif ">28" in wbgt_risk or "HIGH" in wbgt_risk:
        impact -= 0.15
    elif ">26" in wbgt_risk or "MODERATE" in wbgt_risk:
        impact -= 0.08

    # Altitude: reduces performance for non-acclimatized teams
    elevation = env.get("elevation_m", 0)
    if elevation > 2000:
        impact -= 0.12  # Mexico City
    elif elevation > 1500:
        impact -= 0.06  # Guadalajara

    # Roof: mitigates heat
    if env.get("roof"):
        impact = max(impact, -0.05)  # Cap heat penalty with roof

    return round(impact, 3)


# ============================================================
# 5. Main Aggregator
# ============================================================

def fetch_all_news(team_filter: str = None) -> dict:
    """Fetch news from all sources."""
    all_articles = []
    source_counts = {}

    print(f"[{datetime.now().strftime('%H:%M:%S')}] Fetching news...")

    # Dongqiudi
    print("  Dongqiudi (懂球帝)...", end=" ")
    dq_articles = fetch_dongqiudi_news("世界杯")
    all_articles.extend(dq_articles)
    source_counts["dongqiudi"] = len(dq_articles)
    print(f"{len(dq_articles)} articles")

    # International RSS
    for source_key in RSS_SOURCES:
        name = RSS_SOURCES[source_key]["name"]
        print(f"  {name}...", end=" ")
        rss_articles = fetch_rss_feed(source_key)
        all_articles.extend(rss_articles)
        source_counts[source_key] = len(rss_articles)
        print(f"{len(rss_articles)} articles (World Cup related)")

    # Deduplicate by title similarity
    seen = set()
    unique = []
    for a in all_articles:
        key = a["title"][:60].lower().strip()
        if key not in seen:
            seen.add(key)
            unique.append(a)

    result = {
        "updated": datetime.now().isoformat(),
        "total_articles": len(unique),
        "source_counts": source_counts,
        "articles": unique[:100],  # Top 100
    }

    # Team filter
    if team_filter:
        team_articles = filter_team_news(unique, team_filter)
        sentiment = extract_news_sentiment(team_articles)
        result["team_filter"] = team_filter
        result["team_articles"] = team_articles[:20]
        result["team_sentiment"] = sentiment
        print(f"\n  Team filter: {team_filter} → {len(team_articles)} articles")
        print(f"  Sentiment: +{sentiment['positive']}/-{sentiment['negative']}"
              f"/~{sentiment['neutral']} (of {sentiment['total']})")

    # Save
    output_path = DATA_DIR / "news_feed.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(f"\n  Saved to: {output_path}")

    return result


def watch_mode(team_filter: str = None, interval: int = 600):
    """Continuously fetch news every `interval` seconds."""
    print(f"Watch mode: fetching every {interval}s. Ctrl+C to stop.\n")
    try:
        while True:
            fetch_all_news(team_filter)
            print(f"\n  Next refresh in {interval}s...\n")
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n  Stopped.")


# ============================================================
# 6. Model Integration
# ============================================================

def get_team_sentiment_score(team: str) -> float:
    """
    Get team sentiment score from latest news for model integration.
    Range: -1.0 (very negative) to +1.0 (very positive).
    """
    path = DATA_DIR / "news_feed.json"
    if not path.exists():
        return 0.0

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # If we already have a team filter in the data
    if data.get("team_filter") == team and "team_sentiment" in data:
        sent = data["team_sentiment"]
        total = sent.get("total", 1) or 1
        return round((sent["positive"] - sent["negative"]) / total, 3)

    # Otherwise, filter articles for this team
    articles = data.get("articles", [])
    team_articles = filter_team_news(articles, team)
    sent = extract_news_sentiment(team_articles)
    total = sent.get("total", 1) or 1
    return round((sent["positive"] - sent["negative"]) / total, 3)


def print_team_news_brief(team: str):
    """Print a brief news summary for a team."""
    path = DATA_DIR / "news_feed.json"
    if not path.exists():
        print("  No news data available. Run news_feed.py first.")
        return

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    articles = data.get("articles", [])
    team_articles = filter_team_news(articles, team)
    sent = extract_news_sentiment(team_articles)

    print(f"\n  --- {team} News Brief ---")
    print(f"  Sentiment: +{sent['positive']} positive / -{sent['negative']} negative "
          f"/ ~{sent['neutral']} neutral")
    print(f"  Total articles: {sent['total']}")
    if sent["highlights"]:
        print(f"  Key alerts:")
        for h in sent["highlights"][:3]:
            print(f"    {h}")
    if team_articles:
        print(f"  Recent headlines:")
        for a in team_articles[:5]:
            print(f"    [{a['source']}] {a['title'][:80]}")


# ============================================================
# 7. CLI
# ============================================================

if __name__ == "__main__":
    team = None
    if "--team" in sys.argv:
        idx = sys.argv.index("--team")
        if idx + 1 < len(sys.argv):
            team = sys.argv[idx + 1]

    if "--watch" in sys.argv:
        idx = sys.argv.index("--watch")
        interval = int(sys.argv[idx + 1]) if idx + 1 < len(sys.argv) else 600
        watch_mode(team, interval)
    else:
        print("=" * 55)
        print("  World Cup 2026 — News Feed Aggregator")
        print("=" * 55)
        result = fetch_all_news(team)

        if team:
            print_team_news_brief(team)
        else:
            # Show top headlines
            print(f"\n  Top Headlines:")
            for a in result.get("articles", [])[:10]:
                src = a["source"]
                title = a["title"][:85]
                print(f"    [{src}] {title[:80]}")

        print(f"\n  Run 'python news_feed.py --team Spain' for team-specific news.")
