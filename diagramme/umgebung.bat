@echo off
rem Richtet die Python-Umgebung (.venv) ein und prueft bei jedem Aufruf, ob alle Pakete vorhanden sind.
rem Wird von den anderen .bat-Dateien aufgerufen.
cd /d "%~dp0"

if not exist .venv\Scripts\python.exe (
  python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" 2>nul
  if errorlevel 1 (
    echo Benoetigt wird Python 3.11 oder neuer ^(getestet mit 3.13^). Gefunden:
    python --version
    echo Python von https://www.python.org installieren und dabei "Add python.exe to PATH" anhaken.
    exit /b 1
  )
  echo Richte Python-Umgebung ein ...
  python -m venv .venv || exit /b 1
)

.venv\Scripts\python.exe -c "import numpy, pandas, yaml, vl_convert, requests" 2>nul
if errorlevel 1 (
  echo Installiere benoetigte Pakete ...
  .venv\Scripts\python.exe -m pip install --upgrade pip
  .venv\Scripts\python.exe -m pip install -r requirements.txt || exit /b 1
)
exit /b 0
