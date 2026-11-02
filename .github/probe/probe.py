import io, re, time, subprocess, requests, pandas as pd
H = {"User-Agent": "Mozilla/5.0"}
u = "https://statistik.arbeitsagentur.de/Statistikdaten/Detail/Aktuell/iiia7/kurzarbeit-zr2/kurzarbeit-zr2-dwolkraa-0-xlsm.xlsm?__blob=publicationFile&v=1"
for i in range(4):
    r = requests.get(u, headers=H, timeout=90); print("GET", r.status_code, len(r.content), flush=True)
    if r.status_code != 429: break
    time.sleep(30)
sheets = pd.read_excel(io.BytesIO(r.content), sheet_name=None, header=None, engine="openpyxl")
print("SHEETS", list(sheets))
for name, df in sheets.items():
    t = df.astype(object).where(df.notna(), "").astype(str)
    txt = t.apply(lambda r: " | ".join(x for x in r if x), axis=1)
    if any(re.search(r"äquivalent|Arbeitsausfall von", x) for x in txt):
        print("=== SHEET", name, df.shape)
        for i in range(min(14, len(txt))): print("  R", i, txt.iloc[i][:260])
        print("  ...", txt.iloc[14][:200] if len(txt) > 14 else "")
# Eichung: Daten über die eigene Pipeline holen
subprocess.run(["python", "-m", "konjunkturwolf", "run", "--no-cache", "--only", "de_alq_sa", "de_alo_sa", "de_vac_sa", "de_ka_sa"], check=False)
obs = pd.read_csv("data/processed/observations.csv", parse_dates=["date"])
g = {k: obs[obs.series_id == k][["date", "value"]].reset_index(drop=True) for k in ("de_alq_sa", "de_alo_sa", "de_vac_sa", "de_ka_sa")}
for k, v in g.items(): print(k, len(v), v.head(1).values.tolist(), v.tail(1).values.tolist())
from konjunkturwolf.fetchers import sahm_frame
from konjunkturwolf.dashboard import sahm_track, _recessions
recs = _recessions()
for label, extra in [("ohne KA", {"level": g["de_alo_sa"], "vac": g["de_vac_sa"]}),
                     ("KA x0,4", {"level": g["de_alo_sa"], "vac": g["de_vac_sa"], "ka": g["de_ka_sa"].assign(value=g["de_ka_sa"].value * 0.4)})]:
    f = sahm_frame(g["de_alq_sa"], extra)
    x = f.date.dt.strftime("%Y-%m-01").tolist()
    print("==", label, x[0], x[-1], f[["u", "v", "min"]].iloc[-1].round(3).tolist())
    for col in ("u", "min"):
        for thr in [0.1, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5]:
            hits, false = sahm_track(x, f[col].tolist(), thr, recs)
            print(f"  {col} {thr}: {hits} false {len(false)} {[z[:7] for z in false]}")
    print("  max je Jahr", f.set_index("date")["min"].resample("YE").max().round(2).to_dict())
