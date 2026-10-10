import pytest

from ingestion.config import ConfigError, settings_from_dict
from ingestion.redact import redact, register_secret


def base_cfg():
    return {
        "http": {"connect_timeout": 1, "read_timeout": 1, "max_retries": 1, "backoff_factor": 0},
        "eia": {"base_url": "u", "route": "r", "frequency": "annual", "country": "EGY", "page_size": 5000},
        "worldbank": {"base_url": "u", "country": "EGY", "per_page": 100, "indicators": ["A"]},
    }


def test_env_overrides_and_key(tmp_path):
    s = settings_from_dict(
        base_cfg(), project_root=tmp_path,
        env={"EIA_API_KEY": " abc12345 ", "RAW_ROOT": "elsewhere", "LOG_LEVEL": "debug"},
    )
    assert s.eia_api_key == "abc12345"
    assert s.raw_root == tmp_path / "elsewhere"
    assert s.log_level == "DEBUG"


def test_missing_section_and_bad_page_size(tmp_path):
    cfg = base_cfg()
    del cfg["worldbank"]
    with pytest.raises(ConfigError):
        settings_from_dict(cfg, project_root=tmp_path, env={})
    cfg = base_cfg()
    cfg["eia"]["page_size"] = 9000
    with pytest.raises(ConfigError):
        settings_from_dict(cfg, project_root=tmp_path, env={})


def test_redact():
    register_secret("supersecretvalue")
    text = "GET https://api.eia.gov/v2/x/?api_key=abc123&frequency=annual token=supersecretvalue"
    out = redact(text)
    assert "abc123" not in out and "supersecretvalue" not in out and "frequency=annual" in out
    assert redact('{"api_key": "zzz999"}') == '{"api_key": "<redacted>"}'
