import requests, itertools
r = requests.get("https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/namq_10_gdp",
                 params={"format": "JSON", "lang": "en", "geo": "DE", "na_item": "P31_S14_S15", "sinceTimePeriod": "2025-Q1"}, timeout=120)
j = r.json(); print(r.status_code, j.get("label"))
ids, sizes, dims = j["id"], j["size"], j["dimension"]
codes = {d: list(dims[d]["category"]["index"].keys()) for d in ids}
print({d: codes[d] for d in ids if d != "time"})
strides = []; acc = 1
for s in reversed(sizes): strides.append(acc); acc *= s
strides = strides[::-1]
seen = {}
for k, v in j["value"].items():
    k = int(k); combo = tuple(codes[d][(k // st) % sz] for d, st, sz in zip(ids, strides, sizes) if d not in ("time", "freq", "geo", "na_item"))
    seen[combo] = seen.get(combo, 0) + 1
for c, n in sorted(seen.items()):
    if "CON" in " ".join(c): print(c, n)
