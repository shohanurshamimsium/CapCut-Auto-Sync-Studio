@echo off
title CapCut Sync Studio Bulletproof
echo ========================================================
echo   Starting CapCut Sync Studio...
echo ========================================================
python -m pip install -r requirements.txt >nul 2>&1
start http://localhost:8765
python app.py
pause
