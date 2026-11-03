"""Ein Fetcher je Quelle. Jeder liefert ein FetchResult mit 'date'/'value'."""

from __future__ import annotations

import io
import os
from dataclasses import dataclass
from datetime import datetime, timezone

import pandas as pd

from .catalog import SeriesSpec
from .http import FetchError, HttpClient
from .parsers import ParseError, parse_genesis_ffcsv, parse_jsonstat, parse_sdmx

ECB_BASE = "https://data-api.ecb.europa.eu/service/data"
BUNDESBANK_BASE = "https://api.statistiken.bundesbank.de/rest/data"
EUROSTAT_BASE = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data"
GENESIS_BASE = "https://genesis.destatis.de/genesisWS/rest/2020"

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


def monthly_mean(df: pd.DataFrame) -> pd.DataFrame:
    """Tageswerte zu Monatsmitteln (Datum = Monatserster)."""
    out = df.assign(date=df["date"].dt.to_period("M").dt.to_timestamp()).groupby("date", as_index=False)["value"].mean()
    return out


def fetch_ecb(spec: SeriesSpec, client: HttpClient) -> FetchResult:
    flow, _, key = spec.key.partition("/")
    daily = spec.params.get("aggregate") == "monthly_mean"
    resp = client.get(
        f"{ECB_BASE}/{flow}/{key}",
        params={"startPeriod": spec.start if daily else sdmx_start(spec), "format": "csvdata", "detail": "dataonly"},
    )
    df = parse_sdmx(resp.text)
    if daily:
        df = monthly_mean(df)
    return FetchResult(_since(df, spec), resp.url, resp.retrieved_at, resp.from_cache)


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


_GENESIS_AUTH_FAILED: dict[int, str] = {}


def genesis_text(raw: bytes) -> str:
    """GENESIS liefert Tabellen teils als ZIP-Archiv; dann die erste CSV darin lesen."""
    if raw[:2] == b"PK":
        import zipfile

        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            names = [n for n in zf.namelist() if n.lower().endswith((".csv", ".txt"))] or zf.namelist()
            if not names:
                raise ParseError("GENESIS-ZIP ohne Datei.")
            raw = zf.read(names[0])
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def fetch_genesis(spec: SeriesSpec, client: HttpClient) -> FetchResult:
    creds = genesis_credentials()
    if creds is None:
        raise SkipSeries("GENESIS-Zugangsdaten fehlen (GENESIS_USER/GENESIS_PASSWORD nicht gesetzt).")
    if id(client) in _GENESIS_AUTH_FAILED:
        # nach abgelehntem Login keine weiteren Versuche (Schutz vor Kontosperre)
        raise SkipSeries(_GENESIS_AUTH_FAILED[id(client)])
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
    try:
        resp = client.post(
            f"{GENESIS_BASE}/data/tablefile",
            data=data,
            headers={"username": user, "password": password, "Content-Type": "application/x-www-form-urlencoded"},
        )
    except FetchError as exc:
        text = str(exc).lower()
        if "password" in text or "passwort" in text or "anmeld" in text or "token" in text:
            msg = "GENESIS lehnt die Zugangsdaten ab (Secrets GENESIS_USER/GENESIS_PASSWORD prüfen)."
            _GENESIS_AUTH_FAILED[id(client)] = msg
            raise FetchError(msg) from exc
        raise
    df = parse_genesis_ffcsv(
        genesis_text(resp.raw or resp.text.encode("utf-8")),
        value_variable=spec.params.get("value_variable"),
        filters=spec.params.get("filters"),
        value_unit=spec.params.get("value_unit"),
    )
    api_url = f"{GENESIS_BASE}/data/tablefile?name={spec.key}&format=ffcsv"
    return FetchResult(_since(df, spec), api_url, resp.retrieved_at, resp.from_cache)


# ---------------------------------------------------------------------------
# Historische Paneldatensätze (Jahresdaten): JST Macrohistory, Global Macro Database
# ---------------------------------------------------------------------------
JST_URL = "https://www.macrohistory.net/app/download/9834512569/JSTdatasetR6.xlsx"
_PANELS: dict[tuple[int, str], tuple[pd.DataFrame, datetime, bool, str]] = {}


def panel_series(panel: pd.DataFrame, spec: SeriesSpec, country_col: str) -> pd.DataFrame:
    """Wählt Land und Variable aus einem Länder-Jahres-Panel und wendet einfache Umformungen an.

    params: country (ISO3), optional add (Variable addieren), divide_by (Variable teilen), scale (Faktor),
    transform: pct_change (Veränderung gegenüber Vorjahr in %), max_year.
    """
    p = spec.params
    country = str(p.get("country", ""))
    var = spec.key
    rows = panel[panel[country_col] == country]
    if rows.empty:
        raise ParseError(f"Land {country} nicht im Datensatz.")
    if var not in rows.columns:
        raise ParseError(f"Variable {var} nicht im Datensatz.")
    df = rows[["year", var]].rename(columns={var: "value"}).copy()
    if p.get("add"):
        df["value"] = pd.to_numeric(df["value"], errors="coerce") + pd.to_numeric(rows[p["add"]], errors="coerce").values
    if p.get("divide_by"):
        df["value"] = df["value"] / rows[p["divide_by"]].values
    df["value"] = pd.to_numeric(df["value"], errors="coerce") * float(p.get("scale", 1))
    df = df.dropna().sort_values("year")
    df["year"] = df["year"].astype(int)
    if p.get("transform") == "pct_change":
        prev = df.set_index("year")["value"]
        df["value"] = [(v / prev.get(y - 1) - 1) * 100 if prev.get(y - 1) else float("nan")
                       for y, v in zip(df["year"], df["value"])]
        df = df.dropna()
    max_year = int(p.get("max_year", pd.Timestamp.now().year - 1))
    df = df[df["year"] <= max_year]
    df["date"] = pd.to_datetime(df["year"].astype(str) + "-01-01")
    return df[["date", "value"]].reset_index(drop=True)


def fetch_jst(spec: SeriesSpec, client: HttpClient) -> FetchResult:
    from .http import get_bytes

    key = (id(client), "jst")
    if key not in _PANELS:
        raw, when, cached = get_bytes(client, JST_URL)
        _PANELS[key] = (pd.read_excel(io.BytesIO(raw)), when, cached, JST_URL)
    panel, when, cached, url = _PANELS[key]
    return FetchResult(_since(panel_series(panel, spec, "iso"), spec), url, when, cached)


def fetch_gmd(spec: SeriesSpec, client: HttpClient) -> FetchResult:
    key = (id(client), "gmd")
    if key not in _PANELS:
        if client.offline:
            raise FetchError("Offline-Modus: Global Macro Database nicht im Cache.")
        try:
            import contextlib

            from global_macro_data import gmd
        except ImportError as exc:
            raise FetchError("Paket global_macro_data fehlt (pip install global_macro_data).") from exc
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                panel = gmd(country=sorted({s for s in GMD_COUNTRIES}))
        except Exception as exc:  # Paketfehler sauber melden
            raise FetchError(f"Global Macro Database: {exc.__class__.__name__}: {exc}") from exc
        _PANELS[key] = (panel, datetime.now(timezone.utc).replace(microsecond=0), False,
                        "https://www.globalmacrodata.com")
    panel, when, cached, url = _PANELS[key]
    return FetchResult(_since(panel_series(panel, spec, "ISO3"), spec), url, when, cached)


GMD_COUNTRIES: set[str] = set()

NBER_BASE = "https://data.nber.org/databases/macrohistory/rectdata"


def parse_nber(text: str) -> pd.DataFrame:
    """NBER Macrohistory, rectdata: 'Jahr Wert' (jährlich) oder 'Jahr Monat Wert'; '.' = fehlt."""
    rows = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 2 or not parts[0].isdigit():
            continue
        year = int(parts[0])
        if len(parts) >= 3 and parts[1].isdigit() and 1 <= int(parts[1]) <= 12:
            month, raw = int(parts[1]), parts[2]
        else:
            month, raw = 1, parts[1]
        try:
            rows.append((pd.Timestamp(year=year, month=month, day=1), float(raw)))
        except ValueError:
            continue  # '.' = fehlender Wert
    if not rows:
        raise ParseError("NBER-Datei ohne Werte.")
    return pd.DataFrame(rows, columns=["date", "value"])


def fetch_nber(spec: SeriesSpec, client: HttpClient) -> FetchResult:
    sid = spec.key
    resp = client.get(f"{NBER_BASE}/{sid[1:3]}/{sid}.dat")
    return FetchResult(_since(parse_nber(resp.text), spec), resp.url, resp.retrieved_at, resp.from_cache)


STATIC_URL = "https://github.com/wfhungerland/konjunkturwolf/blob/main/data/static"


def static_dir():
    """Ordner der statischen Reihen: KONJUNKTURWOLF_STATIC_DIR, sonst ./data/static, sonst der Ordner im Repo.

    So können andere Projekte (z. B. konjunkturmonitor) die Pipeline mit eigenen statischen Dateien nutzen.
    """
    import os
    from pathlib import Path

    env = os.environ.get("KONJUNKTURWOLF_STATIC_DIR")
    if env:
        return Path(env)
    here = Path.cwd() / "data" / "static"
    return here if here.exists() else Path(__file__).resolve().parent.parent / "data" / "static"


def fetch_static(spec: SeriesSpec, client: HttpClient) -> FetchResult:
    """Fest im Repo abgelegte, einmalig aufbereitete Reihe (data/static/<key>.csv mit date,value)."""
    from pathlib import Path

    path = static_dir() / f"{spec.key}.csv"
    if not path.exists():
        raise FetchError(f"Statische Datei fehlt: data/static/{spec.key}.csv")
    df = pd.read_csv(path, parse_dates=["date"])[["date", "value"]]
    when = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).replace(microsecond=0)
    return FetchResult(_since(df, spec), f"{STATIC_URL}/{spec.key}.csv", when, False)


FETCHERS = {
    "ecb": fetch_ecb,
    "bundesbank": fetch_bundesbank,
    "eurostat": fetch_eurostat,
    "genesis": fetch_genesis,
    "jst": fetch_jst,
    "gmd": fetch_gmd,
    "nber": fetch_nber,
    "static": fetch_static,
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
    if spec.source == "jst":
        return JST_URL
    if spec.source == "gmd":
        return "https://www.globalmacrodata.com"
    if spec.source == "static":
        return f"{STATIC_URL}/{spec.key}.csv"
    if spec.source == "nber":
        return f"{NBER_BASE}/{spec.key[1:3]}/{spec.key}.dat"
    return ""


def _to_level_unit(x: pd.Series, level: pd.Series) -> pd.Series:
    """Personen auf die Einheit der Arbeitslosenzahl bringen (Bundesbank: Arbeitslose in Tausend, Stellen teils in Personen)."""
    return x / 1000.0 if x.median() > 20 * level.median() else x


def sahm_frame(rate: pd.DataFrame, extra: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Michaillat-Saez-Indikator für Deutschland, Spalten u, v, min (Prozentpunkte).

    rate = registrierte Arbeitslosenquote (%), extra: level = Arbeitslose, vac = gemeldete Stellen,
    ka = Kurzarbeit in Vollzeitäquivalenten (optional). Erwerbspersonen L = Arbeitslose / Quote.
    u: 3-Monats-Mittel der Quote inkl. Kurzarbeit minus Tief der letzten 12 Monate (einschließlich heute).
    v: Hoch der letzten 12 Monate minus 3-Monats-Mittel der Vakanzquote V/L.
    """
    df = rate.rename(columns={"value": "rate"}).set_index("date")
    for k in ("level", "vac", "ka", "ka_ratio"):
        if k in extra and extra[k] is not None:
            df = df.join(extra[k].set_index("date")["value"].rename(k), how="left")
    df = df.sort_index()
    L = df["level"] / (df["rate"] / 100.0)
    if "ka" in df:
        # Kurzarbeit: vor Datenbeginn null, fehlende jüngste Monate (Wartezeit der BA) mit dem letzten Wert fortschreiben
        ka = _to_level_unit(df["ka"], df["level"])
        first = ka.first_valid_index()
        ka = ka.ffill()
        if first is not None:
            ka[ka.index < first] = 0.0
        ka = ka.fillna(0.0)
        if "ka_ratio" in df:
            # Vollzeitäquivalente: Anteil des Arbeitsausfalls je Kurzarbeiter (BA), außerhalb der BA-Daten fortgeschrieben
            ka = ka * df["ka_ratio"].ffill().bfill()
    else:
        ka = 0.0
    u = (df["level"] + ka) / L * 100.0
    v = _to_level_unit(df["vac"], df["level"]) / L * 100.0
    u3, v3 = u.rolling(3).mean(), v.rolling(3).mean()
    out = pd.DataFrame({"u": u3 - u3.rolling(13, min_periods=13).min(),
                        "v": v3.rolling(13, min_periods=13).max() - v3})
    out["min"] = out[["u", "v"]].min(axis=1)
    return out.dropna().reset_index().rename(columns={"index": "date"})


def derive_series(spec: SeriesSpec, base: pd.DataFrame, other: pd.DataFrame | None = None,
                  extra: dict[str, pd.DataFrame] | None = None) -> pd.DataFrame:
    """Berechnet abgeleitete Reihen aus einer Basisreihe (Spalten date/value)."""
    op = spec.derive.get("op")
    if op == "sahm":
        f = sahm_frame(base, extra or {})
        return f[["date", spec.derive.get("part", "min")]].rename(columns={spec.derive.get("part", "min"): "value"}).reset_index(drop=True)
    if op == "yoy_pct":
        prev = base.assign(date=base["date"] + pd.DateOffset(years=1)).rename(columns={"value": "prev"})
        merged = base.merge(prev, on="date", how="inner")
        merged["value"] = (merged["value"] / merged["prev"] - 1.0) * 100.0
        return merged[["date", "value"]].dropna().reset_index(drop=True)
    if op == "acr":
        # Handelsgewinne nach Arkolakis, Costinot, Rodríguez-Clare (2012): 1 - lambda^(1/theta),
        # lambda = Inlandsanteil der Ausgaben; base = Exporte, other = Importe, beide in % des BIP
        if other is None:
            raise ValueError("Ableitung acr braucht Exporte (from) und Importe (plus).")
        theta = float(spec.derive.get("theta", 5))
        merged = base.merge(other.rename(columns={"value": "m"}), on="date", how="inner")
        lam = (100 - merged["value"]) / (100 - merged["value"] + merged["m"])
        merged["value"] = (1 - lam ** (1 / theta)) * 100
        return merged[["date", "value"]].dropna().reset_index(drop=True)
    if op in ("diff", "sum"):
        if other is None:
            raise ValueError(f"Ableitung {op} braucht eine zweite Reihe (minus bzw. plus).")
        merged = base.merge(other.rename(columns={"value": "other"}), on="date", how="inner")
        merged["value"] = merged["value"] - merged["other"] if op == "diff" else merged["value"] + merged["other"]
        return merged[["date", "value"]].dropna().reset_index(drop=True)
    raise ValueError(f"Unbekannte Ableitung: {op}")
