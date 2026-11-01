import requests
S = requests.Session()
def get(url, **kw):
    r = S.get(url, timeout=120, **kw); print(f"\n### {r.status_code} {r.url}"); return r
for flt in ["BBDP1/M.DE.N.VPI.....", "BBDP1/M.DE......", "BBDP1/M......"]:
    r = get(f"https://api.statistiken.bundesbank.de/rest/data/{flt}", params={"lastNObservations": 1, "detail": "dataonly"}, headers={"Accept": "application/vnd.sdmx.data+csv;version=1.0.0"})
    lines = r.text.splitlines(); print(len(lines))
    print("\n".join(l for l in lines if "VPI" in l)[:3000] or "\n".join(lines[:15]))
    if r.status_code == 200 and len(lines) > 2: break
r = get("https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/ei_bsco_m", params={"format": "JSON", "lang": "en", "geo": "DE", "lastTimePeriod": 1})
j = r.json()
for d in j.get("id", []):
    cat = j["dimension"][d]["category"]; print(d, [(c, cat.get("label", {}).get(c, "")[:60]) for c in cat["index"]][:30])
