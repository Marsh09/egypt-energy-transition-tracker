# Raw Data Contract

Owner: Ingestion (Member 1). Consumers: Transformation (Member 2), Cloud & Orchestration (Member 4).
Version 1.2 (minimal single-script ingestion).

The raw layer holds what the sources sent, **unchanged**, plus a manifest saying where it came from and when.
Nothing downstream may edit these files. If something looks wrong, fix it in Transformation and keep the raw file as evidence.

> Status: EIA and World Bank formats **confirmed against a real run** (2026-10-10: 16,404 EIA rows, 198 World Bank rows).
> IRENA is still unconfirmed. See `eia_series_guide.md` for what is inside the EIA data.

## 1. Layout

`raw/` is created **next to the project folder**, not inside it (`RAW` in `ingest.py`).

```
raw/
├── eia/ingest_date=YYYY-MM-DD/eia_<route>_<country>_<frequency>_p001.json   (p002, p003 ... if more than one page)
├── worldbank/ingest_date=YYYY-MM-DD/worldbank_<INDICATOR>_p001.json
├── irena/ingest_date=YYYY-MM-DD/irena_capacity.<csv|xlsx|xls>
└── _manifests/
    └── ingestion_manifest_<source>_<YYYY-MM-DD>.json          one per source per day
```

- `ingest_date` is the UTC date of the run. A new day is a new folder; old folders are never deleted by the code.
- Real examples: `eia_international_egy_annual_p001.json`, `worldbank_EG.FEC.RNEW.ZS_p001.json`.

## 2. How to find the data to read

Do **not** guess from folder names. Take the newest manifest for the source (highest date in
`_manifests/ingestion_manifest_<source>_<YYYY-MM-DD>.json`), check `"status": "success"`, and read `files[].path`.

```python
import json
from pathlib import Path

raw = Path("raw")
manifest_file = sorted((raw / "_manifests").glob("ingestion_manifest_eia_*.json"))[-1]
manifest = json.loads(manifest_file.read_text())
paths = [raw / f["path"] for f in manifest["files"]]
```

## 3. Manifest fields

| Field | Meaning |
|---|---|
| `source` | `eia`, `worldbank` or `irena` |
| `ingest_date` | Partition date (UTC) |
| `status` | always `success` |
| `finished_at_utc` | When the source finished |
| `request` | What was asked: URL and parameters. **Never contains the API key** |
| `row_count` | Total data rows over all files (IRENA: `0`, not counted) |
| `files[]` | `path` (relative to `raw/`, forward slashes), `bytes`, `sha256`, `row_count` |

IRENA also has `request.original_filename` (the name of the file you downloaded).

`path` is relative to the raw root, so it is also the blob path if `raw/` is uploaded to a container.

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
- Pages are sorted by `period` ascending and together contain every row exactly once.

### World Bank: `worldbank_<INDICATOR>_p001.json`
A JSON array `[meta, rows]`:

```json
[{"page": 1, "pages": 1, "per_page": "1000", "total": 65, "lastupdated": "..."},
 [{"indicator": {"id": "EG.FEC.RNEW.ZS", "value": "..."}, "country": {...}, "countryiso3code": "EGY",
   "date": "2020", "value": 11.2, ...}]]
```

- Newest year first. `date` is a string; `value` is a number or `null`. Every year 1960 to 2025 is listed (66 rows), but only 32 to 35 per indicator have a value. Latest values: renewable % ends in **2021**, access to electricity and energy use per capita end in **2024**.
- Indicators (`WB_INDICATORS` in `ingest.py`):

| Indicator | Measures |
|---|---|
| `EG.FEC.RNEW.ZS` | Renewable energy consumption, % of **total final energy consumption** (not a share of electricity or capacity: see the BI note on comparing with the official target) |
| `EG.ELC.ACCS.ZS` | Access to electricity, % of population |
| `EG.USE.PCAP.KG.OE` | Energy use, kg of oil equivalent per capita |

### IRENA: `irena_capacity.<ext>`
The downloaded file copied byte-for-byte; the extension is kept. Columns are whatever IRENA's file has **(confirm after the first download)**.
This source is optional: with no file in the `irena/` folder nothing is written.

## 5. Guarantees

1. **Unmodified**: files are the response bytes (EIA, World Bank) or a byte copy (IRENA). Checksums are in the manifest.
2. **No secrets** in files or manifests. The key is read from `eia_key.txt` (git-ignored).
3. **Same-day re-run** overwrites the same file names. If the number of EIA pages ever shrinks, delete that day's folder first, or old extra pages stay behind. (In practice there are 4 pages.)

Not guaranteed (the script is deliberately simple): no retries, no row-total check, no log file. A failed request stops the script with a message. If it stops, run it again. Check `row_count` in the manifest against what you expect (EIA: 16,404 on 2026-10-10).

## 6. For Cloud & Orchestration

- Run: `python ingest.py` from the repo folder. Dependency: `pip install requests`.
- The key is read from `eia_key.txt` next to the script. In a container or VM, write that file from the secret store before starting the job (for example `echo "$SECRET" > eia_key.txt`). Do not bake it into an image.
- A failed request ends the script with an error, so a failed job shows up in the scheduler. A source that fails midway leaves earlier sources saved.
- Upload `raw/` as it is: blob path = manifest `files[].path`. Upload `_manifests/` too.
- Outbound access needed: `api.eia.gov` and `api.worldbank.org`.

## 7. Open items after the first real run

- [x] EIA: real field names, product/activity IDs and units confirmed (`eia_series_guide.md`).
- [x] World Bank: confirmed (66 rows per indicator, 1960 to 2025, about half are null).
- [ ] IRENA: confirm columns and file version string, .
