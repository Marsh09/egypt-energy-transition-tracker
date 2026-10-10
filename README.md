# Egypt Energy Transition Tracker: ingestion

`ingest.py` downloads Egypt energy data from **EIA** and the **World Bank** (and a manual **IRENA** file, optional)
and saves it unchanged in `raw/`, with a small manifest for every source.

## Run it in VS Code

1. Install **Python** (python.org) and **VS Code** with the **Python** extension.
2. **File > Open Folder** and pick this folder.
3. In the terminal (**Terminal > New Terminal**) run once: `pip install requests`
4. Create a file called `eia_key.txt` in this folder and paste your free EIA key in it (nothing else).
   Get a key at <https://www.eia.gov/opendata/register.php>. The file is git-ignored.
5. Open `ingest.py` and press the **Run** (play) button. Or in the terminal: `python ingest.py`

No `eia_key.txt`? The script asks you to paste the key instead.

## What you get

```
raw/
├── eia/ingest_date=YYYY-MM-DD/eia_international_egy_annual_p001.json (p002 ...)
├── worldbank/ingest_date=YYYY-MM-DD/worldbank_<INDICATOR>_p001.json
├── irena/ingest_date=YYYY-MM-DD/irena_capacity.csv      (only if you put a file in irena/)
└── _manifests/ingestion_manifest_<source>_<date>.json
```

Files are exactly what the source sent. The manifest has the source, request, time, row count, file path and checksum.
Running twice on the same day overwrites that day's files.

This script is deliberately bare: no retries, no logging and almost no error handling. If a request fails it
stops with a short message (for example `... answered 403`, which means check the key). Just run it again.

**IRENA** (optional): download the file from IRENA and put the `.csv` or `.xlsx` in the `irena/` folder.

## More

- `docs/raw_data_contract.md`: exact file shapes and rules for whoever reads `raw/` next.
- `docs/eia_series_guide.md`: what is inside the real EIA data and which series make the energy mix.
- `notebooks/01_explore_sources.ipynb`: look around the APIs.
- Earlier, larger versions (retries, logging, tests, config) are in the Git history: commits `5f6e84d` and `52c9187`.
