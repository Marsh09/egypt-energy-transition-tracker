"""Regenerate samples/raw/ : SYNTHETIC files in the exact layout and shape the real run produces.

Runs the real CLI against the local stub in tests/support/fake_apis.py, so the folder names,
file names and manifests are byte-for-byte what `python -m ingestion.run` writes. Transformation
can develop against these before real data exists.

    python scripts/generate_samples.py
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ingestion import run as cli  # noqa: E402
from tests.support.fake_apis import API_KEY, FakeAPIs  # noqa: E402

SAMPLE_DATE = "2000-01-01"   # obviously not a real ingest date
PORT = 8765


def main() -> int:
    out = ROOT / "samples" / "raw"
    shutil.rmtree(out, ignore_errors=True)

    work = Path(tempfile.mkdtemp(prefix="samples_"))
    irena_dir = work / "irena"
    irena_dir.mkdir()
    (irena_dir / "IRENA_synthetic_capacity.csv").write_text(
        "Country,Technology,Year,Capacity_MW\n"
        "Egypt,Solar,2018,1700\nEgypt,Solar,2019,1900\nEgypt,Wind,2018,1400\nEgypt,Wind,2019,1500\n",
        encoding="utf-8",
    )
    config = work / "config.yaml"
    config.write_text(f"""
raw_root: samples/raw
http: {{connect_timeout: 5, read_timeout: 10, max_retries: 1, backoff_factor: 0}}
eia: {{base_url: "http://127.0.0.1:{PORT}/eia/v2", route: international/data, frequency: annual,
      country: EGY, page_size: 5, facets: {{}}}}
worldbank: {{base_url: "http://127.0.0.1:{PORT}/wb/v2", country: EGY, per_page: 1000,
            indicators: [EG.FEC.RNEW.ZS, EG.ELC.ACCS.ZS, EG.USE.PCAP.KG.OE]}}
irena: {{enabled: true, source_path: "{irena_dir}", dataset_version: "synthetic sample", download_date: "{SAMPLE_DATE}"}}
""", encoding="utf-8")

    os.environ.update(EIA_API_KEY=API_KEY, LOGS_DIR=str(work / "logs"), NO_PROXY="127.0.0.1", no_proxy="127.0.0.1")
    api = FakeAPIs(eia_total=12, wb_years=6, port=PORT).start()
    try:
        code = cli.main(["--config", str(config), "--source", "all", "--ingest-date", SAMPLE_DATE])
    finally:
        api.stop()
        shutil.rmtree(work, ignore_errors=True)
    return code


if __name__ == "__main__":
    sys.exit(main())
