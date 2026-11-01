"""Kommandozeile: python -m konjunkturwolf {run,validate,build}."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .catalog import CatalogError, load_catalog
from .pipeline import Paths, load_status


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def _outputs(catalog, result, paths: Paths, site: bool) -> None:
    from .dashboard import build_site
    from .excel import write_workbook

    xlsx = write_workbook(catalog, result, paths.xlsx)
    logging.info("Excel geschrieben: %s", xlsx)
    if site:
        index = build_site(catalog, result, paths.site, xlsx)
        logging.info("Dashboard geschrieben: %s", index)


def status_markdown(catalog, result) -> str:
    counts = result.counts()
    lines = [
        f"**Lauf {result.finished_at}**: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())),
        "",
        "| Reihe | Quelle | Status | Werte | bis | Meldung |",
        "|---|---|---|---:|---|---|",
    ]
    specs = catalog.by_id()
    for st in result.statuses:
        spec = specs.get(st.series_id)
        msg = (st.message or "").replace("|", "/").replace("\n", " ")[:160]
        lines.append(
            f"| {st.series_id} | {spec.source_label if spec else ''} | {st.status} | {st.n_obs} | {st.last} | {msg} |"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="konjunkturwolf", description="Offizielle Wirtschaftsdaten abrufen und ausgeben.")
    parser.add_argument("--root", default=".", help="Projektverzeichnis (Standard: aktuelles Verzeichnis)")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="Reihen abrufen, Daten speichern, Excel und Dashboard erzeugen")
    p_run.add_argument("--only", nargs="+", metavar="ID", help="nur diese Reihen-IDs abrufen")
    p_run.add_argument("--no-cache", action="store_true", help="Cache ignorieren")
    p_run.add_argument("--offline", action="store_true", help="nur aus dem Cache lesen")
    p_run.add_argument("--no-site", action="store_true", help="kein Dashboard erzeugen")
    p_run.add_argument("--strict", action="store_true", help="Exit-Code 1, wenn eine Reihe ohne Daten bleibt")

    sub.add_parser("validate", help="Reihen-Katalog prüfen")
    sub.add_parser("build", help="Excel und Dashboard aus vorhandenen Daten erzeugen")
    sub.add_parser("summary", help="Status des letzten Laufs als Markdown-Tabelle ausgeben")

    args = parser.parse_args(argv)
    _setup_logging(args.verbose)
    paths = Paths(Path(args.root).resolve())

    try:
        catalog = load_catalog(paths.catalog)
    except CatalogError as exc:
        print(exc, file=sys.stderr)
        return 2

    if args.command == "validate":
        print(f"Katalog gültig: {len(catalog.series)} Reihen in {len(catalog.blocks)} Themenblöcken.")
        return 0

    if args.command == "summary":
        result = load_status(paths)
        if result is None:
            print("Noch kein Lauf vorhanden.")
            return 0
        print(status_markdown(catalog, result))
        return 0

    if args.command == "build":
        result = load_status(paths)
        if result is None:
            print("Keine Daten vorhanden. Erst 'run' ausführen.", file=sys.stderr)
            return 1
        _outputs(catalog, result, paths, site=True)
        return 0

    from .http import HttpClient
    from .pipeline import run, save

    client = HttpClient(paths.cache, use_cache=not args.no_cache, offline=args.offline)
    result = run(catalog, paths, client, only=args.only)
    save(result, paths)
    _outputs(catalog, result, paths, site=not args.no_site)
    counts = result.counts()
    logging.info("Fertig: %s", ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    if args.strict and (counts.get("failed", 0) or counts.get("stale", 0)):
        return 1
    return 0
