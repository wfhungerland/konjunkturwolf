import json, os, requests
H = {"username": os.environ["GENESIS_USER"], "password": os.environ.get("GENESIS_PASSWORD", "").strip(),
     "Content-Type": "application/x-www-form-urlencoded"}
B = "https://genesis.destatis.de/genesisWS/rest/2020"
for sel in ["61111-00*", "42151-00*", "61241-00*"]:
    r = requests.post(f"{B}/catalogue/tables", data={"selection": sel, "area": "all", "pagelength": "50", "language": "de"}, headers=H, timeout=120)
    print("\n###", sel, r.status_code)
    try:
        j = r.json()
        for t in (j.get("List") or []):
            print(" ", t.get("Code"), "|", (t.get("Content") or "")[:150], "|", t.get("Time"))
        if not j.get("List"): print(json.dumps(j)[:500])
    except Exception:
        print(r.text[:500])
