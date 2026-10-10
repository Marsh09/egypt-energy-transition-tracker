import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import requests

HERE = Path(__file__).parent
RAW = HERE.parent / "raw"
TODAY = datetime.now(timezone.utc).date().isoformat()
EIA_URL = "https://api.eia.gov/v2/international/data/"
WB_URL = "https://api.worldbank.org/v2/country/EGY/indicator/"
INDICATORS = ["EG.FEC.RNEW.ZS", "EG.ELC.ACCS.ZS", "EG.USE.PCAP.KG.OE"]


def get(url, params):
    try:
        r = requests.get(url, params=params, timeout=60)
    except requests.RequestException as e:
        raise SystemExit(f"{url} failed: {type(e).__name__}")
    if r.status_code != 200:
        raise SystemExit(f"{url} answered {r.status_code}")
    return r


class Ingestor:
    source = ""

    def run(self):
        files, request = self.fetch()
        if not files:
            print(self.source, "- nothing to save")
            return
        folder = RAW / self.source / f"ingest_date={TODAY}"
        folder.mkdir(parents=True, exist_ok=True)
        entries = []
        for name, content, rows in files:
            (folder / name).write_bytes(content)
            entries.append({"path": f"{self.source}/ingest_date={TODAY}/{name}", "bytes": len(content),
                            "sha256": hashlib.sha256(content).hexdigest(), "row_count": rows})
        manifest = {"source": self.source, "ingest_date": TODAY, "status": "success",
                    "finished_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "request": request, "row_count": sum(e["row_count"] or 0 for e in entries), "files": entries}
        manifests = RAW / "_manifests"
        manifests.mkdir(parents=True, exist_ok=True)
        (manifests / f"ingestion_manifest_{self.source}_{TODAY}.json").write_text(json.dumps(manifest, indent=2))
        print(self.source, "- saved", len(files), "file(s),", manifest["row_count"], "rows")


class EIAIngestor(Ingestor):
    source = "eia"

    def __init__(self, key):
        self.key = key

    def fetch(self):
        params = {"frequency": "annual", "data[0]": "value", "facets[countryRegionId][]": "EGY",
                  "sort[0][column]": "period", "sort[0][direction]": "asc", "length": 5000}
        files, offset = [], 0
        while True:
            r = get(EIA_URL, {**params, "offset": offset, "api_key": self.key})
            body = r.json()["response"]
            rows = len(body["data"])
            files.append((f"eia_international_egy_annual_p{len(files) + 1:03d}.json", r.content, rows))
            offset += rows
            if rows == 0 or offset >= int(body["total"]):
                break
        return files, {"url": EIA_URL, "params": params}


class WorldBankIngestor(Ingestor):
    source = "worldbank"

    def fetch(self):
        files = []
        for indicator in INDICATORS:
            r = get(WB_URL + indicator, {"format": "json", "per_page": 1000})
            files.append((f"worldbank_{indicator}_p001.json", r.content, len(r.json()[1])))
        return files, {"url": WB_URL, "indicators": INDICATORS}


class IRENAIngestor(Ingestor):
    source = "irena"

    def fetch(self):
        found = [p for p in (HERE / "irena").glob("*.*") if p.suffix.lower() in (".csv", ".xlsx", ".xls")]
        if not found:
            return [], {}
        file = max(found, key=lambda p: p.stat().st_mtime)
        return [(f"irena_capacity{file.suffix.lower()}", file.read_bytes(), None)], {"original_filename": file.name}


if __name__ == "__main__":
    key_file = HERE / "eia_key.txt"
    key = key_file.read_text().strip() if key_file.exists() else input("Paste your EIA API key: ").strip()
    for ingestor in (EIAIngestor(key), WorldBankIngestor(), IRENAIngestor()):
        ingestor.run()
    print("Saved in:", RAW.resolve())
