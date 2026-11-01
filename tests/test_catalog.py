import copy

import pytest

from konjunkturwolf.catalog import CatalogError, load_catalog, parse_catalog

from .conftest import ROOT

BASE = {
    "blocks": [{"id": "b", "title": "Block", "sheet": "Block"}],
    "charts": {"c": {"title": "Chart"}},
    "geo_names": {"DE": "Deutschland", "FR": "Frankreich"},
    "series": [
        {
            "id": "x_rate", "source": "ecb", "key": "EXR/M.USD.EUR.SP00.A", "title": "USD",
            "unit": "USD je EUR", "frequency": "M", "adjustment": "nicht bereinigt", "block": "b", "chart": "c",
        }
    ],
}


def make(**changes):
    raw = copy.deepcopy(BASE)
    raw["series"][0].update(changes)
    return raw


def test_repository_catalog_is_valid():
    cat = load_catalog(ROOT / "series.yaml")
    assert len(cat.series) >= 4 * 4
    assert all(s.web_link.startswith("https://") for s in cat.series if s.source != "derived")
    assert all(s.unit for s in cat.series)


def test_repository_catalog_covers_all_blocks():
    cat = load_catalog(ROOT / "series.yaml")
    for block in cat.blocks:
        assert len(cat.series_in_block(block.id)) >= 4, block.id


def test_minimal_catalog():
    cat = parse_catalog(make())
    spec = cat.series[0]
    assert spec.start == "2000-01-01"
    assert spec.web_link == "https://data.ecb.europa.eu/data/datasets/EXR/EXR.M.USD.EUR.SP00.A"


@pytest.mark.parametrize(
    "changes, message",
    [
        ({"source": "imf"}, "unbekannte Quelle"),
        ({"frequency": "W"}, "unbekannte Frequenz"),
        ({"block": "zz"}, "unbekannter Themenblock"),
        ({"chart": "zz"}, "Diagramm 'zz'"),
        ({"unit": ""}, "Pflichtfeld 'unit'"),
        ({"id": "Bad-ID"}, "Kleinbuchstaben"),
        ({"key": "EXRM"}, "FLOW/KEY"),
        ({"link": "ftp://x"}, "http"),
        ({"start": "2000"}, "ISO-Datum"),
        ({"title": "BIP {geo}"}, "Platzhalter"),
        ({"style": "area"}, "unbekannter Stil"),
    ],
)
def test_invalid_entries(changes, message):
    with pytest.raises(CatalogError) as err:
        parse_catalog(make(**changes))
    assert any(message in e for e in err.value.errors), err.value.errors


def test_duplicate_ids():
    raw = make()
    raw["series"].append(copy.deepcopy(raw["series"][0]))
    with pytest.raises(CatalogError, match="doppelte"):
        parse_catalog(raw)


def test_expand_geo():
    raw = make(
        id="eu_unemp", source="eurostat", key="une_rt_m", expand={"geo": ["DE", "FR"]},
        params={"geo": "{geo}", "unit": "PC_ACT"}, title="Quote {geo_name}", label="{geo_name}",
    )
    cat = parse_catalog(raw)
    ids = [s.id for s in cat.series]
    assert ids == ["eu_unemp_de", "eu_unemp_fr"]
    fr = cat.series[1]
    assert fr.params == {"geo": "FR", "unit": "PC_ACT"}
    assert fr.title == "Quote Frankreich"
    assert fr.display_label == "Frankreich"


def test_derived_requires_existing_base():
    raw = make()
    raw["series"].append(
        {"id": "d", "source": "derived", "derive": {"from": "nope", "op": "yoy_pct"}, "title": "D",
         "unit": "%", "frequency": "M", "adjustment": "-", "block": "b"}
    )
    with pytest.raises(CatalogError, match="unbekannter Reihe"):
        parse_catalog(raw)


def test_errors_are_collected():
    raw = make(source="imf", frequency="W")
    with pytest.raises(CatalogError) as err:
        parse_catalog(raw)
    assert len(err.value.errors) >= 2


def test_expand_with_custom_names():
    raw = make(
        id="land_cpi", source="genesis", key="61111-0010", expand={"land": ["09"]},
        params={"filters": {"DLAND": "{land}"}}, title="VPI {land_name}",
    )
    raw["names"] = {"land": {"09": "Bayern"}}
    spec = parse_catalog(raw).series[0]
    assert spec.id == "land_cpi_09"
    assert spec.title == "VPI Bayern"
    assert spec.params["filters"] == {"DLAND": "09"}


def test_repository_catalog_resolves_names_and_comparison():
    cat = load_catalog(ROOT / "series.yaml")
    spec = cat.by_id()["eu_hicp_fr"]
    assert spec.label == "Frankreich"
    assert spec.member == "FR"
    assert "DE" in cat.comparison["focus"]
    assert "FR" in cat.comparison["peers"]


def test_repository_panels_are_valid():
    cat = load_catalog(ROOT / "series.yaml")
    assert [p["id"] for p in cat.panels] == ["inflation", "wachstum", "arbeit", "zinsen"]
    for p in cat.panels:
        assert p["left"] and p["right"]


def test_panel_sides_show_same_countries():
    """Links und rechts dieselbe Ländergruppe, damit beide Seiten vergleichbar sind."""
    cat = load_catalog(ROOT / "series.yaml")
    iso3 = {"DEU": "DE", "FRA": "FR", "ITA": "IT", "ESP": "ES", "NLD": "NL", "POL": "PL"}
    for p in cat.panels:
        members = []
        for side in ("left", "right"):
            specs = [s for s in cat.series if s.chart_id == p[side]["chart"]]
            m = {iso3.get(s.member, s.member) for s in specs if s.member in cat.panel_members}
            members.append(m)
        assert "DE" in members[0] and "DE" in members[1], p["id"]
        # JST hat kein Polen; sonst gleich
        assert members[0] - {"PL"} == members[1] - {"PL"}, p["id"]
