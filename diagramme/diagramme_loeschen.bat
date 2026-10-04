@echo off
rem Loescht alle erzeugten Diagramme (PNG, Spezifikationen, Berichte, Zwischenspeicher) im Ergebnisordner aus config.yaml.
rem Rohdaten (GENESIS_Export) bleiben unberuehrt. Vor dem Loeschen wird nachgefragt.
cd /d "%~dp0"
call umgebung.bat || goto fehler
.venv\Scripts\python.exe diagramme_loeschen.py %*
pause
goto :eof
:fehler
echo Einrichtung fehlgeschlagen - bitte die Meldung oben pruefen.
pause
exit /b 1
