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


def panel_facts(catalog: Catalog, sides: dict) -> list[str]:
    """Kurze Einordnung aus den Daten: aktueller Wert, Rang, Lage zur Geschichte."""
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
    facts = [f"Zuletzt ({_period(date, de['frequency'])}): Deutschland {_num(value)} {u}."]
    peers = {s["label"]: dict(zip(s["x"], s["y"]))[date]
             for s in right if s is not de and date in s["x"]}
    if peers:
        rank = 1 + sum(v > value for v in peers.values())
        lo, hi = min(peers, key=peers.get), max(peers, key=peers.get)
        missing = [s["label"] for s in right if s is not de and s["label"] not in peers]
        facts.append(f"Rang {rank} von {len(peers) + 1} Ländern (1 = höchster Wert); "
                     f"Spanne von {lo} {_num(peers[lo])} {u} bis {hi} {_num(peers[hi])} {u}"
                     + (f" ({', '.join(missing)} noch ohne Wert)." if missing else "."))
    hist = next((s for s in left if s["member"] in focus), None)
    if hist and len(hist["y"]) >= 30:
        ys = hist["y"]
        share = round(100 * sum(v < value for v in ys) / len(ys))
        facts.append(f"Von {hist['x'][0][:4]} bis {hist['x'][-1][:4]} lag der Jahreswert in {share} % "
                     f"der Jahre unter dem aktuellen Wert; Median {_num(_quantile(ys, 0.5))} {u}.")
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
        if not by_year:
            continue
        for year in sorted(by_year):
            s["x"].append(f"{year}-01-01")
            s["y"].append(round(sum(by_year[year]) / len(by_year[year]), 6))
        s["ext_from"] = f"{min(by_year)}-01-01"
        first_ext = min(first_ext or 9999, min(by_year))
        y_last = max(by_year)
        per_year = {"monatlich": 12, "vierteljährlich": 4}.get(cur["frequency"])
        if per_year and len(by_year[y_last]) < per_year:
            last_info = f"; {y_last} nur bis {_period(cur['x'][-1], cur['frequency']).rsplit(' ', 1)[0]}"
    if first_ext is None:
        return ""
    return f"Ab {first_ext}: Jahresmittel der aktuellen Werte aus der rechten Abbildung{last_info}."


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
            if cfg.get("chart"):
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
        facts = panel_facts(catalog, sides)
        sides["right"]["history"] = history_band(catalog, sides)
        ext = extend_long(sides)
        if ext:
            sides["left"]["note"] = " ".join(x for x in (sides["left"]["note"], ext) if x)
        out.append({"id": p["id"], "title": p["title"], "question": p.get("question", ""),
                    "text": p.get("text", ""), "facts": facts, **sides})
    return out


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
        "blocks": blocks,
    }


def build_site(catalog: Catalog, result: RunResult, site_dir: str | Path, xlsx_path: str | Path | None) -> Path:
    site = Path(site_dir)
    site.mkdir(parents=True, exist_ok=True)
    payload = build_payload(catalog, result)
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
