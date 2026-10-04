@echo off
rem Schnelle Vorschau: rund 100 Diagramme, ausgewogen ueber alle Themenbereiche und Diagrammtypen.
cd /d "%~dp0"
call diagramme_auto_erstellen.bat --anzahl 100 --ausgabe ../GENESIS_Diagramme
