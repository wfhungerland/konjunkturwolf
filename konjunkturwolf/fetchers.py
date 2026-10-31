"""Ein Fetcher je Quelle. Jeder liefert ein FetchResult mit 'date'/'value'."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from .catalog import SeriesSpec
from .http import HttpClient
from .parsers import parse_genesis_ffcsv, parse_jsonstat, parse_sdmx

ECB_BASE = "https://data-api.ecb.europa.eu/service/data"
BUNDESBANK_BASE = "https://api.statistiken.bundesbank.de/rest/data"
EUROSTAT_BASE = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data"
GENESIS_BASE = "https://www-genesis.destatis.de/genesisWS/rest/2020"

SDMX_CSV = "application/vnd.sdmx.data+csv;version=1.0.0"


class SkipSeries(RuntimeError):
    """Reihe bewusst übersprungen (z. B. fehlende Zugangsdaten)."""


@dataclass
class FetchResult:
    data: pd.DataFrame
    api_url: str
    retrieved_at: datetime
    from_cache: bool


def sdmx_start(spec: SeriesSpec) -> str:
    """Startperiode im Format, das zur Frequenz passt (Bundesbank verlangt das)."""
    y, m, d = spec.start[:4], int(spec.start[5:7]), spec.start[8:10]
    return {
        "D": spec.start,
        "M": f"{y}-{m:02d}",
        "Q": f"{y}-Q{(m - 1) // 3 + 1}",
        "S": f"{y}-S{1 if m <= 6 else 2}",
        "A": y,
    }[spec.frequency]


def _since(df: pd.DataFrame, spec: SeriesSpec) -> pd.DataFrame:
    return df[df["date"] >= pd.Timestamp(spec.start)].reset_index(drop=True)


def fetch_ecb(spec: SeriesSpec, client: HttpClient) -> FetchResult:
    flow, _, key = spec.key.partition("/")
    resp = client.get(
        f"{ECB_BASE}/{flow}/{key}",
        params={"startPeriod": sdmx_start(spec), "format": "csvdata", "detail": "dataonly"},
    )
    return FetchResult(_since(parse_sdmx(resp.text), spec), resp.url, resp.retrieved_at, resp.from_cache)


def fetch_bundesbank(spec: SeriesSpec, client: HttpClient) -> FetchResult:
    flow, _, key = spec.key.partition("/")
    resp = client.get(
        f"{BUNDESBANK_BASE}/{flow}/{key}",
        params={"startPeriod": sdmx_start(spec), "detail": "dataonly"},
        accept=SDMX_CSV,
    )
    return FetchResult(_since(parse_sdmx(resp.text), spec), resp.url, resp.retrieved_at, resp.from_cache)


def fetch_eurostat(spec: SeriesSpec, client: HttpClient) -> FetchResult:
    params = {"format": "JSON", "lang": "en"}
    params.update({k: str(v) for k, v in spec.params.items()})
    resp = client.get(f"{EUROSTAT_BASE}/{spec.key}", params=params)
    df = parse_jsonstat(resp.text, filters=spec.params)
    return FetchResult(_since(df, spec), resp.url, resp.retrieved_at, resp.from_cache)


def genesis_credentials() -> tuple[str, str] | None:
    user = os.environ.get("GENESIS_USER", "").strip()
    if not user:
        return None
    return user, os.environ.get("GENESIS_PASSWORD", "").strip()


def fetch_genesis(spec: SeriesSpec, client: HttpClient) -> FetchResult:
    creds = genesis_credentials()
    if creds is None:
        raise SkipSeries("GENESIS-Zugangsdaten fehlen (GENESIS_USER/GENESIS_PASSWORD nicht gesetzt).")
    user, password = creds
    data = {
        "name": spec.key,
        "area": "all",
        "compress": "false",
        "format": "ffcsv",
        "language": "en",
        "startyear": str(spec.start_year),
    }
    data.update({k: str(v) for k, v in (spec.params.get("query") or {}).items()})
    resp = client.post(
        f"{GENESIS_BASE}/data/tablefile",
        data=data,
        headers={"username": user, "password": password, "Content-Type": "application/x-www-form-urlencoded"},
    )
    df = parse_genesis_ffcsv(
        resp.text,
        value_variable=spec.params.get("value_variable"),
        filters=spec.params.get("filters"),
    )
    api_url = f"{GENESIS_BASE}/data/tablefile?name={spec.key}&format=ffcsv"
    return FetchResult(_since(df, spec), api_url, resp.retrieved_at, resp.from_cache)


FETCHERS = {
    "ecb": fetch_ecb,
    "bundesbank": fetch_bundesbank,
    "eurostat": fetch_eurostat,
    "genesis": fetch_genesis,
}


def api_url_hint(spec: SeriesSpec) -> str:
    """Abruf-URL ohne Netzzugriff (für Excel, auch wenn der Abruf scheiterte)."""
    from urllib.parse import urlencode

    if spec.source == "ecb":
        flow, _, key = spec.key.partition("/")
        return f"{ECB_BASE}/{flow}/{key}?startPeriod={sdmx_start(spec)}&format=csvdata"
    if spec.source == "bundesbank":
        flow, _, key = spec.key.partition("/")
        return f"{BUNDESBANK_BASE}/{flow}/{key}?startPeriod={sdmx_start(spec)}"
    if spec.source == "eurostat":
        params = {"format": "JSON", "lang": "en", **{k: str(v) for k, v in spec.params.items()}}
        return f"{EUROSTAT_BASE}/{spec.key}?{urlencode(params)}"
    if spec.source == "genesis":
        return f"{GENESIS_BASE}/data/tablefile?name={spec.key}&format=ffcsv"
    return ""


def derive_series(spec: SeriesSpec, base: pd.DataFrame) -> pd.DataFrame:
    """Berechnet abgeleitete Reihen aus einer Basisreihe (Spalten date/value)."""
    op = spec.derive.get("op")
    if op == "yoy_pct":
        prev = base.assign(date=base["date"] + pd.DateOffset(years=1)).rename(columns={"value": "prev"})
        merged = base.merge(prev, on="date", how="inner")
        merged["value"] = (merged["value"] / merged["prev"] - 1.0) * 100.0
        return merged[["date", "value"]].dropna().reset_index(drop=True)
    raise ValueError(f"Unbekannte Ableitung: {op}")
