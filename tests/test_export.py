from __future__ import annotations

import csv
import json
import sqlite3
from types import SimpleNamespace

import pytest

from mi_fitness_mcp import main as cli
from mi_fitness_mcp.config import Config
from mi_fitness_mcp.export import export_database
from mi_fitness_mcp.storage import Database


def _sample_database(tmp_path):
    path = tmp_path / "mi_fitness.db"
    Database(path)
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            INSERT INTO daily_activity
              (id, provider, source_type, user_id, date, steps, distance_m, active_kcal)
            VALUES ('daily-1', 'xiaomi', 'cloud', 'private-user', '2026-07-14', 8000, 6000, 400)
            """
        )
        connection.execute(
            """
            INSERT INTO body_measurements
              (id, provider, source_type, user_id, timestamp, weight_kg)
            VALUES ('body-1', 'xiaomi', 'cloud', 'private-user', '2026-07-14T08:00:00', 73.2)
            """
        )
    return path


def test_json_export_has_normalized_records_and_no_credentials(tmp_path):
    database = _sample_database(tmp_path)
    target = tmp_path / "export.json"

    written = export_database(database, target, output_format="json")

    assert written == [target]
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "1.0"
    assert payload["records"]["daily_activity"][0]["steps"] == 8000
    text = target.read_text(encoding="utf-8")
    assert "passToken" not in text


def test_csv_export_can_filter_dataset_and_date(tmp_path):
    database = _sample_database(tmp_path)
    output = tmp_path / "csv"

    written = export_database(
        database,
        output,
        output_format="csv",
        dataset="body_measurements",
        start_date="2026-07-14",
        end_date="2026-07-14",
    )

    assert written == [output / "body_measurements.csv"]
    with written[0].open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["weight_kg"] == "73.2"


def test_cli_export_warns_for_empty_datasets_without_changing_csv_bytes(
    monkeypatch, tmp_path, capsys
):
    database = _sample_database(tmp_path)
    baseline = tmp_path / "baseline"
    cli_output = tmp_path / "cli"

    expected_written = export_database(database, baseline, output_format="csv")
    monkeypatch.setattr(
        cli,
        "load_config",
        lambda: Config(mode="mi_fitness_cloud", database_path=database),
    )

    cli.cmd_export(
        SimpleNamespace(
            output=cli_output,
            format="csv",
            type=None,
            start_date=None,
            end_date=None,
        )
    )

    output = capsys.readouterr().out
    assert "Export completed" in output
    warning_line = next(
        line for line in output.splitlines() if line.startswith("Warning: no rows found")
    )
    assert "sleep" in warning_line
    assert "heart_rate" in warning_line
    assert "daily_activity" not in warning_line
    assert "body_measurements" not in warning_line

    for baseline_path in expected_written:
        cli_path = cli_output / baseline_path.name
        assert cli_path.read_bytes() == baseline_path.read_bytes()


def test_csv_export_escapes_spreadsheet_formula_cells(tmp_path):
    database = _sample_database(tmp_path)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE daily_activity SET user_id = '=cmd|/c calc' WHERE id = 'daily-1'"
        )
    output = tmp_path / "csv-formula"

    written = export_database(
        database, output, output_format="csv", dataset="daily_activity"
    )

    with written[0].open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["user_id"] == "'=cmd|/c calc"
    # 非公式开头的字符串保持不变。
    assert rows[0]["id"] == "daily-1"


@pytest.mark.parametrize("invalid_date", ["2026/07/14", "2026-7-14", "not-a-date"])
def test_export_rejects_malformed_dates_before_opening_database(tmp_path, invalid_date):
    with pytest.raises(ValueError, match="start_date must use YYYY-MM-DD format"):
        export_database(
            tmp_path / "missing.db",
            tmp_path / "export.json",
            start_date=invalid_date,
        )


def test_export_rejects_reversed_date_range(tmp_path):
    with pytest.raises(ValueError, match="start_date must not be after end_date"):
        export_database(
            tmp_path / "missing.db",
            tmp_path / "export.json",
            start_date="2026-07-15",
            end_date="2026-07-14",
        )
