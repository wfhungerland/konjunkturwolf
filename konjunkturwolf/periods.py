"""Umrechnung von Periodenangaben der Quellen in Datumswerte.

Konvention: Jede Periode wird auf ihren ersten Tag abgebildet
(2024-Q2 -> 2024-04-01, 2024-S2 -> 2024-07-01, 2024 -> 2024-01-01).
"""

from __future__ import annotations

import re
from datetime import date

_PATTERNS = [
    (re.compile(r"^(\d{4})-(\d{2})-(\d{2})$"), lambda y, m, d: date(int(y), int(m), int(d))),
    (re.compile(r"^(\d{4})-?M?(\d{2})$"), lambda y, m: date(int(y), int(m), 1)),
    (re.compile(r"^(\d{4})-?Q([1-4])$"), lambda y, q: date(int(y), 3 * (int(q) - 1) + 1, 1)),
    (re.compile(r"^(\d{4})-?[SH]([12])$"), lambda y, s: date(int(y), 6 * (int(s) - 1) + 1, 1)),
    (re.compile(r"^(\d{4})-?W(\d{2})$"), lambda y, w: date.fromisocalendar(int(y), int(w), 1)),
    (re.compile(r"^(\d{4})(?:-A1)?$"), lambda y: date(int(y), 1, 1)),
]


def parse_period(value: str) -> date:
    """Wandelt eine Periodenangabe (SDMX, JSON-stat, GENESIS) in ein Datum um."""
    text = str(value).strip().upper()
    if "T" in text and re.match(r"^\d{4}-\d{2}-\d{2}T", text):
        text = text[:10]
    for pattern, builder in _PATTERNS:
        m = pattern.match(text)
        if m:
            return builder(*m.groups())
    raise ValueError(f"Unbekanntes Periodenformat: {value!r}")


def months_per_period(frequency: str) -> int:
    return {"M": 1, "Q": 3, "S": 6, "A": 12}[frequency]


def period_label(d: date, frequency: str) -> str:
    """Lesbare Periode, z. B. '2024-Q2' oder '2024-05'."""
    if frequency == "A":
        return f"{d.year}"
    if frequency == "S":
        return f"{d.year}-H{1 if d.month <= 6 else 2}"
    if frequency == "Q":
        return f"{d.year}-Q{(d.month - 1) // 3 + 1}"
    if frequency == "M":
        return f"{d.year}-{d.month:02d}"
    return d.isoformat()
