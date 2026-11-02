"""Einmalig: Exportähnlichkeit (datawolf/derived/esi_results.csv) als statische Reihen ablegen.

Schreibt data/static/esi_<land>.csv (date,value). Die Reihen sind im Katalog (series.yaml) als source: static definiert.
"""
import sys
from pathlib import Path

import pandas as pd

src = Path(sys.argv[1] if len(sys.argv) > 1 else "../datawolf/derived/esi_results.csv")
out = Path(__file__).resolve().parent.parent / "data" / "static"
res = pd.read_csv(src, dtype={"key": str})
for k in ("CHN", "USA", "JPN", "KOR", "FRA", "ITA"):
    g = res[(res.measure == "esi_hs2") & (res.key == k)].sort_values("year")
    if g.empty:
        print("fehlt", k); continue
    pd.DataFrame({"date": g.year.astype(int).astype(str) + "-01-01", "value": g.value.round(3)}).to_csv(out / f"esi_{k.lower()}.csv", index=False)
    print(k, len(g), int(g.year.min()), int(g.year.max()), "letzter Wert", g.value.iloc[-1])
