import requests
H = {"User-Agent": "konjunkturwolf-probe"}
for sid in ["m13018", "m13015", "m13028a", "m13028c", "m04054", "m04056", "m08028", "a01008ac", "a01008ad", "a01008aa", "m01134b"]:
    u = f"https://data.nber.org/databases/macrohistory/rectdata/{sid[1:3]}/{sid}.dat"
    r = requests.get(u, headers=H, timeout=60)
    print("DAT", sid, r.status_code, len(r.text.splitlines()))
    print("\n".join(r.text.splitlines()[:4])); print("..."); print("\n".join(r.text.splitlines()[-2:]))
