"""
World Cup 2026 Prediction Web Server
Simple HTTP server with JSON API endpoints.
"""

import json
import http.server
import socketserver
from pathlib import Path
from urllib.parse import urlparse, parse_qs

DATA_DIR = Path(__file__).parent / "data"
PORT = 8080

class APIHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        # Static HTML pages
        if path == "/" or path == "/index.html":
            self.serve_html("index.html")
        elif path == "/matches" or path == "/matches.html":
            self.serve_html("matches.html")
        # API routes
        elif path == "/api/players":
            self.serve_json("world_cup_players.json")
        elif path == "/api/league":
            self.serve_json("league_stats.json")
        elif path == "/api/fifa":
            self.serve_json("fifa_rankings.json")
        elif path == "/api/betting":
            self.serve_json("betting_odds.json")
        elif path == "/api/environment":
            self.serve_json("environment.json")
        elif path == "/api/schedule":
            self.serve_json("match_schedule.json")
        elif path == "/api/tournament":
            self.serve_json("tournament_results.json")
        elif path == "/api/news":
            self.serve_json("news_feed.json")
        elif path == "/api/goalkeepers":
            self.serve_json("goalkeepers.json")
        elif path == "/api/managers":
            self.serve_json("managers.json")
        elif path == "/api/headtohead":
            self.serve_json("head_to_head.json")
        elif path == "/api/international":
            self.serve_json("international_stats.json")
        elif path == "/api/advanced":
            self.serve_json("advanced_stats.json")
        elif path == "/api/odds/live":
            self.serve_json("live_odds.json")
        elif path == "/api/zh_names":
            self.serve_json("zh_names.json")
        elif path == "/api/sponsors":
            self.serve_json("sponsors.json")
        else:
            # Static files
            super().do_GET()

    def serve_json(self, filename):
        filepath = DATA_DIR / filename
        if filepath.exists():
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))
        else:
            self.send_error(404, f"File not found: {filename}")

    def serve_html(self, filename):
        filepath = Path(__file__).parent / filename
        if filepath.exists():
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(content.encode("utf-8"))
        else:
            self.send_error(404)

    def log_message(self, format, *args):
        print(f"  [{self.log_date_time_string()}] {args[0]}")

if __name__ == "__main__":
    print(f"""
╔══════════════════════════════════════════════════╗
║    2026 FIFA World Cup - Prediction Web App      ║
║    Server running at: http://localhost:{PORT}       ║
║    Press Ctrl+C to stop                          ║
╚══════════════════════════════════════════════════╝
""")
    with socketserver.TCPServer(("", PORT), APIHandler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n  Server stopped.")
