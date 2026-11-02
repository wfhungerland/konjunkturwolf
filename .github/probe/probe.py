import re, requests, io
H = {"User-Agent": "Mozilla/5.0 konjunkturwolf-probe", "Accept": "application/vnd.sdmx.genericdata+xml;version=2.1"}
B = "https://api.statistiken.bundesbank.de/rest"
r = requests.get(f"{B}/data/BBDL1?detail=nodata", headers=H, timeout=180)
for blk in re.findall(r"<generic:Series>(.*?)</generic:Series>", r.text, re.S):
    key = ".".join(re.findall(r'<generic:Value id="[^"]+" value="([^"]*)"', blk.split("</generic:SeriesKey>")[0]))
    t = (re.search(r'id="BBK_TITLE" value="([^"]*)"', blk) or [None, ""])[1]
    if re.search(r"stelle|vakan|offen|ausfall|vollzeit|quival", t, re.I) and key.startswith(("M.", "Q.")):
        print("BBDL1", key, "|", t[:170])
# erste/letzte Werte der Kandidaten
for k in ["M.DE.Y.UNE.UBA000.A0000.A01.D00.0.R00.A", "M.DE.Y.LMP.LKA100.A0000.A02.D00.0.ABA.A", "M.DE.Y.UNE.UBA000.A0000.A01.D00.0.ABA.A"]:
    x = requests.get(f"{B}/data/BBDL1/{k}?format=csv&lang=de", headers={"User-Agent": "x"}, timeout=60)
    lines = [l for l in x.text.splitlines() if re.match(r"\d{4}-\d{2}", l)]
    print("SERIES", k, x.status_code, len(lines), lines[:2], lines[-3:])
# Eurostat Vakanzquote
x = requests.get("https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/jvs_q_nace2?geo=DE&format=JSON&lang=EN", timeout=60)
print("JVS", x.status_code, x.text[:200])
try:
    j = x.json(); print("JVS dims", {d: list(j["dimension"][d]["category"]["index"])[:12] for d in j["id"]})
    tt = list(j["dimension"]["time"]["category"]["index"]); print("JVS time", tt[:3], tt[-3:])
except Exception as e: print("JVS ERR", e)
# SVR-Datierung
for u in ["https://www.sachverstaendigenrat-wirtschaft.de/themen/konjunktur-und-wachstum/konjunkturzyklus-datierung.html",
          "https://www.sachverstaendigenrat-wirtschaft.de/en/topics/business-cycles-and-growth/konjunkturzyklus-datierung.html"]:
    try:
        x = requests.get(u, headers={"User-Agent": "Mozilla/5.0"}, timeout=60); print("SVR", u, x.status_code)
        t = " ".join(re.sub(r"<script.*?</script>|<style.*?</style>|<[^>]+>", " ", x.text, flags=re.S).split())
        for m in re.finditer(r".{0,200}(?:Q[1-4]|Quartal|quarter|Hoch|Tief|peak|trough).{0,200}", t): print("  ", m.group(0)[:400])
        print("LINKS", [l for l in re.findall(r'href="([^"]+)"', x.text) if re.search(r"xlsx|pdf|csv", l)][:20])
    except Exception as e: print("SVR ERR", e)
