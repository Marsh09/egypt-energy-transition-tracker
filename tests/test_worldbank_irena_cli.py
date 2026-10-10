import pytest

from ingestion.irena import IRENAIngestor
from ingestion.manifest import latest_manifest
from ingestion.worldbank import WorldBankIngestor
from ingestion import run as cli
from tests.conftest import read_json

DATE = "2026-10-09"


# ---- World Bank ---------------------------------------------------------------
def test_worldbank_three_indicators_with_paging(make_settings):
    settings = make_settings()                      # 5 years, per_page 2 -> 3 pages per indicator
    record = WorldBankIngestor(settings, ingest_date=DATE).run()

    assert record["status"] == "success" and record["row_count"] == 15
    assert len(record["files"]) == 9
    ind = record["details"]["indicators"]["EG.FEC.RNEW.ZS"]
    assert ind["api_total_rows"] == 5 and ind["non_null_values"] == 4
    assert (ind["year_min"], ind["year_max"]) == ("2016", "2020")

    first = read_json(settings.raw_root / "worldbank" / f"ingest_date={DATE}" / "worldbank_EG.FEC.RNEW.ZS_p001.json")
    assert isinstance(first, list) and first[0]["pages"] == 3     # untouched [meta, rows] payload


def test_worldbank_bad_indicator_fails_without_writing(make_settings):
    settings = make_settings(worldbank={"indicators": ["EG.FEC.RNEW.ZS", "NOT.REAL"]})
    record = WorldBankIngestor(settings, ingest_date=DATE).run()
    assert record["status"] == "failed" and "NOT.REAL" in record["error"]
    assert not (settings.raw_root / "worldbank").exists()        # fetch is all-or-nothing


# ---- IRENA --------------------------------------------------------------------
def test_irena_copies_file_unchanged_and_records_version(make_settings, irena_file):
    settings = make_settings()
    record = IRENAIngestor(settings, ingest_date=DATE).run()

    assert record["status"] == "success" and record["row_count"] == 2
    target = settings.raw_root / "irena" / f"ingest_date={DATE}" / "irena_capacity.csv"
    assert target.read_bytes() == irena_file.read_bytes()
    details = record["details"]
    assert details["original_filename"] == "IRENA_Stats_2025.csv"
    assert details["dataset_version"] == "test v1" and details["download_date"]


def test_irena_xlsx_row_count(make_settings, tmp_path):
    from openpyxl import Workbook

    folder = tmp_path / "irena_in"
    folder.mkdir()
    wb = Workbook()
    wb.active.append(["Country", "Technology", "Year", "MW"])
    wb.active.append(["Egypt", "Solar", 2020, 1600])
    wb.save(folder / "stats.xlsx")

    record = IRENAIngestor(make_settings(), ingest_date=DATE).run()
    assert record["status"] == "success" and record["row_count"] == 1
    assert record["files"][0]["path"].endswith("irena_capacity.xlsx")


def test_irena_missing_file_is_skipped_not_failed(make_settings):
    record = IRENAIngestor(make_settings(), ingest_date=DATE).run()
    assert record["status"] == "skipped"


# ---- CLI ----------------------------------------------------------------------
def test_cli_runs_everything_and_exit_code(make_settings, irena_file, tmp_path, monkeypatch, api):
    settings = make_settings()
    monkeypatch.setattr(cli, "load_settings", lambda _path=None: settings)
    monkeypatch.setattr(cli, "setup_logging", lambda *a, **k: tmp_path / "x.log")

    assert cli.main(["--source", "all", "--ingest-date", DATE]) == 0
    for source in ("eia", "worldbank", "irena"):
        assert latest_manifest(settings.raw_root, source)["status"] == "success"

    api.eia_status_override = 500                    # one source failing -> exit 1, others still ran
    assert cli.main(["--source", "all", "--ingest-date", "2026-10-10"]) == 1
    assert latest_manifest(settings.raw_root, "worldbank")["ingest_date"] == "2026-10-10"


def test_cli_rejects_bad_date(capsys):
    assert cli.main(["--ingest-date", "10/09/2026"]) == 2
