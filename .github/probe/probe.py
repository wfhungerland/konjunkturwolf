import re, requests
H = {"User-Agent": "konjunkturwolf-probe"}
r = requests.get("https://data.nber.org/databases/macrohistory/contents/de.html", headers=H, timeout=60)
print(r.status_code, len(r.text))
links = re.findall(r'href="([^"]+)"', r.text)
print("SAMPLELINKS", links[:15])
t = re.sub(r"<[^>]+>", "\n", r.text)
for line in t.split("\n"):
    line = " ".join(line.split())
    if re.match(r"^[am]\d{5}", line) or "Germany" in line[:60]:
        print("S", line[:170])
# Datei-URL-Muster an einer Reihe testen
for u in [l for l in links if l.endswith(".dat")][:2]:
    u2 = u if u.startswith("http") else "https://data.nber.org/databases/macrohistory/" + u.lstrip("./").replace("../", "")
    rr = requests.get(u2, headers=H, timeout=60); print("DAT", u2, rr.status_code); print(rr.text[:400])
