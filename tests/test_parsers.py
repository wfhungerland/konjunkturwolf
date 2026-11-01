import pandas as pd
import pytest

from konjunkturwolf.parsers import (
    ParseError,
    parse_genesis_ffcsv,
    parse_jsonstat,
    parse_sdmx,
    parse_sdmx_csv,
    to_float,
)


def test_to_float_variants():
    assert to_float("1.5") == 1.5
    assert to_float("2,17") == 2.17
    assert to_float("1.234,5") == 1234.5
    assert to_float("...") is None
    assert to_float("-") is None
    assert to_float(None) is None
    assert to_float(3) == 3.0


def test_ecb_csv(fixture_text):
    df = parse_sdmx(fixture_text("ecb_exr.csv"))
    assert list(df.columns) == ["date", "value"]
    assert len(df) == 3
    assert df["date"].iloc[0] == pd.Timestamp("2024-01-01")
    assert df["value"].iloc[1] == pytest.approx(1.0795)


def test_bundesbank_semicolon_csv_skips_missing(fixture_text):
    df = parse_sdmx_csv(fixture_text("bundesbank.csv"))
    assert df["value"].tolist() == [2.17, 2.34]


def test_sdmx_csv_rejects_multiple_series():
    text = "KEY,TIME_PERIOD,OBS_VALUE\nA,2024-01,1\nB,2024-01,2\n"
    with pytest.raises(ParseError, match="2 Reihen"):
        parse_sdmx_csv(text)


def test_sdmx_csv_requires_columns():
    with pytest.raises(ParseError, match="TIME_PERIOD"):
        parse_sdmx_csv("A,B\n1,2\n")


def test_sdmx_json(fixture_text):
    df = parse_sdmx(fixture_text("sdmx.json"))
    assert df["value"].tolist() == [4.0, 3.75]
    assert df["date"].iloc[1] == pd.Timestamp("2024-09-18")


def test_sdmx_xml_error_is_reported():
    with pytest.raises(ParseError, match="XML"):
        parse_sdmx("<error><message>No results found</message></error>")


def test_jsonstat_with_filter(fixture_text):
    df = parse_jsonstat(fixture_text("eurostat_hicp.json"), filters={"geo": "FR"})
    assert df["value"].tolist() == [3.4, 2.4]
    assert df["date"].tolist() == [pd.Timestamp("2024-01-01"), pd.Timestamp("2024-03-01")]


def test_jsonstat_requires_unique_dimensions(fixture_text):
    with pytest.raises(ParseError, match="geo=DE,FR"):
        parse_jsonstat(fixture_text("eurostat_hicp.json"))


def test_jsonstat_error_payload():
    with pytest.raises(ParseError, match="Eurostat-Fehler"):
        parse_jsonstat({"error": [{"status": 400, "label": "Dataset not found"}]})


def test_jsonstat_list_values():
    payload = {
        "id": ["geo", "time"], "size": [1, 2],
        "dimension": {
            "geo": {"category": {"index": {"DE": 0}}},
            "time": {"category": {"index": {"2023-Q4": 0, "2024-Q1": 1}}},
        },
        "value": [0.1, None],
    }
    df = parse_jsonstat(payload)
    assert df["value"].tolist() == [0.1]
    assert df["date"].iloc[0] == pd.Timestamp("2023-10-01")


def test_genesis_value_variable_and_months(fixture_text):
    df = parse_genesis_ffcsv(fixture_text("genesis_61111-0002.csv"), value_variable="PREIS1")
    assert df["value"].tolist() == [117.6, 118.1, 118.6]
    assert df["date"].iloc[2] == pd.Timestamp("2024-03-01")


def test_genesis_ambiguous_without_value_variable(fixture_text):
    with pytest.raises(ParseError, match="PREIS1, PREIS2"):
        parse_genesis_ffcsv(fixture_text("genesis_61111-0002.csv"))


def test_genesis_filters(fixture_text):
    df = parse_genesis_ffcsv(
        fixture_text("genesis_orders.csv"),
        value_variable="AUF103",
        filters={"WZ08V2": "WZ08-C", "BERWE5": "X13JDKSB"},
    )
    assert df["value"].tolist() == [90.1, 91.4]


def test_genesis_unknown_attribute_lists_options(fixture_text):
    with pytest.raises(ParseError, match="WZ08-29, WZ08-C"):
        parse_genesis_ffcsv(fixture_text("genesis_orders.csv"), filters={"WZ08V2": "WZ08-X"})


def test_genesis_error_json():
    with pytest.raises(ParseError, match="GENESIS-Fehler"):
        parse_genesis_ffcsv('{"Status": {"Code": 98, "Content": "Fehler bei der Anmeldung"}}')


def test_sdmx_start_matches_frequency():
    from konjunkturwolf.catalog import SeriesSpec
    from konjunkturwolf.fetchers import sdmx_start

    def spec(freq):
        return SeriesSpec(id="x", source="bundesbank", key="A/B", title="t", unit="u", frequency=freq,
                          adjustment="-", block="b", start="2000-04-01")

    assert sdmx_start(spec("M")) == "2000-04"
    assert sdmx_start(spec("Q")) == "2000-Q2"
    assert sdmx_start(spec("D")) == "2000-04-01"
    assert sdmx_start(spec("A")) == "2000"
    assert sdmx_start(spec("S")) == "2000-S1"


def test_http_client_memoizes_identical_requests(tmp_path, monkeypatch):
    from konjunkturwolf.http import HttpClient

    client = HttpClient(tmp_path, use_cache=False, pause=0)
    calls = []

    class Fake:
        status_code = 200
        text = "ok"
        url = "https://example.test/x"
        encoding = "utf-8"
        headers = {"Content-Type": "text/plain"}

    def fake_request(*args, **kwargs):
        calls.append(1)
        return Fake()

    monkeypatch.setattr(client.session, "request", fake_request)
    client.post("https://example.test/x", data={"name": "61111-0010"})
    client.post("https://example.test/x", data={"name": "61111-0010"})
    assert len(calls) == 1


def test_genesis_stops_after_rejected_login(tmp_path, monkeypatch):
    from konjunkturwolf.catalog import SeriesSpec
    from konjunkturwolf.fetchers import SkipSeries, fetch_genesis
    from konjunkturwolf.http import FetchError, HttpClient

    monkeypatch.setenv("GENESIS_USER", "u")
    monkeypatch.setenv("GENESIS_PASSWORD", "p")
    client = HttpClient(tmp_path, use_cache=False, pause=0)
    calls = []

    def reject(*args, **kwargs):
        calls.append(1)
        raise FetchError('HTTP 404: {"Code":2,"Content":"Your username/token or password is wrong"}')

    monkeypatch.setattr(client, "post", reject)
    spec = SeriesSpec(id="x", source="genesis", key="61111-0010", title="t", unit="u", frequency="M",
                      adjustment="-", block="b")
    with pytest.raises(FetchError, match="lehnt die Zugangsdaten ab"):
        fetch_genesis(spec, client)
    with pytest.raises(SkipSeries):
        fetch_genesis(spec, client)
    assert len(calls) == 1


def test_panel_series_transforms():
    from konjunkturwolf.catalog import SeriesSpec
    from konjunkturwolf.fetchers import panel_series

    panel = pd.DataFrame({
        "iso": ["DEU"] * 4 + ["FRA"] * 4,
        "year": [2020, 2021, 2022, 2023] * 2,
        "cpi": [100.0, 102.0, 110.16, None, 50.0, 51.0, 52.0, 53.0],
        "tloans": [80.0, 90.0, 99.0, 100.0, 1, 1, 1, 1],
        "gdp": [100.0, 100.0, 110.0, 125.0, 1, 1, 1, 1],
    })

    def spec(key, **params):
        return SeriesSpec(id="x", source="jst", key=key, title="t", unit="u", frequency="A",
                          adjustment="-", block="b", params={"country": "DEU", "max_year": 2030, **params})

    infl = panel_series(panel, spec("cpi", transform="pct_change"), "iso")
    assert infl["value"].round(4).tolist() == [2.0, 8.0]
    assert infl["date"].iloc[0] == pd.Timestamp("2021-01-01")

    credit = panel_series(panel, spec("tloans", divide_by="gdp", scale=100), "iso")
    assert credit["value"].round(1).tolist() == [80.0, 90.0, 90.0, 80.0]

    cut = panel_series(panel, spec("tloans", max_year=2021), "iso")
    assert cut["date"].max() == pd.Timestamp("2021-01-01")

    with pytest.raises(ParseError, match="Land"):
        panel_series(panel, SeriesSpec(id="x", source="jst", key="cpi", title="t", unit="u", frequency="A",
                                       adjustment="-", block="b", params={"country": "XXX"}), "iso")


def test_genesis_skips_preamble(fixture_text):
    text = "GENESIS-Tabelle: 61111-0002\nVerbraucherpreisindex\n\n" + fixture_text("genesis_61111-0002.csv")
    df = parse_genesis_ffcsv(text, value_variable="PREIS1")
    assert len(df) == 3


def test_genesis_reports_unknown_format():
    with pytest.raises(ParseError, match="Anfang: Titel"):
        parse_genesis_ffcsv("Titel\nnoch eine Zeile\n1;2;3;4\n")


def test_genesis_zip_is_unpacked(fixture_text):
    import io
    import zipfile

    from konjunkturwolf.fetchers import genesis_text

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("61111-0002_flat.csv", fixture_text("genesis_61111-0002.csv").encode("utf-8"))
    text = genesis_text(buf.getvalue())
    assert parse_genesis_ffcsv(text, value_variable="PREIS1")["value"].tolist() == [117.6, 118.1, 118.6]
    assert genesis_text("ä;b".encode("cp1252")) == "ä;b"
