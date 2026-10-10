"""
Ingestion: EIA + World Bank (+ optional IRENA file) -> raw/

In VS Code: open this folder, press the Run (play) button at the top right. That's it.
Needs:  pip install requests
Key:    put your EIA key in a file called eia_key.txt next to this script (or type it when asked).

Every API response is saved exactly as received. Each run also writes a small manifest
(what was asked, when, row count, file path, checksum) in raw/_manifests/.
Running twice on the same day just replaces that day's files, nothing gets duplicated.
"""

import hashlib
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

# ---------------------------------------------------------------- settings
HERE = Path(__file__).parent
RAW = HERE / "raw"
KEY_FILE = HERE / "eia_key.txt"
IRENA_DIR = HERE / "irena"          # optional: drop the IRENA .csv/.xlsx here

COUNTRY = "EGY"
EIA_URL = "https://api.eia.gov/v2/international/data/"
EIA_PAGE_SIZE = 5000                # the EIA maximum
EIA_FACETS = {}                     # optional filter, e.g. {"activityId": ["2", "12"], "unit": ["QBTU", "BKWH"]}
WB_URL = "https://api.worldbank.org/v2/country/" + COUNTRY + "/indicator/"
WB_INDICATORS = ["EG.FEC.RNEW.ZS", "EG.ELC.ACCS.ZS", "EG.USE.PCAP.KG.OE"]

RETRIES = 5                         # tries per request
WAIT = 2                            # seconds before the 2nd try, doubles after that
TODAY = datetime.now(timezone.utc).date().isoformat()
# ------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler(HERE / "ingestion.log", encoding="utf-8")],
)
log = logging.getLogger("ingest")


def get(url, params, api_key=None):
    """GET with a timeout, retry and backoff. Error messages never include the URL (it holds the key)."""
    if api_key:
        params = params + [("api_key", api_key)]
    for attempt in range(1, RETRIES + 1):
        try:
            r = requests.get(url, params=params, timeout=(10, 60))
        except requests.RequestException as e:
            problem = type(e).__name__
        else:
            if r.status_code == 200:
                return r
            problem = f"HTTP {r.status_code}"
            if r.status_code not in (429, 500, 502, 503, 504):      # not worth retrying
                hint = " - check your API key" if r.status_code in (401, 403) else ""
                raise RuntimeError(problem + hint)
        if attempt == RETRIES:
            raise RuntimeError(f"gave up after {RETRIES} tries ({problem})")
        wait = WAIT * 2 ** (attempt - 1)
        log.warning("%s, trying again in %s s", problem, wait)
        time.sleep(wait)


class Ingestor:
    """Base class. Each source only has to write fetch(). Saving and the manifest are shared."""

    source = ""

    def fetch(self):
        """Return (files, request_info, details). files = [(file name, bytes, row count), ...]"""
        raise NotImplementedError

    def run(self):
        log.info("[%s] starting", self.source)
        try:
            result = self.fetch()
        except Exception as e:
            log.error("[%s] FAILED: %s", self.source, e)
            return "failed"
        if result is None:
            return "skipped"
        files, request_info, details = result

        folder = RAW / self.source / f"ingest_date={TODAY}"
        folder.mkdir(parents=True, exist_ok=True)
        for old in folder.iterdir():             # same-day re-run: start clean, no duplicates
            old.unlink()

        entries = []
        for name, content, rows in files:
            (folder / name).write_bytes(content)  # exactly what the source sent
            entries.append({
                "path": f"{self.source}/ingest_date={TODAY}/{name}",
                "bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
                "row_count": rows,
            })
        manifest = {
            "source": self.source,
            "ingest_date": TODAY,
            "status": "success",
            "finished_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "request": request_info,
            "details": details,
            "row_count": sum(e["row_count"] for e in entries),
            "files": entries,
        }
        manifest_dir = RAW / "_manifests"
        manifest_dir.mkdir(parents=True, exist_ok=True)
        (manifest_dir / f"ingestion_manifest_{self.source}_{TODAY}.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8")
        log.info("[%s] saved %d file(s), %d rows", self.source, len(files), manifest["row_count"])
        return "success"


class EIAIngestor(Ingestor):
    source = "eia"

    def __init__(self, api_key):
        self.api_key = api_key

    def fetch(self):
        params = [
            ("frequency", "annual"),
            ("data[0]", "value"),
            ("facets[countryRegionId][]", COUNTRY),
            ("sort[0][column]", "period"),
            ("sort[0][direction]", "asc"),
            ("length", EIA_PAGE_SIZE),
        ]
        for facet, values in EIA_FACETS.items():
            params += [(f"facets[{facet}][]", v) for v in values]

        files, seen, offset = [], 0, 0
        units, years = set(), []
        while True:
            r = get(EIA_URL, params + [("offset", offset)], self.api_key)
            body = r.json()
            rows = body.get("response", {}).get("data")
            if rows is None:
                raise RuntimeError("EIA answered, but not with data. Check the filters.")
            total = int(body["response"]["total"])           # EIA sends this as text
            if total == 0:
                raise RuntimeError("EIA returned 0 rows. Check the filters.")
            units.update(row["unit"] for row in rows if row.get("unit"))
            years.extend(row["period"] for row in rows)
            files.append((f"eia_international_{COUNTRY.lower()}_annual_p{len(files) + 1:03d}.json", r.content, len(rows)))
            seen += len(rows)
            log.info("[eia] page %d: %d of %d rows", len(files), seen, total)
            if seen >= total:
                break
            if not rows:
                raise RuntimeError("EIA sent an empty page before all rows arrived.")
            offset += len(rows)
        if seen != total:
            raise RuntimeError(f"expected {total} rows but got {seen}")
        details = {"api_total_rows": total, "units_seen": sorted(units),
                   "period_min": min(years), "period_max": max(years)}
        return files, {"url": EIA_URL, "params": [list(p) for p in params]}, details


class WorldBankIngestor(Ingestor):
    source = "worldbank"

    def fetch(self):
        files, details = [], {}
        for indicator in WB_INDICATORS:
            page, pages, seen = 1, 1, 0
            while page <= pages:
                r = get(WB_URL + indicator, [("format", "json"), ("per_page", 1000), ("page", page)])
                body = r.json()
                # a bad indicator comes back as HTTP 200 with a "message" instead of data
                if len(body) < 2 or body[1] is None:
                    raise RuntimeError(f"World Bank has no data for {indicator}: {str(body)[:200]}")
                meta, rows = body
                pages, total = int(meta["pages"]), int(meta["total"])
                files.append((f"worldbank_{indicator}_p{page:03d}.json", r.content, len(rows)))
                seen += len(rows)
                page += 1
            if seen != total:
                raise RuntimeError(f"{indicator}: expected {total} rows but got {seen}")
            details[indicator] = {"api_total_rows": total}
            log.info("[worldbank] %s: %d rows", indicator, total)
        return files, {"url": WB_URL, "indicators": WB_INDICATORS}, {"indicators": details}


class IRENAIngestor(Ingestor):
    source = "irena"

    def fetch(self):
        found = []
        if IRENA_DIR.is_dir():
            found = [p for p in IRENA_DIR.iterdir() if p.suffix.lower() in (".csv", ".xlsx", ".xls")]
        if not found:
            log.warning("[irena] no file in the 'irena' folder, skipping (it is optional)")
            return None
        file = max(found, key=lambda p: p.stat().st_mtime)    # newest file
        modified = datetime.fromtimestamp(file.stat().st_mtime, tz=timezone.utc).date().isoformat()
        rows = None
        if file.suffix.lower() == ".csv":
            lines = [line for line in file.read_text(encoding="utf-8-sig", errors="replace").splitlines() if line.strip()]
            rows = max(len(lines) - 1, 0)                     # without the header (quoted line breaks may add a few)
        content = file.read_bytes()
        details = {"original_filename": file.name, "file_modified_date": modified}
        return [(f"irena_capacity{file.suffix.lower()}", content, rows or 0)], {"source": "manual download"}, details


def get_key():
    if KEY_FILE.exists():
        return KEY_FILE.read_text().strip()
    return input("Paste your EIA API key (or save it in eia_key.txt): ").strip()


def main():
    key = get_key()
    if not key:
        raise SystemExit("No EIA key. Get one free at https://www.eia.gov/opendata/register.php")
    results = {}
    for ingestor in (EIAIngestor(key), WorldBankIngestor(), IRENAIngestor()):
        results[ingestor.source] = ingestor.run()
    print("\nSummary:", ", ".join(f"{name}: {status}" for name, status in results.items()))
    if "failed" in results.values():
        raise SystemExit(1)


if __name__ == "__main__":
    main()
