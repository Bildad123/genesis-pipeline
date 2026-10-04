@echo off
rem Startet die Diagramm-Pipeline (alle Stufen).
cd /d "%~dp0"
call umgebung.bat || goto fehler
.venv\Scripts\python.exe genesis_diagramme.py %*
pause
goto :eof
:fehler
echo.
echo Einrichtung fehlgeschlagen - bitte die Meldung oben pruefen.
pause
exit /b 1
