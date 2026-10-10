"""EIA Open Data API v2 (international data), Egypt, annual, with pagination.

Each API response page is stored exactly as received: eia_<route>_<country>_<frequency>_p001.json, p002 ...
"""

from __future__ import annotations

import logging
from typing import Any

from ingestion.base import BaseIngestor, FetchResult, RawFile
from ingestion.config import ConfigError
from ingestion.httpclient import SourceError
from ingestion.redact import register_secret

log = logging.getLogger(__name__)

MAX_PAGES = 1000  # safety stop against a runaway loop


class EIAIngestor(BaseIngestor):
    source = "eia"
    file_glob = "eia_*.json"

    def fetch(self) -> FetchResult:
        cfg = self.settings.eia
        key = self.settings.eia_api_key
        if not key:
            raise ConfigError("EIA_API_KEY is not set. Get a free key at https://www.eia.gov/opendata/register.php and put it in .env")
        register_secret(key)

        url = f"{cfg['base_url'].rstrip('/')}/{cfg['route'].strip('/')}/"
        page_size = int(cfg["page_size"])
        country = cfg["country"]

        params: list[tuple[str, Any]] = [
            ("frequency", cfg["frequency"]),
            ("data[0]", "value"),
            ("facets[countryRegionId][]", country),
            ("sort[0][column]", "period"),      # stable order so offset paging is reliable
            ("sort[0][direction]", "asc"),
            ("length", page_size),
        ]
        for facet, values in (cfg.get("facets") or {}).items():
            params += [(f"facets[{facet}][]", v) for v in values]
        for name in ("start", "end"):
            if cfg.get(name):
                params.append((name, cfg[name]))

        route_slug = cfg["route"].strip("/").split("/")[0]
        files: list[RawFile] = []
        units: set[str] = set()
        periods: list[str] = []
        rows_seen = 0
        total: int | None = None
        api_version = None
        offset = 0

        while True:
            if len(files) >= MAX_PAGES:
                raise SourceError(f"stopped after {MAX_PAGES} pages; check the filters")
            # the key is added only to the outgoing request, never to `params` (which goes in the manifest)
            response = self.http.get(url, params=params + [("offset", offset), ("api_key", key)])
            try:
                body = response.json()
            except ValueError:
                raise SourceError(f"EIA returned non-JSON content (offset {offset})") from None

            if not isinstance(body, dict) or "response" not in body:
                raise SourceError(f"EIA returned an unexpected payload (offset {offset}): {str(body)[:300]}")
            page = body["response"]
            data = page.get("data")
            if not isinstance(data, list):
                raise SourceError(f"EIA response has no data list (offset {offset})")
            for warning in page.get("warnings") or []:
                log.warning("[eia] API warning: %s", warning)

            total = int(page.get("total", len(data)))  # EIA sends "total" as a string
            api_version = body.get("apiVersion", api_version)
            if total == 0:
                raise SourceError("EIA returned 0 rows: check the country/route/facets in config.yaml")

            for row in data:
                if row.get("unit"):
                    units.add(row["unit"])
                if row.get("period"):
                    periods.append(str(row["period"]))

            files.append(RawFile(
                name=f"eia_{route_slug}_{country.lower()}_{cfg['frequency']}_p{len(files) + 1:03d}.json",
                content=response.content,   # untouched bytes
                row_count=len(data),
            ))
            rows_seen += len(data)
            log.info("[eia] page %d: %d rows (%d of %d)", len(files), len(data), rows_seen, total)

            if rows_seen >= total:
                break
            if not data:
                raise SourceError(f"EIA returned an empty page at offset {offset} but only {rows_seen} of {total} rows were received")
            offset += len(data)

        if rows_seen != total:
            raise SourceError(f"row count mismatch: received {rows_seen}, API total {total}")

        return FetchResult(
            files=files,
            request={
                "url": url,
                "params": _public_params(params),
                "page_size": page_size,
            },
            details={
                "api_total_rows": total,
                "pages": len(files),
                "api_version": api_version,
                "units_seen": sorted(units),
                "period_min": min(periods) if periods else None,
                "period_max": max(periods) if periods else None,
            },
        )


def _public_params(params: list[tuple[str, Any]]) -> dict[str, Any]:
    """Params as a dict for the manifest (repeated keys become lists). The key is never in `params`."""
    out: dict[str, Any] = {}
    for name, value in params:
        if name in out:
            out[name] = out[name] if isinstance(out[name], list) else [out[name]]
            out[name].append(value)
        else:
            out[name] = value
    return out
