"""Ablauf: Katalog laden, Reihen abrufen, tidy speichern, Ausgaben erzeugen."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .catalog import Catalog, SeriesSpec
from .fetchers import FETCHERS, SkipSeries, api_url_hint, derive_series
from .http import HttpClient
from .periods import period_label

log = logging.getLogger(__name__)

TIDY_COLUMNS = ["series_id", "date", "value", "unit", "source", "retrieved_at"]

STATUS_LABELS = {
    "ok": "abgerufen",
    "cache": "aus Cache (< 20 h alt)",
    "stale": "Abruf fehlgeschlagen, letzter Stand beibehalten",
    "skipped": "übersprungen",
    "failed": "fehlgeschlagen, keine Daten",
}


@dataclass
class SeriesStatus:
    series_id: str
    status: str
    n_obs: int = 0
    first: str = ""
    last: str = ""
    last_value: float | None = None
    retrieved_at: str = ""
    api_url: str = ""
    message: str = ""


@dataclass
class RunResult:
    started_at: str
    finished_at: str = ""
    statuses: list[SeriesStatus] = field(default_factory=list)
    observations: pd.DataFrame = field(default_factory=lambda: pd.DataFrame(columns=TIDY_COLUMNS))

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for s in self.statuses:
            out[s.status] = out.get(s.status, 0) + 1
        return out

    def status_map(self) -> dict[str, SeriesStatus]:
        return {s.series_id: s for s in self.statuses}


@dataclass
class Paths:
    root: Path

    @property
    def catalog(self) -> Path:
        return self.root / "series.yaml"

    @property
    def cache(self) -> Path:
        return self.root / "data" / "cache"

    @property
    def processed(self) -> Path:
        return self.root / "data" / "processed"

    @property
    def observations(self) -> Path:
        return self.processed / "observations.csv"

    @property
    def status(self) -> Path:
        return self.processed / "run_status.json"

    @property
    def xlsx(self) -> Path:
        return self.root / "output" / "konjunkturwolf.xlsx"

    @property
    def site(self) -> Path:
        return self.root / "site"


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_previous(paths: Paths) -> pd.DataFrame:
    if not paths.observations.exists():
        return pd.DataFrame(columns=TIDY_COLUMNS)
    df = pd.read_csv(paths.observations, dtype={"series_id": str, "unit": str, "source": str, "retrieved_at": str})
    df["date"] = pd.to_datetime(df["date"])
    return df


def _tidy(spec: SeriesSpec, data: pd.DataFrame, retrieved_at: str) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "series_id": spec.id,
            "date": data["date"].values,
            "value": data["value"].values,
            "unit": spec.unit,
            "source": spec.source_label,
            "retrieved_at": retrieved_at,
        }
    )


def _fill_status(st: SeriesStatus, spec: SeriesSpec, df: pd.DataFrame) -> None:
    st.n_obs = len(df)
    if len(df):
        st.first = period_label(df["date"].min().date(), spec.frequency)
        st.last = period_label(df["date"].max().date(), spec.frequency)
        st.last_value = float(df.sort_values("date")["value"].iloc[-1])


def run(catalog: Catalog, paths: Paths, client: HttpClient, only: list[str] | None = None) -> RunResult:
    result = RunResult(started_at=_iso(datetime.now(timezone.utc)))
    previous = load_previous(paths)
    frames: list[pd.DataFrame] = []
    fetched: dict[str, pd.DataFrame] = {}

    specs = catalog.series
    if only:
        wanted = set(only)
        specs = [s for s in specs if s.id in wanted]

    ordered = [s for s in specs if s.source != "derived"] + [s for s in specs if s.source == "derived"]
    for spec in ordered:
        st = SeriesStatus(series_id=spec.id, status="failed", api_url=api_url_hint(spec))
        try:
            if spec.source == "derived":
                base_id = spec.derive["from"]
                base = fetched.get(base_id)
                if base is None:
                    prev_base = previous[previous["series_id"] == base_id]
                    if prev_base.empty:
                        raise SkipSeries(f"Basisreihe {base_id} nicht verfügbar.")
                    base = prev_base[["date", "value"]]
                data = derive_series(spec, base)
                retrieved = _iso(datetime.now(timezone.utc))
                st.status = "ok"
                st.message = f"berechnet aus {base_id}"
            else:
                res = FETCHERS[spec.source](spec, client)
                data = res.data
                retrieved = _iso(res.retrieved_at)
                st.api_url = res.api_url
                st.status = "cache" if res.from_cache else "ok"
            if data.empty:
                raise ValueError("Keine Beobachtungen ab Startdatum.")
            fetched[spec.id] = data
            st.retrieved_at = retrieved
            frames.append(_tidy(spec, data, retrieved))
            _fill_status(st, spec, data)
            log.info("%-28s %-7s %5d Werte  %s bis %s", spec.id, st.status, st.n_obs, st.first, st.last)
        except Exception as exc:  # eine kaputte Reihe bricht den Lauf nicht ab
            skipped = isinstance(exc, SkipSeries)
            st.message = str(exc)[:500]
            prev = previous[previous["series_id"] == spec.id]
            if not prev.empty:
                st.status = "stale"
                st.retrieved_at = str(prev["retrieved_at"].iloc[0])
                frames.append(prev[TIDY_COLUMNS])
                _fill_status(st, spec, prev)
            else:
                st.status = "skipped" if skipped else "failed"
            level = logging.INFO if skipped else logging.WARNING
            log.log(level, "%-28s %-7s %s", spec.id, st.status, st.message)
        result.statuses.append(st)

    # Reihen außerhalb eines Teil-Laufs (--only) unverändert übernehmen
    if only:
        done = {s.series_id for s in result.statuses}
        keep = previous[~previous["series_id"].isin(done) & previous["series_id"].isin(catalog.by_id())]
        if not keep.empty:
            frames.append(keep[TIDY_COLUMNS])

    obs = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=TIDY_COLUMNS)
    order = {s.id: i for i, s in enumerate(catalog.series)}
    if not obs.empty:
        obs["date"] = pd.to_datetime(obs["date"])
        obs = obs.sort_values(["series_id", "date"], key=lambda c: c.map(order) if c.name == "series_id" else c)
    result.observations = obs.reset_index(drop=True)
    result.finished_at = _iso(datetime.now(timezone.utc))
    if only:
        old = load_status(paths)
        if old:
            merged = {s.series_id: s for s in old.statuses if s.series_id in order}
            merged.update(result.status_map())
            result.statuses = sorted(merged.values(), key=lambda s: order.get(s.series_id, 1e9))
    return result


def save(result: RunResult, paths: Paths) -> None:
    paths.processed.mkdir(parents=True, exist_ok=True)
    out = result.observations.copy()
    out["date"] = pd.to_datetime(out["date"]).dt.strftime("%Y-%m-%d")
    out.to_csv(paths.observations, index=False, float_format="%.6g", lineterminator="\n")
    payload = {
        "started_at": result.started_at,
        "finished_at": result.finished_at,
        "counts": result.counts(),
        "series": [asdict(s) for s in result.statuses],
    }
    paths.status.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def load_status(paths: Paths) -> RunResult | None:
    if not paths.status.exists():
        return None
    payload = json.loads(paths.status.read_text(encoding="utf-8"))
    res = RunResult(started_at=payload.get("started_at", ""), finished_at=payload.get("finished_at", ""))
    res.statuses = [SeriesStatus(**s) for s in payload.get("series", [])]
    res.observations = load_previous(paths)
    return res
