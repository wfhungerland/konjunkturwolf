"""Einmalig: Gravitationsergebnisse (datawolf/derived/gravity_results.csv) als statische Reihen ablegen.

Schreibt data/static/grav_*.csv (date,value). Die Reihen sind im Katalog (series.yaml) als source: static definiert.
"""
import sys
from pathlib import Path

import pandas as pd

src = Path(sys.argv[1] if len(sys.argv) > 1 else "../datawolf/derived/gravity_results.csv")
out = Path(__file__).resolve().parent.parent / "data" / "static"
res = pd.read_csv(src)
MAP = {  # measure, key -> Dateiname
    **{("acr_gain_theta5", k): f"grav_acr_{k.lower()}" for k in ("GER", "FRA", "ITA", "ESP", "NLD")},
    ("acr_gain_theta4", "GER"): "grav_acr_ger_t4", ("acr_gain_theta8", "GER"): "grav_acr_ger_t8",
    **{("novy_theta8", k): f"grav_novy_{k.lower()}" for k in ("FRA", "GBR", "USA", "NLD", "ITA", "RUS")},
    ("mrt_in", "GER_vs_USA"): "grav_mrt_in", ("mrt_out", "GER_vs_USA"): "grav_mrt_out",
    ("dist_elast", "world"): "grav_dist",
    **{("share_exp", k): f"grav_share_{k.lower()}" for k in ("FRA", "GBR", "USA", "NLD", "RUS", "CHN")},
    **{("resid", k): f"grav_resid_{k.lower()}" for k in ("FRA", "GBR", "USA", "NLD", "RUS")},
}
for (m, k), name in MAP.items():
    g = res[(res.measure == m) & (res.key == k)].sort_values("year")
    if g.empty:
        print("fehlt", m, k); continue
    if m == "resid":  # einzelne Jahre schwanken stark (Kriege, Grenzänderungen): zentriertes 5-Jahres-Mittel
        g = g.set_index("year").reindex(range(int(g.year.min()), int(g.year.max()) + 1))
        g["value"] = g.value.rolling(5, center=True, min_periods=3).mean()
        g = g.dropna(subset=["value"]).reset_index()
    pd.DataFrame({"date": g.year.astype(int).astype(str) + "-01-01", "value": g.value.round(5)}).to_csv(out / f"{name}.csv", index=False)
    print(name, len(g), int(g.year.min()), int(g.year.max()))
