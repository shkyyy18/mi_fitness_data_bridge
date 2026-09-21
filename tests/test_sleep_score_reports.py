"""Issue #14: synthetic encrypted HTTP, matching and cache regressions only."""
from __future__ import annotations

import asyncio
import base64
import csv
import json
import sqlite3
from datetime import UTC, datetime
from urllib.parse import parse_qs

import httpx
import pytest
import respx

from mi_fitness_mcp import server
from mi_fitness_mcp.adapters import mi_fitness_cloud as cloud
from mi_fitness_mcp.export import export_database
from mi_fitness_mcp.services.query_service import QueryService
from mi_fitness_mcp.services.sync_service import SyncService
from mi_fitness_mcp.storage import Database

# Entirely fictional account, records, key, cookie and health values.
DAY = "2026-01-10"
MIDNIGHT = int(datetime(2026, 1, 10, tzinfo=UTC).timestamp()) - 8 * 3600
START, END = MIDNIGHT - 3600, MIDNIGHT + 7 * 3600
RAW_PATH = "/app/v1/data/get_fitness_data_by_time"
REPORT_PATH = "/app/v1/data/get_aggregated_fitness_data_by_time"
USER = "synthetic-score-user"


def raw(*, start=START, end=END, sid="synthetic-band", **fields):
    return {
        "time": end, "sid": sid, "zone_offset": 28800,
        "value": {"bedtime": start, "wake_up_time": end,
                  "duration": (end - start) // 60, **fields},
    }


def report(*, score=88, sid="synthetic-band", **fields):
    return {
        "key": "sleep", "tag": "daily_report", "time": MIDNIGHT,
        "zone_offset": 28800, "sid": sid,
        "value": {"sleep_score": score, **fields},
    }


def page(records, **fields):
    return {"data_list": records, "has_more": False, **fields}


async def exercise(records, pages, *, region="cn", status=200, max_pages=200, db=None):
    """Use the real signed/encrypted transport, with all HTTP intercepted."""
    adapter = cloud.MiFitnessCloudAdapter(USER, "synthetic-unused-token", region=region)
    adapter._ssecurity = b"synthetic-session-key"
    adapter._cookies = "serviceToken=synthetic-cookie"
    adapter._connected = True
    adapter.request_retries = 1
    adapter.max_pages = max_pages
    base = "https://hlth.io.mi.com" if region == "cn" else f"https://{region}.hlth.io.mi.com"
    requests = []

    def reply(request):
        form = parse_qs(request.content.decode("utf-8"))
        signed = cloud._gen_signed_nonce(adapter._ssecurity, base64.b64decode(form["_nonce"][0]))
        payload = json.loads(cloud._rc4_crypt(signed, base64.b64decode(form["data"][0])))
        assert "relative_uid" not in payload
        assert "passToken" not in payload
        if request.url.path == RAW_PATH:
            assert payload["key"] == "sleep"
            body = {"code": 0, "result": page(records)}
        else:
            assert payload["key"] == "sleep" and payload["tag"] == "daily_report"
            assert payload["limit"] == 100
            requests.append(payload)
            if status != 200:
                return httpx.Response(status, text="synthetic-upstream-secret")
            result = pages[min(len(requests) - 1, len(pages) - 1)]
            body = {"code": 0, "result": result}
        ciphertext = cloud._rc4_crypt(signed, json.dumps(body).encode("utf-8"))
        return httpx.Response(200, text=base64.b64encode(ciphertext).decode("ascii"))

    with respx.mock(assert_all_called=False) as router:
        router.post(base + RAW_PATH).mock(side_effect=reply)
        router.post(base + REPORT_PATH).mock(side_effect=reply)
        async with httpx.AsyncClient(trust_env=False) as client:
            adapter._client = client
            if db:
                result = await SyncService(adapter, db).sync_data_type("sleep", DAY, DAY)
            else:
                result = [s async for s in adapter.iter_sleep_sessions(DAY, DAY)]
    return result, requests


@pytest.mark.parametrize("region", ["cn", "de", "us"])
def test_own_account_aggregate_score_through_encrypted_transport(region):
    sessions, requests = asyncio.run(exercise([raw()], [page([report()])], region=region))
    assert sessions[0].sleep_score == 88
    assert sessions[0].sleep_score_source == "daily_report"
    # Wake-date padding covers region timezone and chunk boundaries.
    adapter = cloud.MiFitnessCloudAdapter(USER, "synthetic", region=region)
    start, end = adapter._date_range_to_timestamps("2026-01-09", "2026-01-11")
    assert requests == [{"key": "sleep", "tag": "daily_report", "limit": 100,
                         "start_time": start, "end_time": end}]


def test_pagination_and_json_encoded_value():
    row = report()
    row["value"] = json.dumps(row["value"])
    sessions, requests = asyncio.run(exercise([raw()], [
        page([], has_more=True, next_key="synthetic-page-2"), page([row]),
    ]))
    assert sessions[0].sleep_score == 88
    assert requests[1]["next_key"] == "synthetic-page-2"


@pytest.mark.parametrize("pages,max_pages", [
    ([page([report()], has_more=True)], 200),
    ([page([report()], has_more=True, next_key="loop")], 200),
    ([page([report()], has_more=True, next_key="more")], 1),
    ([{}], 200), ([{"data_list": "invalid"}], 200), ([None], 200),
])
def test_bad_or_incomplete_pages_do_not_apply_partial_scores(pages, max_pages, caplog):
    sessions, _ = asyncio.run(exercise([raw()], pages, max_pages=max_pages))
    assert len(sessions) == 1 and sessions[0].sleep_score is None
    assert "daily score lookup unavailable" in caplog.text


@pytest.mark.parametrize("status", [401, 403, 404, 429, 500])
def test_optional_endpoint_failure_preserves_sleep_and_redacts_errors(status, caplog):
    sessions, _ = asyncio.run(exercise([raw()], [], status=status))
    assert len(sessions) == 1 and sessions[0].sleep_score is None
    assert "daily score lookup unavailable" in caplog.text
    assert "synthetic-upstream-secret" not in caplog.text
    assert "synthetic-band" not in caplog.text
    assert "synthetic-cookie" not in caplog.text


@pytest.mark.parametrize("records", [[], [raw(score=81)], [raw(is_nap=True)]])
def test_no_optional_request_without_missing_main_score(records):
    sessions, requests = asyncio.run(exercise(records, []))
    assert requests == []
    if records and not records[0]["value"].get("is_nap"):
        assert sessions[0].sleep_score == 81
        assert sessions[0].sleep_score_source == "sleep_record"


def test_invalid_optional_score_does_not_drop_sleep_and_uses_report():
    sessions, _ = asyncio.run(exercise([raw(score="invalid")], [page([report()])]))
    assert len(sessions) == 1 and sessions[0].sleep_score == 88


def test_raw_score_has_priority_when_other_session_needs_report():
    records = [raw(score=81), raw(start=END + 1800, end=END + 3600)]
    sessions, _ = asyncio.run(exercise(records, [page([report()])]))
    assert [s.sleep_score for s in sessions] == [81, None]
    assert sessions[0].sleep_score_source == "sleep_record"


def test_main_only_not_nap_or_shorter_session():
    records = [raw(), raw(start=END + 1800, end=END + 3600, is_nap=True),
               raw(start=END + 7200, end=END + 10800)]
    sessions, _ = asyncio.run(exercise(records, [page([report()])]))
    assert [s.sleep_score for s in sessions] == [88, None, None]


def test_false_string_is_not_a_nap():
    sessions, _ = asyncio.run(exercise([raw(is_nap="false")], [page([report()])]))
    assert not sessions[0].is_nap and sessions[0].sleep_score == 88


@pytest.mark.parametrize("change", [
    {"sid": "different-synthetic-band"}, {"time": MIDNIGHT + 86400},
    {"key": "steps"}, {"tag": "weekly_report"}, {"time": 0},
    {"zone_offset": "invalid"}, {"value": []},
    {"value": {"sleep_score": 0}}, {"value": {"sleep_score": 101}},
    {"value": {"sleep_score": True}}, {"value": {"sleep_score": "nan"}},
    {"value": {"sleep_score": 88, "segment_details": "invalid"}},
    {"value": {"sleep_score": 88, "segment_details": [None]}},
])
def test_unusable_or_unrelated_report_stays_null(change):
    row = report()
    row.update(change)
    sessions, _ = asyncio.run(exercise([raw()], [page([row])]))
    assert sessions[0].sleep_score is None


def test_report_default_timezone_is_configured_region():
    row = report()
    del row["zone_offset"]
    sessions, _ = asyncio.run(exercise([raw()], [page([row])]))
    assert sessions[0].sleep_score == 88


def test_conflicting_reports_do_not_choose_arbitrary_score():
    sessions, _ = asyncio.run(exercise([raw()], [page([report(score=82), report(score=88)])]))
    assert sessions[0].sleep_score is None


def test_identical_reports_are_not_ambiguous_and_bad_records_are_isolated():
    sessions, _ = asyncio.run(exercise([raw()], [page([None, {}, report(), report()])]))
    assert sessions[0].sleep_score == 88


def test_account_level_report_does_not_choose_between_devices():
    records = [raw(), raw(sid="second-synthetic-band", start=START + 60)]
    sessions, _ = asyncio.run(exercise(records, [page([report(sid="default")])]))
    assert all(s.sleep_score is None for s in sessions)


def test_explicit_device_report_does_not_score_other_device():
    sessions, _ = asyncio.run(exercise([raw(), raw(sid="other-band")], [page([report()])]))
    assert [s.sleep_score for s in sessions] == [88, None]


def test_equal_length_main_candidates_are_ambiguous():
    records = [raw(), raw(start=START + 60, end=END + 60)]
    sessions, _ = asyncio.run(exercise(records, [page([report()])]))
    assert all(s.sleep_score is None for s in sessions)


def test_segment_boundaries_disambiguate_same_day():
    records = [raw(), raw(start=START + 60, end=END + 60)]
    segments = [{"bedtime": START, "wake_up_time": END}]
    sessions, _ = asyncio.run(exercise(records, [page([report(segment_details=segments)])]))
    assert [s.sleep_score for s in sessions] == [88, None]


def test_segment_mismatch_does_not_fall_back_to_date():
    segments = [{"bedtime": START - 60, "wake_up_time": END}]
    sessions, _ = asyncio.run(exercise([raw()], [page([report(segment_details=segments)])]))
    assert sessions[0].sleep_score is None


def test_only_short_report_segment_in_chunk_does_not_receive_daily_score():
    segments = [{"bedtime": START - 3600, "wake_up_time": END},
                {"bedtime": END + 3600, "wake_up_time": END + 5400}]
    records = [raw(start=END + 3600, end=END + 5400)]
    sessions, _ = asyncio.run(exercise(records, [page([report(segment_details=segments)])]))
    assert sessions[0].sleep_score is None


def test_aggregate_score_sync_mcp_export_and_resync_failure(monkeypatch, tmp_path):
    db = Database(tmp_path / "synthetic.db")
    result, _ = asyncio.run(exercise([raw()], [page([report()])], db=db))
    assert result["added"] == 1 and result["skipped"] == 0
    monkeypatch.setattr(server, "query_service", QueryService(db, USER))
    # The raw session starts on Jan 9, but the main-sleep summary uses Jan 10.
    response = asyncio.run(server._handle_query_sleep({"start_date": DAY, "end_date": DAY}))
    main = response["data"]["main_sessions"][0]
    assert main["sleep_score"] == 88 and main["sleep_score_source"] == "daily_report"
    assert response["data"]["data_quality"]["sleep_score_days"] == 1

    target = tmp_path / "synthetic.json"
    export_database(db.db_path, target, output_format="json", dataset="sleep")
    row = json.loads(target.read_text(encoding="utf-8"))["records"]["sleep"][0]
    assert row["sleep_score"] == 88 and row["sleep_score_source"] == "daily_report"
    paths = export_database(db.db_path, tmp_path / "csv", output_format="csv", dataset="sleep")
    with paths[0].open(encoding="utf-8-sig", newline="") as handle:
        row = list(csv.DictReader(handle))[0]
    assert row["sleep_score"] == "88" and row["sleep_score_source"] == "daily_report"

    # An optional report outage must not erase the last known score for the
    # exact same sleep. A subsequent upstream correction must still update it.
    result, _ = asyncio.run(exercise([raw()], [], status=404, db=db))
    assert result["updated"] == 1
    rows = db.query_sleep_sessions(USER, "2026-01-09", DAY)
    assert rows[0]["sleep_score"] == 88 and rows[0]["sleep_score_source"] == "daily_report"
    asyncio.run(exercise([raw(score=91)], [], db=db))
    rows = db.query_sleep_sessions(USER, "2026-01-09", DAY)
    assert rows[0]["sleep_score"] == 91 and rows[0]["sleep_score_source"] == "sleep_record"

    # Changed boundaries with the same ID cannot inherit the old score.
    asyncio.run(exercise([raw(start=START + 60)], [], status=404, db=db))
    rows = db.query_sleep_sessions(USER, "2026-01-09", DAY)
    assert rows[0]["sleep_score"] is None and rows[0]["sleep_score_source"] is None


def test_additive_cache_migration_preserves_existing_rows(tmp_path):
    path = tmp_path / "synthetic.db"
    db = Database(path)
    asyncio.run(exercise([raw(score=81)], [], db=db))
    # Recreate the pre-fix schema using only a synthetic temporary database.
    with sqlite3.connect(path) as conn:
        conn.execute("ALTER TABLE sleep_sessions DROP COLUMN sleep_score_source")
    migrated = Database(path)
    Database(path)  # repeated initialization is idempotent
    rows = migrated.query_sleep_sessions(USER, "2026-01-09", DAY)
    assert len(rows) == 1 and rows[0]["sleep_score"] == 81
    assert rows[0]["sleep_score_source"] is None


def test_cancellation_is_not_swallowed(monkeypatch):
    adapter = cloud.MiFitnessCloudAdapter(USER, "synthetic")
    adapter._connected = True
    adapter._client = object()

    async def raw_fetch(*args):
        return [raw()]

    async def cancel(*args):
        raise asyncio.CancelledError

    monkeypatch.setattr(adapter, "_fetch_key", raw_fetch)
    monkeypatch.setattr(adapter, "_fetch_daily_sleep_reports", cancel)

    async def collect():
        return [s async for s in adapter.iter_sleep_sessions(DAY, DAY)]

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(collect())
