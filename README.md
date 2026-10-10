# Egypt Energy Transition Tracker: ingestion layer

Pulls Egypt energy data from **EIA**, the **World Bank** and (optionally) **IRENA**, and stores it unchanged in
`raw/`, with a manifest for every run. This is stage 1 of the pipeline; Transformation reads what this writes.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp config/.env.example .env                              # then put your EIA key in .env
python -m ingestion.run --source eia                     # first deliverable: EIA only
python -m ingestion.run --source all                     # everything
```

Free EIA key: <https://www.eia.gov/opendata/register.php>. The World Bank needs no key.
`.env` is git-ignored. Never commit it.

**IRENA** (optional): download the capacity file from IRENA, drop the `.csv` or `.xlsx` into `data/irena/`
and set `irena.dataset_version` in `config/config.yaml` (it is recorded in the manifest). With no file the source is skipped.

**No-install alternative:** `scripts/ingest_all.py` is a single-file runner for EIA and the World Bank
(needs only `pip install requests`; asks for the key when run and writes `raw/` plus `raw_for_claude.zip`).

## Options

```
python -m ingestion.run [--source eia worldbank irena | all] [--ingest-date YYYY-MM-DD] [--config path] [--log-level DEBUG]
```

Exit code `0` = ok, `1` = a source failed, `2` = bad config/arguments. One source failing does not stop the others.

## What you get

```
raw/
├── eia/ingest_date=YYYY-MM-DD/*.json
├── worldbank/ingest_date=YYYY-MM-DD/*.json
├── irena/ingest_date=YYYY-MM-DD/irena_capacity.csv
└── _manifests/ingestion_manifest_<source>_<date>.json
logs/ingestion_YYYY-MM-DD.log
```

Full details, file shapes and guarantees: [`docs/raw_data_contract.md`](docs/raw_data_contract.md).
Synthetic example files for developing downstream steps: [`samples/`](samples/README.md).

## How the code is organised

```
ingestion/
├── base.py        BaseIngestor: run -> fetch (per source) -> save -> manifest, idempotency, pruning
├── eia.py         EIAIngestor        (pagination with offset/length, key kept out of manifests)
├── worldbank.py   WorldBankIngestor  (3 indicators, handles the 200-with-error payload)
├── irena.py       IRENAIngestor      (manual file -> raw, records version and download date)
├── manifest.py    manifest files + latest_manifest() for consumers
├── httpclient.py  timeouts + retry with exponential backoff (429, 5xx, connection errors)
├── config.py      config/config.yaml + environment variables
├── redact.py, logging_setup.py, fsutil.py, run.py (CLI)
```

A new source = a new class with `source`, `file_glob` and `fetch()`; saving, checksums and manifests come from `BaseIngestor`.

## Configuration

`config/config.yaml` has the endpoints, country, indicators, page sizes, retry and timeout settings.
Environment variables override paths and log level (`RAW_ROOT`, `LOGS_DIR`, `LOG_LEVEL`, `IRENA_SOURCE_PATH`) and supply the key (`EIA_API_KEY`).

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

The tests start a local stub of the EIA and World Bank APIs, so they need no network or key. They cover pagination,
retry and give-up behaviour, same-day re-runs, stale-file pruning, the failure manifest, key redaction, and the CLI.

`notebooks/01_explore_sources.ipynb` is for exploring the real endpoints (facets, units) before choosing filters.

## Git workflow

`main` is protected by convention: work on a branch (`feature/eia-ingestor`, `fix/...`), open a PR, merge.
`.env`, `raw/` and `logs/` are in `.gitignore`.

## Known limits

- Developed and tested against a local stub. **Run it once with real access** and check the items in section 7 of the contract (EIA field names, product IDs, units).
- EIA's `productId` values are not hard-coded; the pull is every annual Egypt series on the `international` route unless `eia.facets` narrows it.
- IRENA row counts are informational (header excluded); `.xls` files are copied but not counted.
