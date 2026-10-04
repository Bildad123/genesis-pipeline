"""Löscht alle von genesis_diagramme.py erzeugten Diagramme im Ergebnisordner (aus config.yaml).

Gelöscht werden: die Themenbereichsordner (1_… bis 9_…) mit PNG, Vega-Lite-Spezifikationen, Info-Dateien und
kopierten Quelltabellen sowie manifest.json, uebersicht.html, vorschau.html, config.yaml und die Ordner _bericht
und _zwischenspeicher. Nicht angetastet werden die Rohdaten (GENESIS_Export).

    python diagramme_loeschen.py          (fragt vorher nach)
    python diagramme_loeschen.py --ja     (ohne Rückfrage)
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

import yaml

HIER = Path(__file__).resolve().parent
DATEIEN = ("manifest.json", "uebersicht.html", "vorschau.html", "config.yaml")


def main():
    ap = argparse.ArgumentParser(description="Erzeugte Diagramme löschen")
    ap.add_argument("--config", default=str(HIER / "config.yaml"))
    ap.add_argument("--ja", action="store_true", help="ohne Rückfrage löschen")
    args = ap.parse_args()
    cfg_pfad = Path(args.config).resolve()
    cfg = yaml.safe_load(cfg_pfad.read_text(encoding="utf-8"))
    aus = (cfg_pfad.parent / cfg["pfade"]["ausgabe"]).resolve()
    export = (cfg_pfad.parent / cfg["pfade"]["export"]).resolve()

    if not aus.is_dir():
        print(f"Ergebnisordner {aus} existiert nicht – nichts zu löschen.")
        return
    if aus == export or aus in export.parents or aus == HIER or aus in HIER.parents:
        sys.exit(f"Abbruch: {aus} ist kein reiner Ergebnisordner.")

    ordner = [p for p in aus.iterdir() if p.is_dir() and p.name[:1].isdigit() and "_" in p.name]
    ordner += [aus / n for n in ("_bericht", "_zwischenspeicher") if (aus / n).is_dir()]
    dateien = [aus / n for n in DATEIEN if (aus / n).is_file()]
    pngs = sum(1 for o in ordner for _ in o.rglob("*.png"))
    if not ordner and not dateien:
        print(f"Keine erzeugten Diagramme in {aus}.")
        return

    print(f"Ergebnisordner: {aus}")
    print(f"  {pngs} PNG-Bilder in {len(ordner)} Ordnern, {len(dateien)} weitere Dateien")
    if not args.ja:
        try:
            antwort = input("Wirklich alles löschen? (j/n) ").strip().lower()
        except EOFError:
            antwort = ""
        if antwort not in ("j", "ja", "y", "yes"):
            print("Abgebrochen – nichts gelöscht.")
            return
    for o in ordner:
        shutil.rmtree(o)
    for f in dateien:
        f.unlink()
    print(f"Gelöscht: {pngs} PNG-Bilder und alle zugehörigen Dateien.")


if __name__ == "__main__":
    main()
