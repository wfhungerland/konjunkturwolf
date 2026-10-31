import json, requests
S = requests.Session()
def get(url, **kw):
    r = S.get(url, timeout=120, **kw); print(f"\n### {r.status_code} {r.url}"); return r
# 1. Eurostat TOC: HICP- und Energiepreis-Datensätze
r = get("https://ec.europa.eu/eurostat/api/dissemination/catalogue/toc/txt?lang=en")
for line in r.text.splitlines():
    l = line.lower()
    if ("hicp" in l or "nrg_pc_20" in l) and "dataset" in l:
        print(line[:200])
# 2. Struktur nrg_pc_204/205/202/203 (nur geo=DE)
for ds in ["nrg_pc_204", "nrg_pc_205", "nrg_pc_202", "nrg_pc_203"]:
    r = get(f"https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/{ds}", params={"format": "JSON", "lang": "en", "geo": "DE", "lastTimePeriod": 1})
    try:
        j = r.json()
        for d in j["id"]:
            cats = list(j["dimension"][d]["category"]["index"].keys())
            print(d, len(cats), cats[:25])
    except Exception as e:
        print("ERR", e, r.text[:300])
# 3. prc_hicp_manr: coicop-Codes mit Daten 2026
r = get("https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/prc_hicp_manr", params={"format": "JSON", "lang": "en", "geo": "DE", "unit": "RCH_A", "sinceTimePeriod": "2026-01"})
print(r.text[:600])
# 4. EZB ICP DE: alle ANR-Reihen mit letzter Beobachtung
r = get("https://data-api.ecb.europa.eu/service/data/ICP/M.DE.N..4.ANR", params={"lastNObservations": 1, "format": "csvdata", "detail": "dataonly"})
print("\n".join(r.text.splitlines()[:60]))
r = get("https://data-api.ecb.europa.eu/service/data/ICP/M.U2.N..4.ANR", params={"lastNObservations": 1, "format": "csvdata", "detail": "dataonly", "startPeriod": "2026-01"})
print("\n".join(r.text.splitlines()[:40]))
