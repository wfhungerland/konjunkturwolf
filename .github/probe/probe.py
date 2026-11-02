import io, re, time, subprocess, requests, pandas as pd
H = {"User-Agent": "Mozilla/5.0"}
u = "https://statistik.arbeitsagentur.de/Statistikdaten/Detail/Aktuell/iiia7/kurzarbeit-zr2/kurzarbeit-zr2-dwolkraa-0-xlsm.xlsm?__blob=publicationFile&v=1"
for i in range(4):
    r = requests.get(u, headers=H, timeout=90)
    if r.status_code != 429: break
    time.sleep(30)
sheets = pd.read_excel(io.BytesIO(r.content), sheet_name=None, header=None, engine="openpyxl")
COL = 1
MON = {m: i + 1 for i, m in enumerate(["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"])}
rows = []
for name, df in sheets.items():
    t = df.astype(object).where(df.notna(), "").astype(str)
    if name != "Arbeitsausfall": continue
    pass
    print("SHEET", name, df.shape, "|", " ".join(t.iloc[2].tolist())[:150])
    for r in df.values.tolist():
        js = [j for j, v in enumerate(r[:6]) if hasattr(v, "year") or re.match(r"(\w+ \d{4}|\d{4}[-/]\d{2})", str(v).strip())]
        if not js: continue
        COL = js[0] + 1
        c0 = r[js[0]]
        if hasattr(c0, "year"):
            d = f"{c0.year}-{c0.month:02d}-01"
        else:
            m = re.match(r"(\w+) (\d{4})$", str(c0).strip())
            m2 = re.match(r"(\d{4})[-/](\d{2})", str(c0).strip())
            d = f"{m.group(2)}-{MON[m.group(1)]:02d}-01" if (m and m.group(1) in MON) else (f"{m2.group(1)}-{m2.group(2)}-01" if m2 else None)
        if d:
            vals = [pd.to_numeric(v, errors="coerce") for v in r[COL:COL + 6]]
            if pd.notna(vals[0]) and vals[0] > 0:
                w = [0.125, 0.375, 0.625, 0.87, 1.0]
                fte = sum((vals[k + 1] if pd.notna(vals[k + 1]) else 0) * w[k] for k in range(5))
                rows.append((d, vals[0], round(fte / vals[0], 4), name))
    break
ratio = pd.DataFrame(rows, columns=["date", "persons", "ratio", "sheet"]).drop_duplicates("date").sort_values("date")
ratio[["date", "ratio"]].rename(columns={"ratio": "value"}).to_csv("data/static/ba_ka_fte_ratio.csv", index=False)
print("geschrieben", len(ratio), ratio.date.min(), ratio.date.max())
