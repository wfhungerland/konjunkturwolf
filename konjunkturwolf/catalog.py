"""Reihen-Katalog: Laden, Expandieren und Validieren von series.yaml."""

from __future__ import annotations

import itertools
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

SOURCES = {"ecb", "bundesbank", "eurostat", "genesis", "jst", "gmd", "derived"}
FREQUENCIES = {"D", "M", "Q", "S", "A"}
STYLES = {"line", "step", "bar"}
DERIVE_OPS = {"yoy_pct"}
REQUIRED_FIELDS = ("id", "source", "title", "unit", "frequency", "adjustment", "block")
ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
PLACEHOLDER_PATTERN = re.compile(r"\{[a-z_]+\}")

SOURCE_LABELS = {
    "ecb": "EZB Data Portal",
    "bundesbank": "Deutsche Bundesbank",
    "eurostat": "Eurostat",
    "genesis": "Destatis GENESIS-Online",
    "jst": "JST Macrohistory Database",
    "gmd": "Global Macro Database",
    "derived": "Eigene Berechnung",
}


class CatalogError(ValueError):
    """Katalog ist ungültig; enthält alle gefundenen Fehler."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("Ungültiger Reihen-Katalog:\n- " + "\n- ".join(errors))


@dataclass(frozen=True)
class Block:
    id: str
    title: str
    sheet: str
    history: bool = False  # Langfristblock: Dashboard zeigt immer den ganzen Zeitraum


@dataclass(frozen=True)
class Chart:
    id: str
    title: str
    y_min: float | None = None  # feste Achsengrenzen, z.B. gegen Hyperinflationsspitzen
    y_max: float | None = None
    kind: str = "line"  # line | stacked (gestapelte Säulen mit Summenlinie)
    decimals: int | None = None  # feste Nachkommastellen der Werteachse (Inflationsraten: 1)


@dataclass(frozen=True)
class SeriesSpec:
    id: str
    source: str
    key: str
    title: str
    unit: str
    frequency: str
    adjustment: str
    block: str
    params: dict[str, Any] = field(default_factory=dict)
    link: str = ""
    chart: str = ""
    label: str = ""
    style: str = "line"
    start: str = "2000-01-01"
    note: str = ""
    derive: dict[str, Any] = field(default_factory=dict)
    member: str = ""  # erster expand-Wert, z.B. Ländercode
    stale_after_months: int = 0  # 0 = Standard je Frequenz

    @property
    def source_label(self) -> str:
        return SOURCE_LABELS.get(self.source, self.source)

    @property
    def chart_id(self) -> str:
        return self.chart or self.id

    @property
    def display_label(self) -> str:
        return self.label or self.title

    @property
    def start_year(self) -> int:
        return int(self.start[:4])

    @property
    def web_link(self) -> str:
        """Direktlink zur Reihe auf der Website der Quelle."""
        if self.link:
            return self.link
        return default_link(self)


@dataclass
class Catalog:
    blocks: list[Block]
    charts: dict[str, Chart]
    series: list[SeriesSpec]
    geo_names: dict[str, str] = field(default_factory=dict)
    comparison: dict[str, list[str]] = field(default_factory=dict)
    panels: list[dict[str, Any]] = field(default_factory=list)
    panel_members: list[str] = field(default_factory=list)

    def by_id(self) -> dict[str, SeriesSpec]:
        return {s.id: s for s in self.series}

    def block(self, block_id: str) -> Block:
        for b in self.blocks:
            if b.id == block_id:
                return b
        raise KeyError(block_id)

    def series_in_block(self, block_id: str) -> list[SeriesSpec]:
        return [s for s in self.series if s.block == block_id]

    def chart(self, chart_id: str, spec: SeriesSpec | None = None) -> Chart:
        if chart_id in self.charts:
            return self.charts[chart_id]
        return Chart(id=chart_id, title=spec.title if spec else chart_id)


def default_link(spec: SeriesSpec) -> str:
    if spec.source == "ecb":
        flow, _, key = spec.key.partition("/")
        return f"https://data.ecb.europa.eu/data/datasets/{flow}/{flow}.{key}"
    if spec.source == "bundesbank":
        flow, _, key = spec.key.partition("/")
        return (
            "https://www.bundesbank.de/dynamic/action/de/statistiken/"
            "zeitreihen-datenbanken/zeitreihen-datenbank/723452/723452"
            f"?tsId={flow}.{key}"
        )
    if spec.source == "eurostat":
        return f"https://ec.europa.eu/eurostat/databrowser/view/{spec.key}/default/table?lang=de"
    if spec.source == "jst":
        return "https://www.macrohistory.net/database/"
    if spec.source == "gmd":
        return "https://www.globalmacrodata.com"
    if spec.source == "genesis":
        stat = spec.key.split("-")[0]
        return f"https://www-genesis.destatis.de/datenbank/online/statistic/{stat}/table/{spec.key}"
    return ""


def _format_value(value: Any, mapping: dict[str, str]) -> Any:
    if isinstance(value, str):
        out = value
        for k, v in mapping.items():
            out = out.replace("{" + k + "}", v)
        return out
    if isinstance(value, dict):
        return {k: _format_value(v, mapping) for k, v in value.items()}
    if isinstance(value, list):
        return [_format_value(v, mapping) for v in value]
    return value


def _contains_placeholder(value: Any) -> bool:
    if isinstance(value, str):
        return bool(PLACEHOLDER_PATTERN.search(value))
    if isinstance(value, dict):
        return any(_contains_placeholder(v) for v in value.values())
    if isinstance(value, list):
        return any(_contains_placeholder(v) for v in value)
    return False


def expand_entry(entry: dict[str, Any], names: dict[str, dict[str, str]]) -> list[dict[str, Any]]:
    """Vervielfacht einen Eintrag mit 'expand' zu einzelnen Reihen.

    names: je Expand-Schlüssel eine Zuordnung Code -> Name, nutzbar als {<schlüssel>_name}.
    """
    expand = entry.get("expand")
    if not expand:
        return [entry]
    base = {k: v for k, v in entry.items() if k != "expand"}
    keys = list(expand.keys())
    out = []
    for combo in itertools.product(*(expand[k] for k in keys)):
        mapping = {k: str(v) for k, v in zip(keys, combo)}
        for k in keys:
            mapping[f"{k}_name"] = names.get(k, {}).get(mapping[k], mapping[k])
        new = _format_value(base, mapping)
        suffix = "_".join(str(v).lower() for v in combo)
        new["id"] = f"{base['id']}_{suffix}"
        new["member"] = str(combo[0])
        out.append(new)
    return out


def parse_catalog(raw: dict[str, Any]) -> Catalog:
    errors: list[str] = []
    if not isinstance(raw, dict):
        raise CatalogError(["Katalog muss ein YAML-Objekt sein."])

    defaults = raw.get("defaults") or {}
    geo_names = {str(k): str(v) for k, v in (raw.get("geo_names") or {}).items()}
    names = {str(k): {str(c): str(n) for c, n in (v or {}).items()} for k, v in (raw.get("names") or {}).items()}
    names.setdefault("geo", {}).update(geo_names)

    blocks: list[Block] = []
    for b in raw.get("blocks") or []:
        if not isinstance(b, dict) or "id" not in b or "title" not in b:
            errors.append(f"Themenblock ohne id/title: {b!r}")
            continue
        sheet = str(b.get("sheet") or b["title"])
        if len(sheet) > 31 or re.search(r"[\[\]:*?/\\]", sheet):
            errors.append(f"Themenblock {b['id']}: Blattname '{sheet}' ist in Excel unzulässig.")
        blocks.append(Block(id=str(b["id"]), title=str(b["title"]), sheet=sheet, history=bool(b.get("history"))))
    if not blocks:
        errors.append("Keine Themenblöcke definiert.")
    block_ids = {b.id for b in blocks}

    charts = {}
    for cid, c in (raw.get("charts") or {}).items():
        c = c if isinstance(c, dict) else {}
        charts[str(cid)] = Chart(
            id=str(cid),
            title=str(c.get("title") or cid),
            y_min=float(c["y_min"]) if c.get("y_min") is not None else None,
            y_max=float(c["y_max"]) if c.get("y_max") is not None else None,
            kind=str(c.get("kind") or "line"),
            decimals=int(c["decimals"]) if c.get("decimals") is not None else None,
        )

    entries = raw.get("series")
    if not isinstance(entries, list) or not entries:
        errors.append("Keine Reihen unter 'series' definiert.")
        entries = []

    series: list[SeriesSpec] = []
    seen: set[str] = set()
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            errors.append(f"Eintrag {i}: kein YAML-Objekt.")
            continue
        label = entry.get("id", f"#{i}")
        if "expand" in entry and not isinstance(entry["expand"], dict):
            errors.append(f"{label}: 'expand' muss ein Objekt sein.")
            continue
        for e in expand_entry(entry, names):
            errors.extend(_validate_entry(e, block_ids, charts))
            sid = e.get("id")
            if sid in seen:
                errors.append(f"{sid}: doppelte Reihen-ID.")
            seen.add(sid)
            if any(not e.get(f) for f in REQUIRED_FIELDS):
                continue
            series.append(
                SeriesSpec(
                    id=str(e["id"]),
                    source=str(e["source"]),
                    key=str(e.get("key") or ""),
                    title=str(e["title"]),
                    unit=str(e["unit"]),
                    frequency=str(e["frequency"]),
                    adjustment=str(e["adjustment"]),
                    block=str(e["block"]),
                    params=dict(e.get("params") or {}),
                    link=str(e.get("link") or ""),
                    chart=str(e.get("chart") or ""),
                    label=str(e.get("label") or ""),
                    style=str(e.get("style") or "line"),
                    start=str(e.get("start") or defaults.get("start") or "2000-01-01"),
                    note=str(e.get("note") or ""),
                    derive=dict(e.get("derive") or {}),
                    member=str(e.get("member") or ""),
                    stale_after_months=int(e.get("stale_after_months") or 0),
                )
            )

    ids = {s.id for s in series}
    by_id = {s.id: s for s in series}
    for s in series:
        if s.source == "derived":
            src = s.derive.get("from")
            if src not in ids:
                errors.append(f"{s.id}: abgeleitet von unbekannter Reihe '{src}'.")
            elif by_id[src].source == "derived":
                errors.append(f"{s.id}: Ableitung von abgeleiteter Reihe wird nicht unterstützt.")

    if errors:
        raise CatalogError(errors)
    comp = raw.get("comparison") or {}
    comparison = {
        "focus": [str(x) for x in comp.get("focus") or []],
        "peers": [str(x) for x in comp.get("peers") or []],
    }
    panels = list(raw.get("panels") or [])
    for p in panels:
        for side in ("left", "right"):
            cfg = p.get(side) or {}
            if cfg.get("chart") and cfg["chart"] not in charts and cfg["chart"] not in {s.chart_id for s in series}:
                errors.append(f"Panel {p.get('id')}: Diagramm '{cfg['chart']}' unbekannt.")
            for sid in cfg.get("series") or []:
                if sid not in ids:
                    errors.append(f"Panel {p.get('id')}: Reihe '{sid}' unbekannt.")
            if not cfg.get("chart") and not cfg.get("series"):
                errors.append(f"Panel {p.get('id')}: Seite '{side}' braucht 'chart' oder 'series'.")
    if errors:
        raise CatalogError(errors)
    return Catalog(blocks=blocks, charts=charts, series=series, geo_names=geo_names, comparison=comparison,
                   panels=panels, panel_members=[str(m) for m in raw.get("panel_members") or []])


def _validate_entry(e: dict[str, Any], block_ids: set[str], charts: dict[str, Chart]) -> list[str]:
    errors = []
    sid = e.get("id", "?")
    for f in REQUIRED_FIELDS:
        if not e.get(f):
            errors.append(f"{sid}: Pflichtfeld '{f}' fehlt.")
    if sid != "?" and not ID_PATTERN.match(str(sid)):
        errors.append(f"{sid}: ID nur aus Kleinbuchstaben, Ziffern und '_'.")
    source = e.get("source")
    if source and source not in SOURCES:
        errors.append(f"{sid}: unbekannte Quelle '{source}' (erlaubt: {', '.join(sorted(SOURCES))}).")
    if source and source != "derived" and not e.get("key"):
        errors.append(f"{sid}: Pflichtfeld 'key' fehlt.")
    if source in ("ecb", "bundesbank") and e.get("key") and "/" not in str(e["key"]):
        errors.append(f"{sid}: SDMX-Schlüssel muss die Form 'FLOW/KEY' haben.")
    if source == "derived":
        derive = e.get("derive") or {}
        if not derive.get("from"):
            errors.append(f"{sid}: 'derive.from' fehlt.")
        if derive.get("op") not in DERIVE_OPS:
            errors.append(f"{sid}: unbekannte Ableitung '{derive.get('op')}'.")
    freq = e.get("frequency")
    if freq and freq not in FREQUENCIES:
        errors.append(f"{sid}: unbekannte Frequenz '{freq}'.")
    block = e.get("block")
    if block and block not in block_ids:
        errors.append(f"{sid}: unbekannter Themenblock '{block}'.")
    chart = e.get("chart")
    if chart and chart not in charts:
        errors.append(f"{sid}: Diagramm '{chart}' fehlt unter 'charts'.")
    style = e.get("style", "line")
    if style not in STYLES:
        errors.append(f"{sid}: unbekannter Stil '{style}'.")
    link = e.get("link")
    if link and not str(link).startswith(("https://", "http://")):
        errors.append(f"{sid}: Link muss mit http(s):// beginnen.")
    start = e.get("start")
    if start and not re.match(r"^\d{4}-\d{2}-\d{2}$", str(start)):
        errors.append(f"{sid}: 'start' muss ein ISO-Datum sein (JJJJ-MM-TT).")
    if e.get("params") is not None and not isinstance(e.get("params"), dict):
        errors.append(f"{sid}: 'params' muss ein Objekt sein.")
    if _contains_placeholder({k: v for k, v in e.items() if k != "expand"}):
        errors.append(f"{sid}: nicht aufgelöster Platzhalter (fehlt 'expand'?).")
    return errors


def load_catalog(path: str | Path) -> Catalog:
    with open(path, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    return parse_catalog(raw)
