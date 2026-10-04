@echo off
rem Probelauf: laedt nur Statistik 12411 (max. 3 Tabellen) nach GENESIS_Export.
cd /d "%~dp0"
python -m pip install --quiet requests
python genesis_export.py --test
pause
