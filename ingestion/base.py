"""BaseIngestor: shared run / save / manifest logic. Each source only implements fetch()."""

from __future__ import annotations

import logging
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from ingestion.config import Settings
from ingestion.fsutil import atomic_write_bytes, sha256_bytes, sha256_file
from ingestion.httpclient import HttpClient, SourceError
from ingestion.manifest import MANIFEST_VERSION, write_manifest
from ingestion.redact import redact

log = logging.getLogger(__name__)


class SkipSource(Exception):
    """The source is intentionally not ingested this run (e.g. optional IRENA file missing)."""


@dataclass
class RawFile:
    """One file to land in the raw layer. `content` is written byte-for-byte as received."""

    name: str
    content: bytes
    row_count: int | None = None


@dataclass
class FetchResult:
    files: list[RawFile]
    request: dict[str, Any]                       # what was asked (never contains secrets)
    details: dict[str, Any] = field(default_factory=dict)  # source-specific facts for the manifest


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class BaseIngestor(ABC):
    source: str                # "eia" | "worldbank" | "irena": first folder under raw/
    file_glob: str = "*"       # which files in the folder this source owns (used to prune stale ones)

    def __init__(
        self,
        settings: Settings,
        http: HttpClient | None = None,
        ingest_date: str | None = None,
        now: Callable[[], datetime] = utc_now,
    ) -> None:
        self.settings = settings
        self.http = http or HttpClient.from_settings(settings.http)
        self._now = now
        self.ingest_date = ingest_date or now().date().isoformat()

    # ---- to implement per source -------------------------------------------------
    @abstractmethod
    def fetch(self) -> FetchResult:
        """Get everything into memory. Must not touch the raw folder."""

    # ---- shared ------------------------------------------------------------------
    @property
    def out_dir(self) -> Path:
        return self.settings.raw_root / self.source / f"ingest_date={self.ingest_date}"

    def run(self) -> dict[str, Any]:
        """Fetch, save, write the manifest. Returns the manifest record; never raises for source errors."""
        started = self._now()
        run_id = uuid.uuid4().hex
        log.info("[%s] ingest started (ingest_date=%s, run_id=%s)", self.source, self.ingest_date, run_id)
        try:
            result = self.fetch()
            if not result.files:
                raise SourceError("fetch returned no files")
            record = self._persist(result, started, run_id)
        except SkipSource as exc:
            log.warning("[%s] skipped: %s", self.source, exc)
            return {"source": self.source, "status": "skipped", "ingest_date": self.ingest_date, "error": str(exc)}
        except Exception as exc:  # one failing source must not stop the others
            log.error("[%s] FAILED: %s", self.source, redact(str(exc)), exc_info=True)
            record = self._base_record(started, run_id)
            record.update(status="failed", error=redact(f"{type(exc).__name__}: {exc}"), files=[], row_count=None)
            try:
                write_manifest(self.settings.raw_root, record)
            except OSError:
                log.error("[%s] could not write failed manifest", self.source, exc_info=True)
            return record

        log.info(
            "[%s] done: %d file(s), %s row(s) -> %s",
            self.source, len(record["files"]), record["row_count"], self.out_dir,
        )
        return record

    def _base_record(self, started: datetime, run_id: str) -> dict[str, Any]:
        return {
            "manifest_version": MANIFEST_VERSION,
            "run_id": run_id,
            "source": self.source,
            "ingest_date": self.ingest_date,
            "started_at_utc": started.isoformat(timespec="seconds"),
        }

    def _persist(self, result: FetchResult, started: datetime, run_id: str) -> dict[str, Any]:
        out_dir = self.out_dir
        out_dir.mkdir(parents=True, exist_ok=True)

        entries = []
        for raw in result.files:
            path = out_dir / raw.name
            checksum = sha256_bytes(raw.content)
            if path.exists() and sha256_file(path) == checksum:
                action = "unchanged"             # same-day re-run with identical data: leave file alone
            else:
                action = "overwritten" if path.exists() else "created"
                atomic_write_bytes(path, raw.content)
            entries.append({
                "path": path.relative_to(self.settings.raw_root).as_posix(),
                "bytes": len(raw.content),
                "sha256": checksum,
                "row_count": raw.row_count,
                "action": action,
            })

        # a same-day re-run that produces fewer files must not leave the old extras behind
        keep = {raw.name for raw in result.files}
        pruned = []
        for stale in sorted(out_dir.glob(self.file_glob)):
            if stale.name not in keep and stale.is_file():
                stale.unlink()
                pruned.append(stale.relative_to(self.settings.raw_root).as_posix())
                log.info("[%s] removed stale file from earlier same-day run: %s", self.source, stale.name)

        counts = [e["row_count"] for e in entries if e["row_count"] is not None]
        record = self._base_record(started, run_id)
        record.update(
            status="success",
            finished_at_utc=self._now().isoformat(timespec="seconds"),
            request=result.request,
            details=result.details,
            row_count=sum(counts) if counts else None,
            files=entries,
            pruned_files=pruned,
            error=None,
        )
        write_manifest(self.settings.raw_root, record)
        return record
