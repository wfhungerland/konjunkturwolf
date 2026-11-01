"""Statisches Web-Dashboard (Plotly) für GitHub Pages."""

from __future__ import annotations

import json
import shutil
from importlib import resources
from pathlib import Path

import pandas as pd

from .catalog import Catalog
from .pipeline import RunResult

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
        share = round(100 * sum(v < value for v in ys) / len(ys))
        what = "Monatswerte" if hist["frequency"] == "monatlich" else "Jahreswerte"
        span = f"{hist['x'][0][:4]} bis {hist['x'][-1][:4]}"
        if share >= 99:
            facts.append(f"So hoch wie in keinem {'Monat' if what == 'Monatswerte' else 'Jahr'} {span}; Median {_num(_quantile(ys, 0.5))} {u}.")
        elif share <= 1:
            facts.append(f"So niedrig wie in keinem {'Monat' if what == 'Monatswerte' else 'Jahr'} {span}; Median {_num(_quantile(ys, 0.5))} {u}.")
        else:
            facts.append(f"Höher als {share} % der {what} {span}; Median {_num(_quantile(ys, 0.5))} {u}.")
        if "volatility" in (extra or []):
            cut = f"{int(date[:4]) - 5}{date[4:]}"
            recent = [y for x, y in zip(de["x"], de["y"]) if x > cut]
            if len(recent) > 12:
                facts.append(f"Schwankung (Standardabweichung): {span} {_num(_std(ys))} Pp, "
                             f"letzte fünf Jahre {_num(_std(recent))} Pp.")
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
    """Verlängert die langen Jahresreihen mit Jahresmitteln der aktuellen Reihen (gleiches Land)."""
    right = {s["member"]: s for s in sides["right"]["series"] if s["member"] and s["y"]}
    first_ext, last_info = None, ""
    for s in sides["left"]["series"]:
        cur = right.get(ISO3_TO_2.get(s["member"] or "", s["member"]))
        if cur is None or not s["y"]:
            continue
        last_year = int(s["x"][-1][:4])
        by_year: dict[int, list[float]] = {}
        for x, y in zip(cur["x"], cur["y"]):
            if int(x[:4]) > last_year:
                by_year.setdefault(int(x[:4]), []).append(y)
        if not by_year or min(by_year) > last_year + 1:
            continue  # nur lückenlos anschließen
        for year in sorted(by_year):
            s["x"].append(f"{year}-01-01")
            s["y"].append(round(sum(by_year[year]) / len(by_year[year]), 6))
        s["ext_from"] = f"{min(by_year)}-01-01"
        first_ext = min(first_ext or 9999, min(by_year))
        y_last = max(by_year)
        per_year = {"monatlich": 12, "vierteljährlich": 4}.get(cur["frequency"])
        if per_year and len(by_year[y_last]) < per_year and (not last_info or s["member"] in ("DEU", "DE")):
            last_info = f"; {y_last} nur bis {_period(cur['x'][-1], cur['frequency']).rsplit(' ', 1)[0]}"
    if first_ext is None:
        return ""
    return f"Ab {first_ext}: Jahresmittel der aktuellen Werte aus der rechten Abbildung{last_info}."


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
        else:
            item["label"] = ep["label"]
        out.append(item)
    return out


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
                "series": [_item(s, grouped.get(s.id), statuses.get(s.id)) for s in specs],
            }
            if cfg.get("episodes"):
                items = {s["id"]: s for s in sides[side]["series"]}
                eps = episode_items(cfg, items)
                partial = [f"{e['label'].split(' (')[0]}: {e['partial']}" for e in eps if e.get("partial")]
                sides[side].update(kind="episodes", series=eps, full=True, decimals=0,
                                   note="x-Achse: Jahre nach dem Hoch; Jahresmittel."
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
                sd["downloads"] = write_downloads(sd, 2 * pi + k + 1, site / "downloads", note)
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
