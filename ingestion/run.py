"""Command line entry point:  python -m ingestion.run --source all

Exit codes: 0 = every requested source succeeded (or was skipped), 1 = at least one failed, 2 = bad config.
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from typing import Sequence

from ingestion.base import BaseIngestor
from ingestion.config import ConfigError, load_settings
from ingestion.eia import EIAIngestor
from ingestion.irena import IRENAIngestor
from ingestion.logging_setup import setup_logging
from ingestion.worldbank import WorldBankIngestor

# order matters: EIA first, because Transformation needs it first
INGESTORS: dict[str, type[BaseIngestor]] = {
    "eia": EIAIngestor,
    "worldbank": WorldBankIngestor,
    "irena": IRENAIngestor,
}

log = logging.getLogger("ingestion.run")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m ingestion.run", description="Ingest sources into the raw layer.")
    parser.add_argument("--source", nargs="+", choices=[*INGESTORS, "all"], default=["all"],
                        help="which sources to ingest (default: all)")
    parser.add_argument("--config", help="path to config.yaml (default: config/config.yaml)")
    parser.add_argument("--ingest-date", help="YYYY-MM-DD partition to write (default: today, UTC)")
    parser.add_argument("--log-level", help="DEBUG, INFO, WARNING (overrides config)")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.ingest_date and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", args.ingest_date):
        print("--ingest-date must look like 2026-10-09", file=sys.stderr)
        return 2

    try:
        settings = load_settings(args.config)
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    log_path = setup_logging(settings.logs_dir, args.log_level or settings.log_level)
    log.info("raw root: %s | log file: %s", settings.raw_root, log_path)

    names = list(INGESTORS) if "all" in args.source else [n for n in INGESTORS if n in args.source]
    results = []
    for name in names:
        ingestor = INGESTORS[name](settings, ingest_date=args.ingest_date)
        results.append(ingestor.run())

    log.info("---- summary ----")
    for rec in results:
        log.info("%-10s %-8s rows=%s files=%s%s", rec["source"], rec["status"], rec.get("row_count"),
                 len(rec.get("files") or []), f"  ({rec['error']})" if rec.get("error") else "")
    return 1 if any(r["status"] == "failed" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
