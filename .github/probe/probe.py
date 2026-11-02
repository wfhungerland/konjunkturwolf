import io, re, time, requests, pandas as pd
H = {"User-Agent": "Mozilla/5.0"}
u = "https://statistik.arbeitsagentur.de/Statistikdaten/Detail/Aktuell/iiia7/kurzarbeit-zr2/kurzarbeit-zr2-dwolkraa-0-xlsm.xlsm?__blob=publicationFile&v=1"
for i in range(4):
    r = requests.get(u, headers=H, timeout=90); print("GET", r.status_code, len(r.content), flush=True)
    if r.status_code != 429: break
    time.sleep(30)
open("/tmp/zr2.xlsm", "wb").write(r.content)
xl = pd.ExcelFile(io.BytesIO(r.content), engine="openpyxl")
print("SHEETS", xl.sheet_names)
for name in xl.sheet_names:
    df = xl.parse(name, header=None)
    txt = df.astype(str).apply(lambda r: " | ".join(x for x in r if x != "nan"), axis=1)
    hits = [(i, t[:220]) for i, t in enumerate(txt) if re.search(r"äquival|ausfall|Vollzeit", t, re.I)]
    print("SHEET", name, df.shape, "HITS", hits[:8], flush=True)
    if hits:
        print(df.head(14).to_string()[:3000]); print(df.tail(5).to_string()[:1500])
