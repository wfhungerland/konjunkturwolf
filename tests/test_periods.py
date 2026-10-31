from datetime import date

import pytest

from konjunkturwolf.periods import parse_period, period_label


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("2024", date(2024, 1, 1)),
        ("2024-03", date(2024, 3, 1)),
        ("2024M03", date(2024, 3, 1)),
        ("2024-Q2", date(2024, 4, 1)),
        ("2024Q4", date(2024, 10, 1)),
        ("2024-S2", date(2024, 7, 1)),
        ("2024S1", date(2024, 1, 1)),
        ("2024-H2", date(2024, 7, 1)),
        ("2024-06-12", date(2024, 6, 12)),
        ("2024-06-12T00:00:00", date(2024, 6, 12)),
        ("2024-W01", date(2024, 1, 1)),
    ],
)
def test_parse_period(raw, expected):
    assert parse_period(raw) == expected


def test_parse_period_rejects_garbage():
    with pytest.raises(ValueError):
        parse_period("Januar 2024")


def test_period_label():
    assert period_label(date(2024, 4, 1), "Q") == "2024-Q2"
    assert period_label(date(2024, 7, 1), "S") == "2024-H2"
    assert period_label(date(2024, 5, 1), "M") == "2024-05"
    assert period_label(date(2024, 1, 1), "A") == "2024"
