"""Load config/config.yaml plus environment overrides and secrets."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

from ingestion.redact import register_secret

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"


class ConfigError(Exception):
    """Configuration is missing or invalid."""


@dataclass(frozen=True)
class Settings:
    project_root: Path
    raw_root: Path
    logs_dir: Path
    log_level: str
    http: dict[str, Any]
    eia: dict[str, Any]
    worldbank: dict[str, Any]
    irena: dict[str, Any]
    eia_api_key: str | None = None


def _resolve(root: Path, value: str | os.PathLike) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def _section(cfg: Mapping[str, Any], name: str, required: tuple[str, ...]) -> dict[str, Any]:
    section = cfg.get(name)
    if not isinstance(section, dict):
        raise ConfigError(f"config: missing section '{name}'")
    missing = [key for key in required if section.get(key) in (None, "", [])]
    if missing:
        raise ConfigError(f"config: '{name}' is missing {', '.join(missing)}")
    return dict(section)


def settings_from_dict(
    cfg: Mapping[str, Any],
    project_root: Path = PROJECT_ROOT,
    env: Mapping[str, str] | None = None,
) -> Settings:
    env = os.environ if env is None else env

    http = _section(cfg, "http", ("connect_timeout", "read_timeout", "max_retries", "backoff_factor"))
    eia = _section(cfg, "eia", ("base_url", "route", "frequency", "country", "page_size"))
    worldbank = _section(cfg, "worldbank", ("base_url", "country", "per_page", "indicators"))
    irena = dict(cfg.get("irena") or {})

    if not 1 <= int(eia["page_size"]) <= 5000:
        raise ConfigError("config: eia.page_size must be between 1 and 5000 (EIA limit)")
    if not isinstance(worldbank["indicators"], list):
        raise ConfigError("config: worldbank.indicators must be a list")

    if env.get("IRENA_SOURCE_PATH"):
        irena["source_path"] = env["IRENA_SOURCE_PATH"]

    api_key = (env.get("EIA_API_KEY") or "").strip() or None
    register_secret(api_key)

    return Settings(
        project_root=project_root,
        raw_root=_resolve(project_root, env.get("RAW_ROOT") or cfg.get("raw_root") or "raw"),
        logs_dir=_resolve(project_root, env.get("LOGS_DIR") or cfg.get("logs_dir") or "logs"),
        log_level=(env.get("LOG_LEVEL") or cfg.get("log_level") or "INFO").upper(),
        http=http,
        eia=eia,
        worldbank=worldbank,
        irena=irena,
        eia_api_key=api_key,
    )


def load_settings(config_path: str | os.PathLike | None = None) -> Settings:
    """Read the YAML file (and a .env file next to the repo root, if present)."""
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env", override=False)  # real env vars win

    path = Path(config_path or os.environ.get("INGESTION_CONFIG") or DEFAULT_CONFIG_PATH)
    if not path.is_file():
        raise ConfigError(f"config file not found: {path}")
    try:
        cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"config file is not valid YAML: {exc}") from exc
    return settings_from_dict(cfg)
