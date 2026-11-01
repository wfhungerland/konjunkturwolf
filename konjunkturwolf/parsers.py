"""Parser für die Antwortformate der Quellen.

Alle Parser liefern einen DataFrame mit den Spalten 'date' (Periodenbeginn)
und 'value' (float), sortiert und ohne fehlende Werte.
"""

from __future__ import annotations

import csv
import io
import json
import math
import re
from typing import Any

import pandas as pd

from .periods import parse_period

MISSING_MARKERS = {"", ".", "..", "...", "-", "x", "/", "nan", "na", "n/a", "null", "none", "–"}


class ParseError(ValueError):
    """Antwort enthält keine verwertbare Einzelreihe."""


def to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return None if (isinstance(value, float) and math.isnan(value)) else float(value)
    text = str(value).strip().replace(" ", "")
    if text.lower() in MISSING_MARKERS:
        return None
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def _frame(rows: list[tuple[str, Any]]) -> pd.DataFrame:
    records = []
    for period, raw in rows:
        val = to_float(raw)
        if val is None:
            continue
        records.append((pd.Timestamp(parse_period(period)), val))
    if not records:
        raise ParseError("Antwort enthält keine Beobachtungen.")
    df = pd.DataFrame(records, columns=["date", "value"])
    if df["date"].duplicated().any():
        dups = df.loc[df["date"].duplicated(), "date"].dt.date.astype(str).head(3).tolist()
        raise ParseError(f"Mehrere Werte je Periode (z. B. {', '.join(dups)}); Schlüssel nicht eindeutig.")
    return df.sort_values("date").reset_index(drop=True)


# ---------------------------------------------------------------------------
# SDMX (EZB, Bundesbank)
# ---------------------------------------------------------------------------
def parse_sdmx_csv(text: str) -> pd.DataFrame:
    """SDMX-CSV (Spalten TIME_PERIOD und OBS_VALUE, Trennzeichen ',' oder ';')."""
    text = text.lstrip("﻿")
    if not text.strip():
        raise ParseError("Leere Antwort.")
    first = text.splitlines()[0]
    delimiter = ";" if first.count(";") > first.count(",") else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    fields = {f.strip().upper(): f for f in (reader.fieldnames or [])}
    if "TIME_PERIOD" not in fields or "OBS_VALUE" not in fields:
        raise ParseError(f"SDMX-CSV ohne TIME_PERIOD/OBS_VALUE (Spalten: {', '.join(list(fields)[:8])}).")
    tcol, vcol = fields["TIME_PERIOD"], fields["OBS_VALUE"]
    kcol = fields.get("KEY") or fields.get("SERIES_KEY")
    rows, keys = [], set()
    for row in reader:
        if kcol:
            keys.add(row.get(kcol))
        rows.append((row[tcol], row[vcol]))
    if len(keys) > 1:
        raise ParseError(f"Antwort enthält {len(keys)} Reihen; Schlüssel muss genau eine Reihe treffen.")
    return _frame(rows)


def parse_sdmx_json(payload: str | dict) -> pd.DataFrame:
    """SDMX-JSON 1.0/2.0 mit genau einer Reihe."""
    obj = json.loads(payload) if isinstance(payload, str) else payload
    root = obj.get("data", obj)
    datasets = root.get("dataSets") or []
    structure = root.get("structure") or (root.get("structures") or [{}])[0]
    if not datasets:
        raise ParseError("SDMX-JSON ohne dataSets.")
    obs_dims = structure.get("dimensions", {}).get("observation", [])
    time_dim = next((d for d in obs_dims if d.get("id") == "TIME_PERIOD"), obs_dims[0] if obs_dims else None)
    if not time_dim:
        raise ParseError("SDMX-JSON ohne Zeitdimension.")
    periods = [v["id"] for v in time_dim["values"]]
    series = datasets[0].get("series") or {}
    if len(series) != 1:
        raise ParseError(f"Antwort enthält {len(series)} Reihen; Schlüssel muss genau eine Reihe treffen.")
    observations = next(iter(series.values())).get("observations", {})
    rows = [(periods[int(idx)], vals[0] if vals else None) for idx, vals in observations.items()]
    return _frame(rows)


def parse_sdmx(text: str) -> pd.DataFrame:
    stripped = text.lstrip("﻿").lstrip()
    if stripped.startswith("{"):
        return parse_sdmx_json(stripped)
    if stripped.startswith("<"):
        msg = re.sub(r"<[^>]+>", " ", stripped[:600])
        raise ParseError(f"Unerwartete XML-Antwort: {' '.join(msg.split())[:200]}")
    return parse_sdmx_csv(text)


# ---------------------------------------------------------------------------
# Eurostat (JSON-stat 2.0)
# ---------------------------------------------------------------------------
def parse_jsonstat(payload: str | dict, filters: dict[str, Any] | None = None) -> pd.DataFrame:
    """Eurostat-JSON-stat; alle Nicht-Zeit-Dimensionen müssen auf einen Wert festgelegt sein."""
    obj = json.loads(payload) if isinstance(payload, str) else payload
    if "error" in obj:
        err = obj["error"]
        if isinstance(err, list) and err:
            err = err[0]
        label = err.get("label") if isinstance(err, dict) else err
        raise ParseError(f"Eurostat-Fehler: {label}")
    ids: list[str] = obj["id"]
    sizes: list[int] = obj["size"]
    dims = obj["dimension"]
    time_id = "time" if "time" in ids else next(
        (d for d in ids if d in (obj.get("role", {}).get("time") or [])), ids[-1]
    )
    filters = {k: str(v) for k, v in (filters or {}).items()}

    codes: dict[str, list[str]] = {}
    for d in ids:
        index = dims[d]["category"].get("index")
        if isinstance(index, dict):
            codes[d] = [c for c, _ in sorted(index.items(), key=lambda kv: kv[1])]
        elif isinstance(index, list):
            codes[d] = index
        else:
            codes[d] = list(dims[d]["category"]["label"].keys())

    ambiguous = [
        f"{d}={','.join(codes[d][:6])}"
        for d in ids
        if d != time_id and len(codes[d]) > 1 and d not in filters
    ]
    if ambiguous:
        raise ParseError("Dimensionen nicht eindeutig gefiltert: " + "; ".join(ambiguous))

    strides = []
    acc = 1
    for s in reversed(sizes):
        strides.append(acc)
        acc *= s
    strides = list(reversed(strides))

    values = obj.get("value", {})
    items = values.items() if isinstance(values, dict) else enumerate(values)
    rows = []
    for flat, val in items:
        flat = int(flat)
        keep = True
        period = None
        for d, stride, size in zip(ids, strides, sizes):
            pos = (flat // stride) % size
            code = codes[d][pos]
            if d == time_id:
                period = code
            elif d in filters and len(codes[d]) > 1 and code != filters[d]:
                keep = False
                break
        if keep and period is not None:
            rows.append((period, val))
    return _frame(rows)


# ---------------------------------------------------------------------------
# Destatis GENESIS (ffcsv = flat file CSV)
# ---------------------------------------------------------------------------
_GENESIS_COLUMNS = {
    # deutsch -> englisch
    "statistik_code": "statistics_code",
    "zeit_code": "time_code",
    "zeit": "time",
    "wert": "value",
    "wert_merkmal_code": "value_variable_code",
    "wert_einheit": "value_unit",
}
_SUBPERIOD = re.compile(r"^(MONAT|QUART|HJAHR)(\d{1,2})$")


def _genesis_norm(col: str) -> str:
    c = col.strip().lower()
    c = c.replace("merkmal_code", "variable_code").replace("auspraegung_code", "variable_attribute_code")
    c = c.replace("merkmal_label", "variable_label").replace("auspraegung_label", "variable_attribute_label")
    return _GENESIS_COLUMNS.get(c, c)


def parse_genesis_ffcsv(
    text: str,
    value_variable: str | None = None,
    filters: dict[str, str] | None = None,
) -> pd.DataFrame:
    """GENESIS-Tabelle im Format ffcsv.

    value_variable: Code des Wertmerkmals (z. B. PREIS1).
    filters: {Merkmal-Code: Ausprägungs-Code}, z. B. {"WZ08V2": "WZ08-C"}.
    """
    text = text.lstrip("﻿")
    stripped = text.lstrip()
    if stripped.startswith("{"):
        obj = json.loads(stripped)
        status = obj.get("Status") or obj.get("status") or {}
        raise ParseError(f"GENESIS-Fehler: {status.get('Content') or status.get('content') or str(obj)[:200]}")
    # Vorspann (Titelzeilen) überspringen: Kopfzeile ist die erste Zeile mit Zeit- und Wertspalte
    lines = text.splitlines()
    start = next(
        (i for i, line in enumerate(lines[:60])
         if line.count(";") >= 3 and re.search(r"(^|;)\"?(time|zeit)\"?(;|$)", line.lower())),
        None,
    )
    if start is None:
        preview = " | ".join(l.strip() for l in lines[:6])[:400]
        raise ParseError(f"GENESIS-Antwort ohne erkennbare ffcsv-Kopfzeile. Anfang: {preview}")
    df = pd.read_csv(io.StringIO("\n".join(lines[start:])), sep=";", dtype=str, keep_default_na=False)
    df.columns = [_genesis_norm(c) for c in df.columns]
    if "time" not in df.columns or "value" not in df.columns:
        raise ParseError(f"ffcsv ohne Spalten time/value (Spalten: {', '.join(df.columns[:8])}).")

    var_idx = sorted(
        {int(m.group(1)) for c in df.columns if (m := re.match(r"^(\d+)_variable_code$", c))}
    )

    for var, attr in (filters or {}).items():
        hit = None
        for i in var_idx:
            if (df[f"{i}_variable_code"] == var).any():
                hit = i
                break
        if hit is None:
            raise ParseError(f"Merkmal '{var}' nicht in Tabelle; vorhanden: {_genesis_vars(df, var_idx)}")
        col = f"{hit}_variable_attribute_code"
        if not (df[col] == attr).any():
            avail = ", ".join(sorted(df[col].unique())[:15])
            raise ParseError(f"Ausprägung '{attr}' von '{var}' fehlt; vorhanden: {avail}")
        df = df[df[col] == attr]

    if value_variable and "value_variable_code" in df.columns:
        if not (df["value_variable_code"] == value_variable).any():
            avail = ", ".join(sorted(df["value_variable_code"].unique()))
            raise ParseError(f"Wertmerkmal '{value_variable}' fehlt; vorhanden: {avail}")
        df = df[df["value_variable_code"] == value_variable]

    sub_col = None
    for i in var_idx:
        attrs = df[f"{i}_variable_attribute_code"]
        if len(attrs) and attrs.str.match(_SUBPERIOD).all():
            sub_col = f"{i}_variable_attribute_code"
            break

    rows = []
    for _, r in df.iterrows():
        year = str(r["time"]).strip()
        period = year
        if sub_col:
            kind, num = _SUBPERIOD.match(r[sub_col]).groups()
            n = int(num)
            if kind == "MONAT":
                period = f"{year}-{n:02d}"
            elif kind == "QUART":
                period = f"{year}-Q{n}"
            else:
                period = f"{year}-S{n}"
        rows.append((period, r["value"]))
    try:
        return _frame(rows)
    except ParseError as exc:
        if "Mehrere Werte" in str(exc):
            raise ParseError(f"{exc} Weitere Merkmale filtern: {_genesis_vars(df, var_idx)}") from exc
        raise


def _genesis_vars(df: pd.DataFrame, var_idx: list[int]) -> str:
    parts = []
    for i in var_idx:
        codes = df[f"{i}_variable_code"].unique()
        attrs = df[f"{i}_variable_attribute_code"].unique()
        if len(attrs) > 1 and not pd.Series(attrs).str.match(_SUBPERIOD).all():
            parts.append(f"{'/'.join(codes)}: {', '.join(sorted(attrs)[:12])}")
    if "value_variable_code" in df.columns:
        parts.append("Wertmerkmale: " + ", ".join(sorted(df["value_variable_code"].unique())))
    return "; ".join(parts) or "keine weiteren Merkmale"
