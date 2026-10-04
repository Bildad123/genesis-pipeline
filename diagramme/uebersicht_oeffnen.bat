@echo off
rem Erzeugt die Uebersicht (uebersicht.html) aus dem vorhandenen manifest.json neu und oeffnet sie.
cd /d "%~dp0"
if exist .venv\Scripts\python.exe (set PY=.venv\Scripts\python.exe) else (set PY=python)
%PY% uebersicht.py %*
