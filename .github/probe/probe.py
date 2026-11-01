import io, os, zipfile, requests
import pandas as pd
H = {"username": os.environ["GENESIS_USER"], "password": os.environ.get("GENESIS_PASSWORD", "").strip(),
     "Content-Type": "application/x-www-form-urlencoded"}
r = requests.post("https://genesis.destatis.de/genesisWS/rest/2020/data/tablefile",
                  data={"name": "61241-0002", "area": "all", "compress": "false", "format": "ffcsv", "language": "en", "startyear": "2009", "endyear": "2012"},
                  headers=H, timeout=180)
raw = r.content
if raw[:2] == b"PK":
    z = zipfile.ZipFile(io.BytesIO(raw)); raw = z.read(z.namelist()[0])
text = raw.decode("utf-8-sig", errors="replace")
lines = text.splitlines()
start = next(i for i, l in enumerate(lines) if ";time;" in l.lower() or l.lower().startswith("statistics_code"))
print("\n".join(lines[:start]))
df = pd.read_csv(io.StringIO("\n".join(lines[start:])), sep=";", dtype=str)
print(list(df.columns))
for c in df.columns:
    u = df[c].unique()
    if 1 < len(u) < 40: print(c, list(u)[:40])
sub = df[(df["time"] == "2012")]
print(sub.head(40).to_string())
