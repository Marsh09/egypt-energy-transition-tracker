"""A local stand-in for the EIA and World Bank APIs.

Used by the tests and by scripts/generate_samples.py. The payloads follow the documented *shape*
of each API, but all values and product IDs are SYNTHETIC.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

API_KEY = "test-key"

PRODUCTS = [
    ("SYN-1", "Coal"),
    ("SYN-2", "Natural gas"),
    ("SYN-3", "Petroleum and other liquids"),
    ("SYN-4", "Hydroelectricity"),
    ("SYN-5", "Solar and wind"),
]


def eia_row(i: int) -> dict:
    pid, name = PRODUCTS[i % len(PRODUCTS)]
    return {
        "period": str(2015 + i // len(PRODUCTS)),
        "productId": pid,
        "productName": name,
        "activityId": "SYN-A",
        "activityName": "Synthetic activity",
        "countryRegionId": "EGY",
        "countryRegionName": "Egypt",
        "unit": "SYN-UNIT",
        "value": f"{10 + i * 1.5:.1f}",   # EIA sends numbers as strings
    }


def wb_rows(indicator: str, years: list[int]) -> list[dict]:
    return [
        {
            "indicator": {"id": indicator, "value": f"Synthetic {indicator}"},
            "country": {"id": "EG", "value": "Egypt, Arab Rep."},
            "countryiso3code": "EGY",
            "date": str(y),
            "value": None if y == years[-1] else round(10 + (y % 100) * 0.7, 3),
            "unit": "",
            "obs_status": "",
            "decimal": 1,
        }
        for y in reversed(years)   # the World Bank returns newest first
    ]


class FakeAPIs:
    def __init__(self, eia_total: int = 7, wb_years: int = 5, port: int = 0) -> None:
        self.eia_total = eia_total
        self.wb_years = wb_years
        self.requests: list[tuple[str, dict]] = []
        self.fail_next: list[int] = []          # status codes to return before behaving
        self.eia_status_override: int | None = None
        self._server = ThreadingHTTPServer(("127.0.0.1", port), self._handler())
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}"

    def start(self) -> "FakeAPIs":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    def _handler(self):
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # silence
                pass

            def _send(self, status: int, body) -> None:
                payload = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def do_GET(self):
                url = urlparse(self.path)
                query = parse_qs(url.query)
                outer.requests.append((url.path, query))

                if outer.fail_next:
                    return self._send(outer.fail_next.pop(0), {"error": "scripted failure"})

                if url.path.startswith("/eia/v2/international/data"):
                    return self._eia(query)
                if url.path.startswith("/wb/v2/country/EGY/indicator/"):
                    return self._wb(url.path.rsplit("/", 1)[1], query)
                self._send(404, {"error": "not found"})

            def _eia(self, query):
                if query.get("api_key") != [API_KEY]:
                    return self._send(403, {"error": "API_KEY_INVALID"})
                if outer.eia_status_override:
                    return self._send(outer.eia_status_override, {"error": "scripted"})
                offset = int(query.get("offset", ["0"])[0])
                length = min(int(query.get("length", ["5000"])[0]), 5000)
                rows = [eia_row(i) for i in range(outer.eia_total)][offset: offset + length]
                self._send(200, {
                    "response": {
                        "total": str(outer.eia_total),
                        "dateFormat": "YYYY",
                        "frequency": "annual",
                        "data": rows,
                        "description": "synthetic stand-in",
                    },
                    "request": {"command": "/v2/international/data/", "params": {}},
                    "apiVersion": "2.1.0-synthetic",
                })

            def _wb(self, indicator, query):
                if not indicator.startswith("EG."):
                    return self._send(200, [{"message": [{"id": "120", "key": "Invalid value",
                                                          "value": "The provided parameter value is not valid"}]}])
                years = list(range(2020 - outer.wb_years + 1, 2021))
                rows = wb_rows(indicator, years)
                per_page = int(query.get("per_page", ["50"])[0])
                page = int(query.get("page", ["1"])[0])
                pages = -(-len(rows) // per_page)
                meta = {"page": page, "pages": pages, "per_page": str(per_page), "total": len(rows),
                        "sourceid": "2", "lastupdated": "2025-01-28"}
                self._send(200, [meta, rows[(page - 1) * per_page: page * per_page]])

        return Handler
