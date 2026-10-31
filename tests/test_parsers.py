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
