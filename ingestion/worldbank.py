"""World Bank Indicators API v2: three indicators for Egypt, no API key needed.

One file per indicator page, exactly as received: worldbank_<indicator>_p001.json
"""

from __future__ import annotations

import logging
from typing import Any

from ingestion.base import BaseIngestor, FetchResult, RawFile
from ingestion.httpclient import SourceError

log = logging.getLogger(__name__)


class WorldBankIngestor(BaseIngestor):
    source = "worldbank"
    file_glob = "worldbank_*.json"

    def fetch(self) -> FetchResult:
        cfg = self.settings.worldbank
        base = cfg["base_url"].rstrip("/")
        country = cfg["country"]
        per_page = int(cfg["per_page"])

        files: list[RawFile] = []
        per_indicator: dict[str, Any] = {}

        for indicator in cfg["indicators"]:
            url = f"{base}/country/{country}/indicator/{indicator}"
            params: dict[str, Any] = {"format": "json", "per_page": per_page}
            if cfg.get("date"):
                params["date"] = cfg["date"]

            page_no, pages, rows_seen, non_null = 1, 1, 0, 0
            total = lastupdated = None
            years: list[str] = []

            while page_no <= pages:
                response = self.http.get(url, params={**params, "page": page_no})
                try:
                    body = response.json()
                except ValueError:
                    raise SourceError(f"World Bank returned non-JSON for {indicator} page {page_no}") from None

                # errors come back as 200 with [{"message": [...]}]
                if not isinstance(body, list) or not body or "message" in body[0]:
                    raise SourceError(f"World Bank error for {indicator}: {str(body)[:300]}")
                if len(body) < 2 or body[1] is None:
                    raise SourceError(f"World Bank returned no data rows for {indicator} (page {page_no})")

                meta, rows = body[0], body[1]
                pages = int(meta.get("pages", 1))
                total = int(meta.get("total", len(rows)))
                lastupdated = meta.get("lastupdated")
                for row in rows:
                    if (row.get("indicator") or {}).get("id") not in (None, indicator):
                        raise SourceError(f"unexpected indicator {row['indicator']['id']} in response for {indicator}")
                    years.append(str(row.get("date")))
                    if row.get("value") is not None:
                        non_null += 1

                files.append(RawFile(
                    name=f"worldbank_{indicator}_p{page_no:03d}.json",
                    content=response.content,
                    row_count=len(rows),
                ))
                rows_seen += len(rows)
                page_no += 1

            if rows_seen != total:
                raise SourceError(f"{indicator}: received {rows_seen} rows, API total {total}")
            per_indicator[indicator] = {
                "api_total_rows": total,
                "non_null_values": non_null,
                "pages": pages,
                "year_min": min(years),
                "year_max": max(years),
                "source_lastupdated": lastupdated,
            }
            log.info("[worldbank] %s: %d rows (%d non-null), %s..%s", indicator, total, non_null, min(years), max(years))

        return FetchResult(
            files=files,
            request={
                "base_url": base,
                "country": country,
                "indicators": list(cfg["indicators"]),
                "per_page": per_page,
                "date": cfg.get("date"),
            },
            details={"indicators": per_indicator},
        )
