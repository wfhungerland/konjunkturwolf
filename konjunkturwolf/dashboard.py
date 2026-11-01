"""Statisches Web-Dashboard (Plotly) für GitHub Pages."""

from __future__ import annotations

import json
import shutil
from importlib import resources
from pathlib import Path

import pandas as pd

from .catalog import SOURCE_LICENSES, Catalog
from .pipeline import RunResult

SITE_URL = "https://wfhungerland.github.io/konjunkturwolf/"
AUTHOR = "Hungerland, Wolf-Fabian"
REFERENCES = [
    "Jordà, Òscar, Moritz Schularick und Alan M. Taylor (2017): Macrofinancial History and the New Business Cycle Facts. "
    "NBER Macroeconomics Annual 2016, Bd. 31, S. 213–263, https://doi.org/10.1086/690241. Daten: JST Macrohistory Database, Release 6, https://www.macrohistory.net/database/.",
    "Müller, Karsten, Chenzi Xu, Mohamed Lehbib und Ziliang Chen (2025): The Global Macro Database. A New International "
    "Macroeconomic Dataset. NBER Working Paper 33714, https://doi.org/10.3386/w33714. Daten: https://www.globalmacrodata.com.",
    "National Bureau of Economic Research: NBER Macrohistory Database, https://www.nber.org/research/data/nber-macrohistory-database.",
    "Fouquin, Michel und Jules Hugot (2016): Two Centuries of Bilateral Trade and Gravity Data: 1827–2014. CEPII Working Paper "
    "2016-14. Daten: TRADHIST, http://www.cepii.fr.",
    "Fremdling, Rainer und Reiner Stäglin (2014): An Input-Output Table for Germany in 1936. A Documentation of Results, Sources "
    "and Research Strategy. Jahrbuch für Wirtschaftsgeschichte / Economic History Yearbook 2014/2. https://doi.org/10.1515/jbwg-2014-0018.",
    "Eurostat, Europäische Zentralbank, Deutsche Bundesbank, Statistisches Bundesamt (Destatis): Datenbanken, abgerufen über die "
    "jeweiligen Schnittstellen; Direktlinks je Reihe im Excel-Workbook (Blatt Quellen).",
]


def citation(stand: str) -> str:
    return (f"{AUTHOR} ({stand[:4]}): konjunkturwolf. Wirtschaftsdaten im langen Vergleich. "
            f"Datenstand {stand[:10]}. {SITE_URL}")


FREQ_LABELS = {"D": "täglich", "M": "monatlich", "Q": "vierteljährlich", "S": "halbjährlich", "A": "jährlich"}


def _item(spec, g, st) -> dict:
    item = {
        "id": spec.id, "label": spec.display_label, "title": spec.title, "unit": spec.unit,
        "frequency": FREQ_LABELS.get(spec.frequency, spec.frequency), "adjustment": spec.adjustment,
        "source": spec.source_label, "link": spec.web_link, "style": spec.style, "member": spec.member,
        "status": st.status if st else "failed", "outdated": bool(st.outdated) if st else False,
        "message": (st.message if st else "")[:300], "x": [], "y": [],
    }
    if g is not None and not g.empty:
        g = g.sort_values("date")
        item["x"] = pd.to_datetime(g["date"]).dt.strftime("%Y-%m-%d").tolist()
        item["y"] = [round(float(v), 6) for v in g["value"]]
    return item


MONTHS = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August",
          "September", "Oktober", "November", "Dezember"]
ISO3_TO_2 = {"DEU": "DE", "FRA": "FR", "ITA": "IT", "ESP": "ES", "NLD": "NL", "POL": "PL",
             "GBR": "GB", "USA": "US"}


def _num(v: float) -> str:
    return f"{v:.1f}".replace(".", ",").replace("-", "−")


def _unit(u: str) -> str:
    if u.startswith("Index"):
        return "Punkte"
    return "%" if u.startswith("%") else ("Pp" if u.startswith("Pp") else u)


def _period(date: str, freq: str) -> str:
    y, m = int(date[:4]), int(date[5:7])
    if freq == "vierteljährlich":
        return f"Q{(m - 1) // 3 + 1} {y}"
    if freq == "jährlich":
        return str(y)
    return f"{MONTHS[m - 1]} {y}"


def _quantile(ys: list[float], q: float) -> float:
    v = sorted(ys)
    k = (len(v) - 1) * q
    lo = int(k)
    hi = min(lo + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


def _std(ys: list[float]) -> float:
    m = sum(ys) / len(ys)
    return (sum((v - m) ** 2 for v in ys) / max(len(ys) - 1, 1)) ** 0.5


def episode_facts(eps: list[dict]) -> list[str]:
    """Krisenvergleich: Tiefpunkt und Erholung je Episode."""
    out = []
    for e in eps:
        if len(e["y"]) < 2:
            continue
        name = e["label"]
        low = min(e["y"]); t_low = e["x"][e["y"].index(low)]
        back = next((x for x, y in zip(e["x"], e["y"]) if x > t_low and y >= 100), None)
        last_x, last_y = e["x"][-1], e["y"][-1]
        def yrs(n):
            return "einem Jahr" if n == 1 else f"{n} Jahren"
        if back is not None:
            out.append(f"{name}: Tiefpunkt nach {yrs(t_low)} bei {_num(low)} % des Hochs, "
                       f"nach {yrs(back)} wieder auf dem Hoch.")
        elif low == last_y:
            out.append(f"{name}: nach {yrs(last_x)} bei {_num(last_y)} % des Hochs, so tief wie noch nie seit dem Hoch.")
        else:
            out.append(f"{name}: nach {yrs(last_x)} bei {_num(last_y)} % des Hochs, Tiefpunkt bisher "
                       f"{_num(low)} % nach {yrs(t_low)}; das Hoch ist nicht wieder erreicht.")
    return out


def panel_facts(catalog: Catalog, sides: dict, extra: list[str] | None = None) -> list[str]:
    """Kurze Einordnung aus den Daten: aktueller Wert, Lage unter den Nachbarn, Lage zur Geschichte."""
    focus = set(catalog.comparison.get("focus") or [])
    right = [s for s in sides["right"]["series"] if s["y"] and s["member"]]
    left = [s for s in sides["left"]["series"] if s["y"]]
    de = next((s for s in right if s["member"] in focus), None)
    if de is None:
        # ohne Fokusland (z.B. Renditeabstände zu Deutschland): letzte Werte je Land
        if not right:
            return []
        date = max(s["x"][-1] for s in right)
        vals = sorted(((s["y"][-1], s["label"]) for s in right if s["x"][-1] == date), reverse=True)
        u = _unit(right[0]["unit"])
        return [f"Zuletzt ({_period(date, right[0]['frequency'])}): "
                + ", ".join(f"{lab} {_num(v)} {u}" for v, lab in vals) + "."]
    u = _unit(de["unit"])
    date, value = de["x"][-1], de["y"][-1]
    if de["unit"].startswith("Index") and "=100" in de["unit"].replace(" ", ""):
        base = de["unit"].split()[-1].split("=")[0]
        facts = [f"Zuletzt ({_period(date, de['frequency'])}): Deutschland {_num(value)} ({base} = 100), "
                 f"also {_num(abs(value - 100))} % {'unter' if value < 100 else 'über'} {base}."]
    else:
        facts = [f"Zuletzt ({_period(date, de['frequency'])}): Deutschland {_num(value)} {u}."]
    peers = {s["label"]: dict(zip(s["x"], s["y"]))[date]
             for s in right if s is not de and date in s["x"]}
    if peers:
        higher = sum(v > value for v in peers.values())
        lo, hi = min(peers, key=peers.get), max(peers, key=peers.get)
        missing = [s["label"] for s in right if s is not de and s["label"] not in peers]
        n = len(peers)
        lage = (f"Höher als bei allen {n} Nachbarn" if higher == 0 else f"Niedriger als bei allen {n} Nachbarn"
                if higher == n else f"Von {n} Nachbarn liegen {higher} höher und {n - higher} niedriger")
        facts.append(f"{lage} (Spanne {lo} {_num(peers[lo])} bis {hi} {_num(peers[hi])} {u})"
                     + (f"; {', '.join(missing)} noch ohne Wert." if missing else "."))
    hist = next((s for s in left if s["member"] in focus), None)
    if hist and len(hist["y"]) >= 30:
        ys = hist["y"]
        what = "Monatswerte" if hist["frequency"] == "monatlich" else "Jahreswerte"
        span = f"{hist['x'][0][:4]} bis {hist['x'][-1][:4]}"
        # Gleiche Frequenz vergleichen: Jahreswerte der Geschichte gegen das Mittel der letzten 12 Monate bzw. 4 Quartale
        n = {"monatlich": 12, "vierteljährlich": 4}.get(de["frequency"], 1) if what == "Jahreswerte" else 1
        if len(de["y"]) < n:
            n = 1
        cmp_value = sum(de["y"][-n:]) / n
        sides["right"]["hist_value"] = round(cmp_value, 4)
        lead = ("Das Mittel der letzten 12 Monate" if n == 12 else "Das Mittel der letzten vier Quartale" if n == 4
                else "Der aktuelle Wert") + (f" ({_num(cmp_value)} {u})" if n > 1 else "")
        share = round(100 * sum(v < cmp_value for v in ys) / len(ys))
        unit_word = "Monat" if what == "Monatswerte" else "Jahr"
        if share >= 99:
            facts.append(f"{lead} ist so hoch wie in keinem {unit_word} {span}; Median {_num(_quantile(ys, 0.5))} {u}.")
        elif share <= 1:
            facts.append(f"{lead} ist so niedrig wie in keinem {unit_word} {span}; Median {_num(_quantile(ys, 0.5))} {u}.")
        else:
            facts.append(f"{lead} ist höher als {share} % der {what} {span}; Median {_num(_quantile(ys, 0.5))} {u}.")
        if "volatility" in (extra or []):
            cut = f"{int(date[:4]) - 5}{date[4:]}"
            recent = [y for x, y in zip(de["x"], de["y"]) if x > cut]
            win = len(recent)
            if win > 12 and len(ys) > win:
                rolling = [_std(ys[k:k + win]) for k in range(0, len(ys) - win + 1)]
                now_sd = _std(recent)
                pct = round(100 * sum(r < now_sd for r in rolling) / len(rolling))
                facts.append(f"Schwankung der letzten fünf Jahre (Standardabweichung {_num(now_sd)} Pp): höher als in {pct} % "
                             f"aller Fünfjahresfenster {span} (Median {_num(_quantile(rolling, 0.5))} Pp).")
    return facts


def history_band(catalog: Catalog, sides: dict) -> dict | None:
    """Mittlere 50 % und Median der deutschen Jahreswerte (lange Reihe) für die rechte Abbildung."""
    focus = set(catalog.comparison.get("focus") or [])
    hist = next((s for s in sides["left"]["series"] if s["member"] in focus and len(s["y"]) >= 30), None)
    if hist is None:
        return None
    ys = hist["y"]
    return {"p25": round(_quantile(ys, 0.25), 3), "p50": round(_quantile(ys, 0.5), 3),
            "p75": round(_quantile(ys, 0.75), 3), "from": hist["x"][0][:4], "to": hist["x"][-1][:4],
            "values": "Monatswerte" if hist["frequency"] == "monatlich" else "Jahreswerte",
            "p05": round(_quantile(ys, 0.05), 3), "p95": round(_quantile(ys, 0.95), 3),
            "label": hist["label"]}


def extend_long(sides: dict) -> str:
    """Verlängert die langen Jahresreihen mit Jahresmitteln der aktuellen Reihen (gleiches Land).

    Markiert ein unvollständiges letztes Jahr (partial_last) und misst für Deutschland die mittlere
    Abweichung zwischen beiden Quellen in den Jahren, in denen sich beide überschneiden.
    """
    right = {s["member"]: s for s in sides["right"]["series"] if s["member"] and s["y"]}
    first_ext, last_info, overlap = None, "", ""
    for s in sides["left"]["series"]:
        cur = right.get(ISO3_TO_2.get(s["member"] or "", s["member"]))
        if cur is None or not s["y"]:
            continue
        last_year = int(s["x"][-1][:4])
        by_year: dict[int, list[float]] = {}
        for x, y in zip(cur["x"], cur["y"]):
            by_year.setdefault(int(x[:4]), []).append(y)
        per_year = {"monatlich": 12, "vierteljährlich": 4}.get(cur["frequency"], 1)
        # Überschneidung: nur volle Jahre vergleichen
        if s["member"] in ("DEU", "DE"):
            left_by = {int(x[:4]): y for x, y in zip(s["x"], s["y"])}
            common = [yr for yr in by_year if yr in left_by and len(by_year[yr]) >= per_year]
            if len(common) >= 3:
                dev = sum(abs(sum(by_year[yr]) / len(by_year[yr]) - left_by[yr]) for yr in common) / len(common)
                unit = "Pp" if str(s.get("unit", "")).startswith(("%", "Pp")) else "Punkte"
                overlap = (f" Zum Vergleich: In den Jahren {min(common)} bis {max(common)}, die beide Quellen abdecken, "
                           + (f"weichen die Jahresmittel der aktuellen Reihe für Deutschland praktisch nicht von der langen Reihe ab (unter 0,1 {unit})."
                              if dev < 0.05 else
                              f"weicht das Jahresmittel der aktuellen Reihe für Deutschland im Mittel um {_num(dev)} {unit} von der langen Reihe ab."))
        new_years = {yr: v for yr, v in by_year.items() if yr > last_year}
        if not new_years or min(new_years) > last_year + 1:
            continue  # nur lückenlos anschließen
        for year in sorted(new_years):
            s["x"].append(f"{year}-01-01")
            s["y"].append(round(sum(new_years[year]) / len(new_years[year]), 6))
        s["ext_from"] = f"{min(new_years)}-01-01"
        if cur.get("license") and cur["license"] not in s.get("license", ""):
            s["license"] = "; ".join(x for x in (s.get("license"), cur["license"]) if x)
        first_ext = min(first_ext or 9999, min(new_years))
        y_last = max(new_years)
        if per_year > 1 and len(new_years[y_last]) < per_year:
            s["partial_last"] = True
            if not last_info or s["member"] in ("DEU", "DE"):
                last_info = (f"; {y_last} nur bis {_period(cur['x'][-1], cur['frequency']).rsplit(' ', 1)[0]} "
                             f"(hohler Punkt)")
    if first_ext is None:
        return ""
    return (f"Ab {first_ext}: Jahresmittel der aktuellen Werte aus der rechten Abbildung, andere Quelle oder Definition, "
            f"Niveausprünge möglich{last_info}.{overlap}")


def episode_items(cfg: dict, items: dict[str, dict]) -> list[dict]:
    """Krisenvergleich: Jahresmittel je Reihe, Hoch im Fenster = 100, x = Jahre nach dem Hoch."""
    out = []
    horizon = int(cfg.get("years") or 8)
    for ep in cfg["episodes"]:
        src = items[ep["series"]]
        by_year: dict[int, list[float]] = {}
        for x, y in zip(src["x"], src["y"]):
            by_year.setdefault(int(x[:4]), []).append(y)
        annual = {yr: sum(v) / len(v) for yr, v in by_year.items()}
        lo, hi = ep["window"]
        cands = {yr: v for yr, v in annual.items() if lo <= yr <= hi}
        item = dict(src, id=f"{src['id']}_{ep['label']}", member=None, unit="Index, Hoch = 100",
                    frequency="jährlich", x=[], y=[])
        if cands:
            peak = max(cands, key=cands.get)
            item["label"] = f"{ep['label']} (Hoch {peak})"
            for yr in range(peak, peak + horizon + 1):
                if yr in annual:
                    item["x"].append(yr - peak)
                    item["y"].append(round(annual[yr] / annual[peak] * 100, 3))
            last = src["x"][-1] if src["x"] else ""
            per_year = {"monatlich": 12, "vierteljährlich": 4}.get(src["frequency"])
            if per_year and last and len(by_year.get(int(last[:4]), [])) < per_year and int(last[:4]) - peak <= horizon:
                item["partial"] = f"{last[:4]} bis {_period(last, src['frequency']).rsplit(' ', 1)[0]}"
                item["partial_last"] = True
        else:
            item["label"] = ep["label"]
        out.append(item)
    return out


def license_for(spec, by_id) -> str:
    """Lizenz einer Reihe; abgeleitete Reihen tragen die Lizenzen ihrer Basisreihen."""
    if spec.source != "derived":
        return SOURCE_LICENSES.get(spec.source, "")
    parts = []
    for key in ("from", "minus", "plus"):
        base = by_id.get(spec.derive.get(key) or "")
        if base is not None:
            lic = license_for(base, by_id)
            if lic and lic not in parts:
                parts.append(lic)
    return "; ".join(parts)


def build_panels(catalog: Catalog, result: RunResult) -> list[dict]:
    """Kernindikatoren: je Panel links der lange Rand, rechts der aktuelle Rand."""
    obs = result.observations
    statuses = result.status_map()
    grouped = {sid: g for sid, g in obs.groupby("series_id")} if not obs.empty else {}
    by_id = catalog.by_id()
    out = []
    for p in catalog.panels:
        sides = {}
        for side in ("left", "right"):
            cfg = p.get(side) or {}
            if cfg.get("episodes"):
                specs = [by_id[e["series"]] for e in cfg["episodes"]]
                base = catalog.chart(f"{p['id']}_{side}")
            elif cfg.get("chart"):
                specs = [s for s in catalog.series if s.chart_id == cfg["chart"]]
                base = catalog.chart(cfg["chart"], specs[0] if specs else None)
            else:
                specs = [by_id[sid] for sid in cfg["series"]]
                base = catalog.chart(f"{p['id']}_{side}")
            if catalog.panel_members:
                specs = [s for s in specs if not s.member or s.member in catalog.panel_members]
            sides[side] = {
                "id": f"{p['id']}_{side}",
                "title": cfg.get("title") or base.title,
                "full": side == "left",
                "years": cfg.get("years") or (None if side == "left" else 5),
                "y_min": cfg.get("y_min", base.y_min), "y_max": cfg.get("y_max", base.y_max),
                "kind": base.kind, "decimals": cfg.get("decimals", base.decimals),
                "note": cfg.get("note", ""),
                "series": [dict(_item(s, grouped.get(s.id), statuses.get(s.id)), license=license_for(s, by_id),
                                note=s.note or "") for s in specs],
            }
            if cfg.get("episodes"):
                items = {s["id"]: s for s in sides[side]["series"]}
                eps = episode_items(cfg, items)
                partial = [f"{e['label'].split(' (')[0]}: {e['partial']}" for e in eps if e.get("partial")]
                sides[side].update(kind="episodes", series=eps, full=True, decimals=0,
                                   note="x-Achse: Jahre nach dem Hoch; Jahresmittel. 1929 beruht auf dem jährlichen NBER-Produktionsindex "
                                     "(Deutsches Reich), heute auf Eurostat (Industrie ohne Bau); Jahresmittel glätten den Tiefpunkt."
                                        + (f" Laufendes Jahr unvollständig ({'; '.join(partial)})." if partial else ""))
        facts = panel_facts(catalog, sides, p.get("facts"))
        if sides["left"].get("kind") == "episodes":
            facts = episode_facts(sides["left"]["series"]) + facts
        sides["right"]["history"] = history_band(catalog, sides)
        ext = extend_long(sides)
        if ext:
            sides["left"]["note"] = " ".join(x for x in (sides["left"]["note"], ext) if x)
        out.append({"id": p["id"], "title": p["title"], "question": p.get("question", ""),
                    "text": p.get("text", ""), "facts": facts, **sides})
    return out


def _load_io() -> dict | None:
    """Abgeleitete Kennzahlen des IO-Vergleichs (data/static/io_compare.json), falls vorhanden."""
    path = Path(__file__).resolve().parent.parent / "data" / "static" / "io_compare.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def build_payload(catalog: Catalog, result: RunResult) -> dict:
    obs = result.observations
    statuses = result.status_map()
    grouped = {sid: g for sid, g in obs.groupby("series_id")} if not obs.empty else {}
    blocks = []
    for block in catalog.blocks:
        charts: dict[str, dict] = {}
        for spec in catalog.series_in_block(block.id):
            chart = catalog.chart(spec.chart_id, spec)
            entry = charts.setdefault(
                chart.id, {"id": chart.id, "title": chart.title, "full": block.history,
                 "y_min": chart.y_min, "y_max": chart.y_max, "kind": chart.kind, "decimals": chart.decimals, "series": []}
            )
            g = grouped.get(spec.id)
            st = statuses.get(spec.id)
            item = {
                "id": spec.id,
                "label": spec.display_label,
                "title": spec.title,
                "unit": spec.unit,
                "frequency": FREQ_LABELS.get(spec.frequency, spec.frequency),
                "adjustment": spec.adjustment,
                "source": spec.source_label,
                "link": spec.web_link,
                "style": spec.style,
                "member": spec.member,
                "status": st.status if st else "failed",
                "outdated": bool(st.outdated) if st else False,
                "message": (st.message if st else "")[:300],
                "x": [],
                "y": [],
            }
            if g is not None and not g.empty:
                g = g.sort_values("date")
                item["x"] = pd.to_datetime(g["date"]).dt.strftime("%Y-%m-%d").tolist()
                item["y"] = [round(float(v), 6) for v in g["value"]]
            entry["series"].append(item)
        blocks.append({"id": block.id, "title": block.title, "charts": list(charts.values())})
    return {
        "generated_at": result.finished_at,
        "counts": result.counts(),
        "comparison": catalog.comparison,
        "panels": build_panels(catalog, result),
        "io": _load_io(),
        "citation": citation(str(result.finished_at)),
        "references": REFERENCES,
        "blocks": blocks,
    }


def build_site(catalog: Catalog, result: RunResult, site_dir: str | Path, xlsx_path: str | Path | None) -> Path:
    site = Path(site_dir)
    site.mkdir(parents=True, exist_ok=True)
    payload = build_payload(catalog, result)
    from .downloads import write_downloads

    for pi, panel in enumerate(payload["panels"]):
        for k, side in enumerate(("left", "right")):
            sd = panel[side]
            note = "Quelle: " + ", ".join(dict.fromkeys(s["source"] for s in sd["series"] if s["x"])) + ". konjunkturwolf, Stand " + str(payload["generated_at"])[:10]
            try:
                sd["downloads"] = write_downloads(sd, 2 * pi + k + 1, site / "downloads", note, payload["citation"])
            except Exception as exc:  # Downloads dürfen die Seite nicht verhindern
                sd["downloads"] = {}
                print(f"Download für {sd['id']} fehlgeschlagen: {exc}")
    data_js = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    template = resources.files("konjunkturwolf").joinpath("templates/dashboard.html").read_text(encoding="utf-8")
    html = template.replace("/*__DATA__*/null", data_js)
    (site / "index.html").write_text(html, encoding="utf-8")
    (site / "data.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    (site / ".nojekyll").write_text("", encoding="utf-8")
    plotly_js = resources.files("konjunkturwolf").joinpath("static/plotly.min.js")
    (site / "plotly.min.js").write_bytes(plotly_js.read_bytes())
    if xlsx_path and Path(xlsx_path).exists():
        shutil.copy2(xlsx_path, site / "konjunkturwolf.xlsx")
    return site / "index.html"
