import re, requests
from urllib.parse import urljoin
H = {"User-Agent": "Mozilla/5.0"}
B = "https://statistik.arbeitsagentur.de"
seen, found = set(), set()
start = [B + "/DE/Navigation/Statistiken/Fachstatistiken/Leistungen-SGBIII/Kurzarbeitergeld/Kurzarbeitergeld-Nav.html",
         B + "/DE/Navigation/Statistiken/Fachstatistiken/Leistungen-SGBIII/Kurzarbeitergeld/Kurzarbeitergeld-Nav.html?nn=1525066",
         B + "/SiteGlobals/Forms/Suche/Einzelheftsuche_Formular.html?nn=1523064&topic_f=kurzarbeit",
         B + "/SiteGlobals/Forms/Suche/Einzelheftsuche_Formular.html?topic_f=kurzarbeit-zr"]
queue = list(start)
while queue and len(seen) < 40:
    u = queue.pop(0)
    if u in seen: continue
    seen.add(u)
    try:
        r = requests.get(u, headers=H, timeout=40)
    except Exception as e:
        print("ERR", u, e); continue
    print("GET", r.status_code, u[:160], flush=True)
    for l in re.findall(r'href="([^"]+)"', r.text):
        full = urljoin(u, l.replace("&amp;", "&"))
        low = full.lower()
        if re.search(r"\.(xlsx|xls|csv)", low) and "kurzarb" in low:
            found.add(full)
        elif "kurzarb" in low and "statistik.arbeitsagentur.de" in low and full not in seen and len(queue) < 80:
            queue.append(full)
for f in sorted(found): print("FILE", f)
# Kandidaten öffnen und Kopf zeigen
import io, pandas as pd
for f in sorted(found)[:6]:
    try:
        x = requests.get(f, headers=H, timeout=60); print("OPEN", f, x.status_code, len(x.content))
        for name, df in pd.read_excel(io.BytesIO(x.content), sheet_name=None, header=None).items():
            txt = df.astype(str).apply(" ".join, axis=1)
            hits = [t[:200] for t in txt if re.search(r"äquival|ausfall", t, re.I)]
            print("  SHEET", name, df.shape, hits[:5])
    except Exception as e: print("ERR", f, e)
