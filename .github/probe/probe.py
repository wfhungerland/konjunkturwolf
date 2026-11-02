import io, re, time, subprocess, requests, pandas as pd
H = {"User-Agent": "Mozilla/5.0"}
u = "https://statistik.arbeitsagentur.de/Statistikdaten/Detail/Aktuell/iiia7/kurzarbeit-zr2/kurzarbeit-zr2-dwolkraa-0-xlsm.xlsm?__blob=publicationFile&v=1"
for i in range(4):
    r = requests.get(u, headers=H, timeout=90)
    if r.status_code != 429: break
    time.sleep(30)
sheets = pd.read_excel(io.BytesIO(r.content), sheet_name=None, header=None, engine="openpyxl")
MON = {m: i + 1 for i, m in enumerate(["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"])}
rows = []
for name, df in sheets.items():
    t = df.astype(object).where(df.notna(), "").astype(str)
    if not any("Arbeitsausfall von" in " ".join(r) for r in t.values.tolist()[:12]): continue
    print("SHEET", name, df.shape, "|", " ".join(t.iloc[2].tolist())[:150])
    for r in df.values.tolist():
        m = re.match(r"(\w+) (\d{4})$", str(r[0]).strip())
        if m and m.group(1) in MON:
            vals = [pd.to_numeric(v, errors="coerce") for v in r[1:7]]
            if pd.notna(vals[0]) and vals[0] > 0:
                w = [0.125, 0.375, 0.625, 0.87, 1.0]
                fte = sum((vals[k + 1] if pd.notna(vals[k + 1]) else 0) * w[k] for k in range(5))
                rows.append((f"{m.group(2)}-{MON[m.group(1)]:02d}-01", vals[0], round(fte / vals[0], 4), name))
    break
ratio = pd.DataFrame(rows, columns=["date", "persons", "ratio", "sheet"]).drop_duplicates("date").sort_values("date")
print("RATIO_CSV_START")
print("date,value"); [print(f"{d},{v}") for d, v in zip(ratio.date, ratio.ratio)]
print("RATIO_CSV_END")
subprocess.run(["python", "-m", "konjunkturwolf", "run", "--no-cache", "--only", "de_alq_sa", "de_alo_sa", "de_vac_sa", "de_ka_sa"], check=False)
obs = pd.read_csv("data/processed/observations.csv", parse_dates=["date"])
g = {k: obs[obs.series_id == k][["date", "value"]].reset_index(drop=True) for k in ("de_alq_sa", "de_alo_sa", "de_vac_sa", "de_ka_sa")}
for k, v in g.items(): print(k, len(v), v.head(1).values.tolist(), v.tail(1).values.tolist())
rt = pd.DataFrame({"date": pd.to_datetime(ratio.date), "value": ratio.ratio})
from konjunkturwolf.fetchers import sahm_frame
from konjunkturwolf.dashboard import sahm_track, _recessions
recs = _recessions()
base = {"level": g["de_alo_sa"], "vac": g["de_vac_sa"]}
for label, extra in [("ohne KA", base), ("KA FTE", dict(base, ka=g["de_ka_sa"], ka_ratio=rt))]:
    f = sahm_frame(g["de_alq_sa"], extra)
    x = f.date.dt.strftime("%Y-%m-01").tolist()
    print("==", label, x[0], x[-1], f[["u", "v", "min"]].iloc[-1].round(3).tolist())
    for col in ("u", "v", "min"):
        for thr in [0.1, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5, 0.7]:
            hits, false = sahm_track(x, f[col].tolist(), thr, recs)
            print(f"  {col} {thr}: {hits} false {len(false)} {[z[:7] for z in false]}")
