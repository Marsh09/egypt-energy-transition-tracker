"""Console + file logging. Everything written is passed through redact()."""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from ingestion.redact import redact


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


def setup_logging(logs_dir: Path, level: str = "INFO") -> Path:
    """Log to stdout and to logs/ingestion_YYYY-MM-DD.log (appended). Returns the log path."""
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / f"ingestion_{datetime.now(timezone.utc):%Y-%m-%d}.log"

    formatter = RedactingFormatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%Y-%m-%dT%H:%M:%S%z")
    root = logging.getLogger()
    root.setLevel(level)
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    root.addHandler(console)

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    # urllib3 at DEBUG prints full request URLs
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    return log_path
