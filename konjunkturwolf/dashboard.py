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
                "series": [_item(s, grouped.get(s.id), statuses.get(s.id)) for s in specs],
            }
        out.append({"id": p["id"], "title": p["title"], "text": p.get("text", ""), **sides})
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
