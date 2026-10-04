#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
genesis_diagramme.py – Reproduzierbare Erzeugung synthetischer Visualisierungen aus GENESIS-Online.

Verfahren und Begründungen: METHODE.md (gleicher Ordner).

Stufen:
  1 Profilierung        -> _bericht/profil_tabellen.csv, _bericht/ausschluesse.csv
  2 Kandidaten          -> _bericht/kandidaten.csv, _bericht/kapazitaet.csv
  3 Auswahl (Quoten)    -> _bericht/quoten.csv, _bericht/auswahl.csv
  4 Farbzuweisung       -> _bericht/farbpruefung.csv, Spalten thema/palette in auswahl.csv
  5 Diagrammbau         -> <Bereich>/<Statistik>/<Tabelle>/<Tabelle>_<nn>_<typ>.vl.json (+ _info.json, CSV-Kopie)
  6 Qualitätsprüfung    -> _bericht/qualitaet.csv
  7 Rendering           -> *.png (vl-convert, Vega-Lite 5.21, Skalierung 2)
  8 Berichte            -> manifest.json, uebersicht.html, _bericht/unabhaengigkeit_farbe.csv, _bericht/bericht.md

Aufruf:
  python genesis_diagramme.py                     # alle implementierten Stufen
  python genesis_diagramme.py --bis profil        # nur bis Stufe 1 (bzw. kandidaten, auswahl, bau)
  python genesis_diagramme.py --ohne-png          # Spezifikationen ohne Rendering (z. B. ohne vl-convert)
  python genesis_diagramme.py --neu               # Zwischenspeicher verwerfen und alles neu berechnen

Deterministisch: gleiche Rohdaten + gleiche config.yaml -> identische Ergebnisse.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import shutil
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

REGEL_VERSION = "1.3"          # bei Änderung der Regeln erhöhen -> Zwischenspeicher wird neu berechnet
HIER = Path(__file__).resolve().parent
SONDERZEICHEN = {"-", ".", "...", "/", "x", ""}

BEREICHE = {
    "1": "Gebiet, Bevölkerung, Arbeitsmarkt, Wahlen", "2": "Bildung, Sozialleistungen, Gesundheit, Recht",
    "3": "Wohnen, Umwelt", "4": "Wirtschaftsbereiche", "5": "Außenhandel, Unternehmen, Handwerk",
    "6": "Preise, Verdienste, Einkommen und Verbrauch", "7": "Öffentliche Finanzen, Steuern, Personal",
    "8": "Gesamtrechnungen", "9": "Querschnittsthemen",
}

# Die 36 Diagrammtypen (METHODE 6.1): Nummer -> (Kurzname, Idealbereich der Kategorienzahl)
TYPEN = {
    1: ("balken_rangfolge", (5, 20)), 2: ("lollipop", (10, 25)), 3: ("punktdiagramm", (5, 20)),
    4: ("slope", (5, 12)), 5: ("divergierende_balken", (4, 16)), 6: ("abweichung_bund", (16, 16)),
    7: ("dumbbell", (4, 12)), 8: ("gruppierte_balken", (3, 8)), 9: ("pyramide", (15, 100)),
    10: ("stapel_100", (3, 12)), 11: ("haeufigkeitsskala", (3, 12)), 12: ("donut", (2, 4)),
    13: ("torte", (2, 3)), 14: ("treemap", (8, 30)), 15: ("waffel", (2, 3)),
    16: ("saeulen_klassen", (4, 12)), 17: ("streifen", (40, 500)), 18: ("histogramm", (40, 500)),
    19: ("boxplot", (30, 500)), 20: ("linie", (8, 60)), 21: ("linie_hervorhebung", (6, 16)),
    22: ("small_multiples", (4, 16)), 23: ("flaeche_gestapelt", (8, 60)), 24: ("saeulen_zeit", (4, 12)),
    25: ("veraenderung", (4, 16)), 26: ("heatmap_monat", (3, 15)), 27: ("streudiagramm", (10, 400)),
    28: ("blasendiagramm", (10, 60)), 29: ("heatmap_kategorien", (4, 16)), 30: ("karte_laender", (16, 16)),
    31: ("karte_kreise", (300, 420)), 32: ("karte_divergierend", (16, 16)), 33: ("symbolkarte", (16, 420)),
    34: ("karte_regbez", (20, 45)), 35: ("saeulen_groessen", (2, 7)), 36: ("wasserfall", (3, 10)),
}

ORDNUNG_RE = re.compile(r"(?:^unter |bis unter| bis \d|und mehr|und älter|und darüber|^\d+ bis \d+|^\d+ Jahre)", re.I)
RATE_EINHEITEN = {"Prozent", "%", "Promille", "EUR", "Jahre", "Tage", "Stunden", "Std.", "kg", "m²", "qm", "km",
                  "Minuten"}
QUOTE_RE = re.compile(r"Anteil|Quote|je |pro |Durchschnitt|durchschnittl|Dichte|Rate|Median|Index|Mittel", re.I)
FLUSS_RE = re.compile(r"Zugang|Zugänge|Abgang|Abgänge|Zuzug|Zuzüge|Fortzug|Fortzüge|Einnahme|Ausgabe|Saldo|Überschuss|Defizit|Zunahme|Abnahme|Einfuhr|Ausfuhr|Geburten|Sterbefälle|Gestorbene", re.I)
BEREINIGUNG_RE = re.compile(r"^Originalwerte|X13|BV4|[Bb]ereinigt|Trend")
HAEUFIG_RE = re.compile(r"\b(?:jede[mnr]?|Hälfte|regelmäßig|ständig|gelegentlich)\b", re.I)


# =========================================================================================== Hilfen
def lade_config(pfad: Path) -> dict:
    with open(pfad, encoding="utf-8") as f:
        return yaml.safe_load(f)


def h(seed, *teile) -> str:
    """Deterministischer Hashwert (für Gleichstände und Zufallsreihenfolgen)."""
    return hashlib.sha256("|".join([str(seed), *map(str, teile)]).encode("utf-8")).hexdigest()


def schreibe_csv(pfad: Path, zeilen: list[dict], spalten: list[str] | None = None):
    pfad.parent.mkdir(parents=True, exist_ok=True)
    spalten = spalten or (list(zeilen[0].keys()) if zeilen else [])
    with open(pfad, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=spalten, delimiter=";", extrasaction="ignore")
        w.writeheader()
        for z in zeilen:
            w.writerow({k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v)
                        for k, v in z.items()})


def zeitformat(v: str) -> str:
    if re.fullmatch(r"\d{4}", v):
        return "jahr"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
        return "stichtag"
    if re.fullmatch(r"\d{4}/\d{2}", v):
        return "jahr_jahr"
    if re.fullmatch(r"\d{4}-\d{2}P1M", v):
        return "monat"
    if re.fullmatch(r"\d{4}-\d{2}P3M", v):
        return "quartal"
    if re.fullmatch(r"\d{4}-\d{2}P6M", v):
        return "halbjahr"
    if re.fullmatch(r"\d{4}-P1Y", v):
        return "jahr"
    return "sonstige"


# =========================================================================================== Tabelle lesen
def lade_tabelle(pfad: Path):
    """Flatfile-CSV -> (tidy DataFrame, Liste der Dimensionen). Werte: Dezimalkomma, Sonderzeichen -> NaN."""
    d = pd.read_csv(pfad, sep=";", dtype=str, encoding="utf-8-sig", keep_default_na=False)
    nd = max((int(c.split("_")[0]) for c in d.columns if c[:1].isdigit()), default=0)
    t = pd.DataFrame({"time": d["time"].astype(str)})
    dims = []
    for i in range(1, nd + 1):
        t[f"d{i}"] = d[f"{i}_variable_attribute_label"].astype(str)
        t[f"d{i}_c"] = d[f"{i}_variable_attribute_code"].astype(str)
        dims.append({"i": i, "code": d[f"{i}_variable_code"].iloc[0] if len(d) else "",
                     "label": d[f"{i}_variable_label"].iloc[0] if len(d) else ""})
    # "Insgesamt" gilt als Summenzeile, auch wenn GENESIS einen Ausprägungscode vergibt
    for dm in dims:
        ist_summe = t[f"d{dm['i']}"].str.strip().str.lower() == "insgesamt"
        t.loc[ist_summe, f"d{dm['i']}_c"] = ""
    # Messgrößen: Das überarbeitete Flatfile-CSV gibt abgeleitete Werte (Funktionalblöcke, z. B. Veränderung in %)
    # unter demselben Wertmerkmal-Code aus, erkennbar an abweichender Bezeichnung/Einheit. Eine Messgröße ist daher
    # das Tripel (Code, Bezeichnung, Einheit); abgeleitete Messgrößen erhalten eine eindeutige Kennung und Bezeichnung.
    code = d["value_variable_code"].astype(str)
    lab = d["value_variable_label"].astype(str)
    unit = d["value_unit"].astype(str)
    trip = pd.DataFrame({"c": code, "l": lab, "u": unit})
    haupt = {}
    for c, g in trip.drop_duplicates().groupby("c", sort=False):
        kand = g[(g["l"].str.len() > 3) & ~g["u"].isin(["%"])]
        haupt[c] = (kand.iloc[0] if len(kand) else g.iloc[0])[["l", "u"]].tolist()
    ids, labels = [], []
    for c, l, u in zip(code, lab, unit):
        hl, hu = haupt[c]
        if l == hl and u == hu:
            ids.append(c); labels.append(l)
        else:
            ids.append(f"{c}~{l}~{u}")
            labels.append(l if len(l) > 3 else f"{hl}: Veränderung in Prozent")
    t["vv"] = ids
    t["vv_label"] = labels
    t["unit"] = unit
    roh = d["value"].astype(str)
    zahl = roh.where(~roh.isin(SONDERZEICHEN)).str.replace(",", ".", regex=False)
    t["value"] = pd.to_numeric(zahl, errors="coerce")
    t["fehlend"] = roh.isin(SONDERZEICHEN)
    return t, dims


# =========================================================================================== Stufe 1: Profil
def rolle(dim: dict, werte: pd.Series, codes: pd.Series) -> str:
    """Rolle einer Dimension nach METHODE 5.1 (erste zutreffende Regel)."""
    c, lab = dim["code"], dim["label"]
    n = dim["n"]
    echte = codes[codes != ""]
    if n <= 1:
        return "konstant"
    if c in ("MONAT", "QUARTG") or c.startswith("QUARM"):
        return "unterjaehrig"
    if c in ("DINSG", "DG"):
        return "konstant"
    # Länder: Merkmal DLAND oder mindestens 14 der Schlüssel 01–16 (auch mit Zusatzpositionen wie „Ausland“)
    if c in ("DLAND", "DLANDU") or (echte.drop_duplicates().str.fullmatch(r"0[1-9]|1[0-6]").sum() >= 14 and n <= 20):
        return "laender"
    if c.startswith("REGBEZ"):
        return "regbez"
    if c == "KREISE" or (len(echte) and echte.str.fullmatch(r"\d{5}").mean() > .8):
        return "kreise"
    if c.startswith("STAAT") or "Staat" in lab or "Länder" in lab and "Bundesländer" not in lab:
        return "staaten"
    if c == "GES":
        return "geschlecht"
    if c.startswith("ALT"):
        return "alter"
    uniq = werte.drop_duplicates()
    # Bereinigungsverfahren (Originalwerte, X13 JDemetra+, BV4.1) sind keine inhaltlichen Kategorien:
    # die Dimension wird wie eine konstante behandelt und auf 'Originalwerte' festgelegt (METHODE 5.1, Regel R0)
    if len(uniq) and uniq.str.contains(BEREINIGUNG_RE).any() and uniq.str.contains(r"^Originalwerte", regex=True).any():
        return "konstant"
    if len(uniq) and uniq.str.contains(ORDNUNG_RE).mean() >= .5:
        return "klassen"
    return "nominal"


def profiliere(code, pfad: Path, bereich, statistik, t: pd.DataFrame, dims: list) -> dict:
    zeiten = sorted(t["time"].unique())
    p = {"code": code, "bereich": bereich, "statistik": statistik, "mb": round(pfad.stat().st_size / 1e6, 3),
         "zeilen": len(t), "zeitpunkte": len(zeiten), "zeit_min": zeiten[0] if zeiten else "",
         "zeit_max": zeiten[-1] if zeiten else "",
         "zeitformat": Counter(zeitformat(z) for z in zeiten).most_common(1)[0][0] if zeiten else "",
         "wertmerkmale": sorted(t["vv"].unique().tolist(), key=lambda v: ("~" in v, v)),
         "einheiten": t["unit"].value_counts().to_dict(),
         "anteil_fehlend": round(float(t["fehlend"].mean()), 4) if len(t) else 1.0, "dims": []}
    for dm in dims:
        col, colc = f"d{dm['i']}", f"d{dm['i']}_c"
        teil = t[t[colc] != ""]
        dm = dict(dm)
        dm["n"] = int(teil[col].nunique())
        dm["summe"] = bool((t[colc] == "").any())
        dm["rolle"] = rolle(dm, teil[col], t[colc])
        dm["max_label"] = int(teil[col].str.len().max()) if len(teil) else 0
        p["dims"].append(dm)
    return p


def ausschlussgrund(p: dict, cfg: dict) -> str | None:
    a = cfg["ausschluss"]
    if p.get("fehler"):
        return "E1 Datei nicht lesbar: " + p["fehler"]
    if p["zeilen"] == 0:
        return "E1 leer"
    if p["mb"] > a["max_mb"]:
        return f"E2 größer als {a['max_mb']} MB"
    if p["zeilen"] < a["min_zeilen"]:
        return f"E3 weniger als {a['min_zeilen']} Zeilen"
    if p["anteil_fehlend"] > a["max_anteil_fehlend"]:
        return f"E4 mehr als {int(a['max_anteil_fehlend'] * 100)} % fehlende Werte"
    return None


def dubletten(profile: dict) -> dict:
    """E5: gleiche Statistik, gleiche Dimensionen (Code + Anzahl Ausprägungen) und gleiche Messgrößen.
    Behalten wird die Tabelle mit dem jüngsten Zeitpunkt, dann den meisten Zeitpunkten, dann dem kleinsten Code."""
    gruppen = defaultdict(list)
    for code, p in profile.items():
        sig = (p["statistik"], tuple(sorted((d["code"], d["n"]) for d in p["dims"] if d["n"] > 1)),
               tuple(p["wertmerkmale"]))
        gruppen[sig].append(p)
    raus = {}
    for g in gruppen.values():
        if len(g) < 2:
            continue
        g = sorted(g, key=lambda p: (p["zeit_max"], p["zeitpunkte"], [-ord(c) for c in p["code"]]), reverse=True)
        for p in g[1:]:
            raus[p["code"]] = f"E5 Dublette von {g[0]['code']} (gleiche Struktur, älterer Stand)"
    return raus


# =========================================================================================== Stufe 2: Kandidaten
class Ausschnitt:
    """Hilfsobjekt: ein Wertmerkmal einer Tabelle mit Methoden zum Festlegen und Aufschneiden (METHODE 6.2)."""

    def __init__(self, t: pd.DataFrame, prof: dict, vv: str):
        self.t = t[t["vv"] == vv]
        self.prof = prof
        self.vv = vv
        self.vv_label = self.t["vv_label"].iloc[0] if len(self.t) else vv
        self.unit = self.t["unit"].mode().iloc[0] if len(self.t) else ""
        self.dims = [d for d in prof["dims"] if d["n"] > 1]
        self.quote = bool(self.unit in RATE_EINHEITEN or "=100" in self.unit or QUOTE_RE.search(self.vv_label)
                          or re.search(r"\b(je|pro)$", self.vv_label.strip()))
        self.zeiten = sorted(self.t["time"].unique())

    def fixiere(self, behalten: list, zeit: str | None = None):
        """Alle Dimensionen außer 'behalten' auf 'Insgesamt' (bzw. größte Ausprägung) festlegen.
        zeit: None = alle Zeitpunkte, 'letzter' = jüngster Zeitpunkt mit ausreichend Werten, 'ende' = erster+letzter."""
        d = self.t
        fix = {}
        for dm in self.prof["dims"]:
            if dm["i"] in behalten or (dm["n"] <= 1 and not dm["summe"]):
                continue
            col, colc = f"d{dm['i']}", f"d{dm['i']}_c"
            if dm["summe"]:
                d = d[d[colc] == ""]
                fix[dm["label"]] = "Insgesamt"
            elif dm["rolle"] == "konstant" and d[col].eq("Originalwerte").any():
                d = d[d[col] == "Originalwerte"]
                fix[dm["label"]] = "Originalwerte"
            else:
                sums = d.groupby(col)["value"].apply(lambda s: s.abs().sum())
                if not len(sums):
                    return d.iloc[0:0], fix
                wahl = sorted(sums.index, key=lambda k: (-sums[k], k))[0]
                d = d[d[col] == wahl]
                fix[dm["label"]] = wahl
        if zeit and len(d):
            z = sorted(d["time"].unique())
            if zeit == "letzter":
                gueltig = d.groupby("time")["value"].apply(lambda s: s.notna().mean())
                gute = [x for x in z if gueltig.get(x, 0) >= .5] or z
                d = d[d["time"] == gute[-1]]
                fix["Zeit"] = gute[-1]
            elif zeit == "ende" and len(z) >= 2:
                d = d[d["time"].isin([z[0], z[-1]])]
                fix["Zeit"] = f"{z[0]} / {z[-1]}"
        return d, fix


def qualitaet(v, n, lo, hi, max_label, werte, gew) -> dict:
    """Qualitätswert q = w_v·v + w_k·k + w_l·l + w_a·a (METHODE 6.3)."""
    k = 1.0 if lo <= n <= hi else max(0.0, 1 - (lo - n) / max(lo, 1)) if n < lo else max(0.0, 1 - (n - hi) / max(hi, 1))
    l = 1.0 if max_label <= 30 else max(0.0, 1 - (max_label - 30) / 30)
    w = pd.Series(werte, dtype=float).dropna()
    a = 0.0
    if len(w) >= 2 and w.abs().mean() > 0:
        a = float(min(1.0, w.std() / w.abs().mean()))
    q = gew["v"] * v + gew["k"] * k + gew["l"] * l + gew["a"] * a
    return {"q": round(q, 4), "v": round(v, 3), "k": round(k, 3), "l": round(l, 3), "a": round(a, 3)}


def kandidaten_fuer_tabelle(t: pd.DataFrame, prof: dict, cfg: dict) -> list[dict]:
    """Alle datenseitig zulässigen Diagrammtypen einer Tabelle (METHODE 6.1), je Typ der beste Ausschnitt."""
    gew = cfg["kandidaten"]["gewichte"]
    vvs = prof["wertmerkmale"][: cfg["kandidaten"]["max_wertmerkmale_je_tabelle"]]
    beste = {}

    def neu(typ, a: Ausschnitt, dims_used, fix, d_sub, n, max_label, grund, extra=None):
        lo, hi = TYPEN[typ][1]
        v = float(d_sub["value"].notna().mean()) if len(d_sub) else 0.0
        m = qualitaet(v, n, lo, hi, max_label, d_sub["value"], gew)
        c = {"typ": typ, "typname": TYPEN[typ][0], "vv": a.vv, "vv_label": a.vv_label, "einheit": a.unit,
             "dims": dims_used, "fix": fix, "n": n, "grund": grund, **m, **(extra or {})}
        alt = beste.get(typ)
        if alt is None or (c["q"], c["vv"]) > (alt["q"], alt["vv"]):
            beste[typ] = c

    for vv in vvs:
        a = Ausschnitt(t, prof, vv)
        if not len(a.t):
            continue
        D = a.dims
        tp = len(a.zeiten)
        unter = [d for d in D if d["rolle"] == "unterjaehrig"]
        zeitreihe = tp >= 5 or bool(unter)
        kat = [d for d in D if d["rolle"] in ("nominal", "staaten", "laender")]
        geord = [d for d in D if d["rolle"] in ("klassen", "alter")]
        laender = [d for d in D if d["rolle"] == "laender"]
        kreise = [d for d in D if d["rolle"] == "kreise"]
        regbez = [d for d in D if d["rolle"] == "regbez"]
        ges = [d for d in D if d["rolle"] == "geschlecht"]
        alle_kat = [d for d in D if d["rolle"] not in ("unterjaehrig", "konstant")]

        # ---------------- Querschnitt einer Dimension (jüngster Zeitpunkt)
        for dm in kat + geord + kreise + regbez:
            d, fix = a.fixiere([dm["i"]], "letzter")
            d = d[d[f"d{dm['i']}_c"] != ""]
            n = int(d[f"d{dm['i']}"].nunique())
            if n < 2:
                continue
            ml = dm["max_label"]
            w = d["value"].dropna()
            art = dm["rolle"]
            if art in ("nominal", "staaten", "laender"):
                if 5 <= n <= 25:
                    neu(1, a, [dm["i"]], fix, d, n, ml, f"Rangfolge von {n} Kategorien ({dm['label']})")
                    if len(w) and w.std() / max(w.abs().mean(), 1e-9) < .3:
                        neu(3, a, [dm["i"]], fix, d, n, ml, "Rangfolge mit geringer Spannweite -> Punktdiagramm")
                if 10 <= n <= 30:
                    neu(2, a, [dm["i"]], fix, d, n, ml, f"Rangfolge vieler Kategorien ({n})")
                if 3 <= n <= 20 and len(w) and (w < 0).any() and (w > 0).any():
                    neu(5, a, [dm["i"]], fix, d, n, ml, "positive und negative Werte")
                if 2 <= n <= 7 and art != "laender":
                    neu(35, a, [dm["i"]], fix, d, n, ml, f"Größenvergleich weniger Kategorien ({n})")
            if art in ("klassen", "alter") and 3 <= n <= 15:
                neu(16, a, [dm["i"]], fix, d, n, ml, f"geordnete Klassen ({dm['label']})")
            if n >= 40 and art in ("nominal", "kreise", "staaten"):
                neu(17, a, [dm["i"]], fix, d, n, ml, f"Verteilung über {n} Einheiten")
                neu(18, a, [dm["i"]], fix, d, n, ml, f"Verteilung über {n} Einheiten")
            if art == "laender" and n >= 15:
                ges_d = a.fixiere([dm["i"]], "letzter")[0]
                hat_bund = bool((ges_d[f"d{dm['i']}_c"] == "").any()) or dm["summe"]
                if a.quote:
                    neu(30, a, [dm["i"]], fix, d, n, ml, "Quote/Anteil je Bundesland -> Choroplethenkarte")
                    if hat_bund:
                        neu(6, a, [dm["i"]], fix, d, n, ml, "Abweichung vom Bundeswert")
                        neu(32, a, [dm["i"]], fix, d, n, ml, "Abweichung vom Bundeswert -> divergierende Karte")
                else:
                    neu(33, a, [dm["i"]], fix, d, n, ml, "absolute Werte je Bundesland -> Symbolkarte")
            if art == "kreise" and n >= 300:
                if a.quote:
                    neu(31, a, [dm["i"]], fix, d, n, ml, "Quote/Anteil je Kreis -> Choroplethenkarte")
                else:
                    neu(33, a, [dm["i"]], fix, d, n, ml, "absolute Werte je Kreis -> Symbolkarte")
            if art == "regbez" and a.quote:
                neu(34, a, [dm["i"]], fix, d, n, ml, "Quote/Anteil je Regierungsbezirk")

            # ---------------- Teil-Ganzes (Summenzeile vorhanden, Teile additiv)
            if dm["summe"] and not a.quote and art in ("nominal", "klassen", "alter"):
                dd, fx = a.fixiere([dm["i"]], "letzter")
                tot = dd[dd[f"d{dm['i']}_c"] == ""]["value"]
                teile = dd[dd[f"d{dm['i']}_c"] != ""]["value"]
                if len(tot) == 1 and pd.notna(tot.iloc[0]) and tot.iloc[0] > 0 and teile.notna().all() and len(teile):
                    s, T = teile.sum(), tot.iloc[0]
                    add = abs(s - T) / T <= .02
                    anteile = (teile / T * 100).tolist()
                    if add and (teile >= 0).all():
                        if 2 <= n <= 4:
                            neu(12, a, [dm["i"]], fx, dd, n, ml, "2–4 additive Teile -> Donut")
                        if 2 <= n <= 3 and max(anteile) - min(anteile) >= 10:
                            neu(13, a, [dm["i"]], fx, dd, n, ml, "2–3 deutlich verschiedene Teile -> Torte")
                            neu(15, a, [dm["i"]], fx, dd, n, ml, "prägnanter Anteil -> Waffeldiagramm")
                        if 8 <= n <= 40:
                            neu(14, a, [dm["i"]], fx, dd, n, ml, f"{n} additive Teile -> Treemap")
                    fluss = sum(bool(FLUSS_RE.search(x)) for x in dd[f"d{dm['i']}"].unique())
                    if add and (teile < 0).any() and 3 <= n <= 10 and fluss >= 2:
                        neu(36, a, [dm["i"]], fx, dd, n, ml, "Bilanz mit Zu- und Abgängen -> Wasserfall")

        # ---------------- zwei Dimensionen
        for d1 in alle_kat:
            for d2 in alle_kat:
                if d1["i"] == d2["i"]:
                    continue
                d, fix = a.fixiere([d1["i"], d2["i"]], "letzter")
                d = d[(d[f"d{d1['i']}_c"] != "") & (d[f"d{d2['i']}_c"] != "")]
                n1, n2 = d[f"d{d1['i']}"].nunique(), d[f"d{d2['i']}"].nunique()
                if not len(d):
                    continue
                ml = max(d1["max_label"], d2["max_label"])
                if d1["rolle"] == "geschlecht" and d2["rolle"] == "alter" and n2 >= 10:
                    neu(9, a, [d1["i"], d2["i"]], fix, d, int(n2), d2["max_label"], "Alter × Geschlecht -> Pyramide")
                if d1["rolle"] == "geschlecht" and n1 == 2 and 3 <= n2 <= 15 and d2["rolle"] != "alter":
                    neu(7, a, [d1["i"], d2["i"]], fix, d, int(n2), d2["max_label"], "Männer/Frauen je Kategorie -> Dumbbell")
                if d1["rolle"] == "geschlecht" or d2["rolle"] == "geschlecht":
                    continue
                if 2 <= n1 <= 4 and 3 <= n2 <= 10:
                    neu(8, a, [d1["i"], d2["i"]], fix, d, int(n2), ml, f"{n1} Gruppen × {n2} Kategorien")
                if 4 <= n1 <= 20 and 4 <= n2 <= 20:
                    neu(29, a, [d1["i"], d2["i"]], fix, d, int(max(n1, n2)), ml, f"Kreuztabelle {n1} × {n2}")
                if d1["summe"] and not a.quote and 2 <= n1 <= 6 and 3 <= n2 <= 15:
                    dd, fx = a.fixiere([d1["i"], d2["i"]], "letzter")
                    tot = dd[(dd[f"d{d1['i']}_c"] == "") & (dd[f"d{d2['i']}_c"] != "")]["value"].sum()
                    teile = dd[(dd[f"d{d1['i']}_c"] != "") & (dd[f"d{d2['i']}_c"] != "")]["value"].sum()
                    if tot > 0 and teile <= tot * 1.02:
                        hf = sum(bool(HAEUFIG_RE.search(x)) for x in d[f"d{d1['i']}"].unique())
                        typ = 11 if hf >= 2 else 10
                        neu(typ, a, [d1["i"], d2["i"]], fx, dd, int(n2), ml, "Anteile an der Summe je Gruppe")
                if n1 >= 30 and 2 <= n2 <= 8 and d1["rolle"] in ("nominal", "kreise", "staaten"):
                    neu(19, a, [d1["i"], d2["i"]], fix, d, int(n1), ml, f"Verteilung über {n1} Einheiten in {n2} Gruppen")

        # ---------------- Zeitverlauf
        if zeitreihe and not unter:
            d, fix = a.fixiere([], None)
            n = d["time"].nunique()
            if n >= 5:
                neu(20, a, [], fix, d, int(n), 0, f"Zeitreihe mit {n} Zeitpunkten")
            if 3 <= n <= 15:
                neu(24, a, [], fix, d, int(n), 0, f"{n} Zeitpunkte -> Säulen")
            for dm in kat + geord:
                dd, fx = a.fixiere([dm["i"]], None)
                dd = dd[dd[f"d{dm['i']}_c"] != ""]
                k = dd[f"d{dm['i']}"].nunique()
                if dd["time"].nunique() < 5:
                    continue
                if 6 <= k <= 20:
                    neu(21, a, [dm["i"]], fx, dd, int(k), dm["max_label"], f"{k} Zeitreihen, 1–2 hervorgehoben")
                if 4 <= k <= 16:
                    neu(22, a, [dm["i"]], fx, dd, int(k), dm["max_label"], f"{k} Zeitreihen -> Small Multiples")
                if dm["summe"] and not a.quote and 2 <= k <= 6 and (dd["value"].dropna() >= 0).all():
                    neu(23, a, [dm["i"]], fx, dd, int(dd["time"].nunique()), dm["max_label"], "Zusammensetzung über die Zeit")
        if tp >= 2:
            for dm in kat + geord:
                dd, fx = a.fixiere([dm["i"]], "ende")
                dd = dd[dd[f"d{dm['i']}_c"] != ""]
                k = dd[f"d{dm['i']}"].nunique()
                if dd["time"].nunique() < 2:
                    continue
                if 5 <= k <= 15 and dm["rolle"] != "alter":
                    neu(4, a, [dm["i"]], fx, dd, int(k), dm["max_label"], "Rangfolge zu zwei Zeitpunkten -> Slope")
                if 3 <= k <= 20 and (dd["value"].dropna() > 0).all():
                    neu(25, a, [dm["i"]], fx, dd, int(k), dm["max_label"], "Veränderung erster -> letzter Zeitpunkt")
                if 3 <= k <= 15 and not ges:
                    neu(7, a, [dm["i"]], fx, dd, int(k), dm["max_label"], "Vergleich zweier Zeitpunkte -> Dumbbell")
        if unter:
            u = unter[0]
            dd, fx = a.fixiere([u["i"]], None)
            dd = dd[dd[f"d{u['i']}_c"] != ""]
            jahre = dd["time"].str[:4].nunique()
            if jahre >= 3:
                neu(26, a, [u["i"]], fx, dd, int(jahre), 0, f"unterjährige Werte über {jahre} Jahre -> Heatmap")
            if dd["time"].nunique() * dd[f"d{u['i']}"].nunique() >= 8:
                neu(20, a, [u["i"]], fx, dd, int(dd["time"].nunique() * dd[f"d{u['i']}"].nunique()), 0,
                    "unterjährige Zeitreihe")

    # ---------------- Zusammenhang (mehrere Messgrößen je Einheit)
    if len(prof["wertmerkmale"]) >= 2:
        einheiten = [d for d in prof["dims"] if d["n"] >= 8 and d["rolle"] in ("nominal", "laender", "kreise", "staaten")]
        for dm in einheiten[:1]:
            a = Ausschnitt(t, prof, prof["wertmerkmale"][0])
            d, fix = a.fixiere([dm["i"]], "letzter")
            d = d[d[f"d{dm['i']}_c"] != ""]
            n = d[f"d{dm['i']}"].nunique()
            if n >= 8:
                vv2 = prof["wertmerkmale"][:3]
                neu(27, a, [dm["i"]], fix, d, int(n), dm["max_label"], f"2 Messgrößen über {n} Einheiten",
                    {"vv_liste": vv2[:2]})
                if len(vv2) >= 3:
                    neu(28, a, [dm["i"]], fix, d, int(n), dm["max_label"], f"3 Messgrößen über {n} Einheiten",
                        {"vv_liste": vv2})
    return [c for c in beste.values() if c["q"] >= cfg["kandidaten"]["min_qualitaet"]]


# =========================================================================================== Stufe 3: Auswahl
def wasserfuellung(N: int, kap: dict) -> dict:
    """Gleiche Zielgröße je Gruppe, begrenzt durch die Kapazität; Überschuss gleichmäßig verteilen (METHODE 7.2)."""
    ziel = {k: 0.0 for k in kap}
    offen = {k for k in kap if kap[k] > 0}
    rest = float(N)
    while offen and rest > 1e-9:
        anteil = rest / len(offen)
        voll = {k for k in offen if kap[k] - ziel[k] <= anteil}
        if not voll:
            for k in offen:
                ziel[k] += anteil
            rest = 0
            break
        for k in voll:
            rest -= kap[k] - ziel[k]
            ziel[k] = kap[k]
        offen -= voll
    return ziel


def ipf(C: dict, zeilen: dict, spalten: dict, tol: float, max_iter: int):
    """Iterative proportionale Anpassung mit Kapazitätsgrenzen (Deming & Stephan 1940)."""
    n = {k: float(v) for k, v in C.items()}
    it = 0
    for it in range(1, max_iter + 1):
        alt = dict(n)
        for a in zeilen:
            s = sum(n[(a, t)] for t in spalten)
            if s > 0:
                for t in spalten:
                    n[(a, t)] = min(C[(a, t)], n[(a, t)] * zeilen[a] / s)
        for t in spalten:
            s = sum(n[(a, t)] for a in zeilen)
            if s > 0:
                for a in zeilen:
                    n[(a, t)] = min(C[(a, t)], n[(a, t)] * spalten[t] / s)
        if max(abs(n[k] - alt[k]) for k in n) < tol / 100:
            break
    return n, it


def proportional_begrenzt(ziel: float, gewichte: dict, cap: dict) -> dict:
    """Verteilt 'ziel' proportional zu 'gewichte', jede Zelle höchstens 'cap' (iterativ, Überschuss neu verteilt)."""
    x = {k: 0.0 for k in gewichte}
    offen = {k for k in gewichte if cap[k] > 0}
    rest = float(ziel)
    while offen and rest > 1e-9:
        g = {k: (gewichte[k] if gewichte[k] > 0 else 1e-6) for k in offen}
        s = sum(g.values())
        voll = set()
        for k in offen:
            add = rest * g[k] / s
            if x[k] + add >= cap[k]:
                voll.add(k)
        if not voll:
            for k in offen:
                x[k] += rest * g[k] / s
            rest = 0
            break
        for k in voll:
            rest -= cap[k] - x[k]
            x[k] = float(cap[k])
        offen -= voll
    return x


def hamilton(x: dict, C: dict, N: int) -> dict:
    """Ganzzahlige Rundung nach größten Resten, Summe exakt N (soweit Kapazität reicht)."""
    f = {k: int(math.floor(v)) for k, v in x.items()}
    rest = N - sum(f.values())
    reihenfolge = sorted(x, key=lambda k: (-(x[k] - f[k]), k))
    while rest > 0:
        vergeben = False
        for k in reihenfolge:
            if rest <= 0:
                break
            if f[k] < C[k]:
                f[k] += 1
                rest -= 1
                vergeben = True
        if not vergeben:
            break
    return f


def auswahl(kand: list[dict], cfg: dict, seed):
    N = cfg["anzahl_diagramme"]
    A = sorted(BEREICHE)
    T = sorted(TYPEN)
    C = {(a, t): 0 for a in A for t in T}
    for k in kand:
        C[(k["bereich"], k["typ"])] += 1
    zeilen = wasserfuellung(N, {a: sum(C[(a, t)] for t in T) for a in A})
    spalten = wasserfuellung(N, {t: sum(C[(a, t)] for a in A) for t in T})
    x, it = ipf(C, zeilen, spalten, cfg["auswahl"]["ipf_toleranz"], cfg["auswahl"]["ipf_max_iter"])
    # Vorrang der Bereichsziele (Anforderung A2): Zeilensummen werden abschließend exakt hergestellt,
    # die Verteilung auf Typen innerhalb der Zeile folgt dem IPF-Ergebnis (proportional, kapazitätsbegrenzt).
    zeilen_int = hamilton({a: zeilen[a] for a in A}, {a: sum(C[(a, t)] for t in T) for a in A}, N)
    soll = {}
    for a in A:
        gew_a = {t: x[(a, t)] for t in T}
        cap_a = {t: C[(a, t)] for t in T}
        x_a = proportional_begrenzt(zeilen_int[a], gew_a, cap_a)
        soll.update({(a, t): v for t, v in hamilton(x_a, cap_a, zeilen_int[a]).items()})
    x = {(a, t): x[(a, t)] for a in A for t in T}

    # Kandidaten je Zelle, sortiert nach Qualität, Gleichstand per Hash
    zelle = defaultdict(list)
    for k in kand:
        zelle[(k["bereich"], k["typ"])].append(k)
    for z in zelle.values():
        z.sort(key=lambda k: (-k["q"], h(seed, k["id"])))

    max_tab = cfg["auswahl"]["max_je_tabelle"]
    je_tab = Counter()
    je_stat = Counter()
    gewaehlt, ids = [], set()
    ziel_bereich = {a: sum(soll[(a, t)] for t in T) for a in A}
    anzahl_stat = {a: len({k["statistik"] for k in kand if k["bereich"] == a}) for a in A}
    cap_stat = {a: max(math.ceil(cfg["auswahl"]["max_anteil_statistik"] * ziel_bereich[a]),
                        math.ceil(ziel_bereich[a] / max(anzahl_stat[a], 1))) for a in A}

    def zulaessig(k):
        return (k["id"] not in ids and je_tab[k["code"]] < max_tab
                and je_stat[(k["bereich"], k["statistik"])] < cap_stat[k["bereich"]])

    def nimm(k, weg):
        ids.add(k["id"]); je_tab[k["code"]] += 1; je_stat[(k["bereich"], k["statistik"])] += 1
        gewaehlt.append({**k, "auswahlweg": weg})

    def fuelle(a, t, bedarf, weg):
        """Reihum über Statistiken den jeweils besten zulässigen Kandidaten nehmen (Round Robin)."""
        stats = defaultdict(list)
        for k in zelle[(a, t)]:
            stats[k["statistik"]].append(k)
        reihe = sorted(stats, key=lambda s: (-stats[s][0]["q"], h(seed, a, t, s)))
        genommen = 0
        while genommen < bedarf:
            fortschritt = False
            for s in reihe:
                if genommen >= bedarf:
                    break
                for k in stats[s]:
                    if zulaessig(k):
                        nimm(k, weg); genommen += 1; fortschritt = True
                        break
            if not fortschritt:
                break
        return genommen

    ist = Counter()
    # seltene Typen zuerst, damit sie nicht an der Tabellengrenze scheitern
    for t in sorted(T, key=lambda t: (sum(C[(a, t)] for a in A), t)):
        for a in A:
            if soll[(a, t)]:
                ist[(a, t)] += fuelle(a, t, soll[(a, t)], "quote")
    # (a) Fehlmengen innerhalb des Bereichs ausgleichen: Typ mit dem geringsten Erfüllungsgrad zuerst
    def ein_weiteres(a):
        for t in sorted(T, key=lambda t: (ist[(a, t)] / max(spalten[t] / len(A), 1), t)):
            if fuelle(a, t, 1, "ausgleich"):
                ist[(a, t)] += 1
                return True
        return False

    for a in A:
        while sum(ist[(a, t)] for t in T) < ziel_bereich[a] and ein_weiteres(a):
            pass
    # (b) verbleibende Fehlmenge gleichmäßig reihum auf alle Bereiche mit freier Kapazität verteilen
    #     (Wasserfüllprinzip, jeweils ein Diagramm an den Bereich mit dem geringsten Erfüllungsgrad)
    aktiv = set(A)
    while len(gewaehlt) < N and aktiv:
        for a in sorted(aktiv, key=lambda a: (sum(ist[(a, t)] for t in T) / max(ziel_bereich[a], 1), a)):
            if len(gewaehlt) >= N:
                break
            if not ein_weiteres(a):
                aktiv.discard(a)
            break
    quoten = [{"bereich": a, "typ": t, "typname": TYPEN[t][0], "kapazitaet": C[(a, t)],
               "soll_ipf": round(x[(a, t)], 2), "soll": soll[(a, t)], "ist": ist[(a, t)]} for a in A for t in T]
    info = {"ipf_iterationen": it, "ziel_bereiche": {a: round(v, 1) for a, v in zeilen.items()},
            "ziel_typen": {t: round(v, 1) for t, v in spalten.items()}, "cap_statistik": cap_stat}
    return gewaehlt, quoten, info



# =========================================================================================== Stufe 4: Farbe
def farbzuweisung(gew: list, seed) -> tuple[list, list]:
    """Balancierte Zuweisung von Thema und Palette (METHODE 8.4).

    Systematische Blockzuteilung: Die Diagramme werden nach Diagrammtyp und Bereich geordnet (innerhalb der Gruppen
    in geseedeter Zufallsreihenfolge) und fortlaufend in Blöcken aller Themen zugeteilt; jeder Block ist eine neue,
    geseedete Permutation der Themen. Dadurch ist jedes Thema innerhalb jedes Typs (und annähernd jedes Bereichs)
    gleich häufig. Paletten werden je Thema auf dieselbe Weise zugeteilt (ebenfalls nach Typ geordnet) und nur aus
    den für dieses Thema gültigen Paletten (Farbprüfung, METHODE 8.3)."""
    import gestaltung as G
    pruef = [G.pruefe_kombination(t, p) for t in G.THEMEN for p in G.PALETTEN]
    gueltig = {(z["thema"], z["palette"]) for z in pruef if z["gueltig"]}
    themen = sorted(G.THEMEN)

    def zuteilen(liste, optionen, feld, salz):
        block, pos, nr = [], 0, 0
        for k in liste:
            if pos >= len(block):
                block = sorted(optionen, key=lambda o: h(seed, salz, nr, o))
                pos, nr = 0, nr + 1
            k[feld] = block[pos]
            pos += 1

    zuteilen(sorted(gew, key=lambda k: (k["typ"], k["bereich"], h(seed, "t", k["id"]))), themen, "thema", "thema")
    for th in themen:
        liste = sorted([k for k in gew if k["thema"] == th], key=lambda k: (k["typ"], k["bereich"], h(seed, "p", k["id"])))
        zuteilen(liste, sorted(p for p in G.PALETTEN if (th, p) in gueltig), "palette", "palette_" + th)
    prot = [{k: v for k, v in z.items() if not k.startswith("_")} for z in pruef]
    return gew, prot


def _gammq(a, x):
    """Regularisierte obere unvollständige Gammafunktion Q(a, x) (für p-Werte des Chi²-Tests)."""
    if x <= 0:
        return 1.0
    gln = math.lgamma(a)
    if x < a + 1:
        s, d, ap = 1 / a, 1 / a, a
        for _ in range(500):
            ap += 1
            d *= x / ap
            s += d
            if abs(d) < abs(s) * 1e-12:
                break
        return max(0.0, 1 - s * math.exp(-x + a * math.log(x) - gln))
    b, c, d = x + 1 - a, 1 / 1e-300, 1 / (x + 1 - a)
    hh = d
    for i in range(1, 500):
        an = -i * (i - a)
        b += 2
        d = an * d + b
        d = 1e-300 if abs(d) < 1e-300 else d
        c = b + an / c
        c = 1e-300 if abs(c) < 1e-300 else c
        d = 1 / d
        de_ = d * c
        hh *= de_
        if abs(de_ - 1) < 1e-12:
            break
    return math.exp(-x + a * math.log(x) - gln) * hh


def unabhaengigkeit(gew: list, merkmal: str, gegen: str) -> dict:
    """Chi²-Unabhängigkeitstest und Cramérs V (Cramér 1946) für zwei kategoriale Merkmale."""
    zeilen = sorted({str(k[merkmal]) for k in gew})
    spalten = sorted({str(k[gegen]) for k in gew})
    n = len(gew)
    tab = Counter((str(k[merkmal]), str(k[gegen])) for k in gew)
    rz = Counter(str(k[merkmal]) for k in gew)
    sz = Counter(str(k[gegen]) for k in gew)
    chi2 = sum((tab[(a, b)] - rz[a] * sz[b] / n) ** 2 / (rz[a] * sz[b] / n) for a in zeilen for b in spalten)
    df = (len(zeilen) - 1) * (len(spalten) - 1)
    v = math.sqrt(chi2 / (n * max(1, min(len(zeilen), len(spalten)) - 1)))
    p = _gammq(df / 2, chi2 / 2) if df > 0 else 1.0
    return {"pruefung": f"{merkmal} × {gegen}", "chi2": round(chi2, 2), "df": df, "p": round(p, 4), "cramers_v": round(v, 3)}


# =========================================================================================== Stufen 5–8
def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _jsonwert(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return None if np.isnan(o) else float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, float) and math.isnan(o):
        return None
    raise TypeError(type(o))


def pruefe_diagramm(spec: dict, info: dict, kand: dict, kombi_ok: bool, max_titel: int) -> list[str]:
    """Automatische Prüfungen (METHODE 10, Auswahl der programmatisch prüfbaren Regeln)."""
    probleme = []
    if len(info["titel"]) > max_titel:
        probleme.append("Q1 Überschrift zu lang")
    if not info["sachzeile"]:
        probleme.append("Q1 Sachzeile fehlt")
    fuss = json.dumps(spec["vconcat"][-1]["data"]["values"], ensure_ascii=False)
    if kand["code"] not in fuss:
        probleme.append("Q1 Tabellencode fehlt in der Quellzeile")
    if not info["fakten"]:
        probleme.append("Q2 Faktenprotokoll leer")
    if not kombi_ok:
        probleme.append("Q10 ungültige Farbkombination")
    text = json.dumps(spec, ensure_ascii=False, default=_jsonwert)
    if "…" in text:
        probleme.append("Q13 gekürzte Beschriftung („…“)")
    if "NaN" in text:
        probleme.append("Q12 NaN in der Spezifikation")
    return probleme


def aufraeumen(aus: Path, manifest: list):
    """Nur im Volllauf: Diagramme und Tabellenordner früherer Läufe entfernen, die nicht mehr zur Auswahl gehören,
    damit der Ergebnisordner genau dem Manifest entspricht (METHODE 13)."""
    aktuell = {aus / m["datei"] for m in manifest}
    ordner_aktuell = {p.parent for p in aktuell}
    entfernt = 0
    for bereich in aus.iterdir():
        if not (bereich.is_dir() and bereich.name[:1].isdigit()):
            continue
        for f in sorted(bereich.rglob("*"), reverse=True):
            if f.is_file():
                if f.parent not in ordner_aktuell:
                    f.unlink(); entfernt += 1
                elif f.name.endswith((".vl.json", ".png", "_info.json")):
                    stamm = f.name.replace(".vl.json", "").replace("_info.json", "").replace(".png", "")
                    if f.parent / stamm not in aktuell:
                        f.unlink(); entfernt += 1
            elif f.is_dir() and not any(f.iterdir()):
                f.rmdir()
    if entfernt:
        print(f"    {entfernt} Dateien früherer Läufe entfernt (nicht mehr in der Auswahl)")


def stufen_4_bis_8(gew, kand, cache, profile, export: Path, aus: Path, ber: Path, cfg, args, seed) -> dict:
    import diagramme as D
    import gestaltung as G
    import geometrie as GEO
    import shutil

    # ------------------------------------------------ Stufe 4
    gew, prot = farbzuweisung(gew, seed)
    schreibe_csv(ber / "farbpruefung.csv", prot)
    gueltig = {(z["thema"], z["palette"]) for z in prot if z["gueltig"]}
    unabh = [unabhaengigkeit(gew, "thema", "bereich"), unabhaengigkeit(gew, "thema", "typ"),
             unabhaengigkeit(gew, "palette", "bereich"), unabhaengigkeit(gew, "palette", "typ")]
    schreibe_csv(ber / "unabhaengigkeit_farbe.csv", unabh)
    print(f"[4] Farbe: {len(gueltig)} gültige Kombinationen; Cramérs V: " +
          ", ".join(f"{u['pruefung']} = {u['cramers_v']}" for u in unabh))

    # ------------------------------------------------ Stufe 5
    nur = {int(x) for x in args.nur.split(",") if x.strip()} if args.nur else None
    stich = set(str(x) for x in cfg.get("stichproben_statistiken", []))
    geo_ordner = HIER / "geo"
    zelle = defaultdict(list)
    for k in kand:
        zelle[(k["bereich"], k["typ"])].append(k)
    for z in zelle.values():
        z.sort(key=lambda k: (-k["q"], h(seed, k["id"])))
    je_tab = Counter(k["code"] for k in gew)
    benutzt = {k["id"] for k in gew}
    tabellen_cache: dict = {}

    def lade(code, ordner):
        if code not in tabellen_cache:
            if len(tabellen_cache) > 40:
                tabellen_cache.clear()
            f = export / ordner / f"{code}_flatfile.csv"
            t, _ = lade_tabelle(f)
            mp = export / ordner / f"{code}_metadaten.json"
            meta = {}
            if mp.exists():
                try:
                    meta = json.loads(mp.read_text(encoding="utf-8")).get("metadaten") or {}
                except ValueError:
                    meta = {}
            tabellen_cache[code] = (t, meta)
        return tabellen_cache[code]

    gebaut, ersetzt, nicht, qual = [], 0, [], Counter()
    liste = [k for k in sorted(gew, key=lambda k: (k["code"], k["typ"])) if not nur or k["typ"] in nur]
    if args.stichprobe:
        je = defaultdict(list)
        for k in sorted(liste, key=lambda k: h(seed, "stichprobe", k["id"])):
            if len(je[k["typ"]]) < args.stichprobe:
                je[k["typ"]].append(k)
        liste = sorted((k for v in je.values() for k in v), key=lambda k: (k["code"], k["typ"]))
    # Ersatzregel (METHODE 7.5): zuerst der nächstbeste Kandidat derselben Zelle (Bereich × Typ); ist die Zelle
    # erschöpft oder nach 25 Versuchen ohne Erfolg, ein Kandidat desselben Bereichs aus dem Typ, der bisher am
    # seltensten vertreten ist. Farbthema und Palette des Platzes bleiben erhalten (Farbbalance unverändert).
    geplant = Counter(k["typ"] for k in liste)
    typwechsel = 0
    max_je_tab = cfg["auswahl"]["max_je_tabelle"]

    def frei(c):
        return c["id"] not in benutzt and je_tab[c["code"]] < max_je_tab and (not nur or c["typ"] in nur)

    def naechster_ersatz(k, versuche):
        if versuche < 25:
            c = next((c for c in zelle[(k["bereich"], k["typ"])] if frei(c)), None)
            if c is not None:
                return c
        typen = sorted({t for (b, t), z in zelle.items() if b == k["bereich"] and t != 36 and any(frei(c) for c in z)},
                       key=lambda t: (geplant[t], t))
        for t in typen:
            c = next((c for c in zelle[(k["bereich"], t)] if frei(c)), None)
            if c is not None:
                return c
        return None

    for i, k in enumerate(liste, 1):
        versuch, ersatz_von = k, None
        spec = info = None
        grund = ""
        for versuche in range(60):
            try:
                t, meta = lade(versuch["code"], versuch["ordner"])
                F = G.farbschema(k["thema"], k["palette"])
                spec, info = D.baue(versuch, t, profile[versuch["code"]], meta, F, geo_ordner,
                                    versuch["statistik"] in stich, seed)
                break
            except Exception as e:  # noqa: BLE001 – jeder Baufehler führt zu Ersatz und wird protokolliert
                grund = f"{versuch['id']}: {type(e).__name__}: {e}"
                nicht.append({"id": k["id"], "grund": grund})
                ersatz = naechster_ersatz(k, versuche)
                if ersatz is None:
                    break
                benutzt.add(ersatz["id"]); je_tab[ersatz["code"]] += 1
                ersatz_von = ersatz_von or versuch["id"]
                versuch = ersatz
                spec = None
        if spec is None:
            continue
        if ersatz_von:
            ersetzt += 1
            if versuch["typ"] != k["typ"]:
                typwechsel += 1
                geplant[k["typ"]] -= 1
                geplant[versuch["typ"]] += 1
        k2 = {**versuch, "thema": k["thema"], "palette": k["palette"], "ersetzt": ersatz_von or ""}
        prob = pruefe_diagramm(spec, info, k2, (k["thema"], k["palette"]) in gueltig, cfg["text"]["max_titel_zeichen"])
        for p in prob:
            qual[p.split(" ")[0]] += 1
        gebaut.append((k2, spec, info, prob))
        if i % 100 == 0:
            print(f"    {i}/{len(liste)} gebaut")
    # laufende Nummer je Tabelle
    nr = Counter()
    for k2, spec, info, prob in sorted(gebaut, key=lambda x: (x[0]["code"], x[0]["typ"])):
        nr[k2["code"]] += 1
        k2["nr"] = nr[k2["code"]]
    print(f"[5] Diagrammbau: {len(gebaut)} gebaut, {ersetzt} durch Ersatzkandidaten (davon {typwechsel} mit anderem Typ), "
          f"{len(liste) - len(gebaut)} Plätze unbesetzt, {len(nicht)} verworfene Bauversuche")

    # ------------------------------------------------ Stufen 6–7: speichern, prüfen, rendern
    try:
        import vl_convert as vlc
        vl_ver = getattr(vlc, "__version__", "?")
    except ImportError:
        vlc, vl_ver = None, None
    if args.ohne_png:
        vlc = None
    alt_manifest = {}
    mp = aus / "manifest.json"
    if mp.exists() and not args.neu:  # bei Neuerzeugung werden alle PNG neu gerendert
        try:
            alt_manifest = {m["datei"]: m for m in json.loads(mp.read_text(encoding="utf-8"))["diagramme"]}
        except (ValueError, KeyError):
            alt_manifest = {}
    manifest, qual_zeilen, png_n = [], [], 0
    bereich_ordner = {}
    def zielordner(k2):
        """Kurze Ablagepfade (Windows: max. 260 Zeichen): Bereich / Statistik (gekürzt) / Tabellencode."""
        teile = Path(k2["ordner"]).parts
        stat = teile[1] if len(teile) > 1 else k2["statistik"]
        stat = stat[:32].rstrip(" ._,-")
        return aus / teile[0] / stat / k2["code"]

    for k2, spec, info, prob in gebaut:
        ordner = zielordner(k2)
        ordner.mkdir(parents=True, exist_ok=True)
        for suf in ("_flatfile.csv", "_metadaten.json"):
            q = export / k2["ordner"] / f"{k2['code']}{suf}"
            z = ordner / q.name
            if q.exists() and (not z.exists() or z.stat().st_size != q.stat().st_size):
                shutil.copy2(q, z)
        name = f"{k2['code']}_{k2['nr']:02d}_{TYPEN[k2['typ']][0]}"
        spec_txt = json.dumps(spec, ensure_ascii=False, indent=1, default=_jsonwert)
        (ordner / f"{name}.vl.json").write_text(spec_txt, encoding="utf-8")
        spec_hash = sha(spec_txt.encode("utf-8"))
        png = ordner / f"{name}.png"
        png_hash = None
        if vlc is not None:
            alt = alt_manifest.get(str((ordner / name).relative_to(aus)))
            if not (png.exists() and alt and alt.get("sha256_spec") == spec_hash):
                try:
                    png.write_bytes(vlc.vegalite_to_png(json.loads(spec_txt), scale=2, vl_version="5.21"))
                except Exception as e:  # noqa: BLE001
                    prob.append(f"Q12 Rendering fehlgeschlagen: {str(e)[:120]}")
                    qual["Q12"] += 1
            if png.exists():
                png_hash = sha(png.read_bytes())
                png_n += 1
        eintrag = {"datei": str((ordner / name).relative_to(aus)), "tabelle": k2["code"],
                   "tabellentitel": Path(k2["ordner"]).name.split("_", 1)[-1], "quellordner": k2["ordner"], "nr": k2["nr"],
                   "bereich": k2["bereich"], "statistik": k2["statistik"], "typ": k2["typ"], "typname": TYPEN[k2["typ"]][0],
                   "thema": k2["thema"], "palette": k2["palette"], "titel": info["titel"], "sachzeile": info["sachzeile"],
                   "fakten": info["fakten"], "regel": k2["grund"], "qualitaetswert": k2["q"], "ausschnitt": k2["fix"],
                   "messgroesse": k2["vv"], "ersetzt": k2["ersetzt"], "pruefung": prob, "sha256_spec": spec_hash,
                   "sha256_png": png_hash, "seed": seed, "regelversion": REGEL_VERSION}
        (ordner / f"{name}_info.json").write_text(json.dumps(eintrag, ensure_ascii=False, indent=1, default=_jsonwert), encoding="utf-8")
        manifest.append(eintrag)
        qual_zeilen.append({"datei": eintrag["datei"], "typ": k2["typ"], "probleme": "; ".join(prob) or "keine"})
        bereich_ordner.setdefault(k2["bereich"], []).append(eintrag)
    schreibe_csv(ber / "qualitaet.csv", qual_zeilen)
    schreibe_csv(ber / "nicht_baubar.csv", nicht, ["id", "grund"])
    schreibe_csv(ber / "auswahl.csv", [{**k2, "datei": f"{k2['code']}_{k2['nr']:02d}_{TYPEN[k2['typ']][0]}"} for k2, *_ in gebaut],
                 ["id", "code", "nr", "bereich", "statistik", "typ", "typname", "q", "n", "vv", "vv_label", "einheit", "dims",
                  "fix", "grund", "auswahlweg", "ersetzt", "thema", "palette", "datei", "ordner"])
    print(f"[6] Prüfung: {dict(qual) or 'keine Befunde'}")
    print(f"[7] PNG: {png_n}" + ("" if vlc else " (vl-convert nicht verfügbar oder --ohne-png: nur Spezifikationen)"))

    # ------------------------------------------------ Stufe 8
    versionen = {"python": sys.version.split()[0], "pandas": pd.__version__, "vl_convert": vl_ver, "vega_lite": "5.21",
                 "geometrie_sha256": GEO.INFO}
    (aus / "manifest.json").write_text(json.dumps({"erzeugt_von": "genesis_diagramme.py", "regelversion": REGEL_VERSION,
                                                   "seed": seed, "versionen": versionen, "anzahl": len(manifest),
                                                   "diagramme": manifest}, ensure_ascii=False, indent=1, default=_jsonwert),
                                        encoding="utf-8")
    # tatsächlich verwendete Konfiguration (einschließlich Überschreibungen per Kommandozeile) festhalten
    (aus / "config.yaml").write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
    if not nur and not args.stichprobe:
        aufraeumen(aus, manifest)
    import uebersicht as U
    args.uebersicht_pfad = U.schreibe_uebersicht(aus, manifest, seed)
    print(f"[8] Übersicht: {args.uebersicht_pfad}")
    if args.vorschau:
        schreibe_vorschau(manifest, aus, int(args.vorschau), seed)
    return {"kombis_gueltig": len(gueltig), "kombis_alle": len(prot), "unabh": unabh, "gebaut": len(gebaut),
            "ersetzt": ersetzt, "typwechsel": typwechsel, "unbesetzt": len(liste) - len(gebaut),
            "nicht_baubar": len(nicht), "png": png_n, "qualitaet": dict(qual),
            "endbestand": Counter((k2["bereich"], k2["typ"]) for k2, *_ in gebaut)}


def schreibe_vorschau(manifest, aus: Path, n: int, seed):
    """Entwicklungsvorschau: rendert Spezifikationen im Browser mit vega-embed (gleiche Vega-Lite-Version)."""
    je_typ = defaultdict(list)
    for e in manifest:
        je_typ[e["typ"]].append(e)
    wahl = []
    for t in sorted(je_typ):
        wahl += sorted(je_typ[t], key=lambda e: h(seed, "vorschau", e["datei"]))[:max(1, n // max(1, len(je_typ)))]
    specs = []
    for e in wahl[:n]:
        specs.append({"name": e["datei"], "spec": json.loads((aus / (e["datei"] + ".vl.json")).read_text(encoding="utf-8"))})
    (aus / "_zwischenspeicher" / "vorschau_specs.json").write_text(json.dumps(specs, ensure_ascii=False), encoding="utf-8")


# =========================================================================================== Ablauf
def main():
    ap = argparse.ArgumentParser(description="GENESIS -> synthetische Visualisierungen (Stufen 1–3)")
    ap.add_argument("--config", default=str(HIER / "config.yaml"))
    ap.add_argument("--bis", choices=["profil", "kandidaten", "auswahl", "bau", "alles"], default="alles")
    ap.add_argument("--ohne-png", action="store_true", help="keine PNG erzeugen")
    ap.add_argument("--nur", default="", help="nur Diagramme dieser Typen bauen, z. B. 1,20,30 (Entwicklung)")
    ap.add_argument("--stichprobe", type=int, default=0, help="nur N Diagramme je Typ bauen (Entwicklung/Test)")
    ap.add_argument("--vorschau", default="", help="HTML-Vorschau (vega-embed) mit höchstens N Diagrammen schreiben")
    ap.add_argument("--neu", action="store_true", help="Zwischenspeicher verwerfen")
    ap.add_argument("--max-sekunden", type=float, default=0, help="nach dieser Zeit sauber anhalten (fortsetzbar)")
    ap.add_argument("--anzahl", type=int, default=0,
                    help="Zielgröße N (überschreibt anzahl_diagramme aus config.yaml), z. B. 4000")
    ap.add_argument("--seed", type=int, default=None, help="Startwert (überschreibt seed aus config.yaml)")
    ap.add_argument("--ausgabe", default="",
                    help="Ergebnisordner (überschreibt pfade.ausgabe). Ohne Angabe wird bei --anzahl ein eigener "
                         "Ordner <ausgabe>_N<anzahl> verwendet, damit bestehende Läufe nicht überschrieben werden.")
    ap.add_argument("--wiederverwenden", action="store_true",
                    help="Zwischenspeicher und vorhandene PNG weiterverwenden (überschreibt immer_neu_erzeugen)")
    args = ap.parse_args()
    t0 = time.time()
    cfg = lade_config(Path(args.config))
    # Standard: jeder Lauf erzeugt alles neu (Profilierung, Kandidaten, Auswahl, Spezifikationen und PNG)
    if cfg.get("immer_neu_erzeugen", True) and not args.wiederverwenden:
        args.neu = True
    basis = Path(args.config).resolve().parent
    export = (basis / cfg["pfade"]["export"]).resolve()
    aus_standard = (basis / cfg["pfade"]["ausgabe"]).resolve()
    if args.seed is not None:
        cfg["seed"] = args.seed
    if args.anzahl:
        if args.anzahl < 1:
            ap.error("--anzahl muss positiv sein")
        cfg["anzahl_diagramme"] = args.anzahl
    if args.ausgabe:
        aus = (basis / args.ausgabe).resolve()
    elif args.anzahl:
        aus = aus_standard.with_name(f"{aus_standard.name}_N{args.anzahl}")
    else:
        aus = aus_standard
    print(f"[0] Ziel N = {cfg['anzahl_diagramme']} · Seed {cfg['seed']} · Ausgabe {aus} · "
          + ("vollständige Neuerzeugung" if args.neu else "Zwischenspeicher wird weiterverwendet"))
    # Profilierung (Stufen 1-2) ist unabhängig von N: Zwischenspeicher eines früheren Laufs übernehmen, falls vorhanden
    alt_cache = aus_standard / "_zwischenspeicher" / "tabellen.jsonl"
    neu_cache = aus / "_zwischenspeicher" / "tabellen.jsonl"
    if aus != aus_standard and alt_cache.exists() and not neu_cache.exists() and not args.neu:
        neu_cache.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(alt_cache, neu_cache)
        print(f"    Zwischenspeicher der Profilierung übernommen aus {alt_cache.parent}")
    ber = aus / "_bericht"
    cache_d = aus / "_zwischenspeicher"
    ber.mkdir(parents=True, exist_ok=True); cache_d.mkdir(parents=True, exist_ok=True)
    seed = cfg["seed"]
    cfgsig = h(REGEL_VERSION, json.dumps({k: cfg[k] for k in ("ausschluss", "kandidaten")}, sort_keys=True))[:12]

    # ------------------------------------------------ Stufe 1 + 2 je Tabelle (mit Zwischenspeicher)
    cpfad = cache_d / "tabellen.jsonl"
    cache = {}
    if cpfad.exists() and not args.neu:
        for zeile in cpfad.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(zeile); cache[r["code"]] = r
            except ValueError:
                pass
    dateien = sorted(export.rglob("*_flatfile.csv"))
    print(f"[1] {len(dateien)} Tabellen im Export {export}")
    neu_n = 0
    with open(cpfad, "a" if not args.neu else "w", encoding="utf-8") as cf:
        for i, f in enumerate(dateien, 1):
            code = f.name.replace("_flatfile.csv", "")
            st = f.stat()
            sig = f"{st.st_size}|{int(st.st_mtime)}|{cfgsig}"
            if code in cache and cache[code].get("sig") == sig:
                continue
            if args.max_sekunden and time.time() - t0 > args.max_sekunden:
                print(f"    angehalten nach {args.max_sekunden:.0f} s ({i - 1}/{len(dateien)}); erneut starten zum Fortsetzen")
                return
            rel = f.relative_to(export).parts
            bereich, statistik = rel[0][:1], rel[1].split("_")[0]
            r = {"code": code, "sig": sig, "ordner": str(f.parent.relative_to(export))}
            try:
                if st.st_size / 1e6 > cfg["ausschluss"]["max_mb"]:
                    r["profil"] = {"code": code, "bereich": bereich, "statistik": statistik,
                                   "mb": round(st.st_size / 1e6, 3), "zeilen": -1, "zeitpunkte": 0, "zeit_min": "",
                                   "zeit_max": "", "zeitformat": "", "wertmerkmale": [], "einheiten": {},
                                   "anteil_fehlend": 0, "dims": []}
                    r["kandidaten"] = []
                else:
                    t, dims = lade_tabelle(f)
                    prof = profiliere(code, f, bereich, statistik, t, dims)
                    r["profil"] = prof
                    r["kandidaten"] = [] if ausschlussgrund(prof, cfg) else kandidaten_fuer_tabelle(t, prof, cfg)
            except Exception as e:  # noqa: BLE001 – Fehler je Tabelle protokollieren, Lauf fortsetzen
                r["profil"] = {"code": code, "bereich": bereich, "statistik": statistik, "fehler": f"{type(e).__name__}: {e}",
                               "mb": round(st.st_size / 1e6, 3), "zeilen": 0, "zeitpunkte": 0, "dims": [],
                               "wertmerkmale": [], "einheiten": {}, "anteil_fehlend": 1, "zeit_max": ""}
                r["kandidaten"] = []
            cache[code] = r
            cf.write(json.dumps(r, ensure_ascii=False) + "\n"); cf.flush()
            neu_n += 1
            if neu_n % 200 == 0:
                print(f"    {i}/{len(dateien)} Tabellen verarbeitet")
    print(f"    {neu_n} neu berechnet, {len(dateien) - neu_n} aus dem Zwischenspeicher")

    codes = sorted({f.name.replace("_flatfile.csv", "") for f in dateien})
    profile = {c: cache[c]["profil"] for c in codes}
    ausschl = []
    gruende = {}
    for c in codes:
        g = ausschlussgrund(profile[c], cfg) if profile[c]["zeilen"] != -1 else f"E2 größer als {cfg['ausschluss']['max_mb']} MB"
        if g:
            gruende[c] = g
    if cfg["ausschluss"]["dubletten_entfernen"]:
        for c, g in dubletten({c: p for c, p in profile.items() if c not in gruende}).items():
            gruende[c] = g
    for c, g in sorted(gruende.items()):
        ausschl.append({"tabelle": c, "bereich": profile[c]["bereich"], "statistik": profile[c]["statistik"], "grund": g})

    prof_zeilen = []
    for c in codes:
        p = profile[c]
        rollen = Counter(d.get("rolle", "") for d in p.get("dims", []) if d.get("n", 0) > 1)
        prof_zeilen.append({"tabelle": c, "bereich": p["bereich"], "statistik": p["statistik"], "mb": p["mb"],
                            "zeilen": p["zeilen"], "zeitpunkte": p["zeitpunkte"], "zeitformat": p.get("zeitformat", ""),
                            "zeit_min": p.get("zeit_min", ""), "zeit_max": p.get("zeit_max", ""),
                            "wertmerkmale": len(p["wertmerkmale"]), "anteil_fehlend": p["anteil_fehlend"],
                            "dimensionen": "; ".join(f"{d['label']} [{d.get('rolle')}, {d.get('n')}]"
                                                     for d in p.get("dims", []) if d.get("n", 0) > 1),
                            **{f"rolle_{r}": rollen.get(r, 0) for r in ("laender", "kreise", "geschlecht", "alter",
                                                                          "klassen", "nominal", "unterjaehrig")},
                            "ausschluss": gruende.get(c, "")})
    schreibe_csv(ber / "profil_tabellen.csv", prof_zeilen)
    schreibe_csv(ber / "ausschluesse.csv", ausschl, ["tabelle", "bereich", "statistik", "grund"])
    print(f"[1] Profil: {len(codes)} Tabellen, {len(ausschl)} ausgeschlossen -> {ber / 'profil_tabellen.csv'}")
    if args.bis == "profil":
        return

    # ------------------------------------------------ Stufe 2: Kandidatenpool
    kand = []
    for c in codes:
        if c in gruende:
            continue
        p = profile[c]
        for k in cache[c]["kandidaten"]:
            kand.append({"id": f"{c}#{k['typ']:02d}", "code": c, "bereich": p["bereich"], "statistik": p["statistik"],
                         "ordner": cache[c]["ordner"], **k})
    schreibe_csv(ber / "kandidaten.csv", kand,
                 ["id", "code", "bereich", "statistik", "typ", "typname", "q", "v", "k", "l", "a", "n", "vv", "vv_label",
                  "einheit", "dims", "fix", "vv_liste", "grund", "ordner"])
    kap = [{"typ": t, "typname": TYPEN[t][0], **{f"bereich_{a}": sum(1 for k in kand if k["typ"] == t and k["bereich"] == a)
                                                  for a in sorted(BEREICHE)}} for t in sorted(TYPEN)]
    for z in kap:
        z["summe"] = sum(z[f"bereich_{a}"] for a in BEREICHE)
    schreibe_csv(ber / "kapazitaet.csv", kap)
    print(f"[2] Kandidaten: {len(kand)} aus {len(codes) - len(gruende)} Tabellen -> {ber / 'kandidaten.csv'}")
    if args.bis == "kandidaten":
        return

    # ------------------------------------------------ Stufe 3: Auswahl
    gew, quoten, info = auswahl(kand, cfg, seed)
    gew.sort(key=lambda k: (k["bereich"], k["code"], k["typ"]))
    for z in gew:
        z["nr"] = sum(1 for x in gew if x["code"] == z["code"] and x["typ"] < z["typ"]) + 1
    schreibe_csv(ber / "auswahl.csv", gew,
                 ["id", "code", "nr", "bereich", "statistik", "typ", "typname", "q", "n", "vv", "vv_label", "einheit",
                  "dims", "fix", "grund", "auswahlweg", "ordner"])
    schreibe_csv(ber / "quoten.csv", quoten)
    print(f"[3] Auswahl: {len(gew)} Diagramme (Ziel {cfg['anzahl_diagramme']}), IPF-Iterationen {info['ipf_iterationen']}")
    bau_info = {}
    if args.bis not in ("auswahl",):
        bau_info = stufen_4_bis_8(gew, kand, cache, profile, export, aus, ber, cfg, args, seed)

    # ------------------------------------------------ Kurzbericht
    A, T = sorted(BEREICHE), sorted(TYPEN)
    L = [f"# Bericht genesis_diagramme.py – Stufen 1–3", "",
         f"Seed {seed} · Regelversion {REGEL_VERSION} · Ziel N = {cfg['anzahl_diagramme']}", "",
         "## Tabellen", "", "| Bereich | Tabellen | ausgeschlossen | mit Kandidaten | Kandidaten | ausgewählt | Ziel (Wasserfüllung) |",
         "|---|---|---|---|---|---|---|"]
    for a in A:
        tab = [c for c in codes if profile[c]["bereich"] == a]
        L.append(f"| {a} {BEREICHE[a]} | {len(tab)} | {sum(c in gruende for c in tab)} | "
                 f"{len({k['code'] for k in kand if k['bereich'] == a})} | {sum(k['bereich'] == a for k in kand)} | "
                 f"{sum(k['bereich'] == a for k in gew)} | {info['ziel_bereiche'][a]} |")
    L += ["", "## Ausschlussgründe", ""]
    for g, n in Counter(x["grund"].split(" ")[0] for x in ausschl).most_common():
        L.append(f"- {g}: {n}")
    L += ["", "## Auswahl je Diagrammtyp und Bereich", "",
          "| Typ | " + " | ".join(A) + " | Summe | Kapazität | Ziel |", "|---|" + "---|" * (len(A) + 3)]
    for t in T:
        ist = [sum(1 for k in gew if k["typ"] == t and k["bereich"] == a) for a in A]
        L.append(f"| {t:02d} {TYPEN[t][0]} | " + " | ".join(map(str, ist)) +
                 f" | {sum(ist)} | {sum(1 for k in kand if k['typ'] == t)} | {info['ziel_typen'][t]} |")
    L += ["", f"Tabellen mit mindestens einem Diagramm: {len({k['code'] for k in gew})}",
          f"Statistiken mit mindestens einem Diagramm: {len({k['statistik'] for k in gew})}",
          f"Diagramme je Tabelle: {dict(sorted(Counter(Counter(k['code'] for k in gew).values()).items()))}",
          f"Obergrenze je Statistik und Bereich: {info['cap_statistik']}", "",
          f"Laufzeit: {time.time() - t0:.0f} s"]
    if bau_info:
        L += ["", "## Farbthemen und Paletten (Stufe 4)", "", f"gültige Kombinationen: {bau_info['kombis_gueltig']} von {bau_info['kombis_alle']}",
              "", "| Prüfung | Chi² | df | p | Cramérs V |", "|---|---|---|---|---|"]
        for z in bau_info["unabh"]:
            L.append(f"| {z['pruefung']} | {z['chi2']} | {z['df']} | {z['p']} | {z['cramers_v']} |")
        L += ["", "## Diagrammbau (Stufen 5–7)", "", f"gebaut: {bau_info['gebaut']}, ersetzt: {bau_info['ersetzt']} "
              f"(davon mit anderem Typ desselben Bereichs: {bau_info['typwechsel']}), unbesetzte Plätze: "
              f"{bau_info['unbesetzt']}, verworfene Bauversuche: {bau_info['nicht_baubar']} (Gründe in nicht_baubar.csv), "
              f"PNG: {bau_info['png']}", "", f"Qualitätsprüfung: {bau_info['qualitaet']}", "",
              "### Endbestand je Diagrammtyp und Bereich", "",
              "| Typ | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | Summe |", "|---|---|---|---|---|---|---|---|---|---|---|"]
        eb = bau_info["endbestand"]
        for t in sorted(TYPEN):
            zeile = [eb.get((str(b), t), 0) for b in range(1, 10)]
            if sum(zeile):
                L.append(f"| {t:02d} {TYPEN[t][0]} | " + " | ".join(map(str, zeile)) + f" | {sum(zeile)} |")
        L.append("| Summe | " + " | ".join(str(sum(v for (b, _), v in eb.items() if b == str(x))) for x in range(1, 10))
                 + f" | {sum(eb.values())} |")
    (ber / "bericht.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"    Bericht: {ber / 'bericht.md'}")
    # Übersicht aller erzeugten Diagramme im Browser öffnen
    if getattr(args, "uebersicht_pfad", None):
        import uebersicht as U
        U.oeffnen(args.uebersicht_pfad)


if __name__ == "__main__":
    main()
