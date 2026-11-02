import re, requests
H = {"User-Agent": "konjunkturwolf-probe", "Accept": "application/vnd.sdmx.genericdata+xml;version=2.1"}
B = "https://api.statistiken.bundesbank.de/rest"
for flow in ["BBDL1", "BBDY1", "BBKRT"]:
    try:
        r = requests.get(f"{B}/data/{flow}?detail=nodata", headers=H, timeout=180)
        print("FLOW", flow, r.status_code, len(r.content), flush=True)
        if not r.ok:
            print(r.text[:300]); continue
        for blk in re.findall(r"<generic:Series>(.*?)</generic:Series>", r.text, re.S):
            key = ".".join(re.findall(r'<generic:Value id="[^"]+" value="([^"]*)"', blk.split("</generic:SeriesKey>")[0]))
            title = re.search(r'id="BBK_TITLE" value="([^"]*)"', blk)
            t = title.group(1) if title else ""
            if re.search(r"rbeitslos|Stellen|Kurzarb|Vakanz|Unterbesch", t):
                print(flow, key, "|", t[:160])
    except Exception as e:
        print("ERR", flow, e)
