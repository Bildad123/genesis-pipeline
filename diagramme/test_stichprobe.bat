@echo off
rem Testlauf: je Diagrammtyp nur 3 Diagramme (fuer die Entwicklung).
cd /d "%~dp0"
call diagramme_auto_erstellen.bat --stichprobe 3
