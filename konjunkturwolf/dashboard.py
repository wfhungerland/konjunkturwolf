"""Statisches Web-Dashboard (Plotly) für GitHub Pages."""

from __future__ import annotations

import json
import shutil
from importlib import resources
from pathlib import Path

import pandas as pd

from .catalog import SOURCE_LICENSES, Catalog
from .pipeline import RunResult

SITE_URL = "https://wfhungerland.github.io/konjunkturwolf/"
AUTHOR = "Hungerland, Wolf-Fabian"
REFERENCES = [
    "Jordà, Òscar, Moritz Schularick und Alan M. Taylor (2017): Macrofinancial History and the New Business Cycle Facts. "
    "NBER Macroeconomics Annual 2016, Bd. 31, S. 213–263, https://doi.org/10.1086/690241. Daten: JST Macrohistory Database, Release 6, https://www.macrohistory.net/database/.",
    "Müller, Karsten, Chenzi Xu, Mohamed Lehbib und Ziliang Chen (2025): The Global Macro Database. A New International "
    "Macroeconomic Dataset. NBER Working Paper 33714, https://doi.org/10.3386/w33714. Daten: https://www.globalmacrodata.com.",
    "National Bureau of Economic Research: NBER Macrohistory Database, https://www.nber.org/research/data/nber-macrohistory-database.",
    "Fouquin, Michel und Jules Hugot (2016): Two Centuries of Bilateral Trade and Gravity Data: 1827–2014. CEPII Working Paper "
    "2016-14. Daten: TRADHIST, http://www.cepii.fr.",
    "Fremdling, Rainer und Reiner Stäglin (2014): An Input-Output Table for Germany in 1936. A Documentation of Results, Sources "
    "and Research Strategy. Jahrbuch für Wirtschaftsgeschichte / Economic History Yearbook 2014/2. https://doi.org/10.1515/jbwg-2014-0018.",
    "Anderson, James E. und Eric van Wincoop (2003): Gravity with Gravitas. A Solution to the Border Puzzle. American Economic Review 93(1), "
    "S. 170–192, https://doi.org/10.1257/000282803321455214.",
    "Arkolakis, Costas, Arnaud Costinot und Andrés Rodríguez-Clare (2012): New Trade Models, Same Old Gains? American Economic Review 102(1), "
    "S. 94–130, https://doi.org/10.1257/aer.102.1.94.",
    "Disdier, Anne-Célia und Keith Head (2008): The Puzzling Persistence of the Distance Effect on Bilateral Trade. Review of Economics and "
    "Statistics 90(1), S. 37–48, https://doi.org/10.1162/rest.90.1.37.",
    "Fally, Thibault (2015): Structural Gravity and Fixed Effects. Journal of International Economics 97(1), S. 76–85, "
    "https://doi.org/10.1016/j.jinteco.2015.05.005.",
    "Novy, Dennis (2013): Gravity Redux. Measuring International Trade Costs with Panel Data. Economic Inquiry 51(1), S. 101–121, "
    "https://doi.org/10.1111/j.1465-7295.2011.00439.x.",
    "Santos Silva, J. M. C. und Silvana Tenreyro (2006): The Log of Gravity. Review of Economics and Statistics 88(4), S. 641–658, "
    "https://doi.org/10.1162/rest.88.4.641.",
    "Eurostat, Europäische Zentralbank, Deutsche Bundesbank, Statistisches Bundesamt (Destatis): Datenbanken, abgerufen über die "
    "jeweiligen Schnittstellen; Direktlinks je Reihe im Excel-Workbook (Blatt Quellen).",
]


def citation(stand: str) -> str:
    return (f"{AUTHOR} ({stand[:4]}): konjunkturwolf. Wirtschaftsdaten im langen Vergleich. "
            f"Datenstand {stand[:10]}. {SITE_URL}")


FREQ_LABELS = {"D": "täglich", "M": "monatlich", "Q": "vierteljährlich", "S": "halbjährlich", "A": "jährlich"}


def _item(spec, g, st) -> dict:
    item = {
        "id": spec.id, "label": spec.display_label, "title": spec.title, "unit": spec.unit,
        "frequency": FREQ_LABELS.get(spec.frequency, spec.frequency), "adjustment": spec.adjustment,
        "source": spec.source_label, "link": spec.web_link, "style": spec.style, "member": spec.member,
        "status": st.status if st else "failed", "outdated": bool(st.outdated) if st else False,
        "message": (st.message if st else "")[:300], "x": [], "y": [],
    }
    if g is not None and not g.empty:
        g = g.sort_values("date")
        item["x"] = pd.to_datetime(g["date"]).dt.strftime("%Y-%m-%d").tolist()
        item["y"] = [round(float(v), 6) for v in g["value"]]
    return item


MONTHS = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August",
          "September", "Oktober", "November", "Dezember"]
ISO3_TO_2 = {"DEU": "DE", "FRA": "FR", "ITA": "IT", "ESP": "ES", "NLD": "NL", "POL": "PL",
             "GBR": "GB", "USA": "US"}


def _num(v: float) -> str:
    return f"{v:.1f}".replace(".", ",").replace("-", "−")


def _unit(u: str) -> str:
    if u.startswith("Index"):
        return "Punkte"
    return "%" if u.startswith("%") else ("Pp" if u.startswith("Pp") else u)


def _period(date: str, freq: str) -> str:
    y, m = int(date[:4]), int(date[5:7])
    if freq == "vierteljährlich":
        return f"Q{(m - 1) // 3 + 1} {y}"
    if freq == "jährlich":
        return str(y)
    return f"{MONTHS[m - 1]} {y}"


def _quantile(ys: list[float], q: float) -> float:
    v = sorted(ys)
    k = (len(v) - 1) * q
    lo = int(k)
    hi = min(lo + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


def _std(ys: list[float]) -> float:
    m = sum(ys) / len(ys)
    return (sum((v - m) ** 2 for v in ys) / max(len(ys) - 1, 1)) ** 0.5


NUM_WORDS = ["null", "einem", "zwei", "drei", "vier", "fünf", "sechs", "sieben", "acht", "neun", "zehn", "elf", "zwölf"]
QUARTERS = ["ersten", "zweiten", "dritten", "vierten"]


def _n(k: int, dative: bool = True) -> str:
    """Kleine Zahlen als Wort (Dativ: einem), sonst Ziffern."""
    if k == 1 and not dative:
        return "eins"
    return NUM_WORDS[k] if 0 <= k < len(NUM_WORDS) else str(k)


def _years(k: int) -> str:
    return "einem Jahr" if k == 1 else f"{_n(k)} Jahren"


def _when(date: str, freq: str) -> str:
    """Zeitangabe als Satzanfang: Im September 2026, Im dritten Quartal 2026, Im Jahr 2014."""
    y, m = int(date[:4]), int(date[5:7])
    if freq == "vierteljährlich":
        return f"Im {QUARTERS[(m - 1) // 3]} Quartal {y}"
    if freq == "jährlich":
        return f"Im Jahr {y}"
    return f"Im {MONTHS[m - 1]} {y}"


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " und " + items[-1]


def episode_facts(eps: list[dict]) -> list[str]:
    """Krisenvergleich: Tiefpunkt und Erholung je Episode, als vollständige Sätze."""
    out = []
    for e in eps:
        if len(e["y"]) < 2:
            continue
        name = e["label"].split(" (")[0]
        peak = e["label"].split("Hoch ")[-1].rstrip(")") if "Hoch " in e["label"] else ""
        low = min(e["y"]); t_low = e["x"][e["y"].index(low)]
        back = next((x for x, y in zip(e["x"], e["y"]) if x > t_low and y >= 100), None)
        last_x, last_y = e["x"][-1], e["y"][-1]
        if name.lower() == "heute":
            head = f"Seit dem Hoch {peak} ist die Industrieproduktion in DE"
            if low == last_y:
                out.append(f"{head} binnen {_years(last_x)} auf {_num(last_y)} % gefallen, so tief wie noch nie seit dem Hoch.")
            elif back is not None:
                out.append(f"{head} binnen {_years(t_low)} auf {_num(low)} % gefallen und war nach {_years(back)} wieder auf dem Hoch.")
            else:
                out.append(f"{head} binnen {_years(t_low)} auf {_num(low)} % gefallen und liegt nach {_years(last_x)} "
                           f"bei {_num(last_y)} % des Hochs.")
            continue
        head = f"In der {name} fiel die Industrieproduktion vom Hoch {peak} binnen {_years(t_low)} auf {_num(low)} %"
        if back is not None:
            out.append(f"{head} und war nach {_years(back)} wieder auf dem Hoch.")
        else:
            out.append(f"{head}; nach {_years(last_x)} lag sie bei {_num(last_y)} % des Hochs.")
    return out


def panel_facts(catalog: Catalog, sides: dict, extra: list[str] | None = None, say: dict | None = None) -> list[str]:
    """Einordnung aus den Daten als kopierfertige Sätze: aktueller Stand, Lage unter den Vergleichsländern, Geschichte.

    say (aus series.yaml je Panel): subject (z.B. "die Inflation (HVPI)"), short ("die Inflation"), verb ("lag"/"lagen"),
    unit (Einheit im Satz, sonst aus der Reihe), spread (Satz für Abstände zu DE ohne Fokusland).
    """
    say = say or {}
    focus = set(catalog.comparison.get("focus") or [])
    right = [s for s in sides["right"]["series"] if s["y"] and s["member"]]
    left = [s for s in sides["left"]["series"] if s["y"]]
    de = next((s for s in right if s["member"] in focus), None)
    subj = say.get("subject") or sides["right"].get("title", "der Wert")
    short = say.get("short") or subj
    verb = say.get("verb", "lag")
    if de is None:
        # ohne Fokusland (Renditeabstände zu Deutschland): Abstand je Land, absteigend
        if not right:
            return []
        date = max(s["x"][-1] for s in right)
        vals = sorted(((s["y"][-1], s["member"]) for s in right if s["x"][-1] == date), reverse=True)
        u = say.get("unit") or _unit(right[0]["unit"])
        what = say.get("spread", "auf zehnjährige Staatsanleihen")
        def item(v, code, first):
            word = "mehr" if v >= 0 else "weniger"
            return f"{code} {what if first else ''}{' ' if first else ''}{_num(abs(v))} {u} {word}".replace("  ", " ")
        parts = [item(v, c, i == 0) for i, (v, c) in enumerate(vals)]
        return [f"{_when(date, right[0]['frequency'])} zahlte {parts[0]} als DE"
                + (", " + _join(parts[1:]) if len(parts) > 1 else "") + "."]
    u = say.get("unit") or _unit(de["unit"])
    date, value = de["x"][-1], de["y"][-1]
    when = _when(date, de["frequency"])
    peers = {s["member"]: dict(zip(s["x"], s["y"]))[date] for s in right if s is not de and date in s["x"]}
    order = sorted(peers, key=peers.get, reverse=True)
    is_index = de["unit"].startswith("Index") and "=100" in de["unit"].replace(" ", "")
    if is_index:
        base = de["unit"].split()[-1].split("=")[0]
        first = (f"{when} {verb} {subj} in DE bei {_num(value)} ({base} = 100) und damit "
                 f"{_num(abs(value - 100))} % {'unter' if value < 100 else 'über'} {base}")
        rest = [f"{c} {_num(peers[c])}" for c in order]
    else:
        first = f"{when} {verb} {subj} in DE bei {_num(value)} {u}"
        su = _unit(de["unit"])  # Vergleichsländer mit kurzer Einheit, damit der Satz lesbar bleibt
        rest = [f"{c} {_num(peers[c])} {su}" for c in order]
    if rest:
        rest[0] = "in " + rest[0].replace(" ", " bei ", 1)
        first += ("; " if is_index else ", ") + _join(rest)
    facts = [first + "."]
    if peers:
        r = lambda v: round(v, 1)  # wie angezeigt vergleichen, sonst widerspricht der Satz den Zahlen
        n = len(peers)
        higher = [c for c in order if r(peers[c]) > r(value)]
        lower = [c for c in order if r(peers[c]) < r(value)]
        same = [c for c in order if r(peers[c]) == r(value)]
        def cnt(k):
            return "alle" if k == n else ("eines" if k == 1 else _n(k, False))
        bits = []
        if higher:
            bits.append(f"{cnt(len(higher))} höher")
        if lower:
            bits.append(f"{cnt(len(lower))} niedriger")
        if same:
            bits.append(f"{_join(same)} gleichauf")
        if len(higher) == n:
            facts.append(f"Alle {_n(n, False)} Vergleichsländer liegen höher als DE.")
        elif len(lower) == n:
            facts.append(f"Alle {_n(n, False)} Vergleichsländer liegen niedriger als DE.")
        else:
            facts.append(f"Von {_n(n, False)} Vergleichsländern liegen " + _join(bits) + ".")
        missing = [s["member"] for s in right if s is not de and s["member"] not in peers]
        if missing:
            facts.append(f"Für {_join(missing)} liegt noch kein Wert vor.")
    hist = next((s for s in left if s["member"] in focus), None)
    if hist and len(hist["y"]) >= 30 and "no_history" not in (extra or []):
        ys = hist["y"]
        monthly = hist["frequency"] == "monatlich"
        span = f"{hist['x'][0][:4]} bis {hist['x'][-1][:4]}"
        # Gleiche Frequenz vergleichen: Jahreswerte gegen das Mittel der letzten 12 Monate bzw. 4 Quartale
        n = 1 if monthly else {"monatlich": 12, "vierteljährlich": 4}.get(de["frequency"], 1)
        if len(de["y"]) < n:
            n = 1
        cmp_value = sum(de["y"][-n:]) / n
        sides["right"]["hist_value"] = round(cmp_value, 4)
        sides["right"]["hist_label"] = ("12-Monats-Mittel" if n == 12 else "4-Quartals-Mittel" if n == 4
                                        else _period(date, de["frequency"]))
        lead = "Im Mittel der letzten zwölf Monate" if n == 12 else "Im Mittel der letzten vier Quartale" if n == 4 else when
        share = round(100 * sum(v < cmp_value for v in ys) / len(ys))
        unit_word = "Monat" if monthly else "Jahr"
        med = f"Median {_num(_quantile(ys, 0.5))} {u}"
        src = f"; {say['history']}" if say.get("history") else ""
        if share >= 99:
            tail = f"so hoch wie in keinem {unit_word} {span} ({med}{src})"
        elif share <= 1:
            tail = f"so niedrig wie in keinem {unit_word} {span} ({med}{src})"
        else:
            tail = f"höher als in {share} % der {unit_word}e {span} ({med}{src})"
        if n == 1:
            facts.append(f"Das ist {tail}.".replace("Das ist höher", "Das ist mehr"))
        else:
            facts.append(f"{lead} {verb} {short} in DE bei {_num(cmp_value)} {u}, {tail}.")
        if "volatility" in (extra or []):
            cut = f"{int(date[:4]) - 5}{date[4:]}"
            recent = [y for x, y in zip(de["x"], de["y"]) if x > cut]
            win = len(recent)
            if win > 12 and len(ys) > win:
                rolling = [_std(ys[k:k + win]) for k in range(0, len(ys) - win + 1)]
                now_sd = _std(recent)
                pct = round(100 * sum(r < now_sd for r in rolling) / len(rolling))
                cmp = "in jedem Fünfjahresfenster" if pct >= 100 else f"in {pct} % der Fünfjahresfenster"
                facts.append(f"In den letzten fünf Jahren schwankte {short} in DE stärker als {cmp} {span} "
                             f"(Standardabweichung {_num(now_sd)} Pp, Median der Fenster {_num(_quantile(rolling, 0.5))} Pp).")
    return facts


def country_table(catalog: Catalog, side: dict) -> dict | None:
    """Letzte Werte je Land am Stichtag des Fokuslandes (sonst am jüngsten Stichtag), absteigend sortiert."""
    focus = set(catalog.comparison.get("focus") or [])
    ser = [s for s in side.get("series", []) if s.get("y") and s.get("member")]
    if len(ser) < 2 or side.get("kind") == "episodes":
        return None
    de = next((s for s in ser if s["member"] in focus), None)
    date = de["x"][-1] if de else max(s["x"][-1] for s in ser)
    rows = [{"code": s["member"], "label": s["label"], "value": dict(zip(s["x"], s["y"]))[date],
             "focus": s["member"] in focus} for s in ser if date in s["x"]]
    rows.sort(key=lambda r: -r["value"])
    return {"period": _period(date, ser[0]["frequency"]), "unit": _unit(ser[0]["unit"]), "rows": rows,
            "decimals": side.get("decimals") if side.get("decimals") is not None else 1}


def history_band(catalog: Catalog, sides: dict) -> dict | None:
    """Mittlere 50 % und Median der deutschen Jahreswerte (lange Reihe) für die rechte Abbildung."""
    focus = set(catalog.comparison.get("focus") or [])
    hist = next((s for s in sides["left"]["series"] if s["member"] in focus and len(s["y"]) >= 30), None)
    if hist is None:
        return None
    ys = hist["y"]
    return {"p25": round(_quantile(ys, 0.25), 3), "p50": round(_quantile(ys, 0.5), 3),
            "p75": round(_quantile(ys, 0.75), 3), "from": hist["x"][0][:4], "to": hist["x"][-1][:4],
            "values": "Monatswerte" if hist["frequency"] == "monatlich" else "Jahreswerte",
            "p05": round(_quantile(ys, 0.05), 3), "p95": round(_quantile(ys, 0.95), 3),
            "label": hist["label"]}


def extend_long(sides: dict) -> str:
    """Verlängert die langen Jahresreihen mit Jahresmitteln der aktuellen Reihen (gleiches Land).

    Markiert ein unvollständiges letztes Jahr (partial_last) und misst für Deutschland die mittlere
    Abweichung zwischen beiden Quellen in den Jahren, in denen sich beide überschneiden.
    """
    right = {s["member"]: s for s in sides["right"]["series"] if s["member"] and s["y"]}
    first_ext, last_info, overlap = None, "", ""
    for s in sides["left"]["series"]:
        cur = right.get(ISO3_TO_2.get(s["member"] or "", s["member"]))
        if cur is None or not s["y"]:
            continue
        last_year = int(s["x"][-1][:4])
        by_year: dict[int, list[float]] = {}
        for x, y in zip(cur["x"], cur["y"]):
            by_year.setdefault(int(x[:4]), []).append(y)
        per_year = {"monatlich": 12, "vierteljährlich": 4}.get(cur["frequency"], 1)
        # Überschneidung: nur volle Jahre vergleichen
        if s["member"] in ("DEU", "DE"):
            left_by = {int(x[:4]): y for x, y in zip(s["x"], s["y"])}
            common = [yr for yr in by_year if yr in left_by and len(by_year[yr]) >= per_year]
            if len(common) >= 3:
                dev = sum(abs(sum(by_year[yr]) / len(by_year[yr]) - left_by[yr]) for yr in common) / len(common)
                unit = "Pp" if str(s.get("unit", "")).startswith(("%", "Pp")) else "Punkte"
                overlap = (f" Zum Vergleich: In den Jahren {min(common)} bis {max(common)}, die beide Quellen abdecken, "
                           + (f"weichen die Jahresmittel der aktuellen Reihe für Deutschland praktisch nicht von der langen Reihe ab (unter 0,1 {unit})."
                              if dev < 0.05 else
                              f"weicht das Jahresmittel der aktuellen Reihe für Deutschland im Mittel um {_num(dev)} {unit} von der langen Reihe ab."))
        new_years = {yr: v for yr, v in by_year.items() if yr > last_year}
        if not new_years or min(new_years) > last_year + 1:
            continue  # nur lückenlos anschließen
        for year in sorted(new_years):
            s["x"].append(f"{year}-01-01")
            s["y"].append(round(sum(new_years[year]) / len(new_years[year]), 6))
        s["ext_from"] = f"{min(new_years)}-01-01"
        s["ext_source"] = cur.get("source", "")
        if cur.get("license") and cur["license"] not in s.get("license", ""):
            s["license"] = "; ".join(x for x in (s.get("license"), cur["license"]) if x)
        first_ext = min(first_ext or 9999, min(new_years))
        y_last = max(new_years)
        if per_year > 1 and len(new_years[y_last]) < per_year:
            s["partial_last"] = True
            months = sorted(int(x[5:7]) for x in cur["x"] if int(x[:4]) == y_last)
            if cur["frequency"] == "vierteljährlich":
                span = f"Q1 bis Q{(months[-1] - 1) // 3 + 1}" if len(months) > 1 else "nur Q1"
            else:
                span = f"{MONTHS[months[0] - 1]} bis {MONTHS[months[-1] - 1]}" if len(months) > 1 else f"nur {MONTHS[months[0] - 1]}"
            s["partial_label"] = f"Jahresmittel {span}"
            if not last_info or s["member"] in ("DEU", "DE"):
                last_info = (f"; {y_last} nur bis {_period(cur['x'][-1], cur['frequency']).rsplit(' ', 1)[0]} "
                             f"(hohler Punkt)")
    if first_ext is None:
        return ""
    return (f"Ab {first_ext}: Jahresmittel der aktuellen Werte aus der rechten Abbildung, andere Quelle oder Definition, "
            f"Niveausprünge möglich{last_info}.{overlap}")


def episode_items(cfg: dict, items: dict[str, dict]) -> list[dict]:
    """Krisenvergleich: Jahresmittel je Reihe, Hoch im Fenster = 100, x = Jahre nach dem Hoch."""
    out = []
    horizon = int(cfg.get("years") or 8)
    for ep in cfg["episodes"]:
        src = items[ep["series"]]
        by_year: dict[int, list[float]] = {}
        for x, y in zip(src["x"], src["y"]):
            by_year.setdefault(int(x[:4]), []).append(y)
        annual = {yr: sum(v) / len(v) for yr, v in by_year.items()}
        lo, hi = ep["window"]
        cands = {yr: v for yr, v in annual.items() if lo <= yr <= hi}
        item = dict(src, id=f"{src['id']}_{ep['label']}", member=None, unit="Index, Hoch = 100",
                    frequency="jährlich", x=[], y=[])
        if cands:
            peak = max(cands, key=cands.get)
            item["label"] = f"{ep['label']} (Hoch {peak})"
            for yr in range(peak, peak + horizon + 1):
                if yr in annual:
                    item["x"].append(yr - peak)
                    item["y"].append(round(annual[yr] / annual[peak] * 100, 3))
            last = src["x"][-1] if src["x"] else ""
            per_year = {"monatlich": 12, "vierteljährlich": 4}.get(src["frequency"])
            if per_year and last and len(by_year.get(int(last[:4]), [])) < per_year and int(last[:4]) - peak <= horizon:
                item["partial"] = f"{last[:4]} bis {_period(last, src['frequency']).rsplit(' ', 1)[0]}"
                item["partial_last"] = True
        else:
            item["label"] = ep["label"]
        out.append(item)
    return out


def license_for(spec, by_id) -> str:
    """Lizenz einer Reihe; abgeleitete Reihen tragen die Lizenzen ihrer Basisreihen."""
    if spec.source != "derived":
        return SOURCE_LICENSES.get(spec.source, "")
    parts = []
    for key in ("from", "minus", "plus"):
        base = by_id.get(spec.derive.get(key) or "")
        if base is not None:
            lic = license_for(base, by_id)
            if lic and lic not in parts:
                parts.append(lic)
    return "; ".join(parts)


def build_panels(catalog: Catalog, result: RunResult) -> list[dict]:
    """Kernindikatoren: je Panel links der lange Rand, rechts der aktuelle Rand."""
    obs = result.observations
    statuses = result.status_map()
    grouped = {sid: g for sid, g in obs.groupby("series_id")} if not obs.empty else {}
    by_id = catalog.by_id()
    out = []
    for p in catalog.panels:
        if p.get("charts"):
            charts = []
            for c in p["charts"]:
                cfg = c if isinstance(c, dict) else {"chart": c}
                specs = [s for s in catalog.series if s.chart_id == cfg["chart"]]
                base = catalog.chart(cfg["chart"], specs[0] if specs else None)
                charts.append({
                    "id": f"{p['id']}_{cfg['chart']}", "title": cfg.get("title") or base.title, "full": True, "years": None,
                    "y_min": cfg.get("y_min", base.y_min), "y_max": cfg.get("y_max", base.y_max), "kind": base.kind,
                    "decimals": cfg.get("decimals", base.decimals), "note": cfg.get("note", ""),
                    "series": [dict(_item(s, grouped.get(s.id), statuses.get(s.id)), license=license_for(s, by_id),
                                    note=s.note or "") for s in specs]})
            out.append({"id": p["id"], "page": p.get("page", "konjunktur"), "title": p["title"], "question": p.get("question", ""), "text": p.get("text", ""),
                        "facts": list(p.get("facts_text") or []), "charts": charts})
            continue
        sides = {}
        for side in ("left", "right"):
            cfg = p.get(side) or {}
            if cfg.get("episodes"):
                specs = [by_id[e["series"]] for e in cfg["episodes"]]
                base = catalog.chart(f"{p['id']}_{side}")
            elif cfg.get("chart"):
                specs = [s for s in catalog.series if s.chart_id == cfg["chart"]]
                base = catalog.chart(cfg["chart"], specs[0] if specs else None)
            else:
                specs = [by_id[sid] for sid in cfg["series"]]
                base = catalog.chart(f"{p['id']}_{side}")
            if catalog.panel_members:
                specs = [s for s in specs if not s.member or s.member in catalog.panel_members]
            sides[side] = {
                "id": f"{p['id']}_{side}",
                "title": cfg.get("title") or base.title,
                "full": side == "left",
                "years": cfg.get("years") or (None if side == "left" else 5),
                "y_min": cfg.get("y_min", base.y_min), "y_max": cfg.get("y_max", base.y_max),
                "kind": base.kind, "decimals": cfg.get("decimals", base.decimals),
                "note": cfg.get("note", ""),
                "series": [dict(_item(s, grouped.get(s.id), statuses.get(s.id)), license=license_for(s, by_id),
                                note=s.note or "") for s in specs],
            }
            if cfg.get("episodes"):
                items = {s["id"]: s for s in sides[side]["series"]}
                eps = episode_items(cfg, items)
                partial = [f"{e['label'].split(' (')[0]}: {e['partial']}" for e in eps if e.get("partial")]
                sides[side].update(kind="episodes", series=eps, full=True, decimals=0,
                                   note="x-Achse: Jahre nach dem Hoch; Jahresmittel. 1929 beruht auf dem jährlichen NBER-Produktionsindex "
                                     "(Deutsches Reich), heute auf Eurostat (Industrie ohne Bau); Jahresmittel glätten den Tiefpunkt."
                                        + (f" Laufendes Jahr unvollständig ({'; '.join(partial)})." if partial else ""))
        facts = panel_facts(catalog, sides, list(p.get("facts") or []) + ([] if p.get("comparable", True) else ["no_history"]),
                            p.get("say"))
        if sides["left"].get("kind") == "episodes":
            facts = episode_facts(sides["left"]["series"]) + facts
        # comparable: false = lange und aktuelle Reihe messen Verschiedenes (kein Band, keine Verlängerung)
        same = p.get("comparable", True)
        sides["right"]["history"] = history_band(catalog, sides) if same else None
        ext = extend_long(sides) if same else ""
        if ext:
            sides["left"]["note"] = " ".join(x for x in (sides["left"]["note"], ext) if x)
        out.append({"id": p["id"], "page": p.get("page", "konjunktur"), "title": p["title"], "question": p.get("question", ""),
                    "text": p.get("text", ""), "facts": facts, "table": country_table(catalog, sides["right"]), **sides})
    return out


def _load_io() -> dict | None:
    """Abgeleitete Kennzahlen des IO-Vergleichs (data/static/io_compare.json), falls vorhanden."""
    path = Path(__file__).resolve().parent.parent / "data" / "static" / "io_compare.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def build_payload(catalog: Catalog, result: RunResult) -> dict:
    obs = result.observations
    statuses = result.status_map()
    grouped = {sid: g for sid, g in obs.groupby("series_id")} if not obs.empty else {}
    blocks = []
    for block in catalog.blocks:
        charts: dict[str, dict] = {}
        for spec in catalog.series_in_block(block.id):
            chart = catalog.chart(spec.chart_id, spec)
            entry = charts.setdefault(
                chart.id, {"id": chart.id, "title": chart.title, "full": block.history,
                 "y_min": chart.y_min, "y_max": chart.y_max, "kind": chart.kind, "decimals": chart.decimals, "series": []}
            )
            g = grouped.get(spec.id)
            st = statuses.get(spec.id)
            item = {
                "id": spec.id,
                "label": spec.display_label,
                "title": spec.title,
                "unit": spec.unit,
                "frequency": FREQ_LABELS.get(spec.frequency, spec.frequency),
                "adjustment": spec.adjustment,
                "source": spec.source_label,
                "link": spec.web_link,
                "style": spec.style,
                "member": spec.member,
                "status": st.status if st else "failed",
                "outdated": bool(st.outdated) if st else False,
                "message": (st.message if st else "")[:300],
                "x": [],
                "y": [],
            }
            if g is not None and not g.empty:
                g = g.sort_values("date")
                item["x"] = pd.to_datetime(g["date"]).dt.strftime("%Y-%m-%d").tolist()
                item["y"] = [round(float(v), 6) for v in g["value"]]
            entry["series"].append(item)
        blocks.append({"id": block.id, "title": block.title, "charts": list(charts.values())})
    return {
        "generated_at": result.finished_at,
        "counts": result.counts(),
        "comparison": catalog.comparison,
        "panels": build_panels(catalog, result),
        "io": _load_io(),
        "citation": citation(str(result.finished_at)),
        "references": REFERENCES,
        "blocks": blocks,
    }


# Zwei Seiten aus einem Katalog: aktuelle Konjunktur und Außenhandel in langer Frist (Panel-Feld page)
PAGES = {
    "konjunktur": {"file": "index.html", "name": "konjunkturwolf", "title": "konjunkturwolf: Wirtschaftsdaten",
                   "claim": "Deutschlands Wirtschaft heute, verglichen mit früher und mit den europäischen Nachbarn.",
                   "key_panels": ["inflation", "wachstum", "arbeit"]},
    "trade": {"file": "tradewolf.html", "name": "tradewolf", "title": "tradewolf: Außenhandel seit 1827",
              "claim": "Deutschlands Außenhandel seit 1827: wie offen, wie viel er bringt, was er kostet.",
              "key_panels": ["offenheit", "handelsgewinne"]},
}


def build_site(catalog: Catalog, result: RunResult, site_dir: str | Path, xlsx_path: str | Path | None) -> Path:
    site = Path(site_dir)
    site.mkdir(parents=True, exist_ok=True)
    payload = build_payload(catalog, result)
    from .downloads import write_downloads

    pages = []
    for key, cfg in PAGES.items():
        sub = dict(payload)
        sub["panels"] = [pn for pn in payload["panels"] if pn.get("page", "konjunktur") == key]
        if key != "konjunktur":
            sub["io"] = None
        other = [{"name": c["name"], "href": c["file"]} for k, c in PAGES.items() if k != key]
        sub["page"] = {"key": key, "name": cfg["name"], "claim": cfg["claim"], "key_panels": cfg["key_panels"],
                       "title": cfg["title"], "other": other}
        pages.append((cfg["file"], sub))
    for file, sub in pages:
        _write_page(site, file, sub)
    (site / "data.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    (site / ".nojekyll").write_text("", encoding="utf-8")
    plotly_js = resources.files("konjunkturwolf").joinpath("static/plotly.min.js")
    (site / "plotly.min.js").write_bytes(plotly_js.read_bytes())
    if xlsx_path and Path(xlsx_path).exists():
        shutil.copy2(xlsx_path, site / "konjunkturwolf.xlsx")
    return site / "index.html"


def _write_page(site: Path, file: str, payload: dict) -> None:
    """Eine Seite: Downloads je Abbildung (fortlaufend nummeriert) und HTML mit eingebetteten Daten."""
    from .downloads import write_downloads

    number = 0
    for panel in payload["panels"]:
        for sd in (panel["charts"] if panel.get("charts") else [panel["left"], panel["right"]]):
            number += 1
            note = "Quelle: " + ", ".join(dict.fromkeys(s["source"] for s in sd["series"] if s["x"])) + f". {payload['page']['name']}, Stand " + str(payload["generated_at"])[:10]
            try:
                sd["downloads"] = write_downloads(sd, number, site / "downloads", note, payload["citation"])
            except Exception as exc:  # Downloads dürfen die Seite nicht verhindern
                sd["downloads"] = {}
                print(f"Download für {sd['id']} fehlgeschlagen: {exc}")
    data_js = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    template = resources.files("konjunkturwolf").joinpath("templates/dashboard.html").read_text(encoding="utf-8")
    html = template.replace("/*__DATA__*/null", data_js).replace("<title>konjunkturwolf: Wirtschaftsdaten</title>",
                                                                 f"<title>{payload['page']['title']}</title>")
    (site / file).write_text(html, encoding="utf-8")
