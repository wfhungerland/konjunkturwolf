import io, re, time, requests, pandas as pd
H = {"User-Agent": "Mozilla/5.0"}
u = "https://statistik.arbeitsagentur.de/Statistikdaten/Detail/Aktuell/iiia7/kurzarbeit-zr2/kurzarbeit-zr2-dwolkraa-0-xlsm.xlsm?__blob=publicationFile&v=1"
for i in range(4):
    r = requests.get(u, headers=H, timeout=90); print("GET", r.status_code, len(r.content), flush=True)
    if r.status_code != 429: break
    time.sleep(30)
xl = pd.ExcelFile(io.BytesIO(r.content), engine="openpyxl")
print("SHEETS", xl.sheet_names)
for name in xl.sheet_names:
    df = xl.parse(name, header=None).fillna("").astype(str)
    txt = df.apply(lambda r: " | ".join(x for x in r if x), axis=1)
    hits = [(i, t[:200]) for i, t in enumerate(txt) if re.search(r"äquival|ausfall|Vollzeit", t, re.I)]
    print("SHEET", name, df.shape, "HITS", hits[:6], flush=True)
    if hits:
        for i in range(min(16, len(txt))): print("  R", i, txt.iloc[i][:300])
        for i in range(max(0, len(txt) - 4), len(txt)): print("  T", i, txt.iloc[i][:300])
# Eichung mit Bundesbank-Daten
from konjunkturwolf.fetchers import sahm_frame
from konjunkturwolf.dashboard import sahm_track, _recessions
B = "https://api.statistiken.bundesbank.de/rest/data/BBDL1/"
def bb(k):
    t = requests.get(B + k + "?format=csv&lang=en", headers={"User-Agent": "x"}, timeout=60).text
    rows = [l.split(";")[:2] for l in t.splitlines() if re.match(r"\d{4}-\d{2};", l)]
    return pd.DataFrame({"date": pd.to_datetime([a + "-01" for a, _ in rows]), "value": [float(b.replace(",", ".")) for _, b in rows]})
rate = bb("M.DE.Y.UNE.UBA000.A0000.A01.D00.0.R00.A"); lvl = bb("M.DE.Y.UNE.UBA000.A0000.A01.D00.0.ABA.A")
vac = bb("M.DE.Y.VAC.VBA000.A0000.A00.D00.0.ABA.A"); ka = bb("M.DE.Y.LMP.LKA100.A0000.A02.D00.0.ABA.A")
print("VAC", vac.head(2).values.tolist(), vac.tail(2).values.tolist(), "KA", ka.tail(2).values.tolist(), "LVL", lvl.tail(1).values.tolist())
recs = _recessions()
for label, extra in [("ohne KA", {"level": lvl, "vac": vac}), ("KA x0,5", {"level": lvl, "vac": vac, "ka": ka.assign(value=ka.value * 0.5)})]:
    f = sahm_frame(rate, extra)
    x = f.date.dt.strftime("%Y-%m-01").tolist()
    print("==", label, "Start", x[0], "letzter", x[-1], "u/v/min", f[["u", "v", "min"]].iloc[-1].round(3).tolist())
    for col in ("u", "min"):
        for thr in [0.1, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5]:
            hits, false = sahm_track(x, f[col].tolist(), thr, recs)
            print(f"  {col} thr {thr}: hits {hits} false {len(false)} {[z[:7] for z in false]}")
    print(f.set_index("date")["min"].resample("YE").max().round(2).to_dict())
