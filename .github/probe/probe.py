import io, requests, pandas as pd
for u in ["https://www.sachverstaendigenrat-wirtschaft.de/fileadmin/dateiablage/jgonline/2021_ThemenseiteKonjunktur/UebersichtRezessionen.xlsx",
          "https://www.sachverstaendigenrat-wirtschaft.de/fileadmin/dateiablage/jgonline/2021_ThemenseiteKonjunktur_EN/BusinessCycleData.xlsx"]:
    r = requests.get(u, headers={"User-Agent": "Mozilla/5.0"}, timeout=60); print("GET", u, r.status_code, len(r.content))
    if r.ok:
        for name, df in pd.read_excel(io.BytesIO(r.content), sheet_name=None, header=None).items():
            print("SHEET", name, df.shape); print(df.dropna(how="all").head(40).to_string())
