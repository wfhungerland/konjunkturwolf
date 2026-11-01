"""Downloads je Abbildung: Excel mit Diagramm und Daten, CSV (nur Daten), Stata (.dta)."""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

PALETTE = ["#002060", "#0070C0", "#00B0F0", "#51154A", "#7030A0", "#D86DCD", "#47D359"]
PEER_GREY = "#B4B4B4"
FONT = "Arial Narrow"


def chart_frame(side: dict) -> tuple[pd.DataFrame, str]:
    """Breite Tabelle: eine Zeile je Periode, eine Spalte je Reihe."""
    episodes = side.get("kind") == "episodes"
    key = "Jahre nach dem Hoch" if episodes else "Datum"
    cols = []
    for s in side["series"]:
        if not s["x"]:
            continue
        x = s["x"] if episodes else pd.to_datetime(s["x"])
        cols.append(pd.Series(s["y"], index=x, name=s["label"]))
    if not cols:
        return pd.DataFrame(columns=[key]), key
    df = pd.concat(cols, axis=1).sort_index()
    df.index.name = key
    return df.reset_index(), key


def stata_name(label: str, used: set[str]) -> str:
    base = re.sub(r"[^A-Za-z0-9_]", "_", label.translate(str.maketrans("äöüÄÖÜß", "aouAOUs")))
    base = re.sub(r"_+", "_", base).strip("_").lower() or "v"
    if base[0].isdigit():
        base = "v_" + base
    name, i = base[:32], 2
    while name in used:
        suffix = f"_{i}"
        name, i = base[: 32 - len(suffix)] + suffix, i + 1
    used.add(name)
    return name


def write_downloads(side: dict, number: int, folder: Path, source_note: str) -> dict:
    folder.mkdir(parents=True, exist_ok=True)
    stem = f"abb{number:02d}_{side['id']}"
    df, key = chart_frame(side)
    title = f"Abb. {number}: {side['title']}"
    files = {}

    # CSV: Semikolon und Dezimalkomma (öffnet direkt im deutschen Excel)
    csv = folder / f"{stem}.csv"
    out = df.copy()
    if key == "Datum":
        out[key] = pd.to_datetime(out[key]).dt.strftime("%Y-%m-%d")
    out.to_csv(csv, sep=";", decimal=",", index=False, encoding="utf-8-sig")
    files["csv"] = csv.name

    # Stata
    used: set[str] = set()
    names = {c: ("date" if c == "Datum" else "years_after_peak" if c == key else stata_name(c, used)) for c in df.columns}
    st = df.rename(columns=names)
    labels = {names[c]: c[:80] for c in df.columns}
    dta = folder / f"{stem}.dta"
    st.to_stata(dta, write_index=False, version=118, variable_labels=labels, data_label=title[:80],
                convert_dates={"date": "td"} if "date" in st.columns else None)
    files["dta"] = dta.name

    # Excel mit Diagramm
    xlsx = folder / f"{stem}.xlsx"
    with pd.ExcelWriter(xlsx, engine="xlsxwriter", datetime_format="yyyy-mm-dd") as xw:
        wb = xw.book
        sheet = wb.add_worksheet("Abbildung")
        sheet.write(0, 0, title, wb.add_format({"bold": True, "font_name": FONT, "font_size": 12}))
        sheet.write(1, 0, source_note, wb.add_format({"font_name": FONT, "font_color": "#666666"}))
        sheet.hide_gridlines(2)
        df.to_excel(xw, sheet_name="Daten", index=False, startrow=3)
        ws = xw.sheets["Daten"]
        ws.write(0, 0, title, wb.add_format({"bold": True, "font_name": FONT, "font_size": 12}))
        ws.write(1, 0, source_note, wb.add_format({"font_name": FONT, "font_color": "#666666"}))
        ws.set_column(0, 0, 14)
        ws.set_column(1, max(1, len(df.columns) - 1), 16)
        n = len(df)
        if n and len(df.columns) > 1:
            chart = wb.add_chart({"type": "line"} if key == "Datum" else {"type": "scatter", "subtype": "straight_with_markers"})
            focus_seen = False
            for j, col in enumerate(df.columns[1:], start=1):
                spec = next((s for s in side["series"] if s["label"] == col), {})
                is_focus = spec.get("member") in ("DE", "DEU")
                is_peer = spec.get("member") and not is_focus and len(df.columns) > 3
                color = PALETTE[0] if is_focus else (PEER_GREY if is_peer else PALETTE[(j if focus_seen else j - 1) % len(PALETTE)])
                if key != "Datum":  # Krisenvergleich: jüngste Episode dunkelblau, wie auf der Webseite
                    last = j == len(df.columns) - 1
                    color = PALETTE[0] if last else [PALETTE[2], PALETTE[4], PALETTE[5]][(j - 1) % 3]
                focus_seen = focus_seen or is_focus
                chart.add_series({
                    "name": ["Daten", 3, j],
                    "categories": ["Daten", 4, 0, 3 + n, 0],
                    "values": ["Daten", 4, j, 3 + n, j],
                    "line": {"color": color, "width": 2.25 if is_focus else 1.25},
                    "marker": {"type": "none"} if key == "Datum" else {"type": "circle", "size": 4},
                })
            axis_font = {"name": FONT, "size": 9}
            x_opts = {}
            if key == "Datum":
                span = (pd.to_datetime(df[key]).max() - pd.to_datetime(df[key]).min()).days / 365.25
                step = next(k for k in (1, 2, 5, 10, 20, 25, 50) if span / k <= 12)
                x_opts = {"date_axis": True, "num_format": "yyyy", "major_unit": step, "major_unit_type": "years"}
            chart.set_x_axis({"num_font": {**axis_font, "rotation": 0}, "line": {"none": True}, "major_tick_mark": "none",
                              "label_position": "low", **x_opts})
            chart.set_y_axis({"num_font": axis_font, "line": {"none": True}, "major_tick_mark": "none", "label_position": "high",
                              "major_gridlines": {"visible": True, "line": {"color": "#BFBFBF", "width": 0.25}},
                              "num_format": "#,##0.0" if side.get("decimals") == 1 else "#,##0",
                              **({"min": side["y_min"]} if side.get("y_min") is not None else {}),
                              **({"max": side["y_max"]} if side.get("y_max") is not None else {})})
            chart.set_legend({"position": "top", "font": axis_font})
            chart.set_chartarea({"border": {"none": True}})
            chart.set_size({"width": 720, "height": 400})
            sheet.insert_chart(3, 0, chart)
            sheet.activate()
    files["xlsx"] = xlsx.name
    return files
