import json

import pytest

from ingestion.eia import EIAIngestor
from ingestion.fsutil import sha256_file
from ingestion.manifest import latest_manifest, manifest_path
from tests.conftest import read_json

DATE = "2026-10-09"


def run(settings, **kw):
    return EIAIngestor(settings, ingest_date=DATE, **kw).run()


def test_paginates_and_saves_unchanged_pages(make_settings, api):
    settings = make_settings()           # 7 rows, page_size 3 -> 3 pages
    record = run(settings)

    assert record["status"] == "success"
    assert record["row_count"] == 7
    assert [f["row_count"] for f in record["files"]] == [3, 3, 1]
    assert record["details"]["api_total_rows"] == 7
    assert record["details"]["units_seen"] == ["SYN-UNIT"]
    assert (record["details"]["period_min"], record["details"]["period_max"]) == ("2015", "2016")

    folder = settings.raw_root / "eia" / f"ingest_date={DATE}"
    assert sorted(p.name for p in folder.iterdir()) == [
        "eia_international_egy_annual_p001.json",
        "eia_international_egy_annual_p002.json",
        "eia_international_egy_annual_p003.json",
    ]
    # files are the API response, not a re-serialisation
    body = read_json(folder / "eia_international_egy_annual_p001.json")
    assert body["response"]["total"] == "7" and len(body["response"]["data"]) == 3

    # manifest checksums match the files on disk and paths are relative
    manifest = read_json(manifest_path(settings.raw_root, "eia", DATE))
    for entry in manifest["files"]:
        assert not entry["path"].startswith("/")
        assert sha256_file(settings.raw_root / entry["path"]) == entry["sha256"]


def test_request_filters_sent(make_settings, api):
    run(make_settings())
    path, query = api.requests[0]
    assert path == "/eia/v2/international/data/"
    assert query["facets[countryRegionId][]"] == ["EGY"]
    assert query["frequency"] == ["annual"] and query["data[0]"] == ["value"]
    assert [q["offset"][0] for _, q in api.requests] == ["0", "3", "6"]


def test_rerun_same_day_is_idempotent(make_settings):
    settings = make_settings()
    run(settings)
    folder = settings.raw_root / "eia" / f"ingest_date={DATE}"
    before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in folder.iterdir()}

    second = run(settings)

    assert {f["action"] for f in second["files"]} == {"unchanged"}
    after = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in folder.iterdir()}
    assert after == before                                  # nothing rewritten, nothing added
    assert len(list((settings.raw_root / "_manifests").glob("*.json"))) == 1   # one manifest, not two


def test_rerun_with_fewer_pages_prunes_stale_files(make_settings, api):
    settings = make_settings()
    run(settings)                                           # 3 pages
    api.eia_total = 2                                       # now 1 page
    record = run(settings)

    folder = settings.raw_root / "eia" / f"ingest_date={DATE}"
    assert [p.name for p in folder.iterdir()] == ["eia_international_egy_annual_p001.json"]
    assert len(record["pruned_files"]) == 2


def test_new_day_gets_new_partition(make_settings):
    settings = make_settings()
    EIAIngestor(settings, ingest_date="2026-10-08").run()
    EIAIngestor(settings, ingest_date="2026-10-09").run()
    assert sorted(p.name for p in (settings.raw_root / "eia").iterdir()) == [
        "ingest_date=2026-10-08", "ingest_date=2026-10-09"]
    assert latest_manifest(settings.raw_root, "eia")["ingest_date"] == "2026-10-09"


def test_retries_503_then_succeeds(make_settings, api):
    api.fail_next = [503, 429]
    record = run(make_settings())
    assert record["status"] == "success"
    assert len(api.requests) == 2 + 3                       # 2 failed attempts + 3 pages


def test_gives_up_after_max_retries_and_keeps_old_data(make_settings, api):
    settings = make_settings()
    run(settings)
    api.eia_status_override = 503
    record = run(settings)
    assert record["status"] == "failed"
    # previous good files and manifest untouched; failure recorded separately
    assert latest_manifest(settings.raw_root, "eia")["status"] == "success"
    assert manifest_path(settings.raw_root, "eia", DATE, failed=True).exists()
    assert len(list((settings.raw_root / "eia" / f"ingest_date={DATE}").iterdir())) == 3


def test_failed_manifest_removed_after_successful_rerun(make_settings, api):
    settings = make_settings()
    api.eia_status_override = 500
    assert run(settings)["status"] == "failed"
    api.eia_status_override = None
    assert run(settings)["status"] == "success"
    assert not manifest_path(settings.raw_root, "eia", DATE, failed=True).exists()


def test_missing_key_fails_cleanly(make_settings):
    settings = make_settings(env={"EIA_API_KEY": ""})
    record = run(settings)
    assert record["status"] == "failed" and "EIA_API_KEY" in record["error"]


def test_wrong_key_is_reported_and_never_leaked(make_settings, tmp_path):
    from ingestion.logging_setup import setup_logging

    settings = make_settings(env={"EIA_API_KEY": "wrong-key-123"})
    log_path = setup_logging(settings.logs_dir, "DEBUG")     # the real handlers, at the noisiest level
    record = run(settings)
    assert record["status"] == "failed" and "403" in record["error"]

    texts = [json.dumps(record), log_path.read_text()]
    texts += [m.read_text() for m in (settings.raw_root / "_manifests").glob("*.json")]
    assert "api_key=<redacted>" in texts[1]                  # the failure was logged...
    assert all("wrong-key-123" not in t for t in texts)      # ...without the key


def test_success_manifest_has_no_key(make_settings):
    settings = make_settings()
    run(settings)
    text = manifest_path(settings.raw_root, "eia", DATE).read_text()
    assert "test-key" not in text and "api_key" not in text


def test_zero_rows_is_an_error(make_settings, api):
    api.eia_total = 0
    assert run(make_settings())["status"] == "failed"
