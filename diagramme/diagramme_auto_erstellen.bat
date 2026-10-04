@echo off
rem Startet die Diagramm-Pipeline (alle Stufen). Erster Start: richtet eine eigene Python-Umgebung ein.
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Richte Python-Umgebung ein ...
  python -m venv .venv || goto fehler
  .venv\Scripts\python.exe -m pip install --quiet --upgrade pip
  .venv\Scripts\python.exe -m pip install --quiet -r requirements.txt || goto fehler
  .venv\Scripts\python.exe -m pip freeze > requirements_lock.txt
)
.venv\Scripts\python.exe genesis_diagramme.py %*
pause
goto :eof
:fehler
echo Einrichtung fehlgeschlagen - bitte Meldung oben pruefen.
pause
