#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
genesis_export.py – Vollständiger Export aller GENESIS-Online-Tabellen (Destatis)
als Flatfile-CSV (ffcsv) inklusive Metadaten, Hierarchie und Nachverfolgbarkeit.

Grundlage: GENESIS-Anwenderdokumentation „Webservice/API“, Version 5.1 (01.06.2026)
  - catalogue/statistics, catalogue/tables2statistic, catalogue/tables
  - metadata/statistic, metadata/table, metadata/variable
  - data/tablefile (format=ffcsv), data/resultfile (für Batch-Aufträge)
  - profile/removeResult, helloworld/logincheck

Ablagestruktur (Beispiel):
  GENESIS_Export/
    _katalog/            status.sqlite, tabellen.csv, statistiken.csv, merkmale.csv
    _metadaten/merkmale/ <Merkmal>.json
    _log/                export.log
    1_Gebiet, Bevölkerung, Arbeitsmarkt, Wahlen/
      12411_Fortschreibung des Bevölkerungsstandes/
        _statistik_12411.json
        12411-0001_Bevölkerung Deutschland, Stichtag/
          12411-0001_flatfile.csv        <- Daten (ffcsv, unverändert)
          12411-0001_metadaten.json      <- metadata/table (vollständig)
          12411-0001_herkunft.json       <- Nachweis: Quelle, Parameter, Zeitpunkt, SHA-256

Zugangsdaten (niemals in den Code schreiben!) über Umgebungsvariablen:
  GENESIS_TOKEN                     (persönlicher API-Token, 32 Zeichen)  und/oder
  GENESIS_USER + GENESIS_PASSWORD   (nötig für Batch-Aufträge job=true bei sehr großen Tabellen)
Fehlen sie, wird beim Start danach gefragt.

Aufruf-Beispiele:
  python genesis_export.py --test                     # Probelauf: nur Statistik 12411, max. 3 Tabellen
  python genesis_export.py                            # alles
  python genesis_export.py --auswahl "12*"            # nur Statistiken, deren Code mit 12 beginnt
  python genesis_export.py --aktualisieren            # geänderte Tabellen erneut laden
  python genesis_export.py --nur-katalog              # nur Verzeichnis aller Tabellen erstellen

Der Export ist jederzeit abbrech- und fortsetzbar (Strg+C, dann einfach erneut starten).
Benötigt: Python 3.9+, Paket „requests“  (pip install requests)
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import getpass
import hashlib
import io
import json
import logging
import math
import os
import re
import sqlite3
import sys
import time
import zipfile
from pathlib import Path

try:
    import requests
except ImportError:  # pragma: no cover
    sys.exit("Bitte zuerst installieren:  pip install requests")

BASIS_URL = os.environ.get("GENESIS_BASE_URL", "https://genesis.destatis.de/genesisWS/rest/2020/")
SPRACHE = "de"
BEREICH = "all"
MAX_SEITE = 25000  # pagelength-Maximum laut Doku

# Themenbereiche nach erster Ziffer des Statistik-Codes (anpassbar)
THEMENBEREICHE = {
    "1": "Gebiet, Bevölkerung, Arbeitsmarkt, Wahlen",
    "2": "Bildung, Sozialleistungen, Gesundheit, Recht",
    "3": "Wohnen, Umwelt",
    "4": "Wirtschaftsbereiche",
    "5": "Außenhandel, Unternehmen, Handwerk",
    "6": "Preise, Verdienste, Einkommen und Verbrauch",
    "7": "Öffentliche Finanzen, Steuern, Personal",
    "8": "Gesamtrechnungen",
    "9": "Querschnittsthemen",
}

LIZENZ = "Datenlizenz Deutschland – Namensnennung – Version 2.0; Quelle: Statistisches Bundesamt (Destatis), GENESIS-Online"
JOBNAME_RE = re.compile(r"([0-9A-Za-z][0-9A-Za-z\-]*_\d{3,})")

log = logging.getLogger("genesis")


# --------------------------------------------------------------------------------------
# Hilfsfunktionen
# --------------------------------------------------------------------------------------
def jetzt() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def sicherer_name(text: str, maxlen: int = 60) -> str:
    """Ordner-/Dateiname: Umlaute bleiben, verbotene Zeichen (Windows) werden ersetzt."""
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", text or "")
    text = re.sub(r"\s+", " ", text).strip().rstrip(".")
    if len(text) > maxlen:
        text = text[:maxlen].rstrip(" ,.;-")
    return text or "ohne Titel"


def sha256(pfad: Path) -> str:
    h = hashlib.sha256()
    with open(pfad, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def json_schreiben(pfad: Path, obj) -> None:
    pfad.parent.mkdir(parents=True, exist_ok=True)
    tmp = pfad.with_suffix(pfad.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, pfad)


def merkmale_sammeln(struktur, gefunden: set) -> None:
    """Alle Merkmal-Codes rekursiv aus metadata/table → Object.Structure einsammeln."""
    if isinstance(struktur, dict):
        if struktur.get("Type") == "Merkmal" and struktur.get("Code"):
            gefunden.add(struktur["Code"])
        for v in struktur.values():
            merkmale_sammeln(v, gefunden)
    elif isinstance(struktur, list):
        for v in struktur:
            merkmale_sammeln(v, gefunden)


class GenesisFehler(Exception):
    def __init__(self, code, text):
        text = " ".join((text or "").split())
        super().__init__(f"GENESIS-Status {code}: {text}")
        self.code = code
        self.text = text


# --------------------------------------------------------------------------------------
# API-Client
# --------------------------------------------------------------------------------------
class Genesis:
    def __init__(self, token: str | None, user: str | None, passwort: str | None, pause: float):
        self.token, self.user, self.passwort = token, user, passwort
        self.pause = pause
        self.s = requests.Session()
        self.s.headers.update({"Content-Type": "application/x-www-form-urlencoded",
                               "User-Agent": "genesis_export.py (Datenexport, sequentiell)"})
        self._letzte = 0.0

    @property
    def jobs_moeglich(self) -> bool:
        return bool(self.user and self.passwort)

    def _kopf(self, mit_passwort: bool) -> dict:
        if mit_passwort and self.jobs_moeglich:
            return {"username": self.user, "password": self.passwort}
        if self.token:
            return {"username": self.token, "password": ""}
        return {"username": self.user or "", "password": self.passwort or ""}

    def _warten(self):
        d = time.monotonic() - self._letzte
        if d < self.pause:
            time.sleep(self.pause - d)
        self._letzte = time.monotonic()

    def post(self, methode: str, daten: dict, datei: bool = False, mit_passwort: bool = False,
             timeout: int = 180, versuche: int = 6):
        """POST an die API. Gibt dict (JSON) oder bytes (Datei) zurück.
        Wiederholt bei Netzwerk-/Serverfehlern mit exponentiellem Backoff."""
        daten = {"language": SPRACHE, **daten}
        url = BASIS_URL + methode
        for versuch in range(1, versuche + 1):
            self._warten()
            try:
                r = self.s.post(url, headers=self._kopf(mit_passwort), data=daten, timeout=timeout)
            except requests.RequestException as e:
                warte = min(600, 15 * 2 ** (versuch - 1))
                log.warning("Netzwerkfehler bei %s (%s) – neuer Versuch in %ss", methode, e, warte)
                time.sleep(warte)
                continue
            if r.status_code in (429, 500, 502, 503, 504):
                warte = min(600, 30 * 2 ** (versuch - 1))
                log.warning("HTTP %s bei %s – neuer Versuch in %ss", r.status_code, methode, warte)
                if r.status_code == 429:
                    self.aufraeumen()
                time.sleep(warte)
                continue
            if r.status_code in (401, 403):
                raise SystemExit(f"Anmeldung abgelehnt (HTTP {r.status_code}). Zugangsdaten prüfen.")
            r.raise_for_status()

            inhalt = r.content
            ist_json = "json" in r.headers.get("Content-Type", "") or inhalt[:1] in (b"{", b"[")
            if datei and not ist_json:
                return inhalt
            try:
                antwort = r.json()
            except ValueError:
                if datei:
                    return inhalt
                raise GenesisFehler(-1, f"Unerwartete Antwort: {inhalt[:200]!r}")

            status = antwort.get("Status") if isinstance(antwort, dict) else None
            if isinstance(status, dict):
                code = status.get("Code")
                text = status.get("Content") or ""
                if code not in (0, 22, None):
                    # zu viele parallele Anfragen → logincheck beendet hängende Requests
                    if re.search(r"parallel|zu viele|too many", text, re.I):
                        log.warning("Parallel-Limit erreicht – räume auf und warte 60s")
                        self.aufraeumen()
                        time.sleep(60)
                        continue
                    raise GenesisFehler(code, text)
            return antwort
        raise GenesisFehler(-2, f"{methode}: nach {versuche} Versuchen aufgegeben")

    def aufraeumen(self):
        try:
            self.s.post(BASIS_URL + "helloworld/logincheck", headers=self._kopf(False),
                        data={"language": SPRACHE}, timeout=60)
        except requests.RequestException:
            pass

    def liste(self, methode: str, timeout: int = 180, versuche: int = 6, **filter_) -> list:
        """Katalog-Liste; bei Erreichen des Seitenlimits wird nach Präfix aufgeteilt."""
        auswahl = filter_.pop("selection", "*")
        try:
            a = self.post(methode, {"selection": auswahl, "area": BEREICH,
                                    "pagelength": MAX_SEITE, **filter_},
                          timeout=timeout, versuche=versuche)
        except GenesisFehler as e:
            if e.code == 104:  # keine Objekte
                return []
            raise
        eintraege = a.get("List") or []
        if len(eintraege) >= MAX_SEITE and auswahl.endswith("*") and len(auswahl) < 15:
            log.info("Liste %s/%s erreicht Limit – teile auf", methode, auswahl)
            ergebnis, basis = [], auswahl[:-1]
            for z in "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ":
                ergebnis += self.liste(methode, timeout, versuche, selection=f"{basis}{z}*", **filter_)
            return ergebnis
        return eintraege


# --------------------------------------------------------------------------------------
# Status-Datenbank (Fortsetzbarkeit + Nachverfolgbarkeit)
# --------------------------------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS statistiken(
  code TEXT PRIMARY KEY, name TEXT, themenbereich TEXT, pfad TEXT,
  aktualisiert_genesis TEXT, metadaten_geladen TEXT);
CREATE TABLE IF NOT EXISTS tabellen(
  code TEXT PRIMARY KEY, name TEXT, zeitraum TEXT, statistik TEXT, alle_statistiken TEXT,
  pfad TEXT, status TEXT DEFAULT 'offen', stand_genesis TEXT, heruntergeladen_am TEXT,
  dateien TEXT, bytes INTEGER, sha256 TEXT, job_name TEXT, job_seit TEXT, meldung TEXT);
CREATE TABLE IF NOT EXISTS merkmale(
  code TEXT PRIMARY KEY, name TEXT, geladen_am TEXT);
CREATE TABLE IF NOT EXISTS lauf(schluessel TEXT PRIMARY KEY, wert TEXT);
"""


class Export:
    def __init__(self, api: Genesis, ziel: Path, args):
        self.api, self.ziel, self.args = api, ziel, args
        (ziel / "_katalog").mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(ziel / "_katalog" / "status.sqlite")
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        spalten = {z[1] for z in self.db.execute("PRAGMA table_info(tabellen)")}
        for sp in ("teil_von", "startjahr", "endjahr"):  # Teilabrufe sehr großer Tabellen
            if sp not in spalten:
                self.db.execute(f"ALTER TABLE tabellen ADD COLUMN {sp} TEXT")
        self.db.commit()
        self.merkmal_codes: set = set()

    # ---------- 1. Katalog ----------
    def katalog(self):
        schon = self.db.execute("SELECT wert FROM lauf WHERE schluessel='katalog'").fetchone()
        umfang = self.db.execute("SELECT wert FROM lauf WHERE schluessel='katalog_auswahl'").fetchone()
        gleich = umfang and umfang[0] == f"{self.args.auswahl}|{int(self.args.test)}"
        if schon and gleich and not self.args.katalog_neu:
            log.info("Katalog vom %s wird wiederverwendet (--katalog-neu zum Erneuern)", schon[0])
            return
        log.info("Lade Liste der Statistiken (Auswahl %s) …", self.args.auswahl)
        stats = self.api.liste("catalogue/statistics", selection=self.args.auswahl)
        log.info("%d Statistiken gefunden", len(stats))

        for i, st in enumerate(stats, 1):
            code, name = st.get("Code"), " ".join((st.get("Content") or "").split())
            if not self.args.katalog_neu and self.db.execute(
                    "SELECT 1 FROM tabellen WHERE statistik=? LIMIT 1", (code,)).fetchone():
                continue  # bereits im Katalog (Fortsetzung nach Abbruch)
            tb_key = code[:1]
            tb = f"{tb_key}_{THEMENBEREICHE.get(tb_key, 'Sonstige')}"
            pfad = Path(sicherer_name(tb, 80)) / sicherer_name(f"{code}_{name}")
            self.db.execute(
                "INSERT INTO statistiken(code,name,themenbereich,pfad) VALUES(?,?,?,?) "
                "ON CONFLICT(code) DO UPDATE SET name=excluded.name, themenbereich=excluded.themenbereich",
                (code, name, tb, str(pfad)))
            tabs = self.api.liste("catalogue/tables2statistic", name=code, selection="*")
            for t in tabs:
                self._tabelle_eintragen(t, code, pfad)
            self.db.commit()
            log.info("[%d/%d] Statistik %s: %d Tabellen", i, len(stats), code, len(tabs))
            if self.args.test and i >= 1:
                break

        # Tabellen, die keiner Statistik zugeordnet sind (Absicherung)
        if not self.args.test:
            alle = []
            basis = self.args.auswahl.rstrip("*")
            praefixe = [f"{basis}{z}*" for z in "0123456789"] if len(basis) < 2 else [self.args.auswahl]
            for pr in praefixe:
                try:
                    teil = self.api.liste("catalogue/tables", timeout=600, versuche=2, selection=pr)
                    alle += teil
                    log.info("Absicherung catalogue/tables %s: %d Tabellen", pr, len(teil))
                except GenesisFehler as e:
                    log.warning("Absicherung catalogue/tables %s übersprungen: %s", pr, e)
            neu = 0
            for t in alle:
                if not self.db.execute("SELECT 1 FROM tabellen WHERE code=?", (t["Code"],)).fetchone():
                    stat = t["Code"].split("-")[0]
                    row = self.db.execute("SELECT pfad FROM statistiken WHERE code=?", (stat,)).fetchone()
                    pfad = Path(row["pfad"]) if row else Path("_ohne_Statistik")
                    self._tabelle_eintragen(t, stat if row else "", pfad)
                    neu += 1
            self.db.commit()
            log.info("catalogue/tables: %d Tabellen insgesamt, %d zusätzlich ohne Statistik-Zuordnung",
                     len(alle), neu)

        self.db.execute("INSERT OR REPLACE INTO lauf VALUES('katalog',?)", (jetzt(),))
        self.db.execute("INSERT OR REPLACE INTO lauf VALUES('katalog_auswahl',?)",
                        (f"{self.args.auswahl}|{int(self.args.test)}",))
        self.db.commit()

    def _tabelle_eintragen(self, t: dict, stat_code: str, stat_pfad: Path):
        code, name = t.get("Code"), " ".join((t.get("Content") or "").split())
        vorhanden = self.db.execute("SELECT alle_statistiken FROM tabellen WHERE code=?", (code,)).fetchone()
        if vorhanden:  # Tabelle hängt an mehreren Statistiken → nur Verweis ergänzen
            liste = set(filter(None, (vorhanden[0] or "").split(";"))) | {stat_code}
            self.db.execute("UPDATE tabellen SET alle_statistiken=? WHERE code=?",
                            (";".join(sorted(liste)), code))
            return
        pfad = stat_pfad / sicherer_name(f"{code}_{name}")
        self.db.execute(
            "INSERT INTO tabellen(code,name,zeitraum,statistik,alle_statistiken,pfad) VALUES(?,?,?,?,?,?)",
            (code, name, t.get("Time") or "", stat_code, stat_code, str(pfad)))

    # ---------- 2. Statistik-Metadaten ----------
    def statistik_metadaten(self):
        zeilen = self.db.execute("SELECT * FROM statistiken WHERE metadaten_geladen IS NULL "
                                 "OR ?", (1 if self.args.aktualisieren else 0,)).fetchall()
        for st in zeilen:
            try:
                m = self.api.post("metadata/statistic", {"name": st["code"], "area": BEREICH})
            except GenesisFehler as e:
                log.warning("Metadaten Statistik %s: %s", st["code"], e)
                continue
            obj = m.get("Object") or {}
            json_schreiben(self.ziel / st["pfad"] / f"_statistik_{st['code']}.json",
                           {"abgerufen_am": jetzt(), "quelle": BASIS_URL + "metadata/statistic",
                            "lizenz": LIZENZ, "metadaten": obj})
            self.db.execute("UPDATE statistiken SET aktualisiert_genesis=?, metadaten_geladen=? WHERE code=?",
                            (obj.get("Updated"), jetzt(), st["code"]))
            self.db.commit()

    # ---------- 3. Tabellen ----------
    def tabellen(self):
        for runde in range(1, 8):
            if runde > 1:  # nur neu entstandene Teilabschnitte
                sql = "SELECT * FROM tabellen WHERE status='offen' ORDER BY code"
            elif self.args.aktualisieren:
                sql = ("SELECT * FROM tabellen WHERE status NOT IN ('job_wartet','geteilt','zusammengefuehrt') "
                       "AND teil_von IS NULL ORDER BY code")
            else:
                sql = "SELECT * FROM tabellen WHERE status IN ('offen','fehler') ORDER BY code"
            zeilen = self.db.execute(sql).fetchall()
            if self.args.max_tabellen:
                zeilen = zeilen[: self.args.max_tabellen]
            if not zeilen:
                break
            gesamt, start = len(zeilen), time.monotonic()
            log.info("%d Tabellen zu bearbeiten%s", gesamt, f" (Runde {runde}: Teilabschnitte)" if runde > 1 else "")

            for i, t in enumerate(zeilen, 1):
                try:
                    self._eine_tabelle(t)
                except GenesisFehler as e:
                    if e.code == 2 or "maximal erlaubte Anzahl" in e.text:
                        log.warning("Ergebnis-Limit im GENESIS-Konto erreicht – hole zuerst die Batch-Aufträge ab")
                        self.jobs_abholen()
                        try:
                            self._eine_tabelle(t)
                        except GenesisFehler as e2:
                            self._fehler(t, e2)
                    else:
                        self._fehler(t, e)
                self.db.commit()
                if i % 10 == 0 or i == gesamt:
                    rest = (time.monotonic() - start) / i * (gesamt - i)
                    log.info("Fortschritt %d/%d – geschätzte Restzeit %s", i, gesamt,
                             dt.timedelta(seconds=int(rest)))
            if self.args.max_tabellen:
                break
        self.zusammenfuehren()

    def _fehler(self, t, e):
        self.db.execute("UPDATE tabellen SET status='fehler', meldung=? WHERE code=?", (str(e), t["code"]))
        log.error("%s: %s", t["code"], e)

    def _teilen(self, t, e: "GenesisFehler", obj, stand) -> bool:
        """Zu große Tabelle (>~2,5 Mio. Werte) in Jahresabschnitte aufteilen (startyear/endyear)."""
        m = re.search(r"(\d{4,})\s*Werte", e.text)
        werte = int(m.group(1)) if m else 0
        if t["teil_von"]:
            wurzel, a, b = t["teil_von"], int(t["startjahr"]), int(t["endjahr"])
        else:
            quelle = json.dumps((obj or {}).get("Time"), ensure_ascii=False) + " " + (t["zeitraum"] or "")
            jahre = [int(j) for j in re.findall(r"(?<!\d)(1[89]\d\d|20\d\d)(?!\d)", quelle)]
            if not jahre:
                return False
            wurzel, a, b = t["code"], min(jahre), max(jahre)
        spanne = b - a + 1
        if spanne < 2:
            return False
        anzahl = min(spanne, max(2, math.ceil(werte / 1_000_000))) if werte else 2
        schritt = math.ceil(spanne / anzahl)
        n = 0
        for s_ in range(a, b + 1, schritt):
            e_ = min(b, s_ + schritt - 1)
            self.db.execute(
                "INSERT OR IGNORE INTO tabellen(code,name,zeitraum,statistik,alle_statistiken,pfad,status,"
                "stand_genesis,teil_von,startjahr,endjahr) VALUES(?,?,?,?,?,?,'offen',?,?,?,?)",
                (f"{wurzel}__{s_}-{e_}", t["name"], f"{s_}-{e_}", t["statistik"], t["alle_statistiken"],
                 t["pfad"], stand, wurzel, str(s_), str(e_)))
            n += 1
        self.db.execute("UPDATE tabellen SET status='geteilt', stand_genesis=COALESCE(?,stand_genesis), "
                        "meldung=? WHERE code=?", (stand, f"{e.text} → {n} Zeitabschnitte", t["code"]))
        log.info("%s: %s Werte – zu groß, wird in %d Zeitabschnitte %d–%d geteilt",
                 t["code"], werte or "?", n, a, b)
        return True

    def zusammenfuehren(self):
        """Teilabschnitte einer Tabelle zu einer Flatfile-CSV zusammenfügen (Kopfzeile nur einmal)."""
        for p in self.db.execute("SELECT * FROM tabellen WHERE status='geteilt' AND teil_von IS NULL").fetchall():
            teile = self.db.execute("SELECT * FROM tabellen WHERE teil_von=?", (p["code"],)).fetchall()
            if not teile or any(r["status"] in ("offen", "fehler", "job_wartet", "zu_gross") for r in teile):
                continue
            ok = sorted((r for r in teile if r["status"] == "ok"), key=lambda r: int(r["startjahr"]))
            if not ok:
                continue
            ordner = self.ziel / p["pfad"]
            ziel = ordner / f"{p['code']}_flatfile.csv"
            erste, quellen = True, []
            with open(ziel, "wb") as aus:
                for r in ok:
                    for dn in filter(None, (r["dateien"] or "").split(";")):
                        daten = (ordner / dn).read_bytes()
                        if not erste:
                            daten = daten.split(b"\n", 1)[1] if b"\n" in daten else b""
                        if daten and not daten.endswith(b"\n"):
                            daten += b"\n"
                        aus.write(daten)
                        erste = False
                        quellen.append((ordner / dn, r))
            for f, _ in quellen:
                try:
                    f.unlink()
                except OSError:
                    pass
            pruef = sha256(ziel)
            groesse = ziel.stat().st_size
            json_schreiben(ordner / f"{p['code']}_herkunft.json", {
                "tabelle": p["code"], "titel": p["name"], "zeitraum": p["zeitraum"],
                "statistik": p["statistik"], "alle_statistiken": (p["alle_statistiken"] or "").split(";"),
                "stand_genesis": p["stand_genesis"], "abgerufen_am": jetzt(),
                "quelle": BASIS_URL + "data/tablefile",
                "hinweis": "Tabelle war zu groß für einen Abruf; in Zeitabschnitten (startyear/endyear) "
                           "geladen und zusammengefügt. Kopfzeile nur einmal.",
                "teilabrufe": [{"abschnitt": r["zeitraum"], "startyear": r["startjahr"], "endyear": r["endjahr"],
                                "batch_auftrag": r["job_name"], "sha256_teil": r["sha256"],
                                "abgerufen_am": r["heruntergeladen_am"]} for r in ok],
                "format": "ffcsv (Flatfile-CSV)", "dateien": {ziel.name: pruef}, "bytes": groesse,
                "lizenz": LIZENZ,
                "weboberflaeche": f"https://www-genesis.destatis.de/datenbank/online/statistic/"
                                  f"{p['statistik']}/table/{p['code']}",
            })
            self.db.execute("UPDATE tabellen SET status='zusammengefuehrt' WHERE teil_von=? AND status='ok'",
                            (p["code"],))
            self.db.execute("UPDATE tabellen SET status='ok', heruntergeladen_am=?, dateien=?, bytes=?, sha256=?, "
                            "meldung=? WHERE code=?", (jetzt(), ziel.name, groesse, pruef,
                            f"aus {len(ok)} Zeitabschnitten zusammengefügt", p["code"]))
            self.db.commit()
            log.info("OK %s  (aus %d Zeitabschnitten zusammengefügt, %.1f KB)", p["code"], len(ok), groesse / 1024)

    def _eine_tabelle(self, t: sqlite3.Row):
        code, ordner = t["code"], self.ziel / t["pfad"]
        teil = t["teil_von"]
        obj = None
        if teil:  # Teilabschnitt: Metadaten liegen bereits bei der Gesamttabelle
            stand = t["stand_genesis"]
        else:
            m = self.api.post("metadata/table", {"name": code, "area": BEREICH})
            obj = m.get("Object") or {}
            stand = obj.get("Updated")
            merkmale_sammeln(obj.get("Structure"), self.merkmal_codes)

            if t["status"] == "ok" and stand and stand == t["stand_genesis"]:
                return  # unverändert (nur bei --aktualisieren relevant)

            json_schreiben(ordner / f"{code}_metadaten.json",
                           {"abgerufen_am": jetzt(), "quelle": BASIS_URL + "metadata/table",
                            "lizenz": LIZENZ, "metadaten": obj})

        parameter = {"name": teil or code, "area": BEREICH, "format": "ffcsv", "compress": "false",
                     "transpose": "false"}
        if teil:
            parameter.update(startyear=t["startjahr"], endyear=t["endjahr"])
        if self.api.jobs_moeglich:
            parameter["job"] = "true"
        try:
            inhalt = self.api.post("data/tablefile", parameter, datei=True,
                                   mit_passwort=self.api.jobs_moeglich, timeout=900)
        except GenesisFehler as e:
            if e.code == 18054 or "weder im Dialog" in e.text:
                if not self._teilen(t, e, obj, stand):
                    self.db.execute("UPDATE tabellen SET status='zu_gross', meldung=? WHERE code=?",
                                    (e.text + " (nicht weiter teilbar)", code))
                    log.warning("%s: zu groß und nicht weiter nach Jahren teilbar", code)
                return
            job = JOBNAME_RE.search(e.text) if e.code in (98, 99) or "Auftrag" in e.text else None
            if job and self.api.jobs_moeglich:
                self.db.execute("UPDATE tabellen SET status='job_wartet', job_name=?, job_seit=?, "
                                "stand_genesis=?, meldung=? WHERE code=?",
                                (job.group(1), jetzt(), stand, e.text, code))
                log.info("%s: zu groß für Sofortabruf → Batch-Auftrag %s", code, job.group(1))
                return
            if e.code == 98 and not self.api.jobs_moeglich:
                self.db.execute("UPDATE tabellen SET status='zu_gross', meldung=? WHERE code=?",
                                (e.text + " (Batch-Auftrag braucht Kennung+Passwort)", code))
                log.warning("%s: zu groß – Batch-Aufträge benötigen GENESIS_USER/GENESIS_PASSWORD", code)
                return
            raise
        if isinstance(inhalt, dict):
            raise GenesisFehler(-3, f"Keine Datei erhalten: {str(inhalt)[:200]}")
        self._speichern(t, ordner, inhalt, stand, BASIS_URL + "data/tablefile", parameter)

    def _speichern(self, t, ordner: Path, inhalt: bytes, stand, quelle, parameter, job=None):
        code = t["code"]
        teil = t["teil_von"]
        basis = f"{teil}_teil_{t['startjahr']}-{t['endjahr']}" if teil else f"{code}_flatfile"
        ordner.mkdir(parents=True, exist_ok=True)
        dateien = []
        if inhalt[:2] == b"PK":  # ZIP (Standard laut Doku)
            with zipfile.ZipFile(io.BytesIO(inhalt)) as z:
                namen = [n for n in z.namelist() if not n.endswith("/")]
                for n in namen:
                    ziel = (ordner / f"{basis}.csv") if len(namen) == 1 else \
                           (ordner / f"{basis}_{sicherer_name(Path(n).name, 80)}")
                    ziel.write_bytes(z.read(n))
                    dateien.append(ziel)
        else:
            ziel = ordner / f"{basis}.csv"
            ziel.write_bytes(inhalt)
            dateien.append(ziel)

        pruef = {d.name: sha256(d) for d in dateien}
        groesse = sum(d.stat().st_size for d in dateien)
        if not teil:
          json_schreiben(ordner / f"{code}_herkunft.json", {
            "tabelle": code, "titel": t["name"], "zeitraum": t["zeitraum"],
            "statistik": t["statistik"], "alle_statistiken": (t["alle_statistiken"] or "").split(";"),
            "stand_genesis": stand, "abgerufen_am": jetzt(), "quelle": quelle,
            "parameter": parameter, "batch_auftrag": job, "format": "ffcsv (Flatfile-CSV)",
            "dateien": pruef, "bytes": groesse, "lizenz": LIZENZ,
            "weboberflaeche": f"https://www-genesis.destatis.de/datenbank/online/statistic/"
                              f"{t['statistik']}/table/{code}",
        })
        self.db.execute(
            "UPDATE tabellen SET status='ok', stand_genesis=?, heruntergeladen_am=?, dateien=?, bytes=?, "
            "sha256=?, meldung=NULL, job_name=COALESCE(?, job_name) WHERE code=?",
            (stand, jetzt(), ";".join(pruef), groesse, ";".join(pruef.values()), job, code))
        log.info("OK %s  (%s, %.1f KB)", code, t["name"][:70], groesse / 1024)

    # ---------- 4. Batch-Aufträge abholen ----------
    def jobs_abholen(self):
        offen = self.db.execute("SELECT * FROM tabellen WHERE status='job_wartet'").fetchall()
        if not offen:
            return
        log.info("%d Batch-Aufträge warten – frage alle %ss ab (max. %s min)",
                 len(offen), self.args.job_intervall, self.args.job_max_minuten)
        ende = time.monotonic() + self.args.job_max_minuten * 60
        while offen and time.monotonic() < ende:
            for t in offen:
                parameter = {"name": t["job_name"], "area": BEREICH, "format": "ffcsv",
                             "compress": "false"}
                try:
                    inhalt = self.api.post("data/resultfile", parameter, datei=True,
                                           mit_passwort=True, timeout=1800)
                except GenesisFehler as e:
                    log.debug("Auftrag %s noch nicht fertig (%s)", t["job_name"], e)
                    continue
                if isinstance(inhalt, dict):
                    continue
                self._speichern(t, self.ziel / t["pfad"], inhalt, t["stand_genesis"],
                                BASIS_URL + "data/resultfile", parameter, job=t["job_name"])
                self.db.commit()
                try:  # Ergebnis im eigenen Konto löschen (Speicherplatz)
                    self.api.post("profile/removeResult", {"name": t["job_name"], "area": "Meine"},
                                  mit_passwort=True)
                except GenesisFehler as e:
                    log.debug("removeResult %s: %s", t["job_name"], e)
            offen = self.db.execute("SELECT * FROM tabellen WHERE status='job_wartet'").fetchall()
            if offen:
                log.info("%d Aufträge noch in Bearbeitung – warte %ss", len(offen), self.args.job_intervall)
                time.sleep(self.args.job_intervall)
        if offen:
            log.warning("%d Aufträge noch offen – beim nächsten Start wird erneut abgefragt", len(offen))

    # ---------- 5. Merkmal-Metadaten ----------
    def merkmale(self):
        ordner = self.ziel / "_metadaten" / "merkmale"
        # Merkmale aus allen bisher gespeicherten Tabellen-Metadaten (auch früherer Läufe)
        for datei in self.ziel.rglob("*_metadaten.json"):
            try:
                merkmale_sammeln(json.loads(datei.read_text(encoding="utf-8")).get("metadaten"),
                                 self.merkmal_codes)
            except (OSError, ValueError):
                pass
        log.info("%d Merkmale referenziert", len(self.merkmal_codes))
        for code in sorted(self.merkmal_codes):
            if self.db.execute("SELECT 1 FROM merkmale WHERE code=?", (code,)).fetchone() \
                    and not self.args.aktualisieren:
                continue
            try:
                m = self.api.post("metadata/variable", {"name": code, "area": BEREICH})
            except GenesisFehler as e:
                log.warning("Merkmal %s: %s", code, e)
                continue
            obj = m.get("Object") or {}
            json_schreiben(ordner / f"{sicherer_name(code)}.json",
                           {"abgerufen_am": jetzt(), "lizenz": LIZENZ, "metadaten": obj})
            self.db.execute("INSERT OR REPLACE INTO merkmale VALUES(?,?,?)",
                            (code, obj.get("Content") or "", jetzt()))
            self.db.commit()

    # ---------- 6. Verzeichnisse als CSV (für Excel: ; und UTF-8 mit BOM) ----------
    def verzeichnisse(self):
        k = self.ziel / "_katalog"
        ausgaben = {
            "statistiken.csv": ("SELECT code AS Statistik, name AS Bezeichnung, themenbereich AS Themenbereich, "
                                "aktualisiert_genesis AS Stand_GENESIS, pfad AS Ordner FROM statistiken ORDER BY code"),
            "tabellen.csv": ("SELECT t.code AS Tabelle, t.name AS Bezeichnung, t.zeitraum AS Zeitraum, "
                             "t.statistik AS Statistik, s.name AS Statistik_Bezeichnung, "
                             "s.themenbereich AS Themenbereich, t.alle_statistiken AS Alle_Statistiken, "
                             "t.status AS Status, t.stand_genesis AS Stand_GENESIS, "
                             "t.heruntergeladen_am AS Heruntergeladen_am, t.bytes AS Bytes, "
                             "t.sha256 AS SHA256, t.dateien AS Dateien, t.pfad AS Ordner, "
                             "t.job_name AS Batch_Auftrag, t.meldung AS Meldung "
                             "FROM tabellen t LEFT JOIN statistiken s ON s.code=t.statistik ORDER BY t.code"),
            "merkmale.csv": "SELECT code AS Merkmal, name AS Bezeichnung, geladen_am AS Geladen_am FROM merkmale ORDER BY code",
        }
        for datei, sql in ausgaben.items():
            cur = self.db.execute(sql)
            with open(k / datei, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f, delimiter=";")
                w.writerow([c[0] for c in cur.description])
                w.writerows(cur.fetchall())
        z = dict(self.db.execute("SELECT status, COUNT(*) FROM tabellen GROUP BY status").fetchall())
        log.info("Zusammenfassung: %s", ", ".join(f"{k}={v}" for k, v in sorted(z.items())) or "–")


# --------------------------------------------------------------------------------------
ZUGANGSDATEI = "genesis_zugang.ini"            # optional, liegt NEBEN dem Skript, nie weitergeben


def zugangsdaten():
    """Reihenfolge: Umgebungsvariablen → genesis_zugang.ini → Abfrage (Passwort verdeckt).
    Das Passwort steht bewusst NICHT im Skript."""
    import configparser
    token = os.environ.get("GENESIS_TOKEN")
    user = os.environ.get("GENESIS_USER")
    pw = os.environ.get("GENESIS_PASSWORD")

    for ort in (Path(__file__).resolve().parent / ZUGANGSDATEI, Path.cwd() / ZUGANGSDATEI):
        if ort.is_file():
            cfg = configparser.ConfigParser(interpolation=None)
            cfg.read(ort, encoding="utf-8")
            if cfg.has_section("genesis"):
                g = cfg["genesis"]
                user = user or g.get("benutzer", "").strip() or None
                pw = pw or g.get("passwort", "").strip() or None
                token = token or g.get("token", "").strip() or None

    if not user:
        user = input("GENESIS-Benutzer (E-Mail-Adresse): ").strip()
    if not pw:
        pw = getpass.getpass(f"GENESIS-Passwort für {user}: ")
    return token, user, pw


def main():
    p = argparse.ArgumentParser(description="Export aller GENESIS-Online-Tabellen als Flatfile-CSV mit Metadaten")
    p.add_argument("--ziel", default=str(Path(__file__).resolve().parent.parent / "GENESIS_Export"),
                   help="Zielordner (Standard: GENESIS_Export im Hauptordner des Repositorys)")
    p.add_argument("--auswahl", default="*", help='Filter auf Statistik-Codes, z. B. "12*" (Standard: *)')
    p.add_argument("--pause", type=float, default=1.0, help="Sekunden zwischen Anfragen (Standard 1.0)")
    p.add_argument("--max-tabellen", type=int, default=0, help="nur N Tabellen (zum Testen)")
    p.add_argument("--test", action="store_true", help="Probelauf: Statistik 12411, max. 3 Tabellen")
    p.add_argument("--nur-katalog", action="store_true", help="nur Verzeichnis erstellen, keine Daten")
    p.add_argument("--katalog-neu", action="store_true", help="Katalog neu von GENESIS laden")
    p.add_argument("--aktualisieren", action="store_true", help="geänderte Tabellen erneut laden")
    p.add_argument("--ohne-merkmale", action="store_true", help="Merkmal-Metadaten nicht laden")
    p.add_argument("--job-intervall", type=int, default=120, help="Sekunden zwischen Auftrags-Abfragen")
    p.add_argument("--job-max-minuten", type=int, default=180, help="max. Wartezeit auf Aufträge")
    args = p.parse_args()
    if args.test:
        args.auswahl, args.max_tabellen = "12411", args.max_tabellen or 3

    ziel = Path(args.ziel).resolve()
    (ziel / "_log").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s",
                        handlers=[logging.StreamHandler(sys.stdout),
                                  logging.FileHandler(ziel / "_log" / "export.log", encoding="utf-8")])

    token, user, pw = zugangsdaten()
    api = Genesis(token, user, pw, args.pause)
    for versuch in range(1, 31):  # bis ca. 30 min warten, falls alte Requests noch laufen
        a = api.post("helloworld/logincheck", {})
        status = str(a.get("Status") if isinstance(a, dict) else a)
        log.info("Anmeldung: %s", status)
        if re.search(r"parallel|Limit", status, re.I) and "erfolgreich" not in status.lower():
            log.warning("Noch laufende Requests bei GENESIS – warte 60s (Versuch %d/30) …", versuch)
            time.sleep(60)
            continue
        break
    if "erfolgreich" not in status.lower():
        log.error("Anmeldung fehlgeschlagen – bitte Benutzer/Passwort in genesis_zugang.ini prüfen.")
        sys.exit(1)
    if not api.jobs_moeglich:
        log.warning("Nur Token angegeben: sehr große Tabellen können nicht als Batch-Auftrag geladen werden.")

    ex = Export(api, ziel, args)
    try:
        ex.katalog()
        ex.statistik_metadaten()
        if not args.nur_katalog:
            ex.tabellen()
            ex.jobs_abholen()
            if not args.ohne_merkmale:
                ex.merkmale()
    except KeyboardInterrupt:
        log.warning("Abgebrochen – Fortschritt ist gespeichert, einfach erneut starten.")
    finally:
        ex.verzeichnisse()
        log.info("Fertig. Ergebnis: %s", ziel)


if __name__ == "__main__":
    main()
