# konjunkturwolf

Python-Pipeline, die offizielle Wirtschaftsdaten aus Destatis GENESIS-Online, Deutscher Bundesbank, EZB Data Portal und Eurostat abruft. Sie bereitet die Daten einheitlich auf und gibt sie aus als

- auditierbares Excel-Workbook [`output/konjunkturwolf.xlsx`](output/konjunkturwolf.xlsx) und
- statisches Web-Dashboard (GitHub Pages).

Gedacht als dauerhaftes Werkzeug für Vermerke und Grafiken. GitHub Actions aktualisiert die Daten wöchentlich.

## Start

```bash
pip install -e ".[dev]"
```

```bash
python -m konjunkturwolf run
```

Der Lauf holt alle Reihen aus [`series.yaml`](series.yaml) und schreibt:

| Pfad | Inhalt |
|---|---|
| `data/processed/observations.csv` | alle Werte im tidy Format: `series_id, date, value, unit, source, retrieved_at` |
| `data/processed/run_status.json` | Lauf-Log je Reihe (Status, Anzahl Werte, letzte Periode, Fehlermeldung) |
| `output/konjunkturwolf.xlsx` | Workbook mit den Blättern Info, Quellen, Daten und je Themenblock ein Wide-Blatt |
| `site/` | Dashboard (`index.html`, `data.json`, Kopie der xlsx); nicht im Repo, wird in Actions gebaut |
| `data/cache/` | Rohantworten der APIs (20 Stunden gültig); nicht im Repo |

Weitere Befehle:

```bash
python -m konjunkturwolf run --only fx_usd ecb_dfr
```

```bash
python -m konjunkturwolf validate
```

```bash
python -m konjunkturwolf build
```

```bash
python -m konjunkturwolf summary
```

`--only` ruft nur einzelne Reihen ab und übernimmt den Rest unverändert. `validate` prüft den Katalog, `build` erzeugt Excel und Dashboard aus den vorhandenen Daten, `summary` zeigt den Status des letzten Laufs als Markdown-Tabelle. Bei `run` schalten `--no-cache` den Cache ab, `--offline` erzwingt den Cache und `--strict` liefert Exit-Code 1, wenn eine Reihe ohne neue Daten bleibt.

Tests:

```bash
pytest -q
```

## Robustheit

- Jeder Abruf läuft mit Retries (429/5xx, exponentielles Backoff) und Datei-Cache.
- Eine kaputte Reihe bricht den Lauf nicht ab. Scheitert der Abruf, bleiben die Werte des letzten erfolgreichen Laufs erhalten (Status `stale`). Gab es noch nie Daten, lautet der Status `failed`.
- Ohne GENESIS-Zugang werden Destatis-Reihen übersprungen (Status `skipped`) und im Lauf-Log gemeldet.
- Das Blatt Info und die Zusammenfassung jedes Actions-Laufs zeigen den Status jeder Reihe.

## Konventionen

- **Datum:** Jede Periode steht für ihren ersten Tag (Q2 2024 = `2024-04-01`, 2. Halbjahr = `07-01`, Jahr = `01-01`).
- **Einheiten:** stehen je Reihe im Katalog und erscheinen in jeder Ausgabe.
- **Werte:** unverändert aus der Quelle. Einzige Ausnahme sind abgeleitete Reihen (`source: derived`), die als eigene Berechnung gekennzeichnet sind.
- **Abrufzeit:** UTC.

## Reihen-Übersicht

Startjahr ist 2000, soweit die Quelle so weit zurückreicht. Die Eurostat-Energiepreise beginnen 2007.

**Konjunktur Deutschland**

| ID | Reihe | Einheit | Freq. | Quelle |
|---|---|---|---|---|
| `de_gdp_qoq` | BIP real, % gg. Vorquartal | % gg. Vorquartal | quartalsw. | Eurostat |
| `de_gdp_yoy` | BIP real, % gg. Vorjahresquartal | % gg. Vorjahresquartal | quartalsw. | Eurostat |
| `de_cpi` | Verbraucherpreisindex (VPI) | Index 2020=100 | monatl. | Destatis GENESIS |
| `de_cpi_yoy` | VPI, % gg. Vorjahresmonat (berechnet) | % gg. Vorjahresmonat | monatl. | eigene Berechnung |
| `de_hicp_yoy` | HVPI, % gg. Vorjahresmonat | % gg. Vorjahresmonat | monatl. | EZB |
| `de_hicp_core_yoy` | HVPI ohne Energie und Nahrungsmittel | % gg. Vorjahresmonat | monatl. | EZB |
| `de_unemp_ilo` | Erwerbslosenquote (ILO-Konzept) | % der Erwerbspersonen | monatl. | Eurostat |
| `de_employment` | Erwerbstätige (Inlandskonzept) | Tsd. Personen | quartalsw. | Eurostat |
| `de_ip` | Produktion in der Industrie (ohne Bau) | Index 2021=100 | monatl. | Eurostat |
| `de_orders` | Auftragseingang Verarbeitendes Gewerbe, real | Index 2021=100 | monatl. | Destatis GENESIS |

**Energie und Preise**

| ID | Reihe | Einheit | Freq. | Quelle |
|---|---|---|---|---|
| `de_elec_hh` | Strompreis Haushalte (2.500-5.000 kWh), inkl. Steuern | EUR/kWh | halbj. | Eurostat |
| `de_gas_hh` | Gaspreis Haushalte (20-200 GJ), inkl. Steuern | EUR/kWh | halbj. | Eurostat |
| `de_elec_nonhh` | Strompreis Nicht-Haushalte (500-2.000 MWh), ohne MwSt. | EUR/kWh | halbj. | Eurostat |
| `de_gas_nonhh` | Gaspreis Nicht-Haushalte (10.000-100.000 GJ), ohne MwSt. | EUR/kWh | halbj. | Eurostat |
| `de_ppi_total` | Erzeugerpreise Industrie (Inlandsabsatz) | Index 2021=100 | monatl. | Eurostat |
| `de_ppi_energy` | Erzeugerpreise Energie (Inlandsabsatz) | Index 2021=100 | monatl. | Eurostat |
| `de_ppi_destatis` | Erzeugerpreisindex gewerblicher Produkte | Index 2021=100 | monatl. | Destatis GENESIS |
| `de_hicp_energy_yoy` | HVPI Energie | % gg. Vorjahresmonat | monatl. | EZB |
| `de_energy_gae` | Bruttoenergieverbrauch | Tsd. t RÖE | jährl. | Eurostat |
| `de_energy_fec` | Endenergieverbrauch (energetisch) | Tsd. t RÖE | jährl. | Eurostat |

**Finanzen und Zinsen**

| ID | Reihe | Einheit | Freq. | Quelle |
|---|---|---|---|---|
| `ecb_dfr` | EZB-Einlagesatz | % p. a. | täglich | EZB |
| `ecb_mro` | EZB-Hauptrefinanzierungssatz (Festsatz) | % p. a. | täglich | EZB |
| `ecb_mlf` | EZB-Spitzenrefinanzierungssatz | % p. a. | täglich | EZB |
| `de_bund10_bbk` | Rendite Bundeswertpapiere, 10 Jahre (Zinsstruktur) | % p. a. | monatl. | Bundesbank |
| `de_bund2_bbk` | Rendite Bundeswertpapiere, 2 Jahre (Zinsstruktur) | % p. a. | monatl. | Bundesbank |
| `de_ltir_ecb` | Langfristiger Zins DE (Konvergenzkriterium) | % p. a. | monatl. | EZB |
| `de_loans_nfc` | Kredite an nichtfinanzielle Unternehmen, Bestand | Mio. EUR | monatl. | EZB |
| `de_loans_hh` | Kredite an private Haushalte, Bestand | Mio. EUR | monatl. | EZB |
| `de_loans_nfc_growth` | Kredite an Unternehmen, Jahreswachstumsrate | % gg. Vorjahresmonat | monatl. | EZB |
| `de_loans_hh_growth` | Kredite an Haushalte, Jahreswachstumsrate | % gg. Vorjahresmonat | monatl. | EZB |
| `fx_usd`, `fx_gbp`, `fx_chf`, `fx_jpy`, `fx_cny` | Wechselkurse je Euro (Monatsdurchschnitt) | Währung je EUR | monatl. | EZB |

**EU-Vergleich** (je Land eine Reihe: DE, FR, IT, ES, NL, PL, EU27)

| ID | Reihe | Einheit | Freq. | Quelle |
|---|---|---|---|---|
| `eu_gdp_yoy_<land>` | BIP real | % gg. Vorjahresquartal | quartalsw. | Eurostat |
| `eu_hicp_<land>` | HVPI-Inflationsrate | % gg. Vorjahresmonat | monatl. | Eurostat |
| `eu_unemp_<land>` | Erwerbslosenquote (ILO) | % der Erwerbspersonen | monatl. | Eurostat |
| `eu_elec_hh_<land>` | Strompreis Haushalte, inkl. Steuern | EUR/kWh | halbj. | Eurostat |
| `eu_elec_nonhh_<land>` | Strompreis Nicht-Haushalte, ohne MwSt. | EUR/kWh | halbj. | Eurostat |

Welche Reihen beim letzten Lauf Daten lieferten, steht im Blatt Info der xlsx und in `data/processed/run_status.json`.

## Reihe ergänzen

Ein Eintrag in `series.yaml` genügt. Beispiel für einen weiteren EZB-Wechselkurs:

```yaml
  - id: fx_sek
    block: finanzen
    source: ecb
    key: EXR/M.SEK.EUR.SP00.A
    title: Wechselkurs Schwedische Krone je Euro (Monatsdurchschnitt)
    unit: SEK je EUR
    frequency: M
    adjustment: nicht bereinigt
    chart: fx_major
    label: SEK
```

Der Schlüssel `key` hängt von der Quelle ab:

| Quelle | `key` | `params` |
|---|---|---|
| `ecb` | `FLOW/SERIENSCHLÜSSEL`, z. B. `EXR/M.USD.EUR.SP00.A` | keine |
| `bundesbank` | `FLOW/SERIENSCHLÜSSEL`, z. B. `BBSIS/M.I.ZST...` | keine |
| `eurostat` | Datensatz-Code, z. B. `une_rt_m` | Dimensionsfilter, z. B. `{geo: DE, s_adj: SA}`; jede mehrwertige Dimension muss festgelegt sein |
| `genesis` | Tabellencode, z. B. `61111-0002` | `value_variable` (Wertmerkmal), optional `filters: {MERKMAL: AUSPRÄGUNG}` und `query` |
| `derived` | entfällt | `derive: {from: <id>, op: yoy_pct}` |

Weitere Felder: `chart` fasst Reihen in einem Diagramm zusammen (Titel unter `charts`), `label` setzt die Legende, `style: step` zeichnet Treppenkurven, `start` setzt den Beginn, `note` erscheint im Blatt Quellen, und `link` überschreibt den automatisch erzeugten Direktlink. Mit `expand: {geo: [DE, FR]}` entsteht je Land eine Reihe; `{geo}` und `{geo_name}` werden ersetzt.

Danach:

```bash
python -m konjunkturwolf validate
```

```bash
python -m konjunkturwolf run --only fx_sek
```

Passt ein Schlüssel nicht, steht die Fehlermeldung der Quelle im Lauf-Log. Bei Eurostat und GENESIS nennt sie die noch nicht festgelegten Dimensionen und ihre verfügbaren Codes. Ein Pull Request, der `series.yaml` ändert, löst den Workflow „Daten aktualisieren“ aus: Er ruft die Daten ab und committet sie auf den PR-Branch.

## GENESIS-Zugang (Destatis)

GENESIS-Online verlangt eine kostenlose Registrierung unter https://www-genesis.destatis.de. Zugangsdaten gehören nie ins Repository.

1. Im Repository: **Settings > Secrets and variables > Actions > New repository secret**.
2. Secret `GENESIS_USER` mit dem Benutzernamen anlegen (alternativ den API-Token).
3. Secret `GENESIS_PASSWORD` mit dem Passwort anlegen (bei Token-Nutzung leer lassen oder ein Leerzeichen eintragen).

Lokal genügen Umgebungsvariablen:

```bash
export GENESIS_USER=...
```

```bash
export GENESIS_PASSWORD=...
```

Fehlen sie, überspringt die Pipeline die Destatis-Reihen und vermerkt das im Lauf-Log. Die Merkmalscodes der GENESIS-Einträge sind ohne Zugang noch nicht geprüft. Beim ersten Lauf mit Secret listet das Lauf-Log bei Abweichungen die verfügbaren Codes.

## GitHub Pages aktivieren

1. **Settings > Pages > Build and deployment > Source: GitHub Actions** wählen.
2. **Actions > Daten aktualisieren > Run workflow** einmal manuell starten.
3. Das Dashboard liegt danach unter `https://wfhungerland.github.io/konjunkturwolf/`. Den Download der xlsx verlinkt es direkt.

## Automatisierung

| Workflow | Auslöser | Aufgabe |
|---|---|---|
| [`update.yml`](.github/workflows/update.yml) | montags 05:17 UTC, manuell, PRs mit Katalog-/Code-Änderungen | Tests, Pipeline, Commit von `data/processed` und `output`, Deployment des Dashboards (nur auf `main`) |
| [`tests.yml`](.github/workflows/tests.yml) | Push auf `main`, jeder PR | Katalog-Validierung und pytest |

Die Zusammenfassung jedes Laufs (Actions > Lauf > Summary) zeigt den Status aller Reihen.

## Aufbau

```
series.yaml                Reihen-Katalog
konjunkturwolf/
  catalog.py               Laden, Expandieren, Validieren des Katalogs
  http.py                  HTTP-Client mit Retries und Cache
  fetchers.py              ein Fetcher je Quelle, abgeleitete Reihen
  parsers.py               SDMX-CSV/-JSON, JSON-stat, GENESIS-ffcsv
  periods.py               Periodenangaben -> Datum
  pipeline.py              Ablauf, tidy Speicherung, Lauf-Log
  excel.py                 Workbook
  dashboard.py, templates/ Web-Dashboard (Plotly)
tests/                     pytest mit Beispielantworten der Quellen
```
