"""
World Cup 2026 Prediction — Vercel Serverless Flask App
"""
import json, os
from pathlib import Path
from flask import Flask, send_file, jsonify, request

app = Flask(__name__)
DATA_DIR = Path(__file__).parent.parent / "data"

def read_json(filename):
    path = DATA_DIR / filename
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

@app.route("/api/players")
def api_players():
    return jsonify(read_json("world_cup_players.json"))

@app.route("/api/league")
def api_league():
    return jsonify(read_json("league_stats.json"))

@app.route("/api/fifa")
def api_fifa():
    return jsonify(read_json("fifa_rankings.json"))

@app.route("/api/betting")
def api_betting():
    return jsonify(read_json("betting_odds.json"))

@app.route("/api/environment")
def api_environment():
    return jsonify(read_json("environment.json"))

@app.route("/api/schedule")
def api_schedule():
    return jsonify(read_json("match_schedule.json"))

@app.route("/api/tournament")
def api_tournament():
    return jsonify(read_json("tournament_results.json"))

@app.route("/api/goalkeepers")
def api_gk():
    return jsonify(read_json("goalkeepers.json"))

@app.route("/api/managers")
def api_managers():
    return jsonify(read_json("managers.json"))

@app.route("/api/headtohead")
def api_h2h():
    return jsonify(read_json("head_to_head.json"))

@app.route("/api/international")
def api_intl():
    return jsonify(read_json("international_stats.json"))

@app.route("/api/advanced")
def api_advanced():
    return jsonify(read_json("advanced_stats.json"))

@app.route("/api/news")
def api_news():
    return jsonify(read_json("news_feed.json"))

@app.route("/api/odds/live")
def api_live_odds():
    return jsonify(read_json("live_odds.json"))

@app.route("/")
def index_page():
    return send_file(os.path.join(os.path.dirname(__file__), "..", "index.html"))

@app.route("/matches")
@app.route("/matches.html")
def matches_page():
    return send_file(os.path.join(os.path.dirname(__file__), "..", "matches.html"))

@app.route("/<path:filename>")
def static_files(filename):
    path = os.path.join(os.path.dirname(__file__), "..", filename)
    if os.path.isfile(path):
        return send_file(path)
    return "Not found", 404
