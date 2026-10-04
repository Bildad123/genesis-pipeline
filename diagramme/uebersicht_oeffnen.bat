@echo off
rem Erzeugt die Uebersicht (uebersicht.html) aus dem vorhandenen manifest.json neu und oeffnet sie.
cd /d "%~dp0"
call umgebung.bat || goto fehler
.venv\Scripts\python.exe uebersicht.py %*
goto :eof
:fehler
echo Einrichtung fehlgeschlagen - bitte die Meldung oben pruefen.
pause
exit /b 1
