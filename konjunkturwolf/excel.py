"""Excel-Ausgabe: auditierbares Workbook mit Info, Quellen, Daten und Themenblättern."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import xlsxwriter

from .catalog import Catalog
from .pipeline import STATUS_LABELS, RunResult

FREQ_LABELS = {"D": "täglich", "M": "monatlich", "Q": "quartalsweise", "S": "halbjährlich", "A": "jährlich"}

HINTS = [
    "Datumskonvention: Jede Periode steht für ihren ersten Tag (Q2 2024 = 2024-04-01, 2. Halbjahr = 07-01).",
    "Einheiten stehen je Reihe im Blatt Quellen, im Blatt Daten und im Kopf jedes Themenblatts.",
    "Abrufzeiten in UTC. Status 'stale': Abruf gescheitert, Werte des letzten erfolgreichen Laufs.",
    "Destatis-Reihen (GENESIS) benötigen die Secrets GENESIS_USER und GENESIS_PASSWORD; ohne sie fehlen sie.",
    "Abgeleitete Reihen sind eigene Berechnungen aus der genannten Basisreihe.",
    "Werte unverändert aus der Quelle; keine eigenen Saisonbereinigungen.",
]


def write_workbook(catalog: Catalog, result: RunResult, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = xlsxwriter.Workbook(str(path), {"strings_to_urls": False, "nan_inf_to_errors": True})
    fmt = _formats(wb)
    statuses = result.status_map()
    obs = result.observations.copy()
    if not obs.empty:
        obs["date"] = pd.to_datetime(obs["date"])

    _info_sheet(wb, fmt, catalog, result)
    _sources_sheet(wb, fmt, catalog, statuses)
    _data_sheet(wb, fmt, obs)
    for block in catalog.blocks:
        _block_sheet(wb, fmt, catalog, block, obs)
    wb.close()
    return path


def _formats(wb: xlsxwriter.Workbook) -> dict:
    return {
        "title": wb.add_format({"bold": True, "font_size": 14}),
        "bold": wb.add_format({"bold": True}),
        "head": wb.add_format({"bold": True, "bg_color": "#DDE4EE", "border": 1, "text_wrap": True, "valign": "top"}),
        "meta": wb.add_format({"italic": True, "font_color": "#555555", "text_wrap": True, "valign": "top"}),
        "date": wb.add_format({"num_format": "yyyy-mm-dd"}),
        "num": wb.add_format({"num_format": "#,##0.0###"}),
        "url": wb.add_format({"font_color": "#1F5FBF", "underline": 1}),
        "wrap": wb.add_format({"text_wrap": True, "valign": "top"}),
        "warn": wb.add_format({"font_color": "#A33A00"}),
    }


def _info_sheet(wb, fmt, catalog: Catalog, result: RunResult) -> None:
    ws = wb.add_worksheet("Info")
    ws.set_column(0, 0, 30)
    ws.set_column(1, 1, 14)
    ws.set_column(2, 4, 12)
    ws.set_column(5, 5, 90)
    ws.write(0, 0, "konjunkturwolf: offizielle Wirtschaftsdaten", fmt["title"])
    counts = result.counts()
    rows = [
        ("Stand (Laufende, UTC)", result.finished_at),
        ("Laufbeginn (UTC)", result.started_at),
        ("Reihen im Katalog", len(catalog.series)),
        ("davon mit Daten", sum(v for k, v in counts.items() if k in ("ok", "cache", "stale"))),
        ("davon ohne Daten", counts.get("failed", 0) + counts.get("skipped", 0)),
        ("Status-Zählung", ", ".join(f"{k}: {v}" for k, v in sorted(counts.items()))),
        ("Repository", "https://github.com/wfhungerland/konjunkturwolf"),
    ]
    r = 2
    for label, value in rows:
        ws.write(r, 0, label, fmt["bold"])
        if isinstance(value, str) and value.startswith("https://"):
            ws.write_url(r, 1, value, fmt["url"], string=value)
        else:
            ws.write(r, 1, value)
        r += 1
    r += 1
    ws.write(r, 0, "Hinweise", fmt["bold"])
    r += 1
    for hint in HINTS:
        ws.write(r, 0, "•")
        ws.write(r, 1, hint)
        r += 1
    r += 1
    ws.write(r, 0, "Lauf-Log", fmt["bold"])
    r += 1
    headers = ["Reihen-ID", "Status", "Werte", "erste Periode", "letzte Periode", "Meldung"]
    for c, h in enumerate(headers):
        ws.write(r, c, h, fmt["head"])
    first_log_row = r
    r += 1
    for st in result.statuses:
        ws.write(r, 0, st.series_id)
        ws.write(r, 1, st.status, fmt["warn"] if st.status in ("failed", "stale", "skipped") else None)
        ws.write_number(r, 2, st.n_obs)
        ws.write(r, 3, st.first)
        ws.write(r, 4, st.last)
        ws.write(r, 5, st.message or STATUS_LABELS.get(st.status, ""))
        r += 1
    ws.autofilter(first_log_row, 0, max(first_log_row, r - 1), len(headers) - 1)


def _sources_sheet(wb, fmt, catalog: Catalog, statuses) -> None:
    ws = wb.add_worksheet("Quellen")
    headers = [
        ("Reihen-ID", 24), ("Titel", 48), ("Themenblock", 18), ("Quelle", 22), ("API-Schlüssel", 36),
        ("Einheit", 20), ("Frequenz", 13), ("Bereinigung", 30), ("Direktlink", 40), ("API-Abruf", 40),
        ("Abrufzeit (UTC)", 21), ("Status", 9), ("erste Periode", 12), ("letzte Periode", 12),
        ("letzter Wert", 12), ("Hinweis", 60),
    ]
    for c, (h, w) in enumerate(headers):
        ws.write(0, c, h, fmt["head"])
        ws.set_column(c, c, w)
    ws.freeze_panes(1, 1)
    for r, spec in enumerate(catalog.series, start=1):
        st = statuses.get(spec.id)
        key = spec.key
        if spec.params and spec.source in ("eurostat", "genesis"):
            key += " | " + ", ".join(f"{k}={v}" for k, v in spec.params.items())
        if spec.source == "derived":
            key = f"{spec.derive.get('op')}({spec.derive.get('from')})"
        ws.write(r, 0, spec.id)
        ws.write(r, 1, spec.title)
        ws.write(r, 2, catalog.block(spec.block).title)
        ws.write(r, 3, spec.source_label)
        ws.write(r, 4, key)
        ws.write(r, 5, spec.unit)
        ws.write(r, 6, FREQ_LABELS.get(spec.frequency, spec.frequency))
        ws.write(r, 7, spec.adjustment)
        if spec.web_link:
            ws.write_url(r, 8, spec.web_link, fmt["url"], string=spec.web_link)
        api = st.api_url if st else ""
        if api:
            ws.write_url(r, 9, api[:2000], fmt["url"], string=api[:255])
        if st:
            ws.write(r, 10, st.retrieved_at)
            ws.write(r, 11, st.status, fmt["warn"] if st.status in ("failed", "stale", "skipped") else None)
            ws.write(r, 12, st.first)
            ws.write(r, 13, st.last)
            if st.last_value is not None:
                ws.write_number(r, 14, st.last_value, fmt["num"])
        ws.write(r, 15, spec.note)
    ws.autofilter(0, 0, len(catalog.series), len(headers) - 1)


def _data_sheet(wb, fmt, obs: pd.DataFrame) -> None:
    ws = wb.add_worksheet("Daten")
    headers = ["series_id", "date", "value", "unit", "source", "retrieved_at"]
    widths = [26, 12, 14, 22, 24, 21]
    for c, (h, w) in enumerate(zip(headers, widths)):
        ws.write(0, c, h, fmt["head"])
        ws.set_column(c, c, w)
    ws.freeze_panes(1, 0)
    for r, row in enumerate(obs.itertuples(index=False), start=1):
        ws.write_string(r, 0, row.series_id)
        ws.write_datetime(r, 1, row.date.to_pydatetime(), fmt["date"])
        ws.write_number(r, 2, float(row.value))
        ws.write_string(r, 3, str(row.unit))
        ws.write_string(r, 4, str(row.source))
        ws.write_string(r, 5, str(row.retrieved_at))
    ws.autofilter(0, 0, max(len(obs), 1), len(headers) - 1)


def _block_sheet(wb, fmt, catalog: Catalog, block, obs: pd.DataFrame) -> None:
    ws = wb.add_worksheet(block.sheet)
    specs = catalog.series_in_block(block.id)
    ids = [s.id for s in specs]
    sub = obs[obs["series_id"].isin(ids)] if not obs.empty else obs
    labels = ["Reihen-ID", "Titel", "Einheit", "Frequenz", "Quelle", "Bereinigung"]
    for r, label in enumerate(labels):
        ws.write(r, 0, label, fmt["head"])
    ws.set_column(0, 0, 13)
    ws.set_column(1, len(specs), 18)
    ws.set_row(1, 60)
    ws.set_row(5, 30)
    for c, s in enumerate(specs, start=1):
        ws.write(0, c, s.id, fmt["head"])
        ws.write(1, c, s.title, fmt["meta"])
        ws.write(2, c, s.unit, fmt["meta"])
        ws.write(3, c, FREQ_LABELS.get(s.frequency, s.frequency), fmt["meta"])
        if s.web_link:
            ws.write_url(4, c, s.web_link, fmt["url"], string=s.source_label)
        else:
            ws.write(4, c, s.source_label, fmt["meta"])
        ws.write(5, c, s.adjustment, fmt["meta"])
    header_rows = len(labels)
    ws.write(header_rows, 0, "Datum", fmt["head"])
    for c, s in enumerate(specs, start=1):
        ws.write(header_rows, c, s.display_label, fmt["head"])
    ws.freeze_panes(header_rows + 1, 1)
    if sub.empty:
        ws.write(header_rows + 1, 0, "Keine Daten vorhanden (siehe Blatt Info, Lauf-Log).")
        return
    wide = sub.pivot_table(index="date", columns="series_id", values="value", aggfunc="first").sort_index()
    for r, (date, row) in enumerate(wide.iterrows(), start=header_rows + 1):
        ws.write_datetime(r, 0, date.to_pydatetime(), fmt["date"])
        for c, sid in enumerate(ids, start=1):
            if sid in row.index:
                v = row[sid]
                if pd.notna(v):
                    ws.write_number(r, c, float(v))
