import inspect, re, requests
S = requests.Session(); S.headers["User-Agent"] = "Mozilla/5.0 konjunkturwolf"
for url in ["https://www.macrohistory.net/database/", "https://www.macrohistory.net/data/"]:
    try:
        r = S.get(url, timeout=60); print("\n###", r.status_code, r.url)
        for href in sorted(set(re.findall(r'href="([^"]+)"', r.text))):
            if any(k in href.lower() for k in ["xlsx", "dta", "csv", "download", "jst"]): print("  ", href)
    except Exception as e: print("ERR", url, e)
try:
    import global_macro_data as g
    print("\n### GMD-Paket", getattr(g, "__version__", "?"), [n for n in dir(g) if not n.startswith("_")])
    from global_macro_data import gmd
    print(inspect.signature(gmd))
    src = inspect.getsource(gmd)
    print("\n".join(l for l in src.splitlines() if "http" in l or "url" in l.lower())[:2000])
    df = gmd(country="DEU")
    print(df.shape); print(list(df.columns)[:40]); print(df.tail(3).iloc[:, :12].to_string())
except Exception as e:
    import traceback; traceback.print_exc()
