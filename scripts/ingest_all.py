"""
Egypt Energy Transition Tracker - one-file ingestion (EIA + World Bank).

How to run (Windows):
    pip install requests
    python ingest_all.py

It asks for your EIA API key (typing is hidden; the key is never saved or logged).
It writes ./raw/ (the unchanged API responses + manifests) and ./raw_for_claude.zip
"""

import getpass
import hashlib
import json
import os
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

try:
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
except ImportError:
    sys.exit("The 'requests' package is missing. Run:  pip install requests   (or: python -m pip install requests)")

# ---- settings ---------------------------------------------------------------
EIA_BASE = os.environ.get("EIA_BASE_URL", "https://api.eia.gov/v2")
WB_BASE = os.environ.get("WB_BASE_URL", "https://api.worldbank.org/v2")
COUNTRY = "EGY"
EIA_ROUTE = "international/data"
EIA_PAGE = 5000
WB_INDICATORS = ["EG.FEC.RNEW.ZS", "EG.ELC.ACCS.ZS", "EG.USE.PCAP.KG.OE"]
RAW = Path(__file__).resolve().parent / "raw"
TODAY = datetime.now(timezone.utc).date().isoformat()
# -----------------------------------------------------------------------------

SECRET = ""


def redact(text):
    text = re.sub(r"(?i)(api[_-]?key=)[^&\s\"']+", r"\1<redacted>", str(text))
    return text.replace(SECRET, "<redacted>") if SECRET else text


def make_session():
    retry = Retry(total=5, connect=5, read=5, status=5, backoff_factor=1.0,
                  status_forcelist=(429, 500, 502, 503, 504), allowed_methods=frozenset({"GET"}),
                  respect_retry_after_header=True, raise_on_status=True)
    s = requests.Session()
    s.headers["User-Agent"] = "egypt-energy-transition-tracker/1.0 (ingestion)"
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.mount("http://", HTTPAdapter(max_retries=retry))
    return s


SESSION = make_session()


def get(url, params):
    try:
        r = SESSION.get(url, params=params, timeout=(10, 60))
    except requests.exceptions.RequestException as e:
        raise RuntimeError(redact(f"request failed: {type(e).__name__}: {e}")) from None
    if r.status_code >= 400:
        hint = " (check your API key)" if r.status_code in (401, 403) else ""
        raise RuntimeError(redact(f"HTTP {r.status_code}{hint}: {r.text[:300]}"))
    return r


def fetch_eia(key):
    url = f"{EIA_BASE.rstrip('/')}/{EIA_ROUTE}/"
    params = [("frequency", "annual"), ("data[0]", "value"), ("facets[countryRegionId][]", COUNTRY),
              ("sort[0][column]", "period"), ("sort[0][direction]", "asc"), ("length", EIA_PAGE)]
    files, rows_seen, total, offset = [], 0, None, 0
    units, periods = set(), []
    while True:
        r = get(url, params + [("offset", offset), ("api_key", key)])
        body = r.json()
        if not isinstance(body, dict) or "response" not in body or not isinstance(body["response"].get("data"), list):
            raise RuntimeError(redact(f"unexpected EIA payload: {str(body)[:300]}"))
        data = body["response"]["data"]
        total = int(body["response"].get("total", len(data)))
        if total == 0:
            raise RuntimeError("EIA returned 0 rows")
        for row in data:
            units.add(row.get("unit"))
            periods.append(str(row.get("period")))
        files.append((f"eia_international_{COUNTRY.lower()}_annual_p{len(files) + 1:03d}.json", r.content, len(data)))
        rows_seen += len(data)
        print(f"  EIA page {len(files)}: {len(data)} rows ({rows_seen} of {total})")
        if rows_seen >= total:
            break
        if not data:
            raise RuntimeError("EIA returned an empty page before all rows were received")
        offset += len(data)
    if rows_seen != total:
        raise RuntimeError(f"row mismatch: got {rows_seen}, API says {total}")
    return files, {"api_total_rows": total, "units_seen": sorted(u for u in units if u),
                   "period_min": min(periods), "period_max": max(periods)}


def fetch_worldbank():
    files, details = [], {}
    for ind in WB_INDICATORS:
        url = f"{WB_BASE.rstrip('/')}/country/{COUNTRY}/indicator/{ind}"
        page, pages, seen, total = 1, 1, 0, 0
        while page <= pages:
            r = get(url, {"format": "json", "per_page": 1000, "page": page})
            body = r.json()
            if not isinstance(body, list) or not body or "message" in body[0] or len(body) < 2 or body[1] is None:
                raise RuntimeError(f"World Bank error for {ind}: {str(body)[:300]}")
            meta, rows = body[0], body[1]
            pages, total = int(meta.get("pages", 1)), int(meta.get("total", len(rows)))
            files.append((f"worldbank_{ind}_p{page:03d}.json", r.content, len(rows)))
            seen += len(rows)
            page += 1
        if seen != total:
            raise RuntimeError(f"{ind}: got {seen} rows, API says {total}")
        details[ind] = {"api_total_rows": total}
        print(f"  World Bank {ind}: {total} rows")
    return files, {"indicators": details}


def save(source, files, details):
    folder = RAW / source / f"ingest_date={TODAY}"
    folder.mkdir(parents=True, exist_ok=True)
    keep = {name for name, _, _ in files}
    for old in folder.glob(f"{source}_*.json"):       # leftovers of an earlier run today
        if old.name not in keep:
            old.unlink()
    entries = []
    for name, content, n in files:
        (folder / name).write_bytes(content)          # exactly what the API sent
        entries.append({"path": f"{source}/ingest_date={TODAY}/{name}", "bytes": len(content),
                        "sha256": hashlib.sha256(content).hexdigest(), "row_count": n})
    manifest = {"manifest_version": "1.0", "source": source, "ingest_date": TODAY, "status": "success",
                "finished_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "row_count": sum(e["row_count"] for e in entries), "details": details, "files": entries}
    mdir = RAW / "_manifests"
    mdir.mkdir(parents=True, exist_ok=True)
    (mdir / f"ingestion_manifest_{source}_{TODAY}.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def main():
    global SECRET
    print("Egypt Energy Transition Tracker - ingestion\n")
    key = (os.environ.get("EIA_API_KEY") or "").strip()
    if not key:
        key = getpass.getpass("Paste your EIA API key and press Enter (nothing will show as you type): ").strip()
    SECRET = key
    if not key:
        sys.exit("No key entered. Get a free one at https://www.eia.gov/opendata/register.php")

    failed = []
    for source, job in (("eia", lambda: fetch_eia(key)), ("worldbank", fetch_worldbank)):
        print(f"\n{source}:")
        try:
            files, details = job()
            save(source, files, details)
            print(f"  OK - {sum(f[2] for f in files)} rows saved")
        except Exception as e:  # keep going so one failure doesn't block the other source
            failed.append(source)
            print(f"  FAILED: {redact(e)}")

    zip_path = RAW.parent / "raw_for_claude.zip"
    if RAW.exists():
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
            for p in sorted(RAW.rglob("*")):
                if p.is_file():
                    z.write(p, p.relative_to(RAW.parent).as_posix())
        print(f"\nCreated: {zip_path}")
        print("Upload that file (raw_for_claude.zip) to the chat.")
    if failed:
        print(f"\nFailed: {', '.join(failed)}. Copy the FAILED lines above and send them to Claude (they do not contain your key).")
        return 1
    print("\nAll done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
