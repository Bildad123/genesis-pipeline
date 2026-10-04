# -*- coding: utf-8 -*-
"""
gestaltung.py – Farbthemen, Farbprüfung und Formatierung (METHODE.md, Abschnitte 8 und 9).

Farbprüfung:
  * Kontrastverhältnis nach WCAG 2.1 (relative Leuchtdichte, Erfolgskriterien 1.4.3 und 1.4.11)
  * Farbabstand CIEDE2000 (Sharma, Wu & Dalal 2005) in CIELAB (D65)
  * Simulation von Farbfehlsichtigkeit nach Machado, Oliveira & Fernandes (2009), Schweregrad 1,0
"""
from __future__ import annotations

import math
import re
import textwrap

# =========================================================================================== Farbthemen
# Hintergrund und Textfarben je Thema. 'balken' = neutrale Farbe nicht hervorgehobener Elemente.
THEMEN = {
    "T1_weiss":      {"bg": "#ffffff", "ink": "#0b0b0b", "ink2": "#4f4e4a", "muted": "#6e6d69", "grid": "#e6e5e1",
                      "domain": "#b9b8b3", "balken": "#c4c3be", "na": "#e6e5e1", "dunkel": False},
    "T2_creme":      {"bg": "#faf6ee", "ink": "#2b2118", "ink2": "#524638", "muted": "#6f6353", "grid": "#e8dfcf",
                      "domain": "#bfb29c", "balken": "#cfc3ae", "na": "#e8dfcf", "dunkel": False},
    "T3_hellgrau":   {"bg": "#f1f1ef", "ink": "#1f1f1f", "ink2": "#474744", "muted": "#62625e", "grid": "#dcdcd8",
                      "domain": "#aeaea9", "balken": "#bdbdb8", "na": "#dcdcd8", "dunkel": False},
    "T4_dunkelblau": {"bg": "#0f1c2e", "ink": "#eef2f7", "ink2": "#c3cedc", "muted": "#9aa9bd", "grid": "#263850",
                      "domain": "#4a5f7c", "balken": "#4a5f7c", "na": "#263850", "dunkel": True},
    "T5_anthrazit":  {"bg": "#1c1c1c", "ink": "#f2f2f2", "ink2": "#cfcfcf", "muted": "#a8a8a8", "grid": "#343434",
                      "domain": "#5a5a5a", "balken": "#5c5c5c", "na": "#343434", "dunkel": True},
    "T6_pastell":    {"bg": "#eef5f1", "ink": "#1d2b25", "ink2": "#44544c", "muted": "#5b6b63", "grid": "#d6e3dc",
                      "domain": "#a7b8af", "balken": "#b7c7bf", "na": "#d6e3dc", "dunkel": False},
}

# Palettenfamilien: kategorial + sequenziell (hell -> dunkel) + divergierend (negativ -> neutral -> positiv)
PALETTEN = {
    "P1_haus":      {"cat": ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"],
                     "seq": ["#cde2fb", "#86b6ef", "#5598e7", "#1c5cab", "#104281"],
                     "div": ["#b2182b", "#ef8a62", None, "#67a9cf", "#2166ac"]},
    "P2_okabe_ito": {"cat": ["#0072B2", "#E69F00", "#009E73", "#D55E00", "#CC79A7", "#56B4E9", "#F0E442"],
                     "seq": ["#feedde", "#fdbe85", "#fd8d3c", "#e6550d", "#a63603"],
                     "div": ["#7b3294", "#c2a5cf", None, "#a6dba0", "#008837"]},
    "P3_tol_bright": {"cat": ["#4477AA", "#EE6677", "#228833", "#CCBB44", "#66CCEE", "#AA3377"],
                     "seq": ["#f2f0f7", "#cbc9e2", "#9e9ac8", "#756bb1", "#54278f"],
                     "div": ["#a6611a", "#dfc27d", None, "#80cdc1", "#018571"]},
    "P4_dark2":     {"cat": ["#1b9e77", "#d95f02", "#7570b3", "#e7298a", "#66a61e", "#e6ab02", "#a6761d"],
                     "seq": ["#edf8e9", "#bae4b3", "#74c476", "#31a354", "#006d2c"],
                     "div": ["#7b3294", "#c2a5cf", None, "#a6dba0", "#008837"]},
    "P5_set2_viridis": {"cat": ["#66c2a5", "#fc8d62", "#8da0cb", "#e78ac3", "#a6d854", "#ffd92f", "#e5c494"],
                     "seq": ["#fde725", "#5ec962", "#21918c", "#3b528b", "#440154"],
                     "div": ["#b2182b", "#ef8a62", None, "#67a9cf", "#2166ac"]},
    "P6_tol_muted_cividis": {"cat": ["#332288", "#88CCEE", "#44AA99", "#117733", "#999933", "#DDCC77", "#CC6677",
                                     "#882255", "#AA4499"],
                     "seq": ["#fee838", "#c4b56c", "#7f7c75", "#414d6b", "#00224e"],
                     "div": ["#a6611a", "#dfc27d", None, "#80cdc1", "#018571"]},
}

GRENZEN = {"text": 4.5, "grafik": 3.0, "de_normal": 10.0, "de_cvd": 6.0, "min_farben": 3}


# =========================================================================================== Farbmathematik
def hex_rgb(h: str):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def _lin(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _gamma(c):
    c = min(1.0, max(0.0, c))
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def leuchtdichte(h: str) -> float:
    r, g, b = (_lin(c) for c in hex_rgb(h))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def kontrast(a: str, b: str) -> float:
    la, lb = sorted((leuchtdichte(a), leuchtdichte(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _lab(rgb_lin):
    r, g, b = rgb_lin
    x = (0.4124564 * r + 0.3575761 * g + 0.1804375 * b) / 0.95047
    y = (0.2126729 * r + 0.7151522 * g + 0.0721750 * b)
    z = (0.0193339 * r + 0.1191920 * g + 0.9503041 * b) / 1.08883
    f = lambda t: t ** (1 / 3) if t > 216 / 24389 else (24389 / 27 * t + 16) / 116  # noqa: E731
    fx, fy, fz = f(x), f(y), f(z)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def ciede2000(l1, l2) -> float:
    L1, a1, b1 = l1
    L2, a2, b2 = l2
    C1, C2 = math.hypot(a1, b1), math.hypot(a2, b2)
    Cm = (C1 + C2) / 2
    G = 0.5 * (1 - math.sqrt(Cm ** 7 / (Cm ** 7 + 25 ** 7)))
    a1p, a2p = (1 + G) * a1, (1 + G) * a2
    C1p, C2p = math.hypot(a1p, b1), math.hypot(a2p, b2)
    h1p = math.degrees(math.atan2(b1, a1p)) % 360
    h2p = math.degrees(math.atan2(b2, a2p)) % 360
    dLp, dCp = L2 - L1, C2p - C1p
    dhp = 0 if C1p * C2p == 0 else (h2p - h1p if abs(h2p - h1p) <= 180 else h2p - h1p - 360 if h2p > h1p else h2p - h1p + 360)
    dHp = 2 * math.sqrt(C1p * C2p) * math.sin(math.radians(dhp / 2))
    Lpm, Cpm = (L1 + L2) / 2, (C1p + C2p) / 2
    if C1p * C2p == 0:
        hpm = h1p + h2p
    elif abs(h1p - h2p) <= 180:
        hpm = (h1p + h2p) / 2
    else:
        hpm = (h1p + h2p + 360) / 2 if h1p + h2p < 360 else (h1p + h2p - 360) / 2
    T = (1 - 0.17 * math.cos(math.radians(hpm - 30)) + 0.24 * math.cos(math.radians(2 * hpm))
         + 0.32 * math.cos(math.radians(3 * hpm + 6)) - 0.20 * math.cos(math.radians(4 * hpm - 63)))
    dtheta = 30 * math.exp(-(((hpm - 275) / 25) ** 2))
    Rc = 2 * math.sqrt(Cpm ** 7 / (Cpm ** 7 + 25 ** 7))
    Sl = 1 + 0.015 * (Lpm - 50) ** 2 / math.sqrt(20 + (Lpm - 50) ** 2)
    Sc, Sh = 1 + 0.045 * Cpm, 1 + 0.015 * Cpm * T
    Rt = -math.sin(math.radians(2 * dtheta)) * Rc
    return math.sqrt((dLp / Sl) ** 2 + (dCp / Sc) ** 2 + (dHp / Sh) ** 2 + Rt * (dCp / Sc) * (dHp / Sh))


# Machado et al. (2009), Schweregrad 1,0 – Matrizen in linearem RGB
CVD = {
    "protanopie": [[0.152286, 1.052583, -0.204868], [0.114503, 0.786281, 0.099216], [-0.003882, -0.048116, 1.051998]],
    "deuteranopie": [[0.367322, 0.860646, -0.227968], [0.280085, 0.672501, 0.047413], [-0.011820, 0.042940, 0.968881]],
    "tritanopie": [[1.255528, -0.076749, -0.178779], [-0.078411, 0.930809, 0.147602], [0.004733, 0.691367, 0.303900]],
}


def lab_von(h: str, cvd: str | None = None):
    lin = [_lin(c) for c in hex_rgb(h)]
    if cvd:
        m = CVD[cvd]
        lin = [min(1, max(0, sum(m[i][j] * lin[j] for j in range(3)))) for i in range(3)]
    return _lab(lin)


def farbabstand(a: str, b: str, cvd: str | None = None) -> float:
    return ciede2000(lab_von(a, cvd), lab_von(b, cvd))


# =========================================================================================== Validierung
def pruefe_kombination(thema: str, palette: str) -> dict:
    """Prüft Thema × Palette nach METHODE 8.3. Rückgabe: gültige Farben und Prüfprotokoll."""
    T, P = THEMEN[thema], PALETTEN[palette]
    prot = {"thema": thema, "palette": palette}
    prot["kontrast_text"] = round(min(kontrast(T["ink"], T["bg"]), kontrast(T["ink2"], T["bg"]),
                                      kontrast(T["muted"], T["bg"])), 2)
    # kategoriale Farben: nur solche mit ausreichendem Kontrast zum Hintergrund, Reihenfolge bleibt erhalten
    cat = [c for c in P["cat"] if kontrast(c, T["bg"]) >= GRENZEN["grafik"]]
    # paarweise unterscheidbar (normal und unter Farbfehlsichtigkeit) – gierig in Reihenfolge der Palette
    gut = []
    for c in cat:
        ok = all(farbabstand(c, g) >= GRENZEN["de_normal"] for g in gut)
        if ok and len(gut) < 3:  # für die ersten drei Farben zusätzlich Farbfehlsichtigkeit prüfen
            ok = all(farbabstand(c, g, cvd) >= GRENZEN["de_cvd"] for g in gut for cvd in CVD)
        if ok:
            gut.append(c)
    prot["farben_kategorial"] = len(gut)
    seq = P["seq"] if not T["dunkel"] else P["seq"]
    prot["kontrast_seq_max"] = round(max(kontrast(seq[-1], T["bg"]), kontrast(seq[0], T["bg"])), 2)
    prot["abstand_seq_na"] = round(min(farbabstand(T["na"], s) for s in seq), 1)
    fehler = []
    if prot["kontrast_text"] < GRENZEN["text"]:
        fehler.append("Textkontrast < 4,5:1")
    if len(gut) < GRENZEN["min_farben"]:
        fehler.append(f"weniger als {GRENZEN['min_farben']} unterscheidbare kategoriale Farben")
    if prot["kontrast_seq_max"] < GRENZEN["grafik"]:
        fehler.append("sequenzielle Skala ohne Kontrast zum Hintergrund")
    if prot["abstand_seq_na"] < 5:
        fehler.append("Farbe 'keine Angabe' nicht von der Skala unterscheidbar")
    prot["gueltig"] = not fehler
    prot["grund"] = "; ".join(fehler)
    prot["_cat"] = gut
    return prot


def farbschema(thema: str, palette: str) -> dict:
    """Konkretes Farbschema für den Diagrammbau."""
    T, P = THEMEN[thema], PALETTEN[palette]
    prot = pruefe_kombination(thema, palette)
    # neutrale Mitte der divergierenden Skala: auf hellem Grund ein Grau, das sich vom Hintergrund abhebt
    div = [c if c else ("#3a3a3a" if T["dunkel"] else T["grid"]) for c in P["div"]]
    return {**T, "thema": thema, "palette": palette, "cat": prot["_cat"], "akzent": prot["_cat"][0],
            "akzent2": prot["_cat"][1], "seq": list(P["seq"]), "div": div,
            "text_hell": "#ffffff", "text_dunkel": "#0b0b0b"}


def textfarbe_auf(fläche: str) -> str:
    return "#0b0b0b" if leuchtdichte(fläche) > 0.40 else "#ffffff"


# =========================================================================================== Zahlen und Einheiten
def de(v, dec=1) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "–"
    s = f"{abs(v):,.{dec}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return ("-" if v < 0 and s.strip("0,.") else "") + s


def stellen(werte) -> int:
    w = [abs(x) for x in werte if x is not None and not (isinstance(x, float) and math.isnan(x))]
    if not w:
        return 0
    m = max(w)
    if m >= 100:
        return 0
    if m >= 10:
        return 1
    return 1 if m >= 1 else 2


# Einheit -> (Faktor zur Grundeinheit, Grundeinheit, skalierbar, Anzeige)
EINHEITEN = {
    "Anzahl": (1, "", True, ""), "1000": (1e3, "", True, ""), "Tsd.": (1e3, "", True, ""),
    "Mill.": (1e6, "", True, ""), "Mio.": (1e6, "", True, ""), "Mrd.": (1e9, "", True, ""),
    "1000 Pers.": (1e3, "", True, ""), "Personen": (1, "", True, ""),
    "EUR": (1, "Euro", True, "Euro"), "Tsd. EUR": (1e3, "Euro", True, "Euro"), "1000 EUR": (1e3, "Euro", True, "Euro"),
    "Mill. EUR": (1e6, "Euro", True, "Euro"), "Mio. EUR": (1e6, "Euro", True, "Euro"), "Mrd. EUR": (1e9, "Euro", True, "Euro"),
    "t": (1, "Tonnen", True, "Tonnen"), "1000 t": (1e3, "Tonnen", True, "Tonnen"),
    "ha": (1, "Hektar", True, "Hektar"), "1000 ha": (1e3, "Hektar", True, "Hektar"),
    "qm": (1, "m²", True, "m²"), "1000 qm": (1e3, "m²", True, "m²"), "qkm": (1, "km²", True, "km²"),
    "cbm": (1, "m³", True, "m³"), "1000 cbm": (1e3, "m³", True, "m³"),
    "Prozent": (1, "%", False, "Prozent"), "%": (1, "%", False, "Prozent"),
}
# Einheitenzeichen für Wertebeschriftungen („2,3 ha“, „527 Tsd. m²“)
SYMBOLE = {"Tonnen": "t", "Hektar": "ha", "m²": "m²", "km²": "km²", "m³": "m³", "kg": "kg", "km": "km",
           "Stunden": "Std.", "Std.": "Std.", "Tage": "Tage", "Jahre": "Jahre", "Promille": "‰", "MW": "MW",
           "kWh": "kWh", "GWh": "GWh", "Liter": "l", "Hektoliter": "hl", "Stück": "Stück"}
# (Schwelle, Teiler, Kurzform, Langform): Tausender erst ab 100.000, damit kleine Zahlen ungeteilt bleiben
SKALA = [(1e9, 1e9, "Mrd.", "Milliarden"), (1e6, 1e6, "Mio.", "Millionen"), (1e5, 1e3, "Tsd.", "Tausend")]


class Einheit:
    """Bestimmt Skalierung und Beschriftung einer Messgröße (METHODE 9.5)."""

    def __init__(self, unit: str, werte):
        self.roh = unit
        self.faktor, self.basis, skal, self.anzeige = EINHEITEN.get(unit, (1, unit, False, unit))
        self.index = "=100" in unit
        if self.index:
            self.anzeige, self.basis, skal = f"Index ({unit.replace('=', ' = ')})", "", False
        grund = [abs(v * self.faktor) for v in werte if v == v and v is not None]
        m = max(grund) if grund else 0
        klein = min([g for g in grund if g > 0], default=0)
        self.teiler, self.kurz, self.lang = 1, "", ""
        if skal:
            stufen = [(t, k, lng) for schwelle, t, k, lng in SKALA if m >= schwelle]
            # größte passende Stufe, bei der auch der kleinste Wert noch mindestens 0,1 Einheiten ergibt
            for t, k, lng in stufen:
                if klein / t >= 0.1:
                    self.teiler, self.kurz, self.lang = t, k, lng
                    break
        self.prozent = self.basis == "%"

    def wert(self, v):
        return None if v is None or v != v else v * self.faktor / self.teiler

    def text(self) -> str:
        """Einheit für die Sachzeile."""
        if self.prozent:
            return "in Prozent"
        if self.index:
            return self.anzeige
        teile = [x for x in (self.lang, self.anzeige) if x]
        if not teile:
            return "Anzahl"
        return "in " + " ".join(teile)

    def suffix(self) -> str:
        """Kurzform für Wertebeschriftungen."""
        if self.prozent:
            return " %"
        if self.anzeige == "Euro":
            return f" {self.kurz} €".replace("  ", " ") if self.kurz else " €"
        sym = SYMBOLE.get(self.anzeige) or (self.anzeige if self.anzeige and len(self.anzeige) <= 4
                                           and not self.index else "")
        return "".join(f" {x}" for x in (self.kurz, sym) if x)


# =========================================================================================== Zeit
MONATE = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober",
          "November", "Dezember"]


def zeit_text(v: str) -> str:
    if re.fullmatch(r"\d{4}", v):
        return v
    m = re.fullmatch(r"(\d{4})-P(\d+)Y", v)
    if m:
        a, n = int(m.group(1)), int(m.group(2))
        return str(a) if n == 1 else f"{a}–{a + n - 1}"
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", v)
    if m:
        return f"{int(m.group(3))}.{int(m.group(2))}.{m.group(1)}".replace(".", ".", 2)
    m = re.fullmatch(r"(\d{4})-(\d{2})P1M", v)
    if m:
        return f"{MONATE[int(m.group(2)) - 1]} {m.group(1)}"
    m = re.fullmatch(r"(\d{4})-(\d{2})P3M", v)
    if m:
        return f"{(int(m.group(2)) - 1) // 3 + 1}. Quartal {m.group(1)}"
    m = re.fullmatch(r"(\d{4})-(\d{2})P6M", v)
    if m:
        return f"{(int(m.group(2)) - 1) // 6 + 1}. Halbjahr {m.group(1)}"
    return v


def zeit_datum(v: str) -> str:
    """ISO-Datum (Periodenbeginn) für temporale Achsen."""
    m = re.match(r"(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?", v)
    if not m:
        return v
    return f"{m.group(1)}-{m.group(2) or '01'}-{m.group(3) or '01'}"


def jahr(v: str) -> str:
    return v[:4]


# =========================================================================================== Text
# Grundsatz (METHODE 9.8): Beschriftungen werden nie mit „…“ abgeschnitten. Lange Bezeichnungen werden an
# Wortgrenzen umbrochen; Überschriften nennen Kategorien vollständig. Kürzer werden nur Subjekte von Überschriften,
# und zwar ausschließlich an Satzteilgrenzen (vor Präposition/Artikel/Satzzeichen), nie mitten in einer Wortgruppe.

def umbruch(t: str, n: int) -> list[str]:
    """Zeilenumbruch an Wortgrenzen; geschützte Leerzeichen (vor Einheiten) werden nie umbrochen."""
    z = textwrap.wrap(str(t).replace("\u00a0", "\ue000"), n, break_on_hyphens=False, break_long_words=False) or [""]
    return [x.replace("\ue000", "\u00a0") for x in z]


def umbruch_label(t: str, n: int = 24, max_zeilen: int = 3) -> str:
    """Bezeichnung für Achsen/Legenden: Zeilen durch '|' getrennt (in Vega per split() zu mehrzeiligem Text)."""
    z = umbruch(re.sub(r"[ \t\r\n]+", " ", str(t)).strip(), n)
    if len(z) > max_zeilen:
        z = z[: max_zeilen - 1] + [" ".join(z[max_zeilen - 1:])]
    return "|".join(z)


def zeilen_von(t: str) -> int:
    return str(t).count("|") + 1


def kuerze(t: str, n: int = 38) -> str:
    """Nur noch für interne Schlüssel/Protokolle; sichtbare Texte werden umbrochen statt gekürzt."""
    t = re.sub(r"\s+", " ", str(t)).strip()
    return t if len(t) <= n else t[: n - 1].rstrip(" ,;-/") + "…"


FUELLWOERTER = {"und", "oder", "der", "die", "das", "des", "dem", "den", "von", "vom", "für", "mit", "in", "im",
               "je", "an", "am", "aus", "bei", "zum", "zur", "zu", "sowie", "u.", "d.", "v.", "f.", "i.", "z.", "ohne",
               "nach", "über", "unter", "auf", "als", "ein", "eine", "einer", "bzw.", "einschl.", "inkl.", "gegen",
               "durch", "pro", "ab", "bis", "seit", "wegen", "wg."}

# Abkürzungen der GENESIS-Bezeichnungen, die eindeutig und ohne Beugung aufgelöst werden können
# (ermittelt aus allen Bezeichnungen des Exports, nach Häufigkeit; Adjektive bleiben abgekürzt, da ihre
# Endung vom Satzzusammenhang abhängt).
ABKUERZUNGEN = {
    "u.": "und", "v.": "von", "f.": "für", "m.": "mit", "Mill.": "Mio.", "Extrahh.": "Extrahaushalte",
    "Empf.": "Empfänger", "Instandh.": "Instandhaltung", "Instandhalt.": "Instandhaltung",
    "Wasserversorg.": "Wasserversorgung", "Entsorg.": "Entsorgung", "Beseitig.": "Beseitigung",
    "Beseit.": "Beseitigung", "Std.": "Stunden", "Großh.": "Großhandel", "Erzeugn.": "Erzeugnisse",
    "Dienstl.": "Dienstleistungen", "Dienstleist.": "Dienstleistungen", "Dienstleistg.": "Dienstleistung",
    "Unternehm.": "Unternehmen", "Untern.": "Unternehmen", "Staatsangeh.": "Staatsangehörigkeit",
    "Staatsang.": "Staatsangehörigkeit", "Größenkl.": "Größenklassen", "Aufwend.": "Aufwendungen",
    "Veränd.": "Veränderung", "Herst.": "Herstellung", "Herstell.": "Herstellung", "Lfd.": "Laufende",
    "Einw.": "Einwohner", "Einr.": "Einrichtungen", "Forschungseinr.": "Forschungseinrichtungen",
    "Wohngeb.": "Wohngebäude", "Nichtwohngeb.": "Nichtwohngebäude", "Geb.": "Gebäude",
    "Landwirtsch.": "Landwirtschaft", "Forstw.": "Forstwirtschaft", "Tätigk.": "Tätigkeit",
    "Sozialvers.": "Sozialversicherung", "Entwickl.": "Entwicklung", "Entwicklg.": "Entwicklung",
    "Masch.": "Maschinen", "Kreditinst.": "Kreditinstitute", "Nahrungsm.": "Nahrungsmittel",
    "Versorgungszug.": "Versorgungszugänge", "Asylbewerberlstg.": "Asylbewerberleistungen", "Eink.": "Einkommen",
    "Pers.": "Personen", "Privatpers.": "Privatpersonen", "Grundst.": "Grundstücke",
    "Zweigniederl.": "Zweigniederlassung", "Organis.": "Organisation", "Kommunik.": "Kommunikation",
    "Ausrüst.": "Ausrüstung", "Vermiet.": "Vermietung", "Straßenfahrz.": "Straßenfahrzeuge",
    "Tabakerzeugn.": "Tabakerzeugnisse", "Telekomm.": "Telekommunikation", "Haushaltsger.": "Haushaltsgeräte",
    "Verwert.": "Verwertung", "Bekleid.": "Bekleidung", "Bauinstall.": "Bauinstallation", "Rep.": "Reparatur",
    "Beförd.": "Beförderung", "Errichtg.": "Errichtung", "Unterhaltg.": "Unterhaltung",
    "Elektriz.": "Elektrizität", "Schwierigk.": "Schwierigkeiten", "Abschreib.": "Abschreibungen",
    "Vj.": "Vorjahr", "Wärmeerzeug.": "Wärmeerzeugung", "Zusammenfass.": "Zusammenfassung",
    "Umweltverschm.": "Umweltverschmutzung", "Hauptgr.": "Hauptgruppen", "Vervielf.": "Vervielfältigung",
    "Druckerz.": "Druckerzeugnisse", "Sozialleist.": "Sozialleistungen", "Wiedergew.": "Wiedergewinnung",
    "Bauherr.": "Bauherren", "Haush.": "Haushalte", "Auftr.": "Aufträge", "Beschäft.": "Beschäftigte",
    "Leistungsempf.": "Leistungsempfänger", "Leistungserbr.": "Leistungserbringer", "Ruhegeh.": "Ruhegehalt",
    "Gewinngemeinsch.": "Gewinngemeinschaft", "Büromasch.": "Büromaschinen", "Vorprod.": "Vorprodukte",
    "Genussm.": "Genussmittel", "Zubeh.": "Zubehör", "Düngem.": "Düngemittel", "Schwangersch.": "Schwangerschaft",
    "Krankh.": "Krankheiten", "Behand.": "Behandlung", "Tabakverarb.": "Tabakverarbeitung",
    "Lederverarb.": "Lederverarbeitung", "Umverpack.": "Umverpackungen", "Futterm.": "Futtermittel",
    "Bauelem.": "Bauelemente", "Forschg.": "Forschung", "Vermittl.": "Vermittlung", "Rechn.": "Rechnung",
    "Personalaufwendg.": "Personalaufwendungen", "Bruttoinvest.": "Bruttoinvestitionen",
    "Vorratsveränd.": "Vorratsveränderungen", "Verkaufsst.": "Verkaufsstellen", "Neugeb.": "Neugebäude",
    "Sportausrüstg.": "Sportausrüstung", "Verlagserzeugn.": "Verlagserzeugnisse", "Kraftw.": "Kraftwerke",
    "Musikinstr.": "Musikinstrumente", "Notschlacht.": "Notschlachtungen", "Asylverf.": "Asylverfahren",
    "Interessenvertr.": "Interessenvertretungen", "Teilnahmewettb.": "Teilnahmewettbewerb",
    "Nahrungsmittelind.": "Nahrungsmittelindustrie", "Arbeitsst.": "Arbeitsstätten",
    "Vermögensgegenst.": "Vermögensgegenstände", "Bauhauptgew.": "Bauhauptgewerbe",
}
_ABK_RE = re.compile(r"(?<![\wÄÖÜäöüß.])(" + "|".join(re.escape(k) for k in sorted(ABKUERZUNGEN, key=len, reverse=True))
                     + r")(?=[\s,;:)/]|$)")
_BEREICH_RE = re.compile(r"\s*\((?:u|a|o)?\d+\s*[-–]\s*\d+\s*m?\)")
_GEBIET_RE = re.compile(r"^(.+?),\s*(Landkreis|Kreis|Stadtkreis|Regionalverband|Städteregion|kreisfreie Stadt|Stadt|"
                        r"Landeshauptstadt|Hansestadt|Universitätsstadt|Wissenschaftsstadt|Klingenstadt|documenta-Stadt)$")


def _klammern_schliessen(t: str) -> str:
    """Offene Klammer am Ende (Folge der 40-Zeichen-Kürzung in GENESIS) samt Rest entfernen."""
    while t.count("(") > t.count(")"):
        t = t[: t.rfind("(")].rstrip(" ,;:-/")
    return t


def anzeige_label(t: str) -> str:
    """Einheitliche Anzeigeform einer GENESIS-Bezeichnung (METHODE 9.8):
    Leerzeichen nach Abkürzungspunkten, eindeutige Abkürzungen aufgelöst, Altersbereichscodes wie „(u15-75m)“
    entfernt, Tausenderpunkte in Zahlen ab fünf Stellen, 'EUR' -> 'Euro', offene Klammern geschlossen,
    Kreisnamen in natürlicher Reihenfolge („Lindau (Bodensee), Landkreis“ -> „Landkreis Lindau (Bodensee)“)."""
    t = re.sub(r"\s+", " ", str(t)).strip()
    if not t:
        return t
    t = _BEREICH_RE.sub("", t)
    t = re.sub(r"(?<=[A-Za-zäöüÄÖÜß]\.)(?=[A-Za-zÄÖÜäöüß(])", " ", t)
    t = _ABK_RE.sub(lambda m: ABKUERZUNGEN[m.group(1)], t)
    t = re.sub(r"\bEUR\b", "Euro", t)
    t = re.sub(r"(?<![\d.,])(\d{5,})(?![\d,])", lambda m: f"{int(m.group(1)):,}".replace(",", "."), t)
    t = _klammern_schliessen(t)
    m = _GEBIET_RE.match(t)
    if m:
        art = m.group(2)
        t = f"{art} {m.group(1)}" if art in ("Landkreis", "Kreis", "Regionalverband", "Städteregion") else m.group(1)
    return t.strip()


def ohne_fuellwort_ende(t: str) -> str:
    t = t.strip().rstrip(" ,;:-/(")
    while " " in t and t.rsplit(" ", 1)[1].lower() in FUELLWOERTER:
        t = t.rsplit(" ", 1)[0].rstrip(" ,;:-/(")
    return t


def sauberes_label(t: str) -> str:
    """GENESIS kürzt Bezeichnungen auf 40 Zeichen; ein angeschnittenes letztes Wort und Füllwörter am Ende entfallen,
    danach Anzeigeform (anzeige_label)."""
    t = re.sub(r"\s+", " ", str(t)).strip()
    letzt = t.rsplit(" ", 1)[-1]
    if len(t) == 40 and " " in t and not (letzt[:1].isupper() or letzt.endswith((".", ")")) or letzt[:1].isdigit()):
        t = t.rsplit(" ", 1)[0]   # vermutlich angeschnitten (vollständige Bezeichnungen enden meist mit Substantiv)
    return ohne_fuellwort_ende(anzeige_label(t))


_GRENZWORT = FUELLWOERTER | {"(", "–", "-"}


def _gutes_ende(t: str) -> bool:
    letzt = t.rsplit(" ", 1)[-1]
    return bool(letzt) and (letzt[:1].isupper() or letzt[:1].isdigit() or letzt.endswith(")")) and not (
        letzt.endswith(".") and not letzt[:-1].isupper())


def subjekt_kurz(t: str, n: int = 50) -> str | None:
    """Subjekt einer Überschrift (METHODE 9.8): vollständige Bezeichnung, wenn sie höchstens n Zeichen hat und mit
    einem Substantiv endet; sonst der längste Anfang bis n Zeichen, der an einer Satzteilgrenze endet (vor
    Präposition, Artikel, Klammer oder nach Satzzeichen) und mit einem Substantiv (Großschreibung) schließt.
    Nie abgeschnittene Wortgruppen; None, wenn keine solche Form existiert."""
    t = sauberes_label(t)
    if not t:
        return None
    if ": " in t:                     # „Steuerbarer Umsatz: Lieferungen“ -> „Steuerbarer Umsatz (Lieferungen)“
        a, b = t.split(": ", 1)
        t = f"{a} ({b})" if len(a) + len(b) + 3 <= n and "(" not in b and _gutes_ende(b) else a
    if len(t) <= n and _gutes_ende(t):
        return t
    woerter = t.split(" ")
    grenzen = []
    for i in range(1, len(woerter)):
        links, rechts = woerter[i - 1], woerter[i]
        if not (links.endswith((",", ";", ":")) or rechts.lower() in _GRENZWORT or rechts.startswith("(")):
            continue
        kopf = " ".join(woerter[:i]).rstrip(",;:")
        if len(kopf) >= 6 and _gutes_ende(kopf) and kopf.count("(") == kopf.count(")"):
            grenzen.append(kopf)
    passend = [g for g in grenzen if len(g) <= n]
    if passend:
        return passend[-1]
    if grenzen and len(grenzen[0]) <= 1.6 * n:
        return grenzen[0]
    return t if (_gutes_ende(t) and len(t) <= 1.6 * n) else None


def kuerze_wort(t: str, n: int) -> str:
    """Kompatibilität: liefert die vollständige Bezeichnung (Überschriften werden umbrochen, nicht gekürzt)."""
    return re.sub(r"\s+", " ", str(t)).strip()


_ADJ_ENDE = re.compile(r"^[a-zäöüA-ZÄÖÜ][a-zäöüß-]*(e)$")
_FEM_SINGULAR = re.compile(r"(ung|heit|keit|schaft|ion|tät|ur|art|form|stellung|größe|klasse|gruppe)$", re.I)


def _dativ_wort(w: str) -> str:
    """Dativ eines Substantivs: Plural auf -e/-er/-el erhält -n ('Bundesländer' -> 'Bundesländern');
    alle anderen Formen bleiben unverändert (Singular und Plural auf -en/-n/-s)."""
    if w in ("Alter", "Geschlecht", "Semester", "Familienstand", "Gebiet", "Land", "Kapitel", "Zeitraum", "Schwere",
             "Größe", "Höhe", "Stufe", "Dauer", "Reihe", "Sparte", "Branche", "Lage", "Herkunft", "Nutzungsdauer",
             "Wirtschaftsklasse", "Rechtsform", "Fahrzeugklasse", "Nummer"):
        return w
    if re.search(r"(e|er|el)$", w) and not re.search(r"(ee|ie)$", w):
        return w + "n"
    return w


def dativ(label: str) -> str:
    """Merkmalsbezeichnung nach „nach“ in den Dativ setzen (METHODE 9.8):
    'Bundesländer' -> 'Bundesländern', 'Gewinnfälle und Verlustfälle' -> 'Gewinnfällen und Verlustfällen',
    'Beantragte Verfahren' -> 'beantragten Verfahren'. Nur der Kopf vor Artikel/Präposition wird gebeugt
    ('Größenklassen der voraussichtlichen Forderungen'). Ist die Beugung nicht sicher bestimmbar
    ('Früheres Bundesgebiet / Neue Länder'), steht die Bezeichnung in Anführungszeichen."""
    label = anzeige_label(label)
    if not label:
        return label
    woerter = label.split(" ")
    k = len(woerter)
    for i, w in enumerate(woerter):
        if i > 0 and (w.lower() in FUELLWOERTER - {"und", "oder", "sowie"} or w.startswith("(")):
            k = i
            break
    kopf, rest = woerter[:k], woerter[k:]
    if "/" in " ".join(kopf) or any(x.endswith(".") for x in kopf):
        return f"„{label}“"
    # Kopf in Wortgruppen zerlegen (Koordination mit und/oder/sowie bzw. Komma)
    out, gruppe = [], []

    def beuge(gr):
        if not gr:
            return []
        *adj, nomen = gr
        if nomen.endswith("-"):          # „Original- und bereinigte Daten“: Ergänzungsstrich
            return gr
        nk = nomen.rstrip(",")
        nd = _dativ_wort(nk)
        fem = bool(_FEM_SINGULAR.search(nk)) and not nk.endswith("n")
        plural = bool(re.search(r"(e|er|el|en|n|s)$", nk)) and not fem
        if adj and not (fem or plural):
            raise ValueError             # Adjektiv vor maskulinem/neutralem Singular: Beugung unsicher
        a2 = []
        for a in adj:
            if not _ADJ_ENDE.match(a):
                raise ValueError
            a2.append((a[0].lower() + a[1:]) + ("r" if fem else "n"))
        return a2 + [nd + ("," if nomen.endswith(",") else "")]
    try:
        for w in kopf:
            if w in ("und", "oder", "sowie"):
                out += beuge(gruppe) + [w]
                gruppe = []
            else:
                gruppe.append(w)
        out += beuge(gruppe)
    except ValueError:
        return f"„{label}“"
    return " ".join(out + rest)


def klassen_schluessel(lab: str):
    """Sortierschlüssel für geordnete Klassen ('unter 5', '5 bis unter 10', '95 und mehr', '23-Jährige')."""
    s = str(lab).lower().replace(".", "").replace(",", ".")
    zahlen = re.findall(r"\d+(?:\.\d+)?", s)
    if not zahlen:
        return (1, 0.0, str(lab))
    z = float(zahlen[0])
    if s.startswith("unter") or s.startswith("bis ") or s.startswith("weniger"):
        return (0, z - 1e-6, str(lab))
    if re.search(r"und (mehr|älter|darüber)|mehr als|^über", s):
        return (0, z + 1e-6, str(lab))
    return (0, z, str(lab))


def quantor(p: float) -> str | None:
    """Konservative Quantoren (Regelwerk): nur in engen Bereichen, sonst None."""
    regeln = [(10.0, 10.9, "jeder Zehnte"), (19.0, 19.9, "fast jeder Fünfte"), (20.0, 21.9, "jeder Fünfte"),
              (24.0, 24.9, "fast jeder Vierte"), (25.0, 27.9, "gut jeder Vierte"), (32.0, 33.3, "fast jeder Dritte"),
              (33.4, 35.9, "mehr als jeder Dritte"), (45.0, 49.9, "fast jeder Zweite"), (50.0, 52.9, "gut die Hälfte"),
              (66.0, 67.9, "zwei Drittel"), (74.0, 74.9, "fast drei Viertel"), (75.0, 77.9, "drei Viertel")]
    for lo, hi, w in regeln:
        if lo <= p <= hi:
            return w
    return None
