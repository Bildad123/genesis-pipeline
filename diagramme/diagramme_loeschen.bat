@echo off
rem Loescht alle erzeugten Diagramme (PNG, Spezifikationen, Berichte, Zwischenspeicher) im Ergebnisordner aus config.yaml.
rem Rohdaten (GENESIS_Export) bleiben unberuehrt. Vor dem Loeschen wird nachgefragt.
cd /d "%~dp0"
if exist .venv\Scripts\python.exe (set PY=.venv\Scripts\python.exe) else (set PY=python)
%PY% diagramme_loeschen.py %*
pause
