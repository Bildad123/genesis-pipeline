"""Übersicht aller erzeugten Diagramme als eine HTML-Seite (uebersicht.html im Ergebnisordner).

Wird am Ende von genesis_diagramme.py automatisch geschrieben und geöffnet. Kann auch einzeln aufgerufen werden,
um die Übersicht aus einem vorhandenen manifest.json neu zu erzeugen:

    python uebersicht.py                      (Ergebnisordner aus config.yaml)
    python uebersicht.py ..\\GENESIS_Diagramme (beliebiger Ergebnisordner)
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

BEREICHSNAMEN = {
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


def schreibe_uebersicht(aus: Path, manifest: list, seed=None) -> Path:
    """Schreibt aus/uebersicht.html mit Kennzahlen, Filtern und Großansicht."""
    daten = []
    for e in manifest:
        rel = str(e["datei"]).replace("\\", "/")
        png = aus / (rel + ".png")
        daten.append({
            "src": rel + ".png", "ok": png.exists(), "datei": rel.rsplit("/", 1)[-1],
            "bereich": str(e.get("bereich", "")), "typ": e.get("typ"), "typname": e.get("typname", ""),
            "tabelle": e.get("tabelle", ""), "tabellentitel": e.get("tabellentitel", ""),
            "statistik": e.get("statistik", ""), "thema": e.get("thema", ""), "palette": e.get("palette", ""),
            "titel": e.get("titel", ""), "sachzeile": e.get("sachzeile", ""),
            "q": e.get("qualitaetswert"), "pruefung": e.get("pruefung") or [],
        })
    kopf = {
        "anzahl": len(daten), "png": sum(d["ok"] for d in daten),
        "tabellen": len({d["tabelle"] for d in daten}), "typen": len({d["typ"] for d in daten}),
        "befunde": sum(1 for d in daten if d["pruefung"]),
        "bereiche": dict(sorted(Counter(d["bereich"] for d in daten).items())),
        "je_typ": dict(Counter(d["typname"] for d in daten).most_common()),
        "namen": BEREICHSNAMEN, "seed": seed, "zeit": datetime.now().strftime("%d.%m.%Y %H:%M"),
    }
    js = json.dumps({"kopf": kopf, "d": daten}, ensure_ascii=False).replace("</", "<\\/")
    ziel = aus / "uebersicht.html"
    ziel.write_text(VORLAGE.replace("__DATEN__", js), encoding="utf-8")
    return ziel


def oeffnen(pfad: Path) -> None:
    """Öffnet die Übersicht im Standardbrowser (nur unter Windows automatisch)."""
    if sys.platform.startswith("win"):
        try:
            os.startfile(str(pfad))  # noqa: S606
        except OSError:
            pass


VORLAGE = r"""<!doctype html>
<html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Übersicht der erzeugten Diagramme</title>
<style>
:root{--bg:#f5f5f3;--karte:#fff;--text:#1d1d1b;--grau:#6b6b66;--linie:#e2e0dc;--akzent:#1f5fa8;--warn:#b35900}
*{box-sizing:border-box}body{margin:0;font-family:system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif;background:var(--bg);color:var(--text);font-size:15px}
header{position:sticky;top:0;z-index:5;background:var(--karte);border-bottom:1px solid var(--linie);padding:14px 24px}
h1{margin:0 0 10px;font-size:20px}
.kpis{display:flex;flex-wrap:wrap;gap:10px;margin-bottom:12px}
.kpi{background:var(--bg);border:1px solid var(--linie);border-radius:6px;padding:6px 12px}
.kpi b{display:block;font-size:18px}.kpi span{font-size:12px;color:var(--grau)}
.filter{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.filter input,.filter select{font:inherit;padding:6px 8px;border:1px solid var(--linie);border-radius:5px;background:#fff}
.filter input[type=search]{min-width:260px}
.filter label{display:flex;gap:6px;align-items:center;color:var(--grau)}
#treffer{margin-left:auto;color:var(--grau)}
main{padding:18px 24px}
details{background:var(--karte);border:1px solid var(--linie);border-radius:6px;padding:10px 14px;margin-bottom:18px}
summary{cursor:pointer;font-weight:600}
.stat{display:grid;grid-template-columns:repeat(auto-fit,minmax(380px,1fr));gap:24px;margin-top:12px}
.zeile{display:grid;grid-template-columns:230px 1fr 48px;gap:8px;align-items:center;font-size:13px;margin:3px 0;cursor:pointer}
.zeile:hover .name{color:var(--akzent)}
.balken{height:10px;background:var(--akzent);border-radius:2px;opacity:.8}
.zeile .n{text-align:right;color:var(--grau)}
.gitter{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:16px}
figure{margin:0;background:var(--karte);border:1px solid var(--linie);border-radius:6px;overflow:hidden;cursor:zoom-in;display:flex;flex-direction:column}
figure:hover{border-color:var(--akzent)}
.bild{aspect-ratio:4/3;background:#fafaf8;display:flex;align-items:center;justify-content:center}
.bild img{max-width:100%;max-height:100%;object-fit:contain}
.fehlt{color:var(--grau);font-size:13px}
figcaption{padding:8px 10px;border-top:1px solid var(--linie);font-size:13px;line-height:1.35}
figcaption .t{font-weight:600;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
figcaption .m{color:var(--grau);margin-top:3px}
.marke{display:inline-block;font-size:11px;padding:1px 6px;border-radius:9px;background:#fff1e3;color:var(--warn);margin-left:4px}
#mehr{display:block;margin:22px auto;font:inherit;padding:8px 18px;border:1px solid var(--linie);border-radius:5px;background:#fff;cursor:pointer}
#gross{position:fixed;inset:0;background:rgba(20,20,20,.86);display:none;z-index:10;padding:24px}
#gross.an{display:grid;grid-template-columns:1fr 340px;gap:20px}
#gross .links{display:flex;align-items:center;justify-content:center;min-height:0}
#gross img{max-width:100%;max-height:calc(100vh - 48px);background:#fff}
#gross .info{background:#fff;border-radius:6px;padding:16px;overflow:auto;font-size:14px}
#gross .info h2{font-size:16px;margin:0 0 10px}
#gross dl{display:grid;grid-template-columns:110px 1fr;gap:4px 8px;margin:0}#gross dt{color:var(--grau)}#gross dd{margin:0;word-break:break-word}
#gross .knopf{display:flex;gap:8px;margin-top:14px}#gross button{font:inherit;padding:6px 12px;border:1px solid var(--linie);border-radius:5px;background:#fff;cursor:pointer}
@media (max-width:800px){#gross.an{grid-template-columns:1fr}.zeile{grid-template-columns:150px 1fr 40px}}
</style></head><body>
<header>
  <h1>Übersicht der erzeugten Diagramme</h1>
  <div class="kpis" id="kpis"></div>
  <div class="filter">
    <input type="search" id="suche" placeholder="Suche in Überschrift, Tabelle, Datei …">
    <select id="fBereich"><option value="">Alle Themenbereiche</option></select>
    <select id="fTyp"><option value="">Alle Diagrammtypen</option></select>
    <select id="fThema"><option value="">Alle Farbthemen</option></select>
    <label><input type="checkbox" id="fBefund"> nur mit Prüfbefund</label>
    <span id="treffer"></span>
  </div>
</header>
<main>
  <details id="statistik"><summary>Verteilung nach Themenbereich und Diagrammtyp</summary><div class="stat">
    <div><h3>Themenbereiche</h3><div id="sBereich"></div></div>
    <div><h3>Diagrammtypen</h3><div id="sTyp"></div></div>
  </div></details>
  <div class="gitter" id="gitter"></div>
  <button id="mehr">Weitere anzeigen</button>
</main>
<div id="gross"><div class="links"><img id="gBild" alt=""></div><div class="info" id="gInfo"></div></div>
<script>
const {kopf:K, d:D} = __DATEN__;
const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const pfad = s => s.split("/").map(encodeURIComponent).join("/");
const SEITE = 240; let liste = [], gezeigt = 0, aktiv = -1;

$("kpis").innerHTML = [["Diagramme",K.anzahl],["PNG-Bilder",K.png],["Tabellen",K.tabellen],["Diagrammtypen",K.typen],
  ["mit Prüfbefund",K.befunde],["Erzeugt",K.zeit],["Seed",K.seed ?? "–"]]
  .map(([s,w]) => `<div class="kpi"><b>${esc(w)}</b><span>${s}</span></div>`).join("");

const opt = (sel, werte) => werte.forEach(([w,t]) => sel.insertAdjacentHTML("beforeend", `<option value="${esc(w)}">${esc(t)}</option>`));
opt($("fBereich"), Object.keys(K.bereiche).map(b => [b, `${b} ${K.namen[b] ?? ""} (${K.bereiche[b]})`]));
opt($("fTyp"), Object.keys(K.je_typ).sort().map(t => [t, `${t} (${K.je_typ[t]})`]));
opt($("fThema"), [...new Set(D.map(x => x.thema))].sort().map(t => [t, t]));

function balken(ziel, eintraege, feld){
  const max = Math.max(...eintraege.map(e => e[1]), 1);
  $(ziel).innerHTML = eintraege.map(([k,n,name]) => `<div class="zeile" data-f="${feld}" data-w="${esc(k)}"><span class="name">${esc(name)}</span>
    <div class="balken" style="width:${(100*n/max).toFixed(1)}%"></div><span class="n">${n}</span></div>`).join("");
}
balken("sBereich", Object.entries(K.bereiche).map(([b,n]) => [b,n,`${b} ${K.namen[b] ?? ""}`]), "fBereich");
balken("sTyp", Object.entries(K.je_typ).map(([t,n]) => [t,n,t]), "fTyp");
document.querySelectorAll(".zeile").forEach(z => z.onclick = () => { $(z.dataset.f).value = z.dataset.w; filtern(); window.scrollTo({top:0}); });

function karte(x, i){
  const bild = x.ok ? `<img loading="lazy" src="${pfad(x.src)}" alt="${esc(x.titel)}">` : `<span class="fehlt">kein PNG</span>`;
  const befund = x.pruefung.length ? `<span class="marke">${x.pruefung.length} Befund</span>` : "";
  return `<figure data-i="${i}"><div class="bild">${bild}</div><figcaption><div class="t">${esc(x.titel)}</div>
    <div class="m">${esc(x.typname)} · Bereich ${esc(x.bereich)} · ${esc(x.tabelle)}${befund}</div></figcaption></figure>`;
}
function zeige(){
  const teil = liste.slice(gezeigt, gezeigt + SEITE);
  $("gitter").insertAdjacentHTML("beforeend", teil.map((x,j) => karte(x, gezeigt + j)).join(""));
  gezeigt += teil.length;
  $("mehr").style.display = gezeigt < liste.length ? "block" : "none";
}
function filtern(){
  const q = $("suche").value.trim().toLowerCase(), b = $("fBereich").value, t = $("fTyp").value, th = $("fThema").value, bf = $("fBefund").checked;
  liste = D.filter(x => (!b || x.bereich === b) && (!t || x.typname === t) && (!th || x.thema === th) && (!bf || x.pruefung.length)
    && (!q || `${x.titel} ${x.tabelle} ${x.tabellentitel} ${x.datei}`.toLowerCase().includes(q)));
  $("treffer").textContent = `${liste.length} von ${D.length} Diagrammen`;
  $("gitter").innerHTML = ""; gezeigt = 0; zeige();
}
["suche","fBereich","fTyp","fThema","fBefund"].forEach(id => $(id).addEventListener("input", filtern));
$("mehr").onclick = zeige;

function oeffne(i){
  if (i < 0 || i >= liste.length) return;
  aktiv = i; const x = liste[i];
  $("gBild").src = x.ok ? pfad(x.src) : "";
  $("gInfo").innerHTML = `<h2>${esc(x.titel)}</h2><dl>
    <dt>Sachzeile</dt><dd>${esc(x.sachzeile) || "–"}</dd>
    <dt>Diagrammtyp</dt><dd>${esc(x.typname)}</dd>
    <dt>Themenbereich</dt><dd>${esc(x.bereich)} ${esc(K.namen[x.bereich] ?? "")}</dd>
    <dt>Tabelle</dt><dd>${esc(x.tabelle)} – ${esc(x.tabellentitel)}</dd>
    <dt>Farbthema</dt><dd>${esc(x.thema)} / ${esc(x.palette)}</dd>
    <dt>Qualitätswert</dt><dd>${x.q ?? "–"}</dd>
    <dt>Prüfung</dt><dd>${x.pruefung.length ? x.pruefung.map(esc).join("<br>") : "keine Befunde"}</dd>
    <dt>Datei</dt><dd>${esc(x.src)}</dd></dl>
    <div class="knopf"><button id="zur">← zurück</button><button id="vor">weiter →</button><button id="zu">schließen (Esc)</button></div>
    <p style="color:#6b6b66;font-size:12px">${i+1} von ${liste.length}</p>`;
  $("zur").onclick = () => oeffne(aktiv-1); $("vor").onclick = () => oeffne(aktiv+1); $("zu").onclick = schliesse;
  $("gross").classList.add("an");
}
function schliesse(){ $("gross").classList.remove("an"); aktiv = -1; }
$("gitter").addEventListener("click", e => { const f = e.target.closest("figure"); if (f) oeffne(+f.dataset.i); });
$("gross").addEventListener("click", e => { if (e.target.id === "gross" || e.target.classList.contains("links")) schliesse(); });
document.addEventListener("keydown", e => { if (aktiv < 0) return;
  if (e.key === "Escape") schliesse(); if (e.key === "ArrowRight") oeffne(aktiv+1); if (e.key === "ArrowLeft") oeffne(aktiv-1); });
filtern();
</script></body></html>
"""


if __name__ == "__main__":
    hier = Path(__file__).resolve().parent
    if len(sys.argv) > 1:
        ordner = Path(sys.argv[1]).resolve()
    else:
        import yaml
        cfg = yaml.safe_load((hier / "config.yaml").read_text(encoding="utf-8"))
        ordner = (hier / cfg["pfade"]["ausgabe"]).resolve()
    mp = ordner / "manifest.json"
    if not mp.exists():
        sys.exit(f"Kein manifest.json in {ordner} – bitte zuerst die Diagramme erzeugen.")
    m = json.loads(mp.read_text(encoding="utf-8"))
    ziel = schreibe_uebersicht(ordner, m["diagramme"], m.get("seed"))
    print(f"Übersicht: {ziel} ({len(m['diagramme'])} Diagramme)")
    oeffnen(ziel)
