"""Ingestion manifests: one JSON file per source per ingest date.

raw/_manifests/ingestion_manifest_<source>_<YYYY-MM-DD>.json         (success)
raw/_manifests/ingestion_manifest_<source>_<YYYY-MM-DD>_failed.json  (failed run, removed once a later run succeeds)

Re-running on the same day overwrites the same file, so there is no pile-up.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ingestion.fsutil import atomic_write_bytes

MANIFEST_DIR = "_manifests"
MANIFEST_VERSION = "1.0"


def manifest_path(raw_root: Path, source: str, ingest_date: str, failed: bool = False) -> Path:
    suffix = "_failed" if failed else ""
    return raw_root / MANIFEST_DIR / f"ingestion_manifest_{source}_{ingest_date}{suffix}.json"


def write_manifest(raw_root: Path, record: dict[str, Any]) -> Path:
    failed = record["status"] == "failed"
    path = manifest_path(raw_root, record["source"], record["ingest_date"], failed=failed)
    payload = json.dumps(record, indent=2, ensure_ascii=False).encode("utf-8") + b"\n"
    atomic_write_bytes(path, payload)
    if not failed:
        stale = manifest_path(raw_root, record["source"], record["ingest_date"], failed=True)
        stale.unlink(missing_ok=True)
    return path


def latest_manifest(raw_root: Path, source: str) -> dict[str, Any] | None:
    """Newest successful manifest for a source (what Transformation should read), or None."""
    pattern = f"ingestion_manifest_{source}_????-??-??.json"  # '?' matches exactly one char: skips *_failed.json
    candidates = sorted((raw_root / MANIFEST_DIR).glob(pattern))
    for path in reversed(candidates):
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("status") == "success":
            return record
    return None
