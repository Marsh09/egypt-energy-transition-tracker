# Raw Data Contract

Owner: Ingestion (Member 1). Consumers: Transformation (Member 2), Cloud & Orchestration (Member 4).
Version 1.0.

The raw layer holds what the sources sent, **unchanged**, plus a manifest saying where it came from and when.
Nothing downstream may edit these files. If something looks wrong, fix it in Transformation and keep the raw file as evidence.

> Status: EIA and World Bank formats **confirmed against a real run** (2026-10-10: 16,404 EIA rows, 198 World Bank rows).
> IRENA is still unconfirmed. See `eia_series_guide.md` for what is inside the EIA data.

## 1. Layout

```
raw/
├── eia/ingest_date=YYYY-MM-DD/eia_<route>_<country>_<frequency>_p001.json   (p002, p003 ... if more than one page)
├── worldbank/ingest_date=YYYY-MM-DD/worldbank_<INDICATOR>_p001.json
├── irena/ingest_date=YYYY-MM-DD/irena_capacity.<csv|xlsx|xls>
└── _manifests/
    ├── ingestion_manifest_<source>_<YYYY-MM-DD>.json          one per source per day (success)
    └── ingestion_manifest_<source>_<YYYY-MM-DD>_failed.json   only while the last run of that day failed
```

- `ingest_date` is the UTC date of the run. A new day is a new folder; old folders are never deleted by the code.
- Real examples: `eia_international_egy_annual_p001.json`, `worldbank_EG.FEC.RNEW.ZS_p001.json`.
- A copy with synthetic content is in `samples/raw/` (same layout, same manifest format).

## 2. How to find the data to read

Do **not** list folders and guess. Read the newest successful manifest for the source and use its `files[].path`.

```python
from pathlib import Path
from ingestion.manifest import latest_manifest

m = latest_manifest(Path("raw"), "eia")      # None if the source has never succeeded
paths = [Path("raw") / f["path"] for f in m["files"]]
```

If you do not want to import the package: take the highest `ingest_date` among `_manifests/ingestion_manifest_<source>_????-??-??.json`
files (the `_failed` ones do not match that pattern) and check `"status": "success"`.

## 3. Manifest fields

| Field | Meaning |
|---|---|
| `manifest_version` | `"1.0"` |
| `run_id` | Unique id of the run |
| `source` | `eia`, `worldbank` or `irena` |
| `ingest_date` | Partition date (UTC) |
| `started_at_utc`, `finished_at_utc` | Run timestamps |
| `status` | `success` or `failed` |
| `request` | What was asked: URL, parameters, filters. **Never contains the API key** |
| `details` | Source-specific facts (below) |
| `row_count` | Total data rows over all files (`null` if it could not be counted) |
| `files[]` | `path` (relative to `raw/`, forward slashes), `bytes`, `sha256`, `row_count`, `action` (`created`, `overwritten`, `unchanged`) |
| `pruned_files` | Files removed because a same-day re-run produced fewer files |
| `error` | `null` on success, otherwise the message (key redacted) |

`details` by source:

- **eia**: `api_total_rows`, `pages`, `api_version`, `units_seen`, `period_min`, `period_max`
- **worldbank**: `indicators.<id>` with `api_total_rows`, `non_null_values`, `pages`, `year_min`, `year_max`, `source_lastupdated`
- **irena**: `original_filename`, `dataset_version`, `download_date` (and `download_date_is_file_mtime`), `source_file_modified_utc`, plus `encoding_guess` (csv) or `sheets` (xlsx)

`path` is relative to the raw root, so it is also the blob path when `raw/` is uploaded to the `raw` container in ADLS.

## 4. File shapes

### EIA: `eia_*.json`
One file per API page, each the response body as received:

```json
{"response": {"total": "12", "dateFormat": "YYYY", "frequency": "annual", "data": [ {...}, {...} ]},
 "request": {...}, "apiVersion": "2.1.x"}
```

Rows are in `response.data`. Real fields per row (confirmed): `period`, `productId`, `productName`, `activityId`, `activityName`,
`countryRegionId`, `countryRegionName`, `countryRegionTypeId`, `countryRegionTypeName`, `dataFlagId`, `dataFlagDescription`,
`unit`, `unitName`, `value`. One real row:
`{"period":"1973","productId":"53","productName":"Total petroleum and other liquids","activityId":"1","activityName":"Production","unit":"TBPD","unitName":"thousand barrels per day","value":"164.99998...", ...}`

Things Transformation must handle:
- `response.total` and `value` arrive as **strings**. Missing values are the text `NA` (about 400 rows) or `--` (12 rows), not null. Some values are in scientific notation (`9.62E-07`). Parse with a function that turns `NA` and `--` into missing.
- **Units differ between rows, and the same product often appears in several units** (for example Wind generation in BKWH, MTOE, QBTU and TJ). Filter on `unit` before summing anything, or you will double count.
- 16 units are present: BCF, BCM, BDOLPPP, BKWH, MBTUPP, MK, MMTCD, MST, MT, MTOE, QBTU, TBPD, TBTUUSDPP, THP, TJ, TST.
- `dataFlagId` is set on about 8% of rows (estimated/forecast style flags); it is null otherwise. Decide whether to keep it.
- Years run 1973 to 2025; most series cover 1980 to 2024, and 2025 has only 10 rows.
- The pull is deliberately **complete**: 68 products x 13 activities, not only the five energy types in the spec. Choosing which series make up the energy mix is a Transformation decision, see `eia_series_guide.md`.
- Pages are sorted by `period` ascending and together contain every row exactly once (`rows == api_total_rows` is checked before saving).

### World Bank: `worldbank_<INDICATOR>_p001.json`
A JSON array `[meta, rows]`:

```json
[{"page": 1, "pages": 1, "per_page": "1000", "total": 65, "lastupdated": "..."},
 [{"indicator": {"id": "EG.FEC.RNEW.ZS", "value": "..."}, "country": {...}, "countryiso3code": "EGY",
   "date": "2020", "value": 11.2, ...}]]
```

- Newest year first. `date` is a string; `value` is a number or `null`. Every year 1960 to 2025 is listed (66 rows), but only 32 to 35 per indicator have a value. Latest values: renewable % ends in **2021**, access to electricity and energy use per capita end in **2024**.
- Indicators (`config.yaml` → `worldbank.indicators`):

| Indicator | Measures |
|---|---|
| `EG.FEC.RNEW.ZS` | Renewable energy consumption, % of **total final energy consumption** (not a share of electricity or capacity: see the BI note on comparing with the official target) |
| `EG.ELC.ACCS.ZS` | Access to electricity, % of population |
| `EG.USE.PCAP.KG.OE` | Energy use, kg of oil equivalent per capita |

### IRENA: `irena_capacity.<ext>`
The downloaded file copied byte-for-byte; the extension is kept. Columns are whatever IRENA's file has **(confirm after the first download)**.
This source is optional: with no file in `data/irena/` the run reports `skipped`, writes nothing and still exits 0.

## 5. Guarantees

1. **Unmodified**: files are the response bytes (EIA, World Bank) or a byte copy (IRENA). Checksums are in the manifest.
2. **All or nothing per source**: everything is fetched into memory and checked first (row totals match, no API error payload) before any file is written. A failed fetch leaves the previous files alone.
3. **Safe to re-run**: same day, same output paths. Identical content is not rewritten (`action: unchanged`), changed content replaces the file atomically, leftover files from an earlier same-day run are removed, and there is still exactly one manifest per source per day.
4. **No secrets** in files, manifests or logs. The EIA key lives in `EIA_API_KEY` only.
5. **Failure is visible**: a failed run writes a `_failed` manifest and the command exits with code 1. The `_failed` manifest is deleted by the next successful run for that day.

## 6. For Cloud & Orchestration

- Run: `python -m ingestion.run --source all` from the repo root (or `python -m ingestion.run --source eia`). It works from any current directory.
- Exit codes: `0` all requested sources succeeded or were skipped, `1` at least one failed (alert on this), `2` bad configuration or arguments.
- Environment variables: `EIA_API_KEY` (required for EIA), optional `RAW_ROOT`, `LOGS_DIR`, `LOG_LEVEL`, `IRENA_SOURCE_PATH`. Put the key in Key Vault / a container secret, not in the image.
- Upload `raw/` as it is to the `raw` container: blob path = manifest `files[].path`. Upload `_manifests/` too.
- Logs go to stdout and to `logs/ingestion_YYYY-MM-DD.log`.
- Outbound access needed: `api.eia.gov`, `api.worldbank.org`.
- Daily scheduling is safe because of guarantee 3.

## 7. Open items after the first real run

- [x] EIA: real field names, product/activity IDs and units confirmed (`eia_series_guide.md`).
- [x] World Bank: confirmed (66 rows per indicator, 1960 to 2025, about half are null).
- [ ] IRENA: confirm columns and file version string, and set `irena.dataset_version` in `config.yaml`.
- [ ] Replace the synthetic `samples/raw/` with a small slice of the real files (the real EIA pull is 5.5 MB).
