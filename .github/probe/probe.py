import requests
S = requests.Session()
def get(url, **kw):
    r = S.get(url, timeout=120, **kw); print(f"\n### {r.status_code} {r.url}"); return r
r = get("https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/prc_hicp_minr", params={"format": "JSON", "lang": "en", "geo": "DE", "lastTimePeriod": 1})
j = r.json()
for d in j["id"]:
    cat = j["dimension"][d]["category"]
    codes = list(cat["index"].keys())
    print(d, len(codes), [(c, cat.get("label", {}).get(c, "")[:40]) for c in codes[:14]])
    if d.startswith("coicop") or d == "coicop":
        for c in codes:
            lab = cat["label"].get(c, "")
            if any(k in lab.lower() for k in ["all-items", "overall", "energy", "excluding", "total"]):
                print("   ", c, "|", lab)
for flt in ["ICP/M.DE.N..4.ANR", "ICP/M.DE...."]:
    r = get(f"https://data-api.ecb.europa.eu/service/data/{flt}", params={"startPeriod": "2026-06", "lastNObservations": 1, "format": "csvdata", "detail": "dataonly"})
    lines = r.text.splitlines()
    print(len(lines)); print("\n".join(lines[:12]))
    print("\n".join(l for l in lines if any(k in l for k in ["000000", "TOTAL", "NRG", "XEF", "_T"]))[:2000])
r = get("https://data-api.ecb.europa.eu/service/dataflow/ECB")
print("\n".join(l.strip()[:160] for l in r.text.splitlines() if "ICP" in l)[:1500])
