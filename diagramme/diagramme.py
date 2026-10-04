# -*- coding: utf-8 -*-
"""
diagramme.py – Bau der Vega-Lite-Spezifikationen für die 36 Diagrammtypen (METHODE.md, Abschnitte 6 und 9).

Jede Grafik besteht aus: Überschrift (datengebunden), Sachzeile, eigentlicher Grafik und Quellzeile.
Überschriften entstehen aus Vorlagen, deren Lücken nur mit berechneten Werten gefüllt werden (Reiter & Dale 2000);
die stützenden Werte werden als 'fakten' zurückgegeben und im Manifest protokolliert.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path

import pandas as pd

import geometrie
from gestaltung import (Einheit, anzeige_label, de, dativ, farbabstand, klassen_schluessel, kuerze, kuerze_wort,
                        leuchtdichte, ohne_fuellwort_ende, quantor, sauberes_label, stellen, subjekt_kurz,
                        textfarbe_auf, umbruch, umbruch_label, zeilen_von, zeit_datum, zeit_text, MONATE)

FONT = "Arial"
W = 760                     # Breite der Grafik in px (PNG mit Skalierung 2: 1520 px)
INNEN = W - 44              # abzüglich Innenabstand links/rechts
MAX_TITEL = 110            # Überschrift höchstens zwei Zeilen zu je 62 Zeichen (METHODE 9.8)

LOCALE = {
    "number": {"decimal": ",", "thousands": ".", "grouping": [3], "currency": ["", " €"]},
    "time": {"dateTime": "%A, der %e. %B %Y, %X", "date": "%d.%m.%Y", "time": "%H:%M:%S",
             "periods": ["AM", "PM"], "days": ["Sonntag", "Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag",
                                               "Samstag"],
             "shortDays": ["So", "Mo", "Di", "Mi", "Do", "Fr", "Sa"], "months": MONATE,
             "shortMonths": ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"]},
}

VERAENDERUNG_RE = re.compile(r"Veränderung|Wachstum|gegenüber|Vorjahr|Zuwachsrate|Änderung", re.I)
ABK_REST_RE = re.compile(r"(?<![\wÄÖÜäöüß])[a-zäöüA-ZÄÖÜ][a-zäöüß]{0,12}\.(?=\s|$)")

AGGREGAT_BEZEICHNUNGEN = {"Gebietskörperschaften", "Gesamte Volkswirtschaft", "Alle Wirtschaftsbereiche"}
INS_RE = r"(?:^|[-_])INS(?:G|GES|GESAMT)?(?:[-_]\d+)?$|INSGESAMT"

ZEITMODUS = {4: "ende", 25: "ende", 20: None, 21: None, 22: None, 23: None, 24: None, 26: None}


class Unpassend(Exception):
    """Die Daten erlauben den geplanten Diagrammtyp beim Bau doch nicht (wird protokolliert)."""


# =========================================================================================== Kontext
class Kontext:
    def __init__(self, kand: dict, t: pd.DataFrame, prof: dict, meta: dict, F: dict, geo_ordner: Path,
                 stichprobe: bool, seed):
        from genesis_diagramme import Ausschnitt  # Datenzugriff wie in Stufe 2 (identische Ausschnitte)
        self.k, self.prof, self.F, self.geo_ordner, self.seed = kand, prof, F, geo_ordner, seed
        self.typ = int(kand["typ"])
        self.dims = kand["dims"] if isinstance(kand["dims"], list) else json.loads(kand["dims"])
        self.a = Ausschnitt(t, prof, kand["vv"])
        dimrollen = {d["i"]: d for d in prof["dims"]}
        self.dm = [dimrollen[i] for i in self.dims]
        zeit = ZEITMODUS.get(self.typ, "letzter")
        if self.typ == 7 and not any(d["rolle"] == "geschlecht" for d in self.dm):
            zeit = "ende"
        if any(d["rolle"] == "unterjaehrig" for d in self.dm):
            zeit = None
        self.d, self.fix = self.a.fixiere(self.dims, zeit)
        for d in self.dm:  # historische Einheiten „(bis …)“ entfernen
            self.d = self.d[~self.d[f"d{d['i']}"].str.contains(r"\(bis ", regex=True)]
        # Zwischensummen mit Insgesamt-Schlüssel (z. B. „ABGANG-INS-1“ = „Abgänge“) sind keine Kategorien:
        # fehlt eine Summenzeile, wird die erste zur Summenzeile, alle übrigen entfallen (METHODE 9.7)
        self.d = self.d.copy()
        for d in self.dm:
            cc = f"d{d['i']}_c"
            ins = self.d[cc].str.contains(INS_RE, regex=True)
            if ins.any():
                if not (self.d[cc] == "").any():
                    erster = sorted(self.d.loc[ins, cc].unique())[0]
                    self.d.loc[self.d[cc] == erster, cc] = ""
                    ins = self.d[cc].str.contains(INS_RE, regex=True)
                self.d = self.d[~ins]
        # Bezeichnungen mit „insgesamt“ („Staat insgesamt“, „Handwerk insgesamt“) sind Summenzeilen
        self.d = self.d.copy()
        for d in self.dm:
            cc, cl = f"d{d['i']}_c", f"d{d['i']}"
            ist = self.d[cl].str.contains(r"(?i)\binsgesamt\b", regex=True) & (self.d[cc] != "")
            if ist.any():
                if (self.d[cc] == "").any():
                    self.d = self.d[~ist]
                else:
                    self.d.loc[ist, cc] = ""
        self._aggregate_entfernen()
        # Anzeigeform aller Kategorien und Merkmalsbezeichnungen (METHODE 9.8)
        for d in self.dm:
            self.d[f"d{d['i']}"] = self.d[f"d{d['i']}"].map(anzeige_label)
        self.dm = [{**d, "label": anzeige_label(d["label"])} for d in self.dm]
        if not len(self.d) or self.d["value"].notna().sum() < 2:
            raise Unpassend("zu wenige Werte im Ausschnitt")
        schluessel = [f"d{d['i']}" for d in self.dm] + ["time"]
        # gleiche Bezeichnung auf mehreren Hierarchieebenen (z. B. WZ-Abschnitt und -Abteilung) mit gleichem Wert
        self.d = self.d.drop_duplicates(subset=schluessel + ["value"])
        if self.d.duplicated(subset=schluessel).any():
            raise Unpassend("Ausschnitt nicht eindeutig (mehrere Werte je Kategorie und Zeitpunkt)")
        teile = self.d
        for d in self.dm:
            teile = teile[teile[f"d{d['i']}_c"] != ""]
        basis = teile if teile["value"].notna().any() else self.d
        self.E = Einheit(self.a.unit, basis["value"].dropna().tolist())
        titel = (meta or {}).get("Content") or ""
        quellen = [self.a.vv_label]
        if titel and len(prof["wertmerkmale"]) == 1:
            quellen.append(re.split(r":", titel)[0].strip())
        formen = [f for f in (subjekt_kurz(q) for q in quellen) if f]
        # Subjekt ohne verbliebene Abkürzungen bevorzugen; sonst erste gültige Form
        self.S = next((f for f in formen if not ABK_REST_RE.search(f)), formen[0] if formen else sauberes_label(self.a.vv_label))
        self.vv = sauberes_label(self.a.vv_label)
        fixtext = " ".join(str(v) for v in self.fix.values())
        self.veraenderung = bool(VERAENDERUNG_RE.search(self.a.vv_label + " " + fixtext))
        self.anzahl = (not self.E.prozent and not self.E.index and self.E.basis in ("", "Personen")
                       and not self.a.quote)
        self.stichprobe = stichprobe
        self.fuss_extra: list[str] = []
        if getattr(self, "aggregate", None):
            self.fuss_extra.append("Ohne Zwischensumme " + ", ".join(f"„{anzeige_label(x)}“" for x in self.aggregate) + ".")
        self.dec = stellen([self.E.wert(v) for v in self.d["value"].dropna()])
        self.suf = self.E.suffix()

    def _aggregate_entfernen(self):
        """Zwischensummen ohne Kennzeichnung erkennen (METHODE 9.7): Eine Kategorie gilt als Aggregat, wenn ihr Wert
        zu allen (bis zu drei jüngsten) Zeitpunkten der Summe von mindestens zwei anderen Kategorien entspricht
        (Abweichung ≤ 0,2 % bei mindestens zwei, ≤ 0,05 % bei einem Zeitpunkt; Teilmengen aus 2 bis 4 Kategorien).
        Konsolidierte Aggregate, die nicht exakt die Summe ihrer Teile sind, stehen in AGGREGAT_BEZEICHNUNGEN.
        Nur für additive Größen und nominale Merkmale mit höchstens 12 Ausprägungen (bei Gebietsgliederungen wären
        zufällige Treffer zu wahrscheinlich). Geprüft wird über alle Zeitpunkte der Tabelle, nicht nur die gezeigten."""
        from itertools import combinations
        if self.a.quote or "/" in str(self.a.unit) or re.search(r"(?i)index|preis|quote|anteil|durchschn|\bje\b",
                                                                   str(self.a.vv_label)):
            return
        for d in self.dm:
            if d["rolle"] not in ("nominal", "klassen", "staaten"):
                continue
            cc, cl = f"d{d['i']}_c", f"d{d['i']}"
            andere = [x for x in self.dm if x is not d]
            try:
                alle, _ = self.a.fixiere(self.dims, None)
            except Exception:  # noqa: BLE001
                alle = self.d
            basis = alle[(alle[cc] != "") & ~alle[cl].str.contains(r"(?i)\binsgesamt\b|\(bis ", regex=True)
                         & ~alle[cc].str.contains(INS_RE, regex=True)]
            for x in andere:        # andere Merkmale auf ihre Summenzeile, falls vorhanden
                if (basis[f"d{x['i']}_c"] == "").any():
                    basis = basis[basis[f"d{x['i']}_c"] == ""]
            zeiten = sorted(basis["time"].unique())[-3:]
            kats = list(pd.unique(basis[cl]))
            if not 3 <= len(kats) <= 12 or not zeiten:
                continue
            werte = {z: dict(zip(basis[basis["time"] == z][cl], basis[basis["time"] == z]["value"])) for z in zeiten}
            tol = 0.002 if len(zeiten) >= 2 else 0.0005
            aggregat = set()
            for k in kats:
                rest = [x for x in kats if x != k]
                treffer = False
                for r in range(2, min(4, len(rest)) + 1):
                    for teil in combinations(rest, r):
                        ok = True
                        for z in zeiten:
                            v = werte[z].get(k)
                            if v is None or v != v or v <= 0:
                                ok = False
                                break
                            sm = sum(werte[z].get(t, float("nan")) for t in teil)
                            if not (sm == sm and abs(sm - v) <= tol * v):
                                ok = False
                                break
                        if ok:
                            treffer = True
                            break
                    if treffer:
                        break
                if treffer:
                    aggregat.add(k)
            aggregat |= {k for k in kats if k in AGGREGAT_BEZEICHNUNGEN}
            if aggregat and len(aggregat) < len(kats) - 1:
                self.d = self.d[~self.d[cl].isin(aggregat)]
                self.aggregate = sorted(aggregat)

    # ------------------------------------------------------------------ Datenzugriff
    def col(self, d):
        return f"d{d['i']}"

    def teile(self, dmx, d=None):
        """Zeilen ohne Summenzeile einer Dimension, in Reihenfolge des Auftretens."""
        d = self.d if d is None else d
        return d[d[f"d{dmx['i']}_c"] != ""]

    def summe(self, dmx, d=None):
        d = self.d if d is None else d
        s = d[d[f"d{dmx['i']}_c"] == ""]["value"]
        return float(s.iloc[0]) if len(s) and pd.notna(s.iloc[0]) else None

    def quer(self, dmx) -> list[dict]:
        d = self.teile(dmx)
        d = d[d["value"].notna()]
        return [{"k": str(k), "c": str(c), "v": self.E.wert(float(v))}
                for k, c, v in zip(d[self.col(dmx)], d[f"d{dmx['i']}_c"], d["value"])]

    def fmt(self, v, dec=None, suf=True, vorzeichen=False) -> str:
        dec = self.dec if dec is None else dec
        s = de(v, dec)
        if vorzeichen and v is not None and v > 0:
            s = "+" + s
        return s + (self.suf.replace(" ", "\u00a0") if suf else "")   # geschütztes Leerzeichen: kein Umbruch vor der Einheit

    def zeit_label(self):
        z = self.fix.get("Zeit")
        if z and "/" in z and " / " in z:
            a, b = z.split(" / ")
            return f"{zeit_text(a)} und {zeit_text(b)}"
        if z:
            return zeit_text(z)
        zs = sorted(self.d["time"].unique())
        return f"{zeit_text(zs[0])} bis {zeit_text(zs[-1])}" if len(zs) > 1 else zeit_text(zs[0])

    def sachzeile(self, zusatz="") -> str:
        nach = ", ".join(f"nach {dativ(d['label'])}" for d in self.dm
                         if d["rolle"] not in ("unterjaehrig",) and d["label"].strip())
        fest = [f"{anzeige_label(k)}: {anzeige_label(v)}" for k, v in self.fix.items()
                if k != "Zeit" and v != "Insgesamt" and str(k).strip()]
        teile = [self.vv, nach, *fest, self.zeit_label(), self.E.text()]
        if zusatz:
            teile.append(zusatz)
        return ", ".join(t for t in teile if t)

    def fuss(self) -> list[str]:
        f = [f"Quelle: Statistisches Bundesamt (Destatis), GENESIS-Online, Tabelle {self.k['code']}."]
        if self.stichprobe:
            f.append("Hochrechnung aus einer Stichprobe; Werte kleiner Gruppen sind unsicher.")
        return f + self.fuss_extra

    def h(self, *teile) -> float:
        """deterministische Pseudozufallszahl in [0, 1) (z. B. für Streuung im Streifendiagramm)."""
        x = hashlib.sha256("|".join(map(str, (self.seed, *teile))).encode()).hexdigest()
        return int(x[:8], 16) / 16 ** 8


def waehle_titel(varianten: list[str]) -> str:
    """Erste Vorlage, die höchstens MAX_TITEL Zeichen hat; sonst die kürzeste (umbrochen, nie abgeschnitten)."""
    for v in varianten:
        if v and len(v) <= MAX_TITEL:
            return v
    return min((v for v in varianten if v), key=len)


def achse_nom(F, **extra) -> dict:
    """Kategorienachse: mehrzeilige Beschriftung ('|' = Zeilenumbruch), keine Kürzung."""
    return {"title": None, "domain": False, "ticks": False, "labelLimit": 1000, "labelColor": F["ink"],
            "labelExpr": "split(datum.label, '|')", "labelLineHeight": 14, **extra}


def legende(**extra) -> dict:
    return {"title": None, "labelExpr": "split(datum.label, '|')", "labelLimit": 1000, "labelLineHeight": 14.5, **extra}


# =========================================================================================== Grundgerüst
def config(F: dict) -> dict:
    return {
        "font": FONT, "background": F["bg"], "view": {"stroke": None},
        "axis": {"labelFont": FONT, "titleFont": FONT, "labelColor": F["ink2"], "titleColor": F["ink2"],
                 "labelFontSize": 12.5, "titleFontSize": 12.5, "titleFontWeight": "normal", "gridColor": F["grid"],
                 "domainColor": F["domain"], "tickColor": F["domain"], "labelPadding": 5},
        "legend": {"labelFont": FONT, "titleFont": FONT, "labelColor": F["ink2"], "titleColor": F["ink2"],
                   "labelFontSize": 12.5, "titleFontSize": 12.5, "titleFontWeight": "normal", "orient": "top",
                   "direction": "horizontal", "symbolType": "square", "columnPadding": 14, "labelLimit": 260},
        "header": {"labelFont": FONT, "labelColor": F["ink"], "labelFontSize": 12.5, "titleFontSize": 0},
        "text": {"font": FONT, "color": F["ink2"]}, "title": {"font": FONT},
        "locale": LOCALE,
    }


def zusammensetzen(ctx: Kontext, haupt: dict, titel: str, sachzeile: str) -> dict:
    F = ctx.F
    fuss = umbruch(" ".join(ctx.fuss()), 118)
    return {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "background": F["bg"],
        "padding": {"left": 20, "right": 24, "top": 20, "bottom": 16},
        "title": {"text": umbruch(titel, 62), "subtitle": umbruch(sachzeile, 92), "anchor": "start",
                  "frame": "bounds", "font": FONT, "fontSize": 22, "fontWeight": "bold", "color": F["ink"],
                  "lineHeight": 27, "subtitleFont": FONT, "subtitleFontSize": 15, "subtitleColor": F["ink2"],
                  "subtitleLineHeight": 20, "subtitlePadding": 8, "offset": 20},
        "vconcat": [haupt, {
            "width": INNEN, "height": 15 * len(fuss),
            "data": {"values": [{"t": fuss}]},
            "mark": {"type": "text", "align": "left", "baseline": "top", "font": FONT, "fontSize": 11.5,
                     "lineHeight": 15, "color": F["muted"]},
            "encoding": {"text": {"field": "t", "type": "nominal"}, "x": {"value": 0}, "y": {"value": 0}}}],
        "spacing": 22,
        "config": config(F),
    }


def labelbreite(labels, px=6.9, maxb=260) -> int:
    """Breite der Kategorienbeschriftung in px aus der längsten Zeile (Zeilen durch '|' getrennt)."""
    laenge = max((len(z) for x in labels for z in str(x).split("|")), default=4)
    return int(min(maxb, laenge * px + 10))


def zeilenhoehe(labels, einzeilig=27) -> int:
    return max(einzeilig, 15 * max((zeilen_von(x) for x in labels), default=1) + 10)


def halo(F, enc: dict, mark: dict, daten=None) -> list:
    """Wertebeschriftung mit Hintergrund-Halo (lesbar über Linien und Gitter)."""
    zus = {"data": {"values": daten}} if daten is not None else {}
    return [{**zus, "mark": {**mark, "stroke": F["bg"], "strokeWidth": 4, "strokeJoin": "round"}, "encoding": enc},
            {**zus, "mark": mark, "encoding": enc}]


# =========================================================================================== Titelbausteine
def titel_rangfolge(ctx, rows):
    s = sorted(rows, key=lambda r: -r["v"])
    top, zweit = s[0], (s[1] if len(s) > 1 else None)
    S = ctx.S
    abstand = abs(top["v"] - zweit["v"]) if zweit else 99
    rel = abstand / abs(top["v"]) * 100 if top["v"] else 0
    grenze = 2.0 if ctx.stichprobe else 1.0
    knapp = zweit and ((ctx.E.prozent and abstand < grenze) or (not ctx.E.prozent and rel < grenze))
    fakten = {"hoechster": f"{top['k']}: {ctx.fmt(top['v'])}", "zweiter": f"{zweit['k']}: {ctx.fmt(zweit['v'])}" if zweit else ""}
    k = top["k"]
    if knapp:
        return waehle_titel([f"{S}: {k} knapp vor {zweit['k']}", f"{S}: {k} knapp vorn"]), fakten
    return waehle_titel([f"{S}: {k} mit {ctx.fmt(top['v'])} vorn", f"{S}: {k} vorn"]), fakten


def _zahl_prozent(p):
    return de(abs(p), 0 if abs(p) >= 10 else 1)


def titel_verlauf(ctx, pts, name=None, alle=None):
    """Überschrift für Zeitverläufe (METHODE 9.3). Nominalstil ohne finites Verb, damit keine Kongruenzfehler
    zwischen Subjekt und Verb entstehen („Ausgaben … sinkt“). Veränderungsraten erhalten eigene Vorlagen:
    ihr Anstieg/Rückgang wäre sinnlos („steigt auf −3,8 %“)."""
    (z0, v0), (z1, v1) = pts[0], pts[-1]
    j0, j1 = zeit_text(z0), zeit_text(z1)
    S = name or ctx.S
    fakten = {"anfang": f"{j0}: {ctx.fmt(v0)}", "ende": f"{j1}: {ctx.fmt(v1)}"}
    if ctx.veraenderung and alle:
        hz, hv = max(alle, key=lambda x: x[1])
        fakten["hoechster"] = f"{zeit_text(hz)}: {ctx.fmt(hv, vorzeichen=True)}"
        return waehle_titel([f"{S}: {j1} bei {ctx.fmt(v1, vorzeichen=True)}, Höchstwert {zeit_text(hz)} mit {ctx.fmt(hv, vorzeichen=True)}",
                             f"{S}: {j1} bei {ctx.fmt(v1, vorzeichen=True)}"]), fakten
    negativ = alle is not None and any(v is not None and v <= 0 for _, v in alle)
    if ctx.E.prozent or ctx.E.index or v0 is None or v0 <= 0 or negativ:
        diff = v1 - v0
        fakten["differenz"] = ctx.fmt(diff, vorzeichen=True)
        if abs(diff) < 0.05 * max(abs(v0), 1e-9) * (1 if not ctx.E.prozent else 0) + (0.5 if ctx.E.prozent else 0):
            return waehle_titel([f"{S}: {j1} kaum verändert gegenüber {j0}", f"{S}: kaum verändert"]), fakten
        wort = "Anstieg" if diff > 0 else "Rückgang"
        return waehle_titel([f"{S}: {wort} von {ctx.fmt(v0)} ({j0}) auf {ctx.fmt(v1)} ({j1})",
                             f"{S}: {wort} auf {ctx.fmt(v1)} bis {j1}"]), fakten
    p = (v1 / v0 - 1) * 100
    fakten["veraenderung_prozent"] = de(p, 1)
    if abs(p) < 0.5:
        return waehle_titel([f"{S}: {j1} nahezu unverändert bei {ctx.fmt(v1)}", f"{S}: nahezu unverändert"]), fakten
    wort = "Plus" if p > 0 else "Minus"
    return waehle_titel([f"{S}: {wort} von {_zahl_prozent(p)} Prozent seit {j0}",
                         f"{S}: {wort} von {_zahl_prozent(p)} %"]), fakten


def titel_anteil(ctx, part, share, basis=None):
    q = quantor(share)
    S = ctx.S
    fakten = {"anteil": f"{part}: {de(share, 1)} %"}
    wort = q[0].upper() + q[1:] if q else None
    return waehle_titel([f"{S}: {de(share, 0)} Prozent entfallen auf „{part}“" if " " in part else
                         f"{S}: {de(share, 0)} Prozent entfallen auf {part}"]), fakten


# =========================================================================================== Balkenfamilie
def _balken(ctx, rows, farbe_fn, titel, sachzusatz="", ref=None, ref_label=None, sortieren=True, lollipop=False,
            punkte=False, vorzeichen=False, suf=None):
    F = ctx.F
    suf = ctx.suf if suf is None else suf
    rows = sorted(rows, key=lambda r: -r["v"]) if sortieren else rows
    for r in rows:
        r["farbe"] = farbe_fn(r)
        r["k"] = umbruch_label(r["k"], 32)
        r["lab"] = de(r["v"], ctx.dec) + suf if not vorzeichen else (("+" if r["v"] > 0 else "") + de(r["v"], ctx.dec) + suf)
    lb = labelbreite([r["k"] for r in rows])
    zh = zeilenhoehe([r["k"] for r in rows])
    vmin, vmax = min(0, min(r["v"] for r in rows)), max(0, max(r["v"] for r in rows))
    spann = (vmax - vmin) or 1
    dom = [vmin - (0.22 * spann if vmin < 0 else 0), vmax + 0.2 * spann]
    if punkte:
        lo = min(r["v"] for r in rows)
        dom = [lo - 0.1 * (vmax - lo or 1), vmax + 0.25 * (vmax - lo or 1)]
    y = {"field": "k", "type": "nominal", "sort": [r["k"] for r in rows], "axis": achse_nom(F)}
    xs = {"field": "v", "type": "quantitative", "scale": {"domain": dom, "zero": not punkte, "nice": False},
          "axis": None if not punkte else {"title": None, "grid": True, "tickCount": 5, "domain": False, "ticks": False,
                                            "labelExpr": "format(datum.value, ',')"}}
    lagen = []
    if lollipop:
        lagen.append({"mark": {"type": "rule", "strokeWidth": 2}, "encoding": {
            "y": y, "x": {**xs, "field": "v0"}, "x2": {"field": "v"}, "color": {"field": "farbe", "type": "nominal", "scale": None}}})
        lagen.append({"mark": {"type": "circle", "size": 110, "opacity": 1}, "encoding": {
            "y": y, "x": xs, "color": {"field": "farbe", "type": "nominal", "scale": None}}})
        for r in rows:
            r["v0"] = 0
    elif punkte:
        lagen.append({"mark": {"type": "rule", "color": F["grid"], "strokeWidth": 1}, "encoding": {
            "y": y, "x": {**xs, "field": "lo"}, "x2": {"field": "v"}}})
        lagen.append({"mark": {"type": "circle", "size": 130, "opacity": 1, "stroke": F["bg"], "strokeWidth": 1.5},
                      "encoding": {"y": y, "x": xs, "color": {"field": "farbe", "type": "nominal", "scale": None}}})
        for r in rows:
            r["lo"] = dom[0]
    else:
        lagen.append({"mark": {"type": "bar", "cornerRadiusEnd": 3, "height": {"band": 0.68}}, "encoding": {
            "y": y, "x": xs, "color": {"field": "farbe", "type": "nominal", "scale": None}}})
    if ref is not None:
        lagen.append({"mark": {"type": "rule", "color": F["ink"], "strokeWidth": 1.2},
                      "encoding": {"x": {"datum": ref, "type": "quantitative", "scale": xs["scale"], "axis": None}}})
        lagen.append({"mark": {"type": "text", "align": "left", "dx": 4, "dy": -8, "fontWeight": "bold",
                               "color": F["ink"], "fontSize": 12}, "encoding": {
            "x": {"datum": ref, "type": "quantitative", "scale": xs["scale"], "axis": None}, "y": {"value": 0},
            "text": {"value": ref_label}}})
    enc = {"y": y, "x": xs, "text": {"field": "lab"}}
    lagen += halo(F, enc, {"type": "text", "align": {"expr": "datum.v < 0 ? 'right' : 'left'"},
                           "dx": {"expr": "datum.v < 0 ? -5 : 5"}, "fontSize": 12.5, "color": F["ink2"]})
    if vmin < 0 and not punkte:
        lagen.insert(0, {"mark": {"type": "rule", "color": F["domain"], "strokeWidth": 1},
                         "encoding": {"x": {"datum": 0, "type": "quantitative", "scale": xs["scale"], "axis": None}}})
    haupt = {"width": INNEN - lb - 12, "height": max(80, zh * len(rows)), "data": {"values": rows}, "layer": lagen}
    return zusammensetzen(ctx, haupt, titel[0], ctx.sachzeile(sachzusatz)), titel[1]


def ist_geordnet(labels) -> bool:
    """Geordnete Klassen auch ohne Rollenerkennung: ≥ 80 % der Bezeichnungen beginnen mit einer Zahl oder mit
    „unter“/„bis“ („1-9 Beschäftigte“, „20 - 49 tätige Personen“, „unter 5 tätige Personen“)."""
    labels = [str(x).replace("|", " ") for x in labels]
    if not labels:
        return False
    treffer = sum(bool(re.match(r"(\d|unter |bis |weniger als |mehr als |über )", x)) for x in labels)
    return treffer >= 0.8 * len(labels)


def ordne(labels, rolle=None) -> list:
    if rolle in ("klassen", "alter") or ist_geordnet(labels):
        return sorted(labels, key=lambda x: klassen_schluessel(str(x).replace("|", " ")))
    return list(labels)


def strukturbruch(werte) -> bool:
    """Sprung um mehr als das 50-Fache des Medians (z. B. Währungsumstellung) – Verlauf nicht darstellbar."""
    w = sorted(abs(v) for v in werte if v is not None)
    if len(w) < 3:
        return False
    med = w[len(w) // 2]
    return med > 0 and w[-1] > 50 * med


def dim_haupt(ctx, rollen=None):
    for d in ctx.dm:
        if rollen is None or d["rolle"] in rollen:
            return d
    raise Unpassend("keine passende Dimension")


def nur_laender(rows):
    return [r for r in rows if re.fullmatch(r"\d{2}", r["c"]) and "01" <= r["c"] <= "16"]


def b_rangfolge(ctx, lollipop=False, punkte=False):
    dm = dim_haupt(ctx)
    rows = ctx.quer(dm)
    if dm["rolle"] == "laender":
        rows = nur_laender(rows) or rows
    if len(rows) < 3:
        raise Unpassend("weniger als 3 Kategorien")
    rows = sorted(rows, key=lambda r: -r["v"])[:25]
    top = rows[0]["k"]
    tot = ctx.summe(dm)
    ref = ctx.E.wert(tot) if (tot is not None and ctx.a.quote and dm["summe"]) else None
    if ref is not None and not (min(r["v"] for r in rows) <= ref <= max(r["v"] for r in rows)):
        ref = None  # Summenzeile ist eine Summe, kein Durchschnitt
    titel = titel_rangfolge(ctx, rows)
    F = ctx.F
    return _balken(ctx, rows, lambda r: F["akzent"] if r["k"] == top else F["balken"],
                   titel, ref=ref, ref_label=f"Insgesamt: {ctx.fmt(ref)}" if ref is not None else None,
                   lollipop=lollipop, punkte=punkte)


def b_divergierend(ctx):
    dm = dim_haupt(ctx)
    rows = ctx.quer(dm)
    if dm["rolle"] == "laender":
        rows = nur_laender(rows) or rows
    F = ctx.F
    pos = sum(r["v"] > 0 for r in rows)
    neg = sum(r["v"] < 0 for r in rows)
    s = sorted(rows, key=lambda r: -r["v"])
    if pos < 2 or neg < 2:
        raise Unpassend("divergierende Balken brauchen mindestens je zwei positive und negative Werte")
    varianten = [f"{ctx.S}: {s[0]['k']} vorn, {s[-1]['k']} am stärksten im Minus",
                 f"{ctx.S}: {s[0]['k']} vorn, {s[-1]['k']} im Minus",
                 f"{ctx.S}: {pos}-mal Plus, {neg}-mal Minus"]
    titel = (waehle_titel(varianten),
             {"positiv": pos, "negativ": neg, "hoechster": f"{s[0]['k']}: {ctx.fmt(s[0]['v'])}",
              "niedrigster": f"{s[-1]['k']}: {ctx.fmt(s[-1]['v'])}"})
    return _balken(ctx, rows, lambda r: F["akzent"] if r["v"] >= 0 else F["akzent2"], titel, vorzeichen=True)


def b_abweichung(ctx):
    dm = dim_haupt(ctx, ("laender",))
    rows = nur_laender(ctx.quer(dm))
    bund = ctx.summe(dm)
    if bund is None or len(rows) < 10:
        raise Unpassend("kein Bundeswert")
    bund = ctx.E.wert(bund)
    if not (min(r["v"] for r in rows) <= bund <= max(r["v"] for r in rows)):
        raise Unpassend("Bundeswert ist eine Summe, kein Durchschnitt")
    for r in rows:
        r["v"] = r["v"] - bund
    s = sorted(rows, key=lambda r: -r["v"])
    ueber = sum(r["v"] > 0 for r in rows)
    einheit = " Pp." if ctx.E.prozent else ctx.suf
    F = ctx.F
    titel = (waehle_titel([f"{ctx.S}: {s[0]['k']} am weitesten über dem Bundeswert",
                           f"{ctx.S}: {ueber} Länder über dem Bundeswert", f"{ueber} Länder über dem Bundeswert"]),
             {"bundeswert": ctx.fmt(bund), "ueber": ueber, "groesste_abweichung": f"{s[0]['k']}: {de(s[0]['v'], ctx.dec)}{einheit}"})
    return _balken(ctx, rows, lambda r: F["akzent"] if r["v"] >= 0 else F["akzent2"], titel,
                   sachzusatz=f"Abweichung vom Bundeswert ({ctx.fmt(bund)})", vorzeichen=True, suf=einheit)


def b_veraenderung(ctx):
    dm = dim_haupt(ctx)
    d = ctx.teile(dm)
    zs = sorted(d["time"].unique())
    if len(zs) < 2:
        raise Unpassend("weniger als 2 Zeitpunkte")
    a, b = d[d["time"] == zs[0]], d[d["time"] == zs[-1]]
    va = dict(zip(a[ctx.col(dm)], a["value"]))
    rows = []
    for k, v in zip(b[ctx.col(dm)], b["value"]):
        v0 = va.get(k)
        if pd.notna(v) and v0 and pd.notna(v0) and v0 > 0:
            rows.append({"k": k, "c": "", "v": (v - v0) if ctx.E.prozent else (v / v0 - 1) * 100})
    if dm["rolle"] == "laender":
        pass
    if len(rows) < 3:
        raise Unpassend("zu wenige vergleichbare Werte")
    s = sorted(rows, key=lambda r: -r["v"])
    einheit = " Pp." if ctx.E.prozent else " %"
    j0, j1 = zeit_text(zs[0]), zeit_text(zs[-1])
    F = ctx.F
    ctx.dec = 1
    if s[0]["v"] > 0:
        haupt_t = f"{ctx.S}: {s[0]['k']} mit dem stärksten Anstieg (+{de(s[0]['v'], 1)}{einheit})"
    else:
        haupt_t = f"{ctx.S}: {s[-1]['k']} mit dem stärksten Rückgang ({de(s[-1]['v'], 1)}{einheit})"
    titel = (waehle_titel([haupt_t, f"{ctx.S}: Veränderung {j0} bis {j1}"]),
             {"groesster_anstieg": f"{s[0]['k']}: {de(s[0]['v'], 1)}{einheit}", "groesster_rueckgang": f"{s[-1]['k']}: {de(s[-1]['v'], 1)}{einheit}"})
    ctx.fix["Zeit"] = f"{zs[0]} / {zs[-1]}"
    zus = "Veränderung in Prozentpunkten" if ctx.E.prozent else "Veränderung in Prozent"
    ctx.E.text = lambda: zus  # Sachzeile: Einheit ist die Veränderung
    return _balken(ctx, rows, lambda r: F["akzent"] if r["v"] >= 0 else F["akzent2"], titel, vorzeichen=True, suf=einheit)


def b_saeulen(ctx, klassen=False):
    dm = dim_haupt(ctx)
    rows = ctx.quer(dm)
    if len(rows) < 3:
        raise Unpassend("zu wenige Kategorien")
    if not klassen:
        rows = sorted(rows, key=lambda r: -r["v"])[:8]
    else:
        rows = sorted(rows, key=lambda r: klassen_schluessel(r["k"]))
    F = ctx.F
    top = max(rows, key=lambda r: r["v"])
    for r in rows:
        r["lab"] = ctx.fmt(r["v"])
        r["farbe"] = F["akzent"] if (r is top or klassen) else F["balken"]
        r["kz"] = umbruch_label(r["k"], max(10, int(INNEN / len(rows) / 7.2)), 4)
    zeichen = max(10, int(INNEN / len(rows) / 7.2))
    schraeg = any(len(w) > zeichen for r in rows for w in r["k"].split())
    if schraeg:   # ein einzelnes Wort ist breiter als die Säule: schräg und einzeilig statt überlappend
        for r in rows:
            r["kz"] = r["k"]
    if klassen:
        tot = ctx.summe(dm)
        if tot and not ctx.a.quote and tot > 0:
            p = top["v"] / ctx.E.wert(tot) * 100
            vorlagen = ([f"{ctx.S}: am häufigsten {top['k']} ({de(p, 0)}\u00a0%)"] if ctx.anzahl else []) + \
                       [f"{ctx.S}: {de(p, 0)} Prozent entfallen auf {top['k']}"]
            titel = (waehle_titel(vorlagen), {"groesste_klasse": top["k"], "anteil": de(p, 1)})
        else:
            titel = (waehle_titel([f"{ctx.S}: {top['k']} mit dem höchsten Wert ({ctx.fmt(top['v'])})",
                                   f"{ctx.S}: {top['k']} mit dem höchsten Wert"]), {"hoechster": f"{top['k']}: {ctx.fmt(top['v'])}"})
    else:
        titel = titel_rangfolge(ctx, rows)
    x = {"field": "kz", "type": "nominal", "sort": [r["kz"] for r in rows],
         "axis": {"title": None, "labelAngle": -35 if schraeg else 0, "labelAlign": "right" if schraeg else "center",
                  "labelExpr": "split(datum.label, '|')", "domain": True,
                  "ticks": False, "labelColor": F["ink"], "labelLimit": 1000, "labelLineHeight": 14}}
    y = {"field": "v", "type": "quantitative", "axis": None,
         "scale": {"domain": [min(0, min(r["v"] for r in rows)), max(r["v"] for r in rows) * 1.15]}}
    lagen = [{"mark": {"type": "bar", "cornerRadiusEnd": 3, "width": {"band": 0.66}},
              "encoding": {"x": x, "y": y, "color": {"field": "farbe", "type": "nominal", "scale": None}}}]
    lagen += halo(F, {"x": x, "y": y, "text": {"field": "lab"}},
                  {"type": "text", "baseline": "bottom", "dy": -5, "fontSize": 12.5, "fontWeight": "bold", "color": F["ink"]})
    haupt = {"width": INNEN, "height": 330, "data": {"values": rows}, "layer": lagen}
    return zusammensetzen(ctx, haupt, titel[0], ctx.sachzeile()), titel[1]


# =========================================================================================== Zeit
def _zeitpunkte(ctx, d=None, unter=None):
    """[(Zeit-ISO, Zeitschlüssel, Wert)] – bei unterjähriger Dimension aus Jahr + Monat/Quartal zusammengesetzt."""
    d = ctx.d if d is None else d
    out = []
    for _, r in d[d["value"].notna()].iterrows():
        z = r["time"]
        if unter is not None:
            lab = str(r[f"d{unter['i']}"])
            code = r[f"d{unter['i']}_c"]
            if lab in MONATE:
                monat = MONATE.index(lab) + 1
            elif re.search(r"(\d)\.\s*Quartal", lab):
                monat = (int(re.search(r"(\d)\.\s*Quartal", lab).group(1)) - 1) * 3 + 1
            else:
                m = re.search(r"(\d+)$", code)
                if not m:
                    continue
                n = int(m.group(1))
                monat = n if unter["code"] == "MONAT" else (n - 1) * 3 + 1
            if not 1 <= monat <= 12:
                continue
            iso = f"{z[:4]}-{monat:02d}-01"
            key = f"{z[:4]}-{monat:02d}P1M" if unter["code"] == "MONAT" else f"{z[:4]}-{monat:02d}P3M"
        else:
            iso, key = zeit_datum(z), z
        out.append((iso, key, ctx.E.wert(float(r["value"]))))
    return sorted(out)


def _zeitachse(pts):
    jahre = sorted({p[0][:4] for p in pts})
    nur_jahr = all(p[0][5:] == "01-01" for p in pts)
    return {"field": "t", "type": "temporal", "title": None,
            "axis": {"format": "%Y" if (nur_jahr or len(jahre) > 3) else "%b %Y", "grid": False, "domain": True,
                     "ticks": True, "labelOverlap": "greedy",
                     "tickCount": min(10, max(3, len(jahre))) if (nur_jahr or len(jahre) > 3) else 6}}


def z_linie(ctx):
    F = ctx.F
    unter = next((d for d in ctx.dm if d["rolle"] == "unterjaehrig"), None)
    pts = _zeitpunkte(ctx, unter=unter)
    if len(pts) < 4:
        raise Unpassend("zu wenige Zeitpunkte")
    if strukturbruch([p[2] for p in pts]):
        raise Unpassend("Strukturbruch in der Zeitreihe (Sprung > 50 × Median)")
    if len({p[0] for p in pts}) < len(pts):
        raise Unpassend("mehrere Werte je Zeitpunkt")
    if sum(1 for p in pts if p[2] == 0) > len(pts) / 2:
        raise Unpassend("überwiegend Nullwerte")
    rows = [{"t": p[0], "v": p[2]} for p in pts]
    titel = titel_verlauf(ctx, [(pts[0][1], pts[0][2]), (pts[-1][1], pts[-1][2])], alle=[(p[1], p[2]) for p in pts])
    y = {"field": "v", "type": "quantitative", "title": None,
         "scale": {"zero": not (ctx.E.index or min(r["v"] for r in rows) > 0.5 * max(r["v"] for r in rows))},
         "axis": {"grid": True, "domain": False, "ticks": False, "tickCount": 5}}
    x = _zeitachse(pts)
    ende = rows[-1]
    lagen = [{"mark": {"type": "line", "strokeWidth": 2.6, "color": F["akzent"], "interpolate": "linear"},
              "encoding": {"x": x, "y": y}},
             {"data": {"values": [ende]}, "mark": {"type": "circle", "size": 60, "color": F["akzent"], "opacity": 1},
              "encoding": {"x": x, "y": y}},
             {"data": {"values": [{**ende, "lab": ctx.fmt(ende["v"])}]},
              "mark": {"type": "text", "align": "left", "dx": 8, "fontWeight": "bold", "fontSize": 13, "color": F["akzent"]},
              "encoding": {"x": x, "y": y, "text": {"field": "lab"}}}]
    haupt = {"width": INNEN - 110, "height": 320, "data": {"values": rows}, "layer": lagen}
    return zusammensetzen(ctx, haupt, titel[0], ctx.sachzeile()), titel[1]


def _reihen(ctx, dm):
    d = ctx.teile(dm)
    reihen = {}
    for k, g in d.groupby(ctx.col(dm), sort=False):
        pts = _zeitpunkte(ctx, g)
        if len(pts) >= 3:
            reihen[k] = pts
    return reihen


def z_hervorhebung(ctx):
    F = ctx.F
    dm = dim_haupt(ctx)
    reihen = _reihen(ctx, dm)
    if len(reihen) < 4:
        raise Unpassend("zu wenige Reihen")
    wachstum = {}
    for k, p in reihen.items():
        if p[0][2] and p[0][2] > 0 and not ctx.E.prozent:
            wachstum[k] = (p[-1][2] / p[0][2] - 1) * 100
        else:
            wachstum[k] = p[-1][2] - p[0][2]
    top = sorted(wachstum, key=lambda k: -wachstum[k])[:2]
    rows = []
    for k, p in reihen.items():
        for iso, _, v in p:
            rows.append({"t": iso, "v": v, "k": k, "farbe": F["cat"][top.index(k)] if k in top else F["balken"],
                         "breite": 2.6 if k in top else 1.2, "ord": 1 if k in top else 0})
    allpts = [q for p in reihen.values() for q in p]
    x = _zeitachse(allpts)
    y = {"field": "v", "type": "quantitative", "title": None, "axis": {"grid": True, "domain": False, "ticks": False, "tickCount": 5}}
    enden = [{"t": reihen[k][-1][0], "v": reihen[k][-1][2], "lab": umbruch(k, 22)[:3], "farbe": F["cat"][i]} for i, k in enumerate(top)]
    if len(enden) == 2:  # Endbeschriftungen nicht übereinander
        lo_, hi_ = min(p[2] for p in allpts), max(p[2] for p in allpts)
        a_, b_ = sorted(enden, key=lambda e: e["v"])
        mind = (hi_ - lo_) * 0.075 * max(len(a_["lab"]), len(b_["lab"]))
        if b_["v"] - a_["v"] < mind:
            mitte = (a_["v"] + b_["v"]) / 2
            a_["vl"], b_["vl"] = mitte - mind / 2, mitte + mind / 2
    for e in enden:
        e.setdefault("vl", e["v"])
    einheit = " Pp." if ctx.E.prozent else " %"
    k0 = top[0]
    art = "Zunahme" if ctx.E.prozent else "prozentualen Zunahme"
    titel = (waehle_titel([f"{ctx.S}: {k0} mit der stärksten {art}", f"{ctx.S}: {k0} mit der stärksten Zunahme"])
             if wachstum[k0] > 0 else
             waehle_titel([f"{ctx.S}: überall Rückgang, am geringsten bei {k0}" if all(w < 0 for w in wachstum.values())
                           else f"{ctx.S}: {k0} mit dem geringsten Rückgang"]),
             {"hervorgehoben": top, "veraenderung": {k: de(wachstum[k], 1) + einheit for k in top}})
    lagen = [{"mark": {"type": "line", "interpolate": "linear"},
              "encoding": {"x": x, "y": y, "detail": {"field": "k"}, "color": {"field": "farbe", "type": "nominal", "scale": None},
                           "strokeWidth": {"field": "breite", "type": "quantitative", "scale": None},
                           "order": {"field": "ord"}}},
             {"data": {"values": enden}, "mark": {"type": "text", "align": "left", "dx": 6, "fontWeight": "bold", "fontSize": 12.5, "lineHeight": 15},
              "encoding": {"x": x, "y": {**y, "field": "vl"}, "text": {"field": "lab"}, "color": {"field": "farbe", "type": "nominal", "scale": None}}}]
    haupt = {"width": INNEN - 170, "height": 330, "data": {"values": rows}, "layer": lagen}
    return zusammensetzen(ctx, haupt, titel[0], ctx.sachzeile(f"hervorgehoben: {', '.join(top)}")), titel[1]


def z_small_multiples(ctx):
    F = ctx.F
    dm = dim_haupt(ctx)
    reihen = _reihen(ctx, dm)
    if len(reihen) < 4:
        raise Unpassend("zu wenige Reihen")
    # Reihenfolge der Felder: nach letztem Wert absteigend (größte Reihen oben links)
    reihen = dict(sorted(reihen.items(), key=lambda kv: -(kv[1][-1][2] or 0))[:16])
    rows = [{"t": iso, "v": v, "k": umbruch_label(k, 24, 2)} for k, p in reihen.items() for iso, _, v in p]
    wachstum = {k: (p[-1][2] - p[0][2]) for k, p in reihen.items()}
    top = max(wachstum, key=lambda k: wachstum[k])
    titel = (waehle_titel([f"{ctx.S}: Entwicklung nach {dativ(dm['label'])}",
                           f"{ctx.S}: {top} mit dem stärksten Anstieg"]),
             {"staerkster_anstieg": f"{top}: {ctx.fmt(wachstum[top], vorzeichen=True)}"})
    spalten = 4
    breite = int((INNEN - (spalten - 1) * 16 - 50) / spalten)
    allpts = [q for p in reihen.values() for q in p]
    x = _zeitachse(allpts)
    x["axis"] = {**x["axis"], "tickCount": 3, "labelFontSize": 11}
    haupt = {"data": {"values": rows}, "columns": spalten, "spacing": {"row": 18, "column": 16},
             "facet": {"field": "k", "type": "nominal", "sort": [umbruch_label(k, 24, 2) for k in reihen], "title": None,
                       "header": {"labelAnchor": "start", "labelFontWeight": "bold", "labelPadding": 4,
                                  "labelExpr": "split(datum.label, '|')", "labelLimit": 1000, "labelLineHeight": 14}},
             "spec": {"width": breite, "height": 90, "layer": [
                 {"mark": {"type": "area", "color": F["akzent"], "opacity": 0.15}, "encoding": {"x": x, "y": {"field": "v", "type": "quantitative", "title": None, "axis": {"grid": True, "domain": False, "ticks": False, "tickCount": 3, "labelFontSize": 11}}}},
                 {"mark": {"type": "line", "color": F["akzent"], "strokeWidth": 2}, "encoding": {"x": x, "y": {"field": "v", "type": "quantitative"}}}]}}
    return zusammensetzen(ctx, haupt, titel[0], ctx.sachzeile()), titel[1]


def z_flaeche(ctx):
    F = ctx.F
    dm = dim_haupt(ctx)
    reihen = _reihen(ctx, dm)
    if len(reihen) < 2:
        raise Unpassend("zu wenige Teile")
    namen = ordne(list(reihen), dm["rolle"])[: len(F["cat"])]
    rows = [{"t": iso, "v": v, "k": umbruch_label(k, 30, 2), "o": namen.index(k)} for k in namen for iso, _, v in reihen[k]]
    letzte = {k: reihen[k][-1][2] for k in namen}
    s = sum(v for v in letzte.values() if v)
    top = max(letzte, key=lambda k: letzte[k])
    share = letzte[top] / s * 100 if s else 0
    titel = titel_anteil(ctx, top, share)
    x = _zeitachse([q for k in namen for q in reihen[k]])
    haupt = {"width": INNEN, "height": 320, "data": {"values": rows}, "mark": {"type": "area", "line": {"strokeWidth": 0.8, "stroke": F["bg"]}},
             "encoding": {"x": x, "y": {"field": "v", "type": "quantitative", "stack": "zero", "title": None,
                                        "axis": {"grid": True, "domain": False, "ticks": False, "tickCount": 5}},
                          "color": {"field": "k", "type": "nominal", "sort": [umbruch_label(k, 30, 2) for k in namen],
                                    "scale": {"range": F["cat"][: len(namen)]}, "legend": legende(columns=min(3, len(namen)))},
                          "order": {"field": "o"}}}
    return zusammensetzen(ctx, haupt, titel[0], ctx.sachzeile()), titel[1]


def z_saeulen(ctx):
    F = ctx.F
    pts = _zeitpunkte(ctx)
    if len(pts) < 3:
        raise Unpassend("zu wenige Zeitpunkte")
    pts = pts[-15:]
    if strukturbruch([p[2] for p in pts]):
        raise Unpassend("Strukturbruch in der Zeitreihe (Sprung > 50 × Median)")
    rows = [{"z": zeit_text(p[1]), "v": p[2], "lab": ctx.fmt(p[2], suf=False),
             "farbe": F["akzent"] if i == len(pts) - 1 else F["balken"]} for i, p in enumerate(pts)]
    titel = titel_verlauf(ctx, [(pts[0][1], pts[0][2]), (pts[-1][1], pts[-1][2])], alle=[(p[1], p[2]) for p in pts])
    x = {"field": "z", "type": "nominal", "sort": [r["z"] for r in rows],
         "axis": {"title": None, "labelAngle": 0 if len(rows) * max(len(r["z"]) for r in rows) * 7.5 < INNEN else -45,
                  "ticks": False, "labelColor": F["ink"], "domain": min(r["v"] for r in rows) >= 0}}
    lo, hi = min(0, min(r["v"] for r in rows)), max(0, max(r["v"] for r in rows))
    spann = (hi - lo) or 1
    y = {"field": "v", "type": "quantitative", "axis": None,
         "scale": {"domain": [lo - (0.12 * spann if lo < 0 else 0), hi + 0.12 * spann], "nice": False}}
    lagen = [{"mark": {"type": "bar", "cornerRadiusEnd": 3, "width": {"band": 0.66}},
              "encoding": {"x": x, "y": y, "color": {"field": "farbe", "type": "nominal", "scale": None}}}]
    if lo < 0:  # Nulllinie
        lagen.append({"data": {"values": [{"null": 0}]}, "mark": {"type": "rule", "color": F["domain"], "strokeWidth": 1},
                      "encoding": {"y": {"field": "null", "type": "quantitative", "scale": y["scale"], "axis": None}}})
    # Beschriftung: positive Säulen über dem Ende, negative unter dem Ende (zwei Ebenen mit festen Eigenschaften)
    gross = 11.5 if len(rows) > 10 else 12.5
    for bed, bl, dy in (("datum.v >= 0", "bottom", -5), ("datum.v < 0", "top", 5)):
        for lage in halo(F, {"x": x, "y": y, "text": {"field": "lab"}},
                         {"type": "text", "baseline": bl, "dy": dy, "fontSize": gross, "color": F["ink2"]}):
            lagen.append({"transform": [{"filter": bed}], **lage})
    haupt = {"width": INNEN, "height": 320, "data": {"values": rows}, "layer": lagen}
    return zusammensetzen(ctx, haupt, titel[0], ctx.sachzeile()), titel[1]


def z_heatmap_monat(ctx):
    F = ctx.F
    unter = next((d for d in ctx.dm if d["rolle"] == "unterjaehrig"), None)
    pts = _zeitpunkte(ctx, unter=unter)
    rows = []
    for iso, key, v in pts:
        m = int(iso[5:7])
        spalte = MONATE[m - 1][:3] if unter and unter["code"] == "MONAT" else f"{(m - 1) // 3 + 1}. Quartal"
        rows.append({"j": iso[:4], "m": spalte, "mo": m, "v": v})
    jahre = sorted({r["j"] for r in rows})[-15:]
    rows = [r for r in rows if r["j"] in jahre]
    if len(jahre) < 3:
        raise Unpassend("zu wenige Jahre")
    brks = klassen_grenzen([r["v"] for r in rows], 5)
    labels, cls = klassen_labels(brks, ctx.dec)
    if len(labels) < 3:
        raise Unpassend("weniger als drei Farbklassen – kaum Variation")
    for r in rows:
        r["kl"] = cls(r["v"])
    mittel = {}
    for r in rows:
        mittel.setdefault(r["m"], []).append(r["v"])
    best = max(mittel, key=lambda m: sum(mittel[m]) / len(mittel[m]))
    titel = (waehle_titel([f"{ctx.S}: im Mittel am höchsten im {best}", f"{ctx.S}: Verlauf über das Jahr"]),
             {"hoechster_mittelwert": best})
    if unter and unter["code"] == "MONAT":
        voll = {m[:3]: m for m in MONATE}
        titel = (waehle_titel([f"{ctx.S}: im Mittel am höchsten im {voll.get(best, best)}", f"{ctx.S}: Verlauf über das Jahr"]), titel[1])
    reihenfolge = sorted({(r["mo"], r["m"]) for r in rows})
    haupt = {"width": INNEN - 60, "height": max(160, 22 * len(jahre)), "data": {"values": rows},
             "mark": {"type": "rect", "stroke": F["bg"], "strokeWidth": 1.5},
             "encoding": {"x": {"field": "m", "type": "ordinal", "sort": [m for _, m in reihenfolge], "title": None,
                                "axis": {"orient": "top", "ticks": False, "domain": False, "labelAngle": 0}},
                          "y": {"field": "j", "type": "ordinal", "title": None, "axis": {"ticks": False, "domain": False}},
                          "color": {"field": "kl", "type": "ordinal", "sort": labels,
                                    "scale": {"domain": labels, "range": F["seq"][: len(labels)]},
                                    "legend": {"title": ctx.E.text(), "orient": "top", "direction": "horizontal"}}}}
    return zusammensetzen(ctx, haupt, titel[0], ctx.sachzeile()), titel[1]


def z_slope(ctx):
    F = ctx.F
    dm = dim_haupt(ctx)
    d = ctx.teile(dm)
    zs = sorted(d["time"].unique())
    if len(zs) < 2:
        raise Unpassend("weniger als 2 Zeitpunkte")
    a, b = zs[0], zs[-1]
    wa = dict(zip(d[d["time"] == a][ctx.col(dm)], d[d["time"] == a]["value"]))
    wb = dict(zip(d[d["time"] == b][ctx.col(dm)], d[d["time"] == b]["value"]))
    ks = [k for k in wb if pd.notna(wb[k]) and k in wa and pd.notna(wa[k])][:12]
    if len(ks) < 3:
        raise Unpassend("zu wenige Kategorien")
    diff = {k: ctx.E.wert(wb[k]) - ctx.E.wert(wa[k]) for k in ks}
    auf = max(ks, key=lambda k: diff[k])
    ab = min(ks, key=lambda k: diff[k])
    ja, jb = zeit_text(a), zeit_text(b)
    rows = []
    for k in ks:
        f = F["akzent"] if k == auf else (F["akzent2"] if k == ab and diff[ab] < 0 else F["balken"])
        rows += [{"x": ja, "v": ctx.E.wert(wa[k]), "k": k, "farbe": f, "o": 1 if f != F["balken"] else 0},
                 {"x": jb, "v": ctx.E.wert(wb[k]), "k": k, "farbe": f, "o": 1 if f != F["balken"] else 0}]
    rechts = sorted([r for r in rows if r["x"] == jb], key=lambda r: r["v"])
    links = sorted([r for r in rows if r["x"] == ja], key=lambda r: r["v"])
    rng = (max(r["v"] for r in rows) - min(r["v"] for r in rows)) or 1
    for seite in (links, rechts):
        pos = dodge([r["v"] for r in seite], rng * 0.055)
        for r, p in zip(seite, pos):
            r["vl"] = p
            r["lab"] = f"{r['k']} {ctx.fmt(r['v'])}" if seite is rechts else ctx.fmt(r["v"])
    titel = (waehle_titel([f"{ctx.S}: {auf} mit dem stärksten Anstieg" if diff[auf] > 0 else
                           f"{ctx.S}: überall Rückgang seit {ja}", f"{ctx.S}: {ja} und {jb} im Vergleich"]),
             {"groesster_anstieg": f"{auf}: {ctx.fmt(diff[auf], vorzeichen=True)}", "groesster_rueckgang": f"{ab}: {ctx.fmt(diff[ab], vorzeichen=True)}"})
    x = {"field": "x", "type": "ordinal", "sort": [ja, jb], "title": None,
         "axis": {"orient": "top", "labelAngle": 0, "domain": False, "ticks": False, "labelFontWeight": "bold",
                  "labelColor": F["ink"], "labelFontSize": 13}, "scale": {"padding": 0.1}}
    y = {"field": "v", "type": "quantitative", "axis": None, "scale": {"zero": False}}
    yl = {"field": "vl", "type": "quantitative", "axis": None, "scale": {"zero": False}}
    lagen = [{"mark": {"type": "line", "strokeWidth": 2}, "encoding": {"x": x, "y": y, "detail": {"field": "k"},
                                                                       "color": {"field": "farbe", "type": "nominal", "scale": None}, "order": {"field": "o"}}},
             {"mark": {"type": "circle", "size": 45, "opacity": 1}, "encoding": {"x": x, "y": y, "color": {"field": "farbe", "type": "nominal", "scale": None}}},
             {"transform": [{"filter": f"datum.x == '{jb}'"}], "mark": {"type": "text", "align": "left", "dx": 8, "fontSize": 12},
              "encoding": {"x": x, "y": yl, "text": {"field": "lab"}, "color": {"value": F["ink2"]}}},
             {"transform": [{"filter": f"datum.x == '{ja}'"}], "mark": {"type": "text", "align": "right", "dx": -8, "fontSize": 12},
              "encoding": {"x": x, "y": yl, "text": {"field": "lab"}, "color": {"value": F["ink2"]}}}]
    haupt = {"width": 330, "height": 380, "data": {"values": rows}, "layer": lagen, "resolve": {"scale": {"y": "shared"}}}
    return zusammensetzen(ctx, haupt, titel[0], ctx.sachzeile()), titel[1]


def dodge(werte, abstand):
    """Beschriftungspositionen ohne Überlappung (vertikal), Reihenfolge bleibt erhalten."""
    pos = list(werte)
    for _ in range(50):
        bewegt = False
        for i in range(1, len(pos)):
            if pos[i] - pos[i - 1] < abstand:
                m = (pos[i] + pos[i - 1]) / 2
                pos[i - 1], pos[i] = m - abstand / 2, m + abstand / 2
                bewegt = True
        if not bewegt:
            break
    return pos


# =========================================================================================== Vergleich
def v_dumbbell(ctx):
    F = ctx.F
    ges = next((d for d in ctx.dm if d["rolle"] == "geschlecht"), None)
    kat = next((d for d in ctx.dm if d["rolle"] != "geschlecht"), None)
    if kat is None:
        raise Unpassend("keine Kategorie")
    d = ctx.teile(kat)
    if ges is not None:
        d = d[d[f"d{ges['i']}_c"] != ""]
        gruppen = list(pd.unique(d[ctx.col(ges)]))[:2]
        gcol = ctx.col(ges)
    else:
        zs = sorted(d["time"].unique())
        gruppen = [zs[0], zs[-1]]
        gcol = "time"
    if len(gruppen) < 2:
        raise Unpassend("keine zwei Gruppen")
    namen = {g: ("Männer" if str(g).startswith("männ") else "Frauen" if str(g).startswith("weib") else zeit_text(str(g))) for g in gruppen}
    werte = {}
    for _, r in d.iterrows():
        if pd.notna(r["value"]) and r[gcol] in gruppen:
            werte.setdefault(r[ctx.col(kat)], {})[r[gcol]] = ctx.E.wert(float(r["value"]))
    ks = [k for k, v in werte.items() if len(v) == 2][:15]
    if len(ks) < 3:
        raise Unpassend("zu wenige vollständige Paare")
    ks.sort(key=lambda k: -max(werte[k].values()))
    rel = [abs(werte[k][gruppen[0]] - werte[k][gruppen[1]]) / (max(abs(v) for v in werte[k].values()) or 1) for k in ks]
    if max(rel) < 0.05:
        raise Unpassend("Unterschiede zwischen den Gruppen unter 5 % – Hantel ohne Aussage")
    rows, verb = [], []
    vmax = max(max(werte[k].values()) for k in ks)
    for k in ks:
        a, b = werte[k][gruppen[0]], werte[k][gruppen[1]]
        kk = umbruch_label(k, 30)
        verb.append({"k": kk, "a": a, "b": b})
        rows += [{"k": kk, "g": namen[gruppen[0]], "v": a}, {"k": kk, "g": namen[gruppen[1]], "v": b}]
        verb[-1]["lab"] = f"{namen[gruppen[0]]} {ctx.fmt(a)} · {namen[gruppen[1]]} {ctx.fmt(b)}"
        verb[-1]["pos"] = max(a, b)
    gap = max(ks, key=lambda k: abs(werte[k][gruppen[0]] - werte[k][gruppen[1]]))
    titel = (waehle_titel([f"{ctx.S}: {gap} mit dem größten Unterschied"]),
             {"groesster_unterschied": f"{gap}: {namen[gruppen[0]]} {ctx.fmt(werte[gap][gruppen[0]])}, {namen[gruppen[1]]} {ctx.fmt(werte[gap][gruppen[1]])}"})
    lb = labelbreite([r["k"] for r in verb])
    y = {"field": "k", "type": "nominal", "sort": [r["k"] for r in verb], "axis": achse_nom(F)}
    vmin = min(min(werte[k].values()) for k in ks)
    lo = 0 if vmin < 0.4 * vmax else vmin * 0.85
    lo = lo - (vmax - lo) * 0.03           # Abstand der Punkte zur Achsenbeschriftung
    spann = (vmax + (vmax - lo) * 0.9) - lo
    breite = INNEN - lb - 12
    if max(abs(werte[k][gruppen[0]] - werte[k][gruppen[1]]) for k in ks) / spann * breite < 18:
        raise Unpassend("größter Unterschied unter 18 px – die Punkte der Hantel überdecken sich")
    xs = {"type": "quantitative", "scale": {"domain": [lo, vmax + (vmax - lo) * 0.9], "nice": False, "zero": False},
          "axis": None}
    lagen = [{"data": {"values": verb}, "mark": {"type": "rule", "strokeWidth": 3, "color": F["balken"]},
              "encoding": {"y": y, "x": {**xs, "field": "a"}, "x2": {"field": "b"}}},
             {"mark": {"type": "circle", "size": 150, "opacity": 1, "stroke": F["bg"], "strokeWidth": 2},
              "encoding": {"y": y, "x": {**xs, "field": "v"}, "color": {"field": "g", "type": "nominal",
                                                                         "scale": {"domain": [namen[g] for g in gruppen], "range": [F["cat"][0], F["cat"][1]]},
                                                                         "legend": {"title": None, "symbolType": "circle"}}}},
             {"data": {"values": verb}, "mark": {"type": "text", "align": "left", "dx": 12, "fontSize": 12, "color": F["ink2"]},
              "encoding": {"y": y, "x": {**xs, "field": "pos"}, "text": {"field": "lab"}}}]
    haupt = {"width": INNEN - lb - 12, "height": max(34, zeilenhoehe([r["k"] for r in verb])) * len(verb), "data": {"values": rows}, "layer": lagen}
    return zusammensetzen(ctx, haupt, titel[0], ctx.sachzeile()), titel[1]


def v_gruppiert(ctx):
    F = ctx.F
    g, k = ctx.dm[0], ctx.dm[1]
    d = ctx.d[(ctx.d[f"d{g['i']}_c"] != "") & (ctx.d[f"d{k['i']}_c"] != "") & ctx.d["value"].notna()]
    gruppen = list(pd.unique(d[ctx.col(g)]))[: min(4, len(F["cat"]))]
    kats = list(pd.unique(d[ctx.col(k)]))
    kats = ordne(kats, k["rolle"])[:10]
    gruppen = ordne(gruppen, g["rolle"])
    d = d[d[ctx.col(g)].isin(gruppen) & d[ctx.col(k)].isin(kats)]
    if len(gruppen) < 2 or len(kats) < 2:
        raise Unpassend("zu wenige Gruppen")
    rows = [{"k": umbruch_label(r[ctx.col(k)], 30), "g": umbruch_label(r[ctx.col(g)], 30, 2), "v": ctx.E.wert(float(r["value"]))} for _, r in d.iterrows()]
    for r in rows:
        r["lab"] = ctx.fmt(r["v"])
    top = max(rows, key=lambda r: r["v"])
    tk, tg = top["k"].replace("|", " "), top["g"].replace("|", " ")
    titel = (waehle_titel([f"{ctx.S}: Höchstwert bei „{tk}“ ({tg})", f"{ctx.S}: Höchstwert bei „{tk}“"]),
             {"hoechster": f"{tk} / {tg}: {ctx.fmt(top['v'])}"})
    lb = labelbreite([r["k"] for r in rows])
    y = {"field": "k", "type": "nominal", "sort": [umbruch_label(x, 30) for x in kats], "axis": achse_nom(F)}
    x = {"field": "v", "type": "quantitative", "axis": None, "scale": {"domain": [min(0, min(r["v"] for r in rows)), max(r["v"] for r in rows) * 1.2]}}
    gl = [umbruch_label(x, 30, 2) for x in gruppen]
    farbe = {"field": "g", "type": "nominal", "sort": gl, "scale": {"domain": gl, "range": F["cat"][: len(gruppen)]},
             "legend": legende(columns=min(2, len(gruppen)) if max(len(x) for x in gruppen) > 20 else len(gruppen))}
    yo = {"field": "g", "type": "nominal", "sort": gl}
    lagen = [{"mark": {"type": "bar", "cornerRadiusEnd": 2}, "encoding": {"y": y, "x": x, "color": farbe, "yOffset": yo}},
             {"mark": {"type": "text", "align": "left", "dx": 4, "fontSize": 11, "color": F["ink2"]},
              "encoding": {"y": y, "x": x, "yOffset": yo, "text": {"field": "lab"}}}]
    haupt = {"width": INNEN - lb - 12, "height": max(120, len(kats) * max(14 * len(gruppen) + 12, zeilenhoehe([r["k"] for r in rows]))), "data": {"values": rows}, "layer": lagen}
    return zusammensetzen(ctx, haupt, titel[0], ctx.sachzeile()), titel[1]


def v_pyramide(ctx):
    F = ctx.F
    ges = next(d for d in ctx.dm if d["rolle"] == "geschlecht")
    alt = next(d for d in ctx.dm if d["rolle"] != "geschlecht")
    d = ctx.d[(ctx.d[f"d{ges['i']}_c"] != "") & (ctx.d[f"d{alt['i']}_c"] != "") & ctx.d["value"].notna()]
    alter = sorted(pd.unique(d[ctx.col(alt)]), key=klassen_schluessel)
    if len(alter) < 5:
        raise Unpassend("zu wenige Altersgruppen")
    rows, summe = [], {"Männer": 0.0, "Frauen": 0.0}
    for _, r in d.iterrows():
        g = "Männer" if str(r[ctx.col(ges)]).startswith("männ") else "Frauen"
        v = ctx.E.wert(float(r["value"]))
        summe[g] += v
        rows.append({"a": r[ctx.col(alt)], "g": g, "v": v, "x": -v if g == "Männer" else v})
    m = max(abs(r["v"]) for r in rows)
    anteil_m = summe["Männer"] / (summe["Männer"] + summe["Frauen"]) * 100
    titel = (waehle_titel([f"{ctx.S}: {de(anteil_m, 0)} Prozent Männer, {de(100 - anteil_m, 0)} Prozent Frauen",
                           f"{de(anteil_m, 0)} Prozent Männer, {de(100 - anteil_m, 0)} Prozent Frauen"]),
             {"maenneranteil": de(anteil_m, 1) + " %"})
    lb = labelbreite([r["a"] for r in rows], maxb=200)
    # Bei vielen Altersjahren nur jede 5. Beschriftung (glatte Alter) plus erste und letzte Klasse
    if len(alter) > 25:
        def _z(a):
            m = re.search(r"\d+", str(a))
            return int(m.group()) if m else None
        zeige = [a for i, a in enumerate(alter) if i in (0, len(alter) - 1) or (_z(a) is not None and _z(a) % 5 == 0
                                                                                and 1 < i < len(alter) - 2)]
    else:
        zeige = list(alter)
    y = {"field": "a", "type": "nominal", "sort": list(reversed(alter)),
         "axis": {"title": None, "domain": False, "ticks": False, "labelLimit": 1000, "values": zeige, "labelOverlap": False}}
    hoehe = 20 * len(alter) if len(alter) <= 30 else min(6 * len(alter), 600)
    haupt = {"width": INNEN - lb - 12, "height": max(200, hoehe), "data": {"values": rows},
             "mark": {"type": "bar", "height": {"band": 0.8}},
             "encoding": {"y": y, "x": {"field": "x", "type": "quantitative", "title": ctx.E.text(),
                                        "scale": {"domain": [-m * 1.05, m * 1.05]},
                                        "axis": {"labelExpr": "format(abs(datum.value), ',')", "grid": True, "tickCount": 6}},
                          "color": {"field": "g", "type": "nominal", "scale": {"domain": ["Männer", "Frauen"], "range": [F["cat"][0], F["cat"][1]]},
                                    "legend": {"title": None}}}}
    return zusammensetzen(ctx, haupt, titel[0], ctx.sachzeile()), titel[1]


# =========================================================================================== Teil-Ganzes
def _teile(ctx, dm, max_teile):
    rows = ctx.quer(dm)
    tot = ctx.summe(dm)
    if tot is None or tot <= 0:
        raise Unpassend("keine Summenzeile")
    tot = ctx.E.wert(tot)
    rows = sorted(rows, key=lambda r: -r["v"])
    if len(rows) > max_teile:
        rest = sum(r["v"] for r in rows[max_teile - 1:])
        rows = rows[: max_teile - 1] + [{"k": "Übrige", "c": "", "v": rest}]
    for r in rows:
        r["p"] = r["v"] / tot * 100
    return rows, tot


def t_kreis(ctx, donut=True):
    F = ctx.F
    dm = ctx.dm[0]
    rows, tot = _teile(ctx, dm, min(4, len(F["cat"])))
    farben = F["cat"][: len(rows)]
    namen = []
    for i, r in enumerate(rows):
        r["o"] = i
        r["name"] = umbruch_label(f"{r['k']} ({de(r['p'], 0)}\u00a0%)", 34)
        r["farbe"] = F["balken"] if r["k"] == "Übrige" else farben[i]
        r["lab"] = f"{de(r['p'], 0)} %" if r["p"] >= 6 else ""
        r["tf"] = textfarbe_auf(r["farbe"])
        namen.append(r["name"])
    titel = titel_anteil(ctx, rows[0]["k"], rows[0]["p"])
    R = 165
    theta = {"field": "v", "type": "quantitative", "stack": True}
    farbe = {"field": "name", "type": "nominal", "sort": namen,
             "scale": {"domain": namen, "range": [r["farbe"] for r in rows]},
             "legend": legende(orient="right", direction="vertical", symbolType="circle", labelFontSize=13, rowPadding=8)}
    lagen = [{"mark": {"type": "arc", "innerRadius": 88 if donut else 0, "outerRadius": R, "stroke": F["bg"], "strokeWidth": 2},
              "encoding": {"theta": theta, "order": {"field": "o"}, "color": farbe}},
             {"mark": {"type": "text", "radius": (R + 88) / 2 if donut else R * 0.62, "fontSize": 13, "fontWeight": "bold"},
              "encoding": {"theta": theta, "order": {"field": "o"}, "text": {"field": "lab"},
                           "color": {"field": "tf", "type": "nominal", "scale": None}}}]
    if donut:
        lagen.append({"data": {"values": [{"t": [ctx.fmt(tot), "insgesamt"]}]},
                      "mark": {"type": "text", "fontSize": 15, "fontWeight": "bold", "color": F["ink"], "lineHeight": 18},
                      "encoding": {"text": {"field": "t"}}})
    haupt = {"width": 360, "height": 360, "data": {"values": rows}, "layer": lagen, "view": {"stroke": None}}
    return zusammensetzen(ctx, haupt, titel[0], ctx.sachzeile("Anteile an insgesamt")), titel[1]


def t_waffel(ctx):
    F = ctx.F
    dm = ctx.dm[0]
    rows, tot = _teile(ctx, dm, 3)
    # 100 Felder nach dem Verfahren der größten Reste
    roh = [r["p"] for r in rows]
    fl = [int(math.floor(x)) for x in roh]
    rest = 100 - sum(fl)
    for i in sorted(range(len(roh)), key=lambda i: -(roh[i] - fl[i]))[:max(0, rest)]:
        fl[i] += 1
    zellen, idx = [], 0
    for i, n in enumerate(fl):
        for _ in range(n):
            zellen.append({"x": idx % 10, "y": idx // 10, "k": umbruch_label(f"{rows[i]['k']} ({de(rows[i]['p'], 0)}\u00a0%)", 30)})
            idx += 1
    namen = [umbruch_label(f"{r['k']} ({de(r['p'], 0)}\u00a0%)", 30) for r in rows]
    farben = [F["akzent"], F["balken"], F["cat"][1]][: len(rows)] if len(rows) > 1 else [F["akzent"]]
    titel = titel_anteil(ctx, rows[0]["k"], rows[0]["p"])
    haupt = {"width": 330, "height": 330, "data": {"values": zellen}, "mark": {"type": "square", "size": 700, "opacity": 1},
             "encoding": {"x": {"field": "x", "type": "ordinal", "axis": None}, "y": {"field": "y", "type": "ordinal", "axis": None, "sort": "descending"},
                          "color": {"field": "k", "type": "nominal", "sort": namen, "scale": {"domain": namen, "range": farben},
                                    "legend": legende(title="1 Quadrat = 1 Prozent", orient="right", direction="vertical", symbolSize=200, rowPadding=6)}}}
    return zusammensetzen(ctx, haupt, titel[0], ctx.sachzeile("Anteile an insgesamt")), titel[1]


def squarify(werte, x, y, w, h):
    """Squarified Treemap (Bruls, Huizing & van Wijk 2000): Rechtecke mit möglichst quadratischem Seitenverhältnis."""
    werte = [v for v in werte]
    gesamt = sum(werte)
    flaechen = [v / gesamt * w * h for v in werte]
    out = []

    def schlechteste(reihe, seite):
        s = sum(reihe)
        return max(max(seite * seite * r / (s * s), (s * s) / (seite * seite * r)) for r in reihe)

    def lege(reihe, x, y, w, h):
        s = sum(reihe)
        if w >= h:
            bw = s / h
            yy = y
            for r in reihe:
                bh = r / bw
                out.append((x, yy, bw, bh))
                yy += bh
            return x + bw, y, w - bw, h
        bh = s / w
        xx = x
        for r in reihe:
            bw = r / bh
            out.append((xx, y, bw, bh))
            xx += bw
        return x, y + bh, w, h - bh

    rest = list(flaechen)
    reihe = []
    while rest:
        seite = min(w, h)
        r = rest[0]
        if not reihe or schlechteste(reihe + [r], seite) <= schlechteste(reihe, seite):
            reihe.append(r)
            rest.pop(0)
        else:
            x, y, w, h = lege(reihe, x, y, w, h)
            reihe = []
    if reihe:
        lege(reihe, x, y, w, h)
    return out


def _treemap_text(name, p, w, h, px=6.6, zeile=14):
    """Beschriftung einer Kachel: Name an Wortgrenzen umbrochen (nie mitten im Wort), darunter der Anteil.
    Passt ein Wort nicht in die Kachelbreite oder reichen die Zeilen nicht, entfällt der Name bzw. die ganze
    Beschriftung (dann nur über die Legende der großen Kacheln erkennbar)."""
    breite = int((w - 12) / px)
    max_zeilen = int((h - 10) / zeile)
    if breite < 4 or max_zeilen < 1:
        return []
    anteil = f"{de(p, 1)} %"
    zeilen = umbruch(name, breite)
    if max(len(z) for z in zeilen) <= breite and len(zeilen) + 1 <= max_zeilen:
        return zeilen + [anteil]
    return [anteil] if len(anteil) <= breite else []


def t_treemap(ctx):
    F = ctx.F
    dm = ctx.dm[0]
    rows, tot = _teile(ctx, dm, 30)
    rows = [r for r in rows if r["v"] > 0]
    Wp, Hp = INNEN, 420
    rects = squarify([r["v"] for r in rows], 0, 0, Wp, Hp)
    daten = []
    for i, (r, (x, y, w, h)) in enumerate(zip(rows, rects)):
        farbe = F["akzent"] if i == 0 else (F["cat"][1] if i == 1 else F["balken"])
        t = _treemap_text(r["k"], r["p"], w, h)
        daten.append({"x": x, "x2": x + w, "y": y, "y2": y + h, "farbe": farbe, "t": t, "tx": x + 6, "ty": y + 6,
                      "tf": textfarbe_auf(farbe)})
    titel = titel_anteil(ctx, rows[0]["k"], rows[0]["p"])
    sx = {"type": "quantitative", "scale": {"domain": [0, Wp]}, "axis": None}
    sy = {"type": "quantitative", "scale": {"domain": [0, Hp], "reverse": True}, "axis": None}
    lagen = [{"mark": {"type": "rect", "stroke": F["bg"], "strokeWidth": 2},
              "encoding": {"x": {**sx, "field": "x"}, "x2": {"field": "x2"}, "y": {**sy, "field": "y"}, "y2": {"field": "y2"},
                           "color": {"field": "farbe", "type": "nominal", "scale": None}}},
             {"mark": {"type": "text", "align": "left", "baseline": "top", "fontSize": 11.5, "lineHeight": 14},
              "encoding": {"x": {**sx, "field": "tx"}, "y": {**sy, "field": "ty"}, "text": {"field": "t"},
                           "color": {"field": "tf", "type": "nominal", "scale": None}}}]
    haupt = {"width": Wp, "height": Hp, "data": {"values": daten}, "layer": lagen}
    return zusammensetzen(ctx, haupt, titel[0], ctx.sachzeile("Anteile an insgesamt; Fläche proportional zum Wert")), titel[1]


def t_stapel(ctx, haeufigkeit=False):
    F = ctx.F
    teil, gruppe = ctx.dm[0], ctx.dm[1]
    if gruppe["summe"] is False and teil["summe"] is False:
        raise Unpassend("keine Summenzeile")
    d = ctx.d[ctx.d[f"d{gruppe['i']}_c"] != ""]
    teile = list(pd.unique(d[d[f"d{teil['i']}_c"] != ""][ctx.col(teil)]))
    teile = ordne(teile, teil["rolle"])
    if len(teile) > 6:
        raise Unpassend("zu viele Teile")
    if haeufigkeit:
        farben = rampe(list(reversed(F["seq"])), len(teile))
    elif len(teile) <= len(F["cat"]):
        farben = F["cat"][: len(teile)]
    elif len(teile) <= len(F["seq"]):
        farben = F["seq"][-len(teile):]   # mehr Teile als kategoriale Farben: sequenzielle Skala
    else:
        raise Unpassend("mehr Teile als unterscheidbare Farben")
    rows, labels, summen = [], [], {}
    gruppen = []
    for gname, g in d.groupby(ctx.col(gruppe), sort=False):
        tot = g[g[f"d{teil['i']}_c"] == ""]["value"]
        if not len(tot) or not pd.notna(tot.iloc[0]) or tot.iloc[0] <= 0:
            continue
        T = float(tot.iloc[0])
        start, zeilen = 0.0, []
        for i, tn in enumerate(teile):
            v = g[g[ctx.col(teil)] == tn]["value"]
            if not len(v) or not pd.notna(v.iloc[0]):
                zeilen = None
                break
            p = float(v.iloc[0]) / T * 100
            zeilen.append({"g": umbruch_label(gname, 32), "t": umbruch_label(tn, 34, 2), "x0": start, "x1": start + p, "p": p, "o": i,
                           "farbe": farben[i], "mid": start + p / 2, "lab": de(p, 0) if p >= 4 else "",
                           "tf": textfarbe_auf(farben[i])})
            start += p
        if zeilen:
            rows += zeilen
            summen[umbruch_label(gname, 32)] = start
            gruppen.append(umbruch_label(gname, 32))
    if len(gruppen) < 2:
        raise Unpassend("zu wenige vollständige Gruppen")
    gruppen = gruppen[:15]
    rows = [r for r in rows if r["g"] in gruppen]
    erst = {r["g"]: r["p"] for r in rows if r["o"] == 0}
    top = max(erst, key=lambda g: erst[g])
    topn = top.replace("|", " ")
    titel = (waehle_titel([f"{ctx.S}: „{teile[0]}“ mit dem größten Anteil bei „{topn}“ ({de(erst[top], 0)}\u00a0%)",
                           f"{ctx.S}: Zusammensetzung nach {dativ(gruppe['label'])}"]),
             {"hoechster_anteil": f"{topn}: {de(erst[top], 1)} % {teile[0]}"})
    lb = labelbreite(gruppen)
    xmax = max(100, max(summen.values()))
    y = {"field": "g", "type": "nominal", "sort": gruppen, "axis": achse_nom(F)}
    x = {"field": "x0", "type": "quantitative", "scale": {"domain": [0, xmax], "nice": False},
         "axis": {"title": None, "grid": False, "tickCount": 5, "labelExpr": "datum.value + ' %'", "domain": False}}
    namen = [umbruch_label(t, 34, 2) for t in teile]
    lagen = [{"mark": {"type": "bar", "height": {"band": 0.68}, "stroke": F["bg"], "strokeWidth": 1},
              "encoding": {"y": y, "x": x, "x2": {"field": "x1"},
                           "color": {"field": "t", "type": "nominal", "sort": namen, "scale": {"domain": namen, "range": farben},
                                     "legend": legende(columns=2 if sum(len(n) for n in namen) > 70 else len(namen))}}},
             {"mark": {"type": "text", "fontSize": 11.5}, "encoding": {"y": y, "x": {"field": "mid", "type": "quantitative"}, "text": {"field": "lab"},
                                                                         "color": {"field": "tf", "type": "nominal", "scale": None}}}]
    haupt = {"width": INNEN - lb - 12, "height": max(30, zeilenhoehe(gruppen, 30)) * len(gruppen), "data": {"values": rows}, "layer": lagen}
    rest = " Rest zu 100 %: ohne Angabe bzw. nicht zutreffend." if any(v < 99 for v in summen.values()) else ""
    if rest:
        ctx.fuss_extra.append(rest.strip())
    return zusammensetzen(ctx, haupt, titel[0], ctx.sachzeile("Anteile an insgesamt")), titel[1]


def rampe(farben: list, n: int) -> list:
    """n Farben aus einer geordneten Skala; bei Bedarf linear (in sRGB) zwischen den Stützfarben interpoliert."""
    if n <= len(farben):
        idx = [round(i * (len(farben) - 1) / max(1, n - 1)) for i in range(n)]
        return [farben[i] for i in idx]
    rgb = [tuple(int(f[i:i + 2], 16) for i in (1, 3, 5)) for f in farben]
    out = []
    for i in range(n):
        t = i * (len(rgb) - 1) / (n - 1)
        a, b = int(math.floor(t)), min(len(rgb) - 1, int(math.floor(t)) + 1)
        w = t - a
        out.append("#" + "".join(f"{round(rgb[a][j] * (1 - w) + rgb[b][j] * w):02x}" for j in range(3)))
    return out


def t_wasserfall(ctx):
    raise Unpassend("kein echter Saldo in den Daten")


# =========================================================================================== Verteilung
def _einheiten(ctx, dm):
    if re.search(r"(?i)gruppierung|aggregat", dm["label"]):
        raise Unpassend("Gruppierungen überschneiden sich – keine Verteilung gleichartiger Einheiten")
    rows = ctx.quer(dm)
    rows = [r for r in rows if r["v"] is not None]
    if len(rows) < 20:
        raise Unpassend("zu wenige Einheiten")
    return rows


def median(xs):
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def d_streifen(ctx):
    F = ctx.F
    dm = dim_haupt(ctx)
    rows = _einheiten(ctx, dm)
    vs = [r["v"] for r in rows]
    log = min(vs) > 0 and max(vs) / min(vs) > 50
    for r in rows:
        r["j"] = (ctx.h(r["c"] or r["k"]) - 0.5) * 50
    med = median(vs)
    lo, hi = min(rows, key=lambda r: r["v"]), max(rows, key=lambda r: r["v"])
    titel = (waehle_titel([f"{ctx.S}: Median bei {ctx.fmt(med)}, Spitze {hi['k']} mit {ctx.fmt(hi['v'])}",
                           f"{ctx.S}: Median bei {ctx.fmt(med)}"]),
             {"median": ctx.fmt(med), "minimum": f"{lo['k']}: {ctx.fmt(lo['v'])}", "maximum": f"{hi['k']}: {ctx.fmt(hi['v'])}"})
    achse = {"grid": True, "tickCount": 6, "labelExpr": "format(datum.value, ',')", "labelOverlap": "greedy", "labelSeparation": 6}
    if log:
        lo10, hi10 = math.floor(math.log10(min(vs))), math.ceil(math.log10(max(vs)))
        faktoren = (1, 2, 5) if hi10 - lo10 <= 3 else (1,)
        achse["values"] = [f * 10 ** e for e in range(lo10, hi10 + 1) for f in faktoren if min(vs) / 1.01 <= f * 10 ** e <= max(vs) * 1.01] or None
        achse["labelExpr"] = "format(datum.value, ',~r')"
    x = {"field": "v", "type": "quantitative", "title": ctx.E.text() + (" (logarithmische Skala)" if log else ""),
         "scale": {"type": "log" if log else "linear", "zero": False, "nice": not log}, "axis": achse}
    lagen = [{"mark": {"type": "circle", "size": 40, "opacity": 0.6, "color": F["akzent"]},
              "encoding": {"x": x, "yOffset": {"field": "j", "type": "quantitative", "scale": {"domain": [-40, 40]}},
                           "y": {"value": 70}}},
             {"data": {"values": [{"v": med, "lab": f"Median {ctx.fmt(med)}"}]}, "mark": {"type": "tick", "thickness": 3, "size": 80, "color": F["ink"]},
              "encoding": {"x": x, "y": {"value": 70}}},
             {"data": {"values": [{"v": med, "lab": f"Median {ctx.fmt(med)}"}]}, "mark": {"type": "text", "dy": -52, "fontWeight": "bold", "color": F["ink"]},
              "encoding": {"x": x, "y": {"value": 70}, "text": {"field": "lab"}}},
             {"data": {"values": [{**lo, "lab": umbruch(lo["k"], 26)[:3]}]},
              "mark": {"type": "text", "dy": 50, "fontSize": 11.5, "color": F["ink2"], "align": "left", "baseline": "top", "lineHeight": 14},
              "encoding": {"x": x, "y": {"value": 70}, "text": {"field": "lab"}}},
             {"data": {"values": [{**hi, "lab": umbruch(hi["k"], 26)[:3]}]},
              "mark": {"type": "text", "dy": 50, "fontSize": 11.5, "color": F["ink2"], "align": "right", "baseline": "top", "lineHeight": 14},
              "encoding": {"x": x, "y": {"value": 70}, "text": {"field": "lab"}}}]
    haupt = {"width": INNEN - 20, "height": 170, "data": {"values": rows}, "layer": lagen}
    return zusammensetzen(ctx, haupt, titel[0], ctx.sachzeile()), titel[1]


def nice_schritt(x):
    e = 10 ** math.floor(math.log10(x)) if x > 0 else 1
    for m in (1, 2, 2.5, 5, 10):
        if m * e >= x:
            return m * e
    return 10 * e


def d_histogramm(ctx):
    F = ctx.F
    dm = dim_haupt(ctx)
    rows = _einheiten(ctx, dm)
    vs = sorted(r["v"] for r in rows)
    n = len(vs)
    if vs[n // 2] > 0 and vs[-1] / vs[n // 2] > 20:
        raise Unpassend("Verteilung zu schief für ein Histogramm")
    q1, q3 = vs[int(n * 0.25)], vs[int(n * 0.75)]
    breite = 2 * (q3 - q1) / n ** (1 / 3) if q3 > q1 else (vs[-1] - vs[0]) / 10 or 1  # Freedman-Diaconis
    breite = nice_schritt(max(breite, (vs[-1] - vs[0]) / 25 or 1))
    start = math.floor(vs[0] / breite) * breite
    bins = {}
    for v in vs:
        b = start + math.floor((v - start) / breite) * breite
        if v == vs[-1] and b == v and v > start:   # Maximum auf der Klassengrenze (z. B. 100 %) zur letzten Klasse
            b -= breite
        bins[b] = bins.get(b, 0) + 1
    daten = [{"a": b, "b": b + breite, "n": c} for b, c in sorted(bins.items())]
    modal = max(daten, key=lambda x: x["n"])
    med = median(vs)
    titel = (waehle_titel([f"{ctx.S}: meist zwischen {de(modal['a'], ctx.dec)} und {de(modal['b'], ctx.dec)}{ctx.suf}",
                           f"{ctx.S}: Median {ctx.fmt(med)}"]),
             {"haeufigste_klasse": f"{de(modal['a'], ctx.dec)} bis unter {de(modal['b'], ctx.dec)}: {modal['n']}", "median": ctx.fmt(med)})
    haupt = {"width": INNEN - 50, "height": 300, "data": {"values": daten},
             "layer": [{"mark": {"type": "bar", "color": F["akzent"], "stroke": F["bg"], "strokeWidth": 1},
                        "encoding": {"x": {"field": "a", "type": "quantitative", "bin": {"binned": True, "step": breite},
                                           "title": ctx.E.text(), "axis": {"labelExpr": "format(datum.value, ',')", "grid": False, "labelOverlap": "greedy", "labelSeparation": 6}},
                                     "x2": {"field": "b"},
                                     "y": {"field": "n", "type": "quantitative", "title": f"Anzahl ({dm['label']})" if dm["label"] else "Anzahl",
                                           "axis": {"grid": True, "domain": False, "ticks": False, "tickMinStep": 1}}}},
                       {"data": {"values": [{"v": med}]}, "mark": {"type": "rule", "color": F["ink"], "strokeWidth": 1.5, "strokeDash": [4, 3]},
                        "encoding": {"x": {"field": "v", "type": "quantitative"}}},
                       {"data": {"values": [{"v": med, "lab": f"Median {ctx.fmt(med)}"}]},
                        "mark": {"type": "text", "align": "left", "dx": 5, "y": 8, "fontWeight": "bold", "color": F["ink"]},
                        "encoding": {"x": {"field": "v", "type": "quantitative"}, "text": {"field": "lab"}}}]}
    return zusammensetzen(ctx, haupt, titel[0], ctx.sachzeile()), titel[1]


def d_boxplot(ctx):
    F = ctx.F
    ein, grp = ctx.dm[0], ctx.dm[1]
    if re.search(r"(?i)gruppierung|aggregat", ein["label"]):
        raise Unpassend("Gruppierungen überschneiden sich – keine Verteilung gleichartiger Einheiten")
    d = ctx.d[(ctx.d[f"d{ein['i']}_c"] != "") & (ctx.d[f"d{grp['i']}_c"] != "") & ctx.d["value"].notna()]
    rows = [{"g": umbruch_label(r[ctx.col(grp)], 30), "v": ctx.E.wert(float(r["value"]))} for _, r in d.iterrows()]
    gruppen = list(dict.fromkeys(r["g"] for r in rows))
    gruppen = ordne(gruppen, grp["rolle"])
    if len(gruppen) < 2 or len(rows) < 30:
        raise Unpassend("zu wenige Werte")
    werte_g = {g: sorted(r["v"] for r in rows if r["g"] == g) for g in gruppen}
    spann = (max(r["v"] for r in rows) - min(r["v"] for r in rows)) or 1
    iqr = [w[int(len(w) * .75)] - w[int(len(w) * .25)] for w in werte_g.values() if len(w) >= 4]
    if not iqr or median(iqr) < 0.05 * spann:
        raise Unpassend("Boxen nicht erkennbar (Quartilsabstand < 5 % der Spannweite, stark schiefe Verteilung)")
    meds = {g: median(werte_g[g]) for g in gruppen}
    top = max(meds, key=lambda g: meds[g])
    topn = top.replace("|", " ")
    titel = (waehle_titel([f"{ctx.S}: höchster Median bei „{topn}“ ({ctx.fmt(meds[top])})", f"{ctx.S}: höchster Median bei „{topn}“"]),
             {"hoechster_median": f"{topn}: {ctx.fmt(meds[top])}"})
    lb = labelbreite(gruppen)
    haupt = {"width": INNEN - lb - 12, "height": max(44, zeilenhoehe(gruppen)) * len(gruppen), "data": {"values": rows},
             "mark": {"type": "boxplot", "extent": 1.5, "size": 22, "color": F["akzent"],
                      "median": {"color": F["bg"], "strokeWidth": 2}, "rule": {"color": F["ink2"]},
                      "outliers": {"color": F["akzent"], "opacity": 0.6, "size": 18}},
             "encoding": {"y": {"field": "g", "type": "nominal", "sort": gruppen, "axis": achse_nom(F)},
                          "x": {"field": "v", "type": "quantitative", "title": ctx.E.text(),
                                "axis": {"grid": True, "labelExpr": "format(datum.value, ',')", "labelOverlap": "greedy", "labelSeparation": 6}}}}
    ctx.fuss_extra.append("Box: mittlere 50 % der Werte, Strich: Median, Antennen: bis 1,5-facher Quartilsabstand.")
    return zusammensetzen(ctx, haupt, titel[0], ctx.sachzeile()), titel[1]


# =========================================================================================== Zusammenhang
def r_streu(ctx, blasen=False):
    F = ctx.F
    dm = dim_haupt(ctx)
    k = ctx.k
    vvs = k.get("vv_liste") or []
    if isinstance(vvs, str):
        vvs = json.loads(vvs)
    if len(vvs) < 2:
        raise Unpassend("keine zweite Messgröße")
    if dm["rolle"] not in ("laender", "kreise", "regbez", "staaten"):
        raise Unpassend("Streudiagramm nur für Gebietseinheiten (Merkmalsausprägungen sind sonst keine Beobachtungseinheiten)")
    from genesis_diagramme import Ausschnitt
    reihen, namen, einh = [], [], []
    for vv in vvs[: 3 if blasen else 2]:
        a = Ausschnitt(ctx._t, ctx.prof, vv)
        d, _ = a.fixiere([dm["i"]], "letzter")
        d = d[d[f"d{dm['i']}_c"] != ""]
        if dm["rolle"] == "laender":   # nur die 16 Länder (keine Positionen wie „Ausland“ oder „Restposition“)
            d = d[d[f"d{dm['i']}_c"].str.fullmatch(r"(0[1-9]|1[0-6])")]
        d = d.assign(**{f"d{dm['i']}": d[f"d{dm['i']}"].map(anzeige_label)})
        E = Einheit(a.unit, d["value"].dropna().tolist())
        reihen.append({r[f"d{dm['i']}"]: E.wert(float(r["value"])) for _, r in d.iterrows() if pd.notna(r["value"])})
        namen.append(sauberes_label(a.vv_label))
        if blasen and len(reihen) == 3 and (VERAENDERUNG_RE.search(a.vv_label) or min(reihen[-1].values(), default=0) < 0):
            raise Unpassend("Blasengröße braucht eine nichtnegative Bestandsgröße (keine Veränderungsrate)")
        einh.append(E.text())
    gemeinsam = [x for x in reihen[0] if all(x in r for r in reihen[1:])]
    if dm["rolle"] == "laender":
        pass
    if len(gemeinsam) < 8:
        raise Unpassend("zu wenige gemeinsame Einheiten")
    xs = [reihen[0][g] for g in gemeinsam]
    ys = [reihen[1][g] for g in gemeinsam]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    sxy = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    sx = math.sqrt(sum((a - mx) ** 2 for a in xs))
    sy = math.sqrt(sum((b - my) ** 2 for b in ys))
    r = sxy / (sx * sy) if sx and sy else 0
    if abs(r) > 0.98:
        raise Unpassend("Messgrößen nahezu identisch (|r| > 0,98)")
    staerke = "starker" if abs(r) >= 0.7 else ("mäßiger" if abs(r) >= 0.4 else "schwacher")
    richtung = "positiver" if r > 0 else "negativer"
    kurz = [subjekt_kurz(n_, 34) or n_ for n_ in namen]
    if kurz[0] == kurz[1]:
        kurz = namen[:2]
    if kurz[0] == kurz[1]:
        raise Unpassend("beide Messgrößen tragen dieselbe Bezeichnung")
    if abs(r) < 0.2:
        haupttitel = [f"{kurz[0]} und {kurz[1]}: kaum Zusammenhang"]
    else:
        haupttitel = [f"{kurz[0]} und {kurz[1]}: {staerke} {richtung} Zusammenhang"]
    titel = (waehle_titel(haupttitel), {"pearson_r": round(r, 3), "n": len(gemeinsam)})
    rows = []
    for g in gemeinsam:
        row = {"k": g, "x": reihen[0][g], "y": reihen[1][g]}
        if blasen:
            row["s"] = reihen[2][g]
        rows.append(row)
    # Beschriftung der drei auffälligsten Einheiten (größter Abstand zum Mittelpunkt, standardisiert)
    def z(rw):
        return ((rw["x"] - mx) / (sx / math.sqrt(len(xs)) or 1)) ** 2 + ((rw["y"] - my) / (sy / math.sqrt(len(ys)) or 1)) ** 2
    # Beschriftung: auffälligste Punkte, aber nur, wenn sie im Bild weit genug auseinanderliegen (keine Überlappung)
    B, H = INNEN - 80, 380
    xmin, xmax = min(xs), max(xs) or 1
    ymin, ymax = min(ys), max(ys) or 1
    def px(rw):
        return ((rw["x"] - xmin) / ((xmax - xmin) or 1) * B, (1 - (rw["y"] - ymin) / ((ymax - ymin) or 1)) * H)
    auff = []
    for rw in sorted(rows, key=lambda rw: -z(rw)):
        x0, y0 = px(rw)
        if all(abs(y0 - px(a)[1]) > 22 or abs(x0 - px(a)[0]) > 170 for a in auff):
            auff.append({**rw, "al": "right" if x0 > 0.62 * B else "left"})
        if len(auff) == 3:
            break
    enc = {"x": {"field": "x", "type": "quantitative", "title": umbruch(f"{namen[0]} ({einh[0]})", 80), "scale": {"zero": False},
                 "axis": {"grid": True, "labelExpr": "format(datum.value, ',')", "labelOverlap": "greedy", "labelSeparation": 6}},
           "y": {"field": "y", "type": "quantitative", "title": umbruch(f"{namen[1]} ({einh[1]})", 55), "scale": {"zero": False},
                 "axis": {"grid": True, "labelExpr": "format(datum.value, ',')", "labelOverlap": "greedy", "labelSeparation": 6}}}
    punkt = {"type": "circle", "opacity": 0.7, "color": F["akzent"], "stroke": F["bg"], "strokeWidth": 1}
    size_leg = {"title": umbruch(f"{namen[2]} ({einh[2]})", 60), "titleLimit": 1000, "symbolType": "circle", "symbolFillColor": F["akzent"],
                "symbolStrokeColor": F["bg"]} if blasen else None
    if blasen:
        size_leg["values"] = groessen_werte([rw["s"] for rw in rows])
    lagen = [{"mark": punkt, "encoding": {**enc, **({"size": {"field": "s", "type": "quantitative", "scale": {"range": [30, 900], "zero": True},
                                                              "legend": size_leg}} if blasen else {"size": {"value": 70}})}},
             {"data": {"values": [a for a in auff if a["al"] == "left"]},
              "mark": {"type": "text", "align": "left", "dx": 8, "dy": -6, "fontSize": 11.5, "color": F["ink"]},
              "encoding": {**enc, "text": {"field": "k"}}},
             {"data": {"values": [a for a in auff if a["al"] == "right"]},
              "mark": {"type": "text", "align": "right", "dx": -8, "dy": -6, "fontSize": 11.5, "color": F["ink"]},
              "encoding": {**enc, "text": {"field": "k"}}}]
    haupt = {"width": INNEN - 80, "height": 380, "data": {"values": rows}, "layer": lagen}
    return zusammensetzen(ctx, haupt, titel[0], ctx.sachzeile(f"Korrelation r = {de(r, 2)}, {len(gemeinsam)} Einheiten")), titel[1]


def r_heatmap(ctx):
    F = ctx.F
    d1, d2 = ctx.dm[0], ctx.dm[1]
    d = ctx.d[(ctx.d[f"d{d1['i']}_c"] != "") & (ctx.d[f"d{d2['i']}_c"] != "") & ctx.d["value"].notna()]
    a = list(pd.unique(d[ctx.col(d1)]))
    b = list(pd.unique(d[ctx.col(d2)]))
    a, b = ordne(a, d1["rolle"]), ordne(b, d2["rolle"])
    a, b = a[:16], b[:16]
    d = d[d[ctx.col(d1)].isin(a) & d[ctx.col(d2)].isin(b)]
    if len(a) < 3 or len(b) < 3:
        raise Unpassend("zu kleine Kreuztabelle")
    rows = [{"a": umbruch_label(r[ctx.col(d1)], 30), "b": r[ctx.col(d2)], "v": ctx.E.wert(float(r["value"]))} for _, r in d.iterrows()]
    # Zeilen ohne natürliche Ordnung nach Zeilenmittel absteigend sortieren (Muster sichtbar, METHODE 6.2)
    if d1["rolle"] not in ("klassen", "alter") and not ist_geordnet(a):
        mittel = {x: sum(r["v"] for r in rows if r["a"] == umbruch_label(x, 30)) for x in a}
        a = sorted(a, key=lambda x: -mittel[x])
    # Spaltenbreite aus verfügbarer Breite; Spaltenköpfe waagerecht und mehrzeilig statt gedreht und gekürzt
    lb = labelbreite([r["a"] for r in rows])
    zelle = int(max(44, min(120, (INNEN - lb - 12) / len(b))))
    zeichen = max(6, int((zelle - 6) / 6.3))
    waagerecht = all(len(umbruch(x, zeichen)) <= 4 and max(len(z) for z in umbruch(x, zeichen)) <= zeichen for x in b)
    kopf = (lambda x: umbruch_label(x, zeichen, 4)) if waagerecht else (lambda x: x)
    for r in rows:
        r["b"] = kopf(r["b"])
    brks = klassen_grenzen([r["v"] for r in rows], 5)
    labels, cls = klassen_labels(brks, ctx.dec)
    farbe = dict(zip(labels, F["seq"]))
    for r in rows:
        r["kl"] = cls(r["v"])
        r["tf"] = textfarbe_auf(farbe.get(r["kl"], F["na"]))
        r["lab"] = de(r["v"], ctx.dec) if len(rows) <= 120 and zelle >= 44 else ""
    top = max(rows, key=lambda r: r["v"])
    ta, tb = top["a"].replace("|", " "), top["b"].replace("|", " ")
    titel = (waehle_titel([f"{ctx.S}: Höchstwert bei „{ta}“ und „{tb}“ ({ctx.fmt(top['v'])})",
                           f"{ctx.S}: Muster nach {dativ(d1['label'])}"]),
             {"hoechster": f"{ta} / {tb}: {ctx.fmt(top['v'])}"})
    enc = {"y": {"field": "a", "type": "nominal", "sort": [umbruch_label(x, 30) for x in a], "title": None,
                 "axis": achse_nom(F, labelColor=F["ink2"])},
           "x": {"field": "b", "type": "nominal", "sort": [kopf(x) for x in b], "title": None,
                 "axis": achse_nom(F, orient="top", labelColor=F["ink2"],
                                   **({"labelAngle": 0, "labelBaseline": "bottom",
                                       "labelPadding": 5 + 14 * (max(zeilen_von(kopf(x)) for x in b) - 1)} if waagerecht else
                                      {"labelAngle": -40, "labelAlign": "left", "labelBaseline": "middle"}))}}
    lagen = [{"mark": {"type": "rect", "stroke": F["bg"], "strokeWidth": 1.5},
              "encoding": {**enc, "color": {"field": "kl", "type": "ordinal", "sort": labels,
                                            "scale": {"domain": labels, "range": F["seq"][: len(labels)]},
                                            "legend": {"title": ctx.E.text(), "orient": "top", "direction": "horizontal"}}}},
             {"mark": {"type": "text", "fontSize": 10.5}, "encoding": {**enc, "text": {"field": "lab"}, "color": {"field": "tf", "type": "nominal", "scale": None}}}]
    haupt = {"width": zelle * len(b), "height": max(26, zeilenhoehe([r["a"] for r in rows], 26)) * len(a), "data": {"values": rows}, "layer": lagen}
    return zusammensetzen(ctx, haupt, titel[0], ctx.sachzeile()), titel[1]


# =========================================================================================== Karten
def signif(x, stellen=2):
    if x == 0:
        return 0.0
    return round(x, -int(math.floor(math.log10(abs(x)))) + (stellen - 1))


def klassen_grenzen(werte, n=5):
    """Klassengrenzen: Quantile, auf zwei signifikante Stellen gerundet, streng steigend (METHODE 9.6)."""
    w = sorted(v for v in werte if v is not None)
    if not w:
        return [0]
    qs = [w[min(len(w) - 1, int(len(w) * i / n))] for i in range(1, n)]
    out = []
    for q in qs:
        r = signif(q, 2)
        if (not out or r > out[-1]) and w[0] < r <= w[-1]:
            out.append(r)
    return out or [signif(w[len(w) // 2], 2)]


def _stellen_fuer(brks):
    for d in range(0, 4):
        if len({de(b, d) for b in brks}) == len(brks) and all(abs(round(b, d) - b) < 1e-9 for b in brks):
            return d
    return 3


def klassen_labels(brks, dec):
    d = _stellen_fuer(brks)
    fmt = lambda b: de(b, d)  # noqa: E731
    labels = [f"unter {fmt(brks[0])}"] + [f"{fmt(a)} bis unter {fmt(b)}" for a, b in zip(brks[:-1], brks[1:])] + [f"{fmt(brks[-1])} und mehr"]

    def cls(v):
        if v is None:
            return "keine Angabe"
        for i, b in enumerate(brks):
            if v < b:
                return labels[i]
        return labels[-1]
    return labels, cls


def groessen_werte(werte):
    """Legendenwerte für Kreisgrößen: runde Werte vom kleinen bis zum großen Ende der Daten."""
    w = [v for v in werte if v and v > 0]
    if not w:
        return None
    lo, hi = min(w), max(w)
    kand = [signif(hi, 1), signif(hi / 3, 1), signif(hi / 10, 1), signif(lo * 1.5, 1)]
    return sorted({k for k in kand if lo * 0.5 <= k <= hi * 1.05})


def _karte_basis(ctx, ebene):
    geo = geometrie.gebiete(ebene, ctx.geo_ordner)
    ctx.fuss_extra.append("Geometrie: © GeoBasis-DE / BKG (2025), dl-de/by-2-0.")
    return geo


def k_choropleth(ctx, ebene="lan", divergierend=False):
    F = ctx.F
    rolle = {"lan": "laender", "krs": "kreise", "rbz": "regbez"}[ebene]
    dm = dim_haupt(ctx, (rolle,))
    geo = _karte_basis(ctx, ebene)
    stellen_n = geometrie.STELLEN[ebene]
    werte = {r["c"][:stellen_n]: r for r in ctx.quer(dm) if re.fullmatch(r"\d+", r["c"] or "") and len(r["c"]) >= stellen_n}
    treffer = [c for c in geo if c in werte]
    if len(treffer) < 0.8 * len(geo):
        raise Unpassend(f"nur {len(treffer)} von {len(geo)} Gebieten zugeordnet")
    bund = ctx.summe(dm)
    bund = ctx.E.wert(bund) if bund is not None else None
    vals = {c: werte[c]["v"] for c in treffer}
    if divergierend:
        if bund is None:
            raise Unpassend("kein Bundeswert")
        if not (min(vals.values()) <= bund <= max(vals.values())):
            raise Unpassend("Bundeswert ist eine Summe, kein Durchschnitt")
        vals = {c: v - bund for c, v in vals.items()}
        m = max(abs(v) for v in vals.values()) or 1
        s = nice_schritt(m / 2.5)
        brks = [-1.5 * s, -0.5 * s, 0.5 * s, 1.5 * s]
        labels, cls = klassen_labels(brks, ctx.dec)
        farben = F["div"]
    else:
        brks = klassen_grenzen(list(vals.values()), 5)
        labels, cls = klassen_labels(brks, ctx.dec)
        farben = F["seq"][: len(labels)] if len(labels) <= len(F["seq"]) else F["seq"]
    feats = []
    for c, g in geo.items():
        v = vals.get(c)
        kl = cls(v) if v is not None else "keine Angabe"
        feats.append({"type": "Feature", "geometry": g["geometry"],
                      "properties": {"c": c, "name": g["name"], "kl": kl, "v": v}})
    dom = labels + (["keine Angabe"] if any(f["properties"]["kl"] == "keine Angabe" for f in feats) else [])
    rng = list(farben[: len(labels)]) + ([F["na"]] if "keine Angabe" in dom else [])
    proj = {"type": "mercator"}
    lagen = [{"data": {"values": {"type": "FeatureCollection", "features": feats}, "format": {"type": "json", "property": "features"}},
              "mark": {"type": "geoshape", "stroke": F["domain"] if ebene == "lan" else F["bg"],
                       "strokeWidth": 0.7 if ebene == "lan" else 0.25},
              "encoding": {"color": {"field": "properties.kl", "type": "ordinal", "sort": dom,
                                     "scale": {"domain": dom, "range": rng},
                                     "legend": {"title": (("Abweichung in Prozentpunkten" if ctx.E.prozent else "Abweichung, " + ctx.E.text())
                                                          if divergierend else ctx.E.text()), "titleLimit": 1000,
                                                "orient": "top", "direction": "horizontal", "columns": 3, "symbolSize": 150}}}}]
    if ebene == "rbz":
        lan0 = geometrie.gebiete("lan", ctx.geo_ordner)
        lagen.insert(0, {"data": {"values": {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": g["geometry"], "properties": {}} for g in lan0.values()]},
                                  "format": {"type": "json", "property": "features"}},
                         "mark": {"type": "geoshape", "fill": F["bg"], "stroke": F["domain"], "strokeWidth": 0.8}})
        ctx.fuss_extra.append("Ohne Füllung: Länder ohne Regierungsbezirke.")
    if ebene != "lan":
        lan = geometrie.gebiete("lan", ctx.geo_ordner)
        lagen.append({"data": {"values": {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": g["geometry"], "properties": {}} for g in lan.values()]},
                               "format": {"type": "json", "property": "features"}},
                      "mark": {"type": "geoshape", "fill": None, "filled": False, "stroke": F["ink2"], "strokeWidth": 0.9}})
    if ebene == "lan":
        pts = []
        for c, g in geo.items():
            if c not in vals:
                continue
            lon, lat = g["pt"]
            dx, dy = geometrie.LAND_SCHIEBEN.get(c, (0, 0))
            lab = f"{geometrie.LAND_KURZ.get(c, c)} {de(werte[c]['v'], ctx.dec)}"
            if c in geometrie.STADT_VERSATZ:
                ox, oy, al = geometrie.STADT_VERSATZ[c]
                pts.append({"lon": lon + ox, "lat": lat + oy, "lon0": lon, "lat0": lat, "lab": lab, "al": al, "linie": True})
            else:
                pts.append({"lon": lon + dx, "lat": lat + dy, "lab": lab, "al": "center", "linie": False})
        linien = [p for p in pts if p["linie"]]
        lagen.append({"data": {"values": linien}, "mark": {"type": "rule", "color": F["ink2"], "strokeWidth": 0.8},
                      "encoding": {"longitude": {"field": "lon0", "type": "quantitative"}, "latitude": {"field": "lat0", "type": "quantitative"},
                                   "longitude2": {"field": "lon"}, "latitude2": {"field": "lat"}}})
        for al in ("center", "left", "right"):
            sub = [p for p in pts if p["al"] == al]
            if not sub:
                continue
            enc = {"longitude": {"field": "lon", "type": "quantitative"}, "latitude": {"field": "lat", "type": "quantitative"}, "text": {"field": "lab"}}
            lagen += halo(F, enc, {"type": "text", "align": al, "fontSize": 11.5, "fontWeight": "bold", "color": F["ink"]}, daten=sub)
    haupt = {"width": 560, "height": 700 if ebene != "krs" else 720, "projection": proj, "layer": lagen}
    top = max(vals, key=lambda c: vals[c])
    name_top = werte[top]["k"] if ebene != "lan" else geo[top]["name"]
    if divergierend:
        ueber = sum(v > 0 for v in vals.values())
        titel = (waehle_titel([f"{ctx.S}: {ueber} Länder über dem Bundeswert", f"{ueber} Länder über dem Bundeswert"]),
                 {"bundeswert": ctx.fmt(bund), "ueber": ueber})
        zus = f"Abweichung vom Bundeswert ({ctx.fmt(bund)})"
    else:
        titel = titel_rangfolge(ctx, [{"k": werte[c]["k"] if ebene != "lan" else geo[c]["name"], "v": werte[c]["v"]} for c in treffer])
        zus = f"Deutschland: {ctx.fmt(bund)}" if (bund is not None and ctx.a.quote) else ""
    titel[1]["zuordnung"] = f"{len(treffer)}/{len(geo)}"
    return zusammensetzen(ctx, haupt, titel[0], ctx.sachzeile(zus)), titel[1]


def k_symbol(ctx):
    F = ctx.F
    dm = dim_haupt(ctx, ("laender", "kreise"))
    ebene = "lan" if dm["rolle"] == "laender" else "krs"
    geo = _karte_basis(ctx, ebene)
    n = geometrie.STELLEN[ebene]
    werte = {r["c"][:n]: r for r in ctx.quer(dm) if re.fullmatch(r"\d+", r["c"] or "") and len(r["c"]) >= n}
    treffer = [c for c in geo if c in werte]
    if len(treffer) < 0.8 * len(geo):
        raise Unpassend("Gebiete nicht zuordenbar")
    lan = geo if ebene == "lan" else geometrie.gebiete("lan", ctx.geo_ordner)
    basis = {"data": {"values": {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": g["geometry"], "properties": {}} for g in lan.values()]},
                      "format": {"type": "json", "property": "features"}},
             "mark": {"type": "geoshape", "fill": F["na"], "stroke": F["bg"], "strokeWidth": 1}}
    schieb = geometrie.LAND_SCHIEBEN if ebene == "lan" else {}
    pts = [{"lon": geo[c]["pt"][0] + schieb.get(c, (0, 0))[0], "lat": geo[c]["pt"][1] + schieb.get(c, (0, 0))[1],
            "v": max(0.0, werte[c]["v"]), "k": werte[c]["k"],
            "lab": f"{geometrie.LAND_KURZ.get(c, '')} {de(werte[c]['v'], ctx.dec)}" if ebene == "lan" else ""} for c in treffer]
    vmax = max(p["v"] for p in pts) or 1
    lagen = [basis, {"data": {"values": pts}, "mark": {"type": "circle", "opacity": 0.75, "color": F["akzent"], "stroke": F["bg"], "strokeWidth": 1},
                     "encoding": {"longitude": {"field": "lon", "type": "quantitative"}, "latitude": {"field": "lat", "type": "quantitative"},
                                  "size": {"field": "v", "type": "quantitative", "scale": {"domain": [0, vmax], "range": [0, 2400 if ebene == "lan" else 400]},
                                           "legend": {"title": ctx.E.text(), "orient": "top", "direction": "horizontal", "symbolType": "circle",
                                                      "symbolFillColor": F["akzent"], "symbolOpacity": 0.75, "symbolStrokeColor": F["bg"],
                                                      "values": groessen_werte([p["v"] for p in pts])}}}}]
    if ebene == "lan":
        lagen += halo(F, {"longitude": {"field": "lon", "type": "quantitative"}, "latitude": {"field": "lat", "type": "quantitative"}, "text": {"field": "lab"}},
                      {"type": "text", "dy": -2, "fontSize": 11, "fontWeight": "bold", "color": F["ink"], "baseline": "bottom"},
                      daten=[{**p, "lat": p["lat"] + 0.18} for p in pts])
    haupt = {"width": 560, "height": 700, "projection": {"type": "mercator"}, "layer": lagen}
    titel = titel_rangfolge(ctx, [{"k": werte[c]["k"], "v": werte[c]["v"]} for c in treffer])
    ctx.fuss_extra.append("Kreisfläche proportional zum Wert.")
    return zusammensetzen(ctx, haupt, titel[0], ctx.sachzeile()), titel[1]


# =========================================================================================== Verteiler
BAUER = {
    1: lambda c: b_rangfolge(c), 2: lambda c: b_rangfolge(c, lollipop=True), 3: lambda c: b_rangfolge(c, punkte=True),
    4: z_slope, 5: b_divergierend, 6: b_abweichung, 7: v_dumbbell, 8: v_gruppiert, 9: v_pyramide,
    10: lambda c: t_stapel(c), 11: lambda c: t_stapel(c, haeufigkeit=True), 12: lambda c: t_kreis(c, True),
    13: lambda c: t_kreis(c, False), 14: t_treemap, 15: t_waffel, 16: lambda c: b_saeulen(c, klassen=True),
    17: d_streifen, 18: d_histogramm, 19: d_boxplot, 20: z_linie, 21: z_hervorhebung, 22: z_small_multiples,
    23: z_flaeche, 24: z_saeulen, 25: b_veraenderung, 26: z_heatmap_monat, 27: lambda c: r_streu(c),
    28: lambda c: r_streu(c, blasen=True), 29: r_heatmap, 30: lambda c: k_choropleth(c, "lan"),
    31: lambda c: k_choropleth(c, "krs"), 32: lambda c: k_choropleth(c, "lan", divergierend=True), 33: k_symbol,
    34: lambda c: k_choropleth(c, "rbz"), 35: lambda c: b_saeulen(c), 36: t_wasserfall,
}


def baue(kand: dict, t: pd.DataFrame, prof: dict, meta: dict, F: dict, geo_ordner: Path, stichprobe: bool, seed):
    """-> (Vega-Lite-Spezifikation, Fakten). Wirft Unpassend, wenn die Daten den Typ doch nicht tragen."""
    ctx = Kontext(kand, t, prof, meta, F, geo_ordner, stichprobe, seed)
    ctx._t = t
    typ = int(kand["typ"])
    unit, label = str(ctx.a.unit), str(ctx.a.vv_label)
    # „jeweilige Maßeinheit“: jede Kategorie hat eine eigene Einheit -> nur Zeitverläufe einer Reihe zulässig
    if re.search(r"jew\.?\s*ME|jeweilige", unit + " " + label) and typ not in (20, 24, 26):
        raise Unpassend("jeweilige Maßeinheit: Kategorien nicht vergleichbar")
    # Teil-Ganzes-Darstellungen nur für additive Bestandsgrößen (keine Preise, Kurse, Indizes, Quoten, Raten)
    if typ in (10, 11, 12, 13, 14, 15, 23) and (ctx.a.quote or ctx.E.index or ctx.E.prozent and typ == 23 or "/" in unit
                                                 or re.search(r"preis|kurs|index|quote|anteil|\bje\b|\bpro\b|durchschn", label, re.I)):
        raise Unpassend("keine additive Größe – Anteile/Stapel nicht sinnvoll")
    spec, fakten = BAUER[typ](ctx)
    titel = spec["title"]["text"]
    return spec, {"titel": " ".join(titel), "sachzeile": " ".join(spec["title"]["subtitle"]), "fakten": fakten}
