@echo off
chcp 65001 >nul 2>&1
set PYTHONIOENCODING=utf-8
cd /d "C:\Users\29746\Documents\world-cup-model"

echo ============================================
echo  World Cup 2026 - 8h Auto Refresh
echo  %date% %time%
echo ============================================

echo [1/4] News...
python news_feed.py 2>nul
echo.

echo [2/4] Betfair index...
python betfair_fetcher.py 2>nul
echo.

echo [3/4] Tournament sim (1000x)...
python tournament.py 1000 2>nul
echo.

echo [4/4] Merge website data...
python auto_refresh.py 2>nul
echo.

echo [5/5] Deploy to Vercel...
call vercel deploy --prod --yes 2>nul
echo.

echo ============================================
echo  DONE: %date% %time%
echo ============================================
