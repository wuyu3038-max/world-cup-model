@echo off
chcp 65001 >nul 2>&1
set PYTHONIOENCODING=utf-8
cd /d "C:\Users\29746\Documents\world-cup-model"

echo ============================================
echo  World Cup 2026 - Auto Refresh Pipeline
echo  %date% %time%
echo ============================================

echo [1/6] Live Scores (auto-fetch results)...
python live_score_fetcher.py
echo.

echo [2/6] Betfair Index (money flow)...
python betfair_fetcher.py
echo.

echo [3/6] Match Odds (regenerate 1X2 probs)...
python refresh_match_odds.py
echo.

echo [4/6] News Feed...
python news_feed.py
echo.

echo [5/6] Merge all_data.json...
python auto_refresh.py --merge-only
echo.

echo [6/6] Git Push -> Vercel Deploy...
git add -A
git commit -m "auto-refresh: %date% %time%" 2>nul
git push origin master
echo.

echo ============================================
echo  DONE: %date% %time%
echo  Website: https://world-cup-model.vercel.app
echo ============================================
pause
