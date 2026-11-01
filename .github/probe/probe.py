import re, requests, io
import pandas as pd
H = {"User-Agent": "konjunkturwolf-probe"}
def get(u):
    r = requests.get(u, headers=H, timeout=60); print("GET", u, r.status_code, len(r.content)); return r
for u in ["https://data.nber.org/databases/macrohistory/contents/germany.html",
          "https://www.nber.org/research/data/nber-macrohistory-database",
          "https://data.nber.org/databases/macrohistory/contents/chapter04.html",
          "https://data.nber.org/databases/macrohistory/contents/"]:
    try:
        r = get(u)
        if r.ok:
            t = re.sub(r"<[^>]+>", " ", r.text)
            links = re.findall(r'href="([^"]+)"', r.text)
            print("LINKS", [l for l in links if "germ" in l.lower() or l.endswith(".html")][:60])
            for line in t.split("\n"):
                if re.search(r"German|Germany", line): print("  ", " ".join(line.split())[:200])
    except Exception as e: print("ERR", u, e)
r = get("https://data.nber.org/databases/macrohistory/contents/germany.html")
if r.ok:
    rows = re.findall(r'(m\d{5}[a-z]?)\.(?:dat|db|txt)', r.text)
    print("SERIES", sorted(set(rows)))
    for m in re.finditer(r'(m\d{5}[a-z]?)[^<]*?</a>(.{0,200})', r.text, re.S):
        print("S", m.group(1), " ".join(re.sub(r"<[^>]+>", " ", m.group(2)).split())[:150])
# Eurostat Industrieproduktion
r = get("https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/sts_inpr_m?geo=DE&nace_r2=B-D&s_adj=SCA&unit=I21&indic_bt=PRD&format=JSON&sinceTimePeriod=2007-01")
print(r.text[:300])
# JST Spalten
x = pd.read_excel(io.BytesIO(get("https://www.macrohistory.net/app/download/9834512569/JSTdatasetR6.xlsx").content))
print("JST", [c for c in x.columns])
