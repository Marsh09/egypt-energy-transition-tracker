import json
import logging

import pytest

from ingestion.config import Settings, settings_from_dict
from ingestion.redact import register_secret
from tests.support.fake_apis import API_KEY, FakeAPIs


@pytest.fixture(autouse=True)
def _no_proxy(monkeypatch):
    # the sandbox/CI may route HTTP through a proxy; the fake server is on localhost
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")


@pytest.fixture
def api():
    server = FakeAPIs().start()
    yield server
    server.stop()


@pytest.fixture
def make_settings(tmp_path, api):
    def _make(**overrides) -> Settings:
        cfg = {
            "raw_root": str(tmp_path / "raw"),
            "logs_dir": str(tmp_path / "logs"),
            "http": {"connect_timeout": 2, "read_timeout": 5, "max_retries": 3, "backoff_factor": 0},
            "eia": {
                "base_url": f"{api.base}/eia/v2", "route": "international/data", "frequency": "annual",
                "country": "EGY", "page_size": 3, "facets": {},
            },
            "worldbank": {
                "base_url": f"{api.base}/wb/v2", "country": "EGY", "per_page": 2,
                "indicators": ["EG.FEC.RNEW.ZS", "EG.ELC.ACCS.ZS", "EG.USE.PCAP.KG.OE"],
            },
            "irena": {"enabled": True, "source_path": str(tmp_path / "irena_in"), "dataset_version": "test v1"},
        }
        env = {"EIA_API_KEY": API_KEY}
        for key, value in overrides.items():
            if key == "env":
                env.update(value)
            else:
                cfg[key].update(value) if isinstance(value, dict) else cfg.__setitem__(key, value)
        return settings_from_dict(cfg, project_root=tmp_path, env=env)

    return _make


@pytest.fixture
def irena_file(tmp_path):
    folder = tmp_path / "irena_in"
    folder.mkdir()
    path = folder / "IRENA_Stats_2025.csv"
    path.write_text("Country,Technology,Year,Capacity_MW\nEgypt,Solar,2020,1600\nEgypt,Wind,2020,1400\n", encoding="utf-8")
    return path


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def _clean_logging():
    yield
    root = logging.getLogger()
    for handler in list(root.handlers):
        if isinstance(handler, logging.FileHandler):
            root.removeHandler(handler)
            handler.close()
