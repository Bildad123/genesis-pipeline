@echo off
rem Laedt alle GENESIS-Tabellen als Flatfile-CSV nach GENESIS_Export (mehrere Stunden, jederzeit fortsetzbar).
cd /d "%~dp0"
python -m pip install --quiet requests
python genesis_export.py %*
pause
