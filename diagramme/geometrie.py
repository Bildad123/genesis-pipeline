# -*- coding: utf-8 -*-
"""
geometrie.py – Kartengrundlagen (METHODE.md, Abschnitt 9.6).

Geometrie: BKG, Verwaltungsgebiete 1:5 000 000 (VG5000, Stand 31.12.), Datenlizenz Deutschland – Namensnennung 2.0.
Ebenen: lan (Bundesländer), rbz (Regierungsbezirke), krs (Kreise). Einmalig geladen und in geo/ zwischengespeichert.

Aufbereitung:
  * nur Landflächen (Geofaktor 4 oder 9; Wasserflächen wie der Bodensee entfallen)
  * Achsenreihenfolge [Länge, Breite] prüfen
  * Vereinfachung nach Douglas-Peucker (Toleranz 0,005° Länder, 0,003° Bezirke, 0,002° Kreise)
  * Umlaufsinn nach d3-Konvention (Außenringe im Uhrzeigersinn), sonst füllt Vega die ganze Welt
  * Beschriftungspunkt im Inneren der größten Teilfläche
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

GEO_URL = ("https://sgx.geodatenzentrum.de/wfs_vg5000_1231?SERVICE=WFS&VERSION=2.0.0&REQUEST=GetFeature"
           "&TYPENAMES=vg5000_{e}&OUTPUTFORMAT=application/json&SRSNAME=EPSG:4326")
TOLERANZ = {"lan": 0.005, "rbz": 0.003, "krs": 0.002}
STELLEN = {"lan": 2, "rbz": 3, "krs": 5}
INFO: dict = {}
_CACHE: dict = {}

LAND_KURZ = {"01": "SH", "02": "HH", "03": "NI", "04": "HB", "05": "NW", "06": "HE", "07": "RP", "08": "BW",
             "09": "BY", "10": "SL", "11": "BE", "12": "BB", "13": "MV", "14": "SN", "15": "ST", "16": "TH"}
# Stadtstaaten: Beschriftung außerhalb mit Führungslinie (Versatz in Grad: dx, dy, Ausrichtung)
STADT_VERSATZ = {"02": (1.25, 0.55, "left"), "04": (-1.3, 0.35, "right"), "11": (1.5, 0.45, "left")}
LAND_SCHIEBEN = {"12": (0.25, -0.55)}


def roh(ebene: str, ordner: Path) -> dict:
    p = ordner / f"vg5000_{ebene}.geojson"
    if not p.exists():
        import requests  # nur für den einmaligen Download
        p.parent.mkdir(parents=True, exist_ok=True)
        print(f"    lade Geometrie {p.name} (BKG VG5000) …")
        r = requests.get(GEO_URL.format(e=ebene), timeout=180)
        r.raise_for_status()
        p.write_bytes(r.content)
    b = p.read_bytes()
    INFO[p.name] = hashlib.sha256(b).hexdigest()
    return json.loads(b.decode("utf-8"))


def _runde(c, nd=4):
    if isinstance(c, (list, tuple)) and c and isinstance(c[0], (int, float)):
        return [round(float(c[0]), nd), round(float(c[1]), nd)]
    return [_runde(x, nd) for x in c]


def _flaeche(r):
    return 0.5 * sum(r[i][0] * r[i + 1][1] - r[i + 1][0] * r[i][1] for i in range(len(r) - 1))


def _dp(pts, tol):
    n = len(pts)
    if n < 6:
        return pts
    keep = [False] * n
    keep[0] = keep[-1] = True
    far = max(range(1, n - 1), key=lambda i: (pts[i][0] - pts[0][0]) ** 2 + (pts[i][1] - pts[0][1]) ** 2)
    keep[far] = True
    stack = [(0, far), (far, n - 1)]
    while stack:
        a, b = stack.pop()
        if b - a < 2:
            continue
        ax, ay = pts[a]
        bx, by = pts[b]
        dx, dy = bx - ax, by - ay
        L = math.hypot(dx, dy)
        md, mi = 0.0, -1
        for i in range(a + 1, b):
            px, py = pts[i]
            dd = abs(dy * px - dx * py + bx * ay - by * ax) / L if L > 0 else math.hypot(px - ax, py - ay)
            if dd > md:
                md, mi = dd, i
        if md > tol:
            keep[mi] = True
            stack += [(a, mi), (mi, b)]
    out = [p for p, k in zip(pts, keep) if k]
    return out if len(out) >= 4 else pts


def _pip(x, y, ring):
    inside = False
    for i in range(len(ring) - 1):
        x1, y1 = ring[i]
        x2, y2 = ring[i + 1]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def _innenpunkt(poly):
    ext = poly[0]
    ys = sorted(p[1] for p in ext)
    best = None
    for f in (0.5, 0.45, 0.55, 0.4, 0.6, 0.35, 0.65):
        y = ys[0] + (ys[-1] - ys[0]) * f
        xs = []
        for i in range(len(ext) - 1):
            (x1, y1), (x2, y2) = ext[i], ext[i + 1]
            if (y1 > y) != (y2 > y):
                xs.append((x2 - x1) * (y - y1) / (y2 - y1) + x1)
        xs.sort()
        for a, b in zip(xs[::2], xs[1::2]):
            if best is None or b - a > best[0]:
                x = (a + b) / 2
                if not any(_pip(x, y, h) for h in poly[1:]):
                    best = (b - a, x, y)
        if best:
            break
    return (best[1], best[2]) if best else tuple(ext[0])


def _aufbereiten(geoms, tol):
    polys = []
    for g in geoms:
        polys += g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
    out, groesste = [], (0, None)
    for poly in polys:
        ringe = []
        for k, r in enumerate(poly):
            r = [list(map(float, p[:2])) for p in r]
            if r[0] != r[-1]:
                r.append(r[0])
            r2 = _dp(r, tol)
            a = _flaeche(r2)
            if (k == 0 and a > 0) or (k > 0 and a < 0):
                r2 = r2[::-1]
            ringe.append(r2)
        fl = abs(_flaeche(ringe[0])) - sum(abs(_flaeche(h)) for h in ringe[1:])
        out.append(ringe)
        if fl > groesste[0]:
            groesste = (fl, ringe)
    pt = _innenpunkt(groesste[1])
    geom = ({"type": "MultiPolygon", "coordinates": _runde(out)} if len(out) > 1
            else {"type": "Polygon", "coordinates": _runde(out[0])})
    return geom, (round(pt[0], 4), round(pt[1], 4))


def gebiete(ebene: str, ordner: Path) -> dict:
    """{Schlüssel: {"geometry", "name", "pt"}} – Schlüssel 2-stellig (Länder), 3-stellig (Bezirke), 5-stellig (Kreise)."""
    if ebene in _CACHE:
        return _CACHE[ebene]
    daten = roh(ebene, ordner)
    gruppen, namen = {}, {}
    for f in daten["features"]:
        pr = f["properties"]
        if int(pr.get("gf", 4)) not in (4, 9):
            continue
        code = str(pr.get("ars") or pr.get("ags"))[: STELLEN[ebene]]
        gruppen.setdefault(code, []).append(f["geometry"])
        namen[code] = pr.get("gen")
    c0 = next(iter(gruppen.values()))[0]["coordinates"]
    while isinstance(c0[0], list):
        c0 = c0[0]
    if c0[0] > 40:  # Breite/Länge vertauscht
        def sw(c):
            return [c[1], c[0]] if isinstance(c[0], (int, float)) else [sw(x) for x in c]
        gruppen = {k: [{"type": g["type"], "coordinates": sw(g["coordinates"])} for g in v] for k, v in gruppen.items()}
    out = {}
    for code, geoms in sorted(gruppen.items()):
        geom, pt = _aufbereiten(geoms, TOLERANZ[ebene])
        out[code] = {"geometry": geom, "name": namen[code], "pt": pt}
    _CACHE[ebene] = out
    return out
