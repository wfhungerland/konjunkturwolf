"""Ende-zu-Ende ohne Netz: Fetcher werden durch Testdaten ersetzt."""

import json
from datetime import datetime, timezone

import openpyxl
import pandas as pd
import pytest

from konjunkturwolf import fetchers, pipeline
from konjunkturwolf.catalog import load_catalog
from konjunkturwolf.dashboard import build_site
from konjunkturwolf.excel import write_workbook
from konjunkturwolf.fetchers import FetchResult, SkipSeries
from konjunkturwolf.http import FetchError

from .conftest import ROOT


@pytest.fixture
def project(tmp_path):
    (tmp_path / "series.yaml").write_text((ROOT / "series.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    return pipeline.Paths(tmp_path)


def fake_fetch(spec, client):
    if spec.id == "fx_gbp":
        raise FetchError("HTTP 404 für Test")
    if spec.source == "genesis" and spec.id != "de_cpi":
        raise SkipSeries("GENESIS-Zugangsdaten fehlen")
    dates = pd.date_range("2020-01-01", periods=36, freq="MS")
    data = pd.DataFrame({"date": dates, "value": [100 + i for i in range(36)]})
    return FetchResult(data, f"https://example.test/{spec.id}", datetime(2026, 1, 1, tzinfo=timezone.utc), False)


def test_full_run(project, monkeypatch):
    for src in ("ecb", "bundesbank", "eurostat", "genesis"):
        monkeypatch.setitem(fetchers.FETCHERS, src, fake_fetch)
    monkeypatch.setattr(pipeline, "FETCHERS", fetchers.FETCHERS)
    catalog = load_catalog(project.catalog)

    result = pipeline.run(catalog, project, client=None)
    pipeline.save(result, project)
    st = result.status_map()
    assert st["fx_gbp"].status == "failed"
    assert st["de_ppi_destatis"].status == "skipped"
    assert st["de_cpi_energy_yoy"].status == "ok"
    assert st["de_cpi_land_yoy_09"].status == "skipped"
    assert st["fx_usd"].n_obs == 36

    obs = pd.read_csv(project.observations)
    assert list(obs.columns) == pipeline.TIDY_COLUMNS
    yoy = obs[obs["series_id"] == "de_cpi_energy_yoy"]
    assert len(yoy) == 24
    assert yoy["value"].iloc[0] == pytest.approx(12 / 100 * 100)

    xlsx = write_workbook(catalog, result, project.xlsx)
    wb = openpyxl.load_workbook(xlsx)
    assert wb.sheetnames[:3] == ["Info", "Quellen", "Daten"]
    assert {b.sheet for b in catalog.blocks} <= set(wb.sheetnames)
    quellen = wb["Quellen"]
    header = [c.value for c in quellen[1]]
    assert "Direktlink" in header and "Einheit" in header
    link_cell = quellen.cell(row=2, column=header.index("Direktlink") + 1)
    assert link_cell.hyperlink is not None
    assert wb["Daten"].max_row == len(obs) + 1

    index = build_site(catalog, result, project.site, xlsx)
    html = index.read_text(encoding="utf-8")
    assert "/*__DATA__*/null" not in html
    payload = json.loads((project.site / "data.json").read_text(encoding="utf-8"))
    assert [b["id"] for b in payload["blocks"]] == [b.id for b in catalog.blocks]
    assert (project.site / "konjunkturwolf.xlsx").exists()
    assert (project.site / "plotly.min.js").stat().st_size > 1_000_000
    assert "cdn.plot.ly" not in html


def test_failed_fetch_keeps_previous_data(project, monkeypatch):
    for src in ("ecb", "bundesbank", "eurostat", "genesis"):
        monkeypatch.setitem(fetchers.FETCHERS, src, fake_fetch)
    catalog = load_catalog(project.catalog)
    pipeline.save(pipeline.run(catalog, project, client=None, only=["fx_usd"]), project)

    def broken(spec, client):
        raise FetchError("Server down")

    monkeypatch.setitem(fetchers.FETCHERS, "ecb", broken)
    result = pipeline.run(catalog, project, client=None, only=["fx_usd"])
    st = result.status_map()["fx_usd"]
    assert st.status == "stale"
    assert st.n_obs == 36
    assert "Server down" in st.message


def test_is_outdated():
    today = pd.Timestamp("2026-10-31")
    assert pipeline.is_outdated(pd.Timestamp("2025-12-01"), "M", today)
    assert not pipeline.is_outdated(pd.Timestamp("2026-08-01"), "M", today)
    assert not pipeline.is_outdated(pd.Timestamp("2024-01-01"), "A", today)
    assert pipeline.is_outdated(pd.Timestamp("2026-08-15"), "D", today)


def test_panel_facts_rank_and_history():
    from konjunkturwolf.dashboard import panel_facts

    class Cat:
        comparison = {"focus": ["DE", "DEU"]}

    def s(member, label, x, y, freq="monatlich"):
        return {"member": member, "label": label, "x": x, "y": y, "frequency": freq}

    sides = {
        "right": {"series": [s("DE", "Deutschland", ["2026-09-01"], [2.0]),
                             s("FR", "Frankreich", ["2026-09-01"], [3.0]),
                             s("IT", "Italien", ["2026-09-01"], [1.0])]},
        "left": {"series": [s("DEU", "Deutschland", [f"{y}-01-01" for y in range(1900, 1940)],
                              [float(i % 4) for i in range(40)], "jährlich")]},
    }
    facts = panel_facts(Cat(), sides)
    assert facts[0] == "Zuletzt (September 2026): Deutschland 2,0 %."
    assert facts[1].startswith("Rang 2 von 3 Ländern")
    assert "in 50 % der Jahre darunter" in facts[2]
