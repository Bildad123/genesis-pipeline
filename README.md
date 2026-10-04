# GENESIS-Diagramme

Reproduzierbare Erzeugung von Datenvisualisierungen aus den Tabellen von
[GENESIS-Online](https://www-genesis.destatis.de), der Datenbank des Statistischen Bundesamtes (Destatis).

Die Pipeline wählt aus rund 2.900 amtlichen Tabellen ausgewogen über neun Themenbereiche und 36 Diagrammtypen aus,
baut daraus redaktionell gestaltete Grafiken mit datengebundenen Überschriften und dokumentiert jede Entscheidung.
Gleiche Daten und gleiche Konfiguration ergeben stets dieselben Grafiken.

## Merkmale

- **36 Diagrammtypen** von Balken und Linien über Treemaps und Boxplots bis zu Choroplethen- und Symbolkarten
- **Ausgewogene Auswahl** über Themenbereiche und Diagrammtypen mit iterativer proportionaler Anpassung
- **Datengebundene Überschriften**, deren Aussagen sich vollständig aus den Daten belegen lassen
- **Kontrollierte Farbgestaltung** mit sechs Farbthemen, sechs geprüften Paletten und Unabhängigkeitstest
- **Vollständige Nachvollziehbarkeit** durch Berichte zu jeder Stufe und ein Manifest mit Prüfsummen

## Projektstruktur

```
├── export/                Abruf der Rohdaten über die GENESIS-Schnittstelle
├── GENESIS_Export/        Rohdaten: Flatfile-CSV, Metadaten und Herkunftsnachweis je Tabelle
├── diagramme/             Pipeline, Konfiguration und Methodendokumentation
└── GENESIS_Diagramme/     Ergebnisse eines Laufs (wird erzeugt)
```

## Voraussetzungen

- Windows
- **Python 3.13** von [python.org](https://www.python.org/downloads/) (mindestens Python 3.11; ältere Versionen wie
  3.10 werden von den verwendeten Paketen nicht unterstützt)
- für einen neuen Export der Rohdaten zusätzlich ein kostenloses Konto bei GENESIS-Online

Die installierte Version lässt sich in der Eingabeaufforderung prüfen:

```bat
python --version
```

## Schnellstart

1. Python 3.13 installieren (siehe oben).
2. Repository klonen:
   ```bat
   git clone <URL dieses Repositorys>
   ```
3. In den Ordner `diagramme` wechseln und die Pakete installieren:
   ```bat
   cd diagramme
   pip install -r requirements.txt
   ```
4. `test_stichprobe.bat` per Doppelklick starten. Es entsteht eine Vorschau mit rund 100 Diagrammen in
   `GENESIS_Diagramme/`, die sich anschließend per Doppelklick auf `uebersicht.html` durchsehen lässt.

Weitere Startdateien im Ordner `diagramme/`:

| Datei | Wirkung |
|---|---|
| `test_stichprobe.bat` | schnelle Vorschau mit rund 100 Diagrammen |
| `diagramme_auto_erstellen.bat` | vollständiger Lauf mit der Zielanzahl aus `config.yaml` |
| `uebersicht_oeffnen.bat` | Übersichtsseite der erzeugten Grafiken öffnen |
| `uebersicht.html` | dieselbe Übersichtsseite per Doppelklick direkt im Browser öffnen |
| `diagramme_loeschen.bat` | alle erzeugten Grafiken und Berichte löschen |

Ohne Windows lässt sich die Pipeline direkt aufrufen:

```bash
cd diagramme
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python genesis_diagramme.py --anzahl 100 --ausgabe ../GENESIS_Diagramme
```

## Rohdaten

`GENESIS_Export/` enthält den Export vom 28.09.2026 mit 2.907 Tabellen. Nicht enthalten sind die Tabellen 12421-0002
und 12421-0004, die mit über 100 MB die Dateigrenze von GitHub überschreiten; die Pipeline schließt Tabellen über 50 MB
ohnehin aus.

Ein neuer Export ist nur zur Aktualisierung nötig:

1. `export/genesis_zugang.example.ini` nach `export/genesis_zugang.ini` kopieren und die Zugangsdaten eintragen.
2. `export/export_test.bat` starten, um den Zugang mit drei Tabellen zu prüfen.
3. `export/export_starten.bat` starten, um alle Tabellen zu laden.

Der vollständige Export dauert mehrere Stunden und lässt sich jederzeit abbrechen und fortsetzen.

## Konfiguration

Alle Parameter des Verfahrens stehen in `diagramme/config.yaml`, darunter Zielanzahl, Startwert, Ausschlusskriterien
und Obergrenzen je Tabelle und Statistik. Zielanzahl, Startwert und Ergebnisordner lassen sich auch beim Aufruf
festlegen (`--anzahl`, `--seed`, `--ausgabe`).

## Ergebnisse

Ein Lauf schreibt nach `GENESIS_Diagramme/`:

| Inhalt | Beschreibung |
|---|---|
| `<Themenbereich>/<Statistik>/<Tabelle>/` | je Grafik PNG, Vega-Lite-Spezifikation und Protokoll der Entscheidungen, dazu eine Kopie der Quelldaten |
| `manifest.json` | alle Grafiken mit Eigenschaften, Prüfsummen und Versionen |
| `uebersicht.html` | Übersicht mit Filter und Suche |
| `_bericht/` | Zwischenergebnisse aller Stufen und Zusammenfassung (`bericht.md`) |

## Dokumentation

Das Verfahren mit allen Regeln, Begründungen und Quellen beschreibt
[`diagramme/METHODE.md`](diagramme/METHODE.md).

## Datenquellen und Lizenzen

- Statistische Daten: © Statistisches Bundesamt (Destatis), GENESIS-Online,
  [Datenlizenz Deutschland – Namensnennung – Version 2.0](https://www.govdata.de/dl-de/by-2-0)
- Verwaltungsgrenzen (`diagramme/geo/`): © GeoBasis-DE / BKG, VG5000,
  [Datenlizenz Deutschland – Namensnennung – Version 2.0](https://www.govdata.de/dl-de/by-2-0)
