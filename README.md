# Egypt Energy Transition Tracker: ingestion

`ingest.py` downloads Egypt energy data from **EIA** and the **World Bank** (and a manual **IRENA** file, optional)
and saves it unchanged in `raw/`, with a small manifest for every run.

## Run it in VS Code

1. Install **Python** (python.org) and **VS Code** with the **Python** extension.
2. In VS Code: **File > Open Folder** and pick this folder.
3. Open the terminal (**Terminal > New Terminal**) and run once: `pip install requests`
4. Create a file called `eia_key.txt` in this folder and paste your free EIA key in it (nothing else).
   Get a key at <https://www.eia.gov/opendata/register.php>. The file is git-ignored.
5. Open `ingest.py` and press the **Run** (play) button at the top right. Or in the terminal: `python ingest.py`

No `eia_key.txt`? The script asks you to paste the key instead.

## What you get

```
raw/
├── eia/ingest_date=YYYY-MM-DD/eia_international_egy_annual_p001.json (p002 ...)
├── worldbank/ingest_date=YYYY-MM-DD/worldbank_<INDICATOR>_p001.json
├── irena/ingest_date=YYYY-MM-DD/irena_capacity.csv      (only if you put a file in irena/)
└── _manifests/ingestion_manifest_<source>_<date>.json
ingestion.log
```

- Files are exactly what the source sent. The manifest has the source, request, time, row count, path and checksum.
- Run it twice on the same day: the day's files are replaced, nothing is duplicated.
- If one source fails, the others still run, the failure is in `ingestion.log`, and the script ends with an error status.
- **IRENA** (optional): download the file from IRENA and put the `.csv` or `.xlsx` in the `irena/` folder.

## Settings

All at the top of `ingest.py`: country, the three World Bank indicators, number of retries, and `EIA_FACETS`
(an optional filter, empty by default, so the pull is complete).

## More

- `docs/raw_data_contract.md`: exact file shapes and rules for whoever reads `raw/` next.
- `docs/eia_series_guide.md`: what is inside the real EIA data and which series make the energy mix.
- `notebooks/01_explore_sources.ipynb`: look around the APIs before choosing filters.
- The earlier, larger version (package, tests, config files) is in the Git history, commit `5f6e84d`.
