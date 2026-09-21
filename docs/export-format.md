# Export format

The `mi-fitness-bridge export` command writes normalized records from the local SQLite cache without including saved Xiaomi credentials. Exports can be written as one JSON envelope or as one CSV file per selected dataset.

> **Sensitive data:** exports never contain the Xiaomi passToken, but they do include plaintext identifier columns such as `user_id`. Treat every export file as sensitive personal data: store it somewhere private and do not commit or share it.

## JSON envelope

JSON export writes a single file. If `--output` ends in `.json`, that path is used directly. Otherwise the exporter creates `mi_fitness_export.json` inside the output directory.

The top-level payload contains:

| Field | Description |
| --- | --- |
| `schema_version` | Export schema version. The current value is `1.0`. |
| `source` | Export source identifier. The current value is `mi_fitness_data_bridge`. |
| `generated_at` | UTC timestamp generated when the export is written. |
| `filters` | The requested `dataset`, `start_date`, and `end_date` filter values. Values are `null` when omitted. |
| `records` | Object keyed by dataset name. Each value is a list of row objects from that dataset. |

Synthetic example:

```json
{
  "schema_version": "1.0",
  "source": "mi_fitness_data_bridge",
  "generated_at": "2026-07-15T12:00:00+00:00",
  "filters": {
    "dataset": "daily_activity",
    "start_date": "2026-07-15",
    "end_date": "2026-07-15"
  },
  "records": {
    "daily_activity": [
      {
        "date": "2026-07-15",
        "steps": 8000,
        "distance_m": 5200,
        "active_kcal": 310,
        "active_minutes": 45
      }
    ]
  }
}
```

All values above are synthetic examples.

## CSV layout

CSV export writes one `<dataset>.csv` file for each selected dataset. When `--type` is omitted, the exporter writes every supported dataset. When `--type` is provided, it writes only that dataset.

CSV files use:

- one header row from the selected table's current columns;
- `utf-8-sig` encoding so spreadsheet tools such as Excel detect UTF-8 correctly;
- rows ordered by the dataset's date column.

Supported dataset names and their date columns:

| Dataset | SQLite table | Date column used for ordering and filters |
| --- | --- | --- |
| `daily_activity` | `daily_activity` | `date` |
| `sleep` | `sleep_sessions` | `start_at` |
| `workouts` | `workouts` | `start_at` |
| `body_measurements` | `body_measurements` | `timestamp` |
| `heart_rate` | `heart_rate_samples` | `timestamp` |
| `spo2` | `spo2_samples` | `timestamp` |
| `stress` | `stress_samples` | `timestamp` |
| `abnormal_heart_beat` | `abnormal_heart_beat_events` | `start_at` |

## Date filtering

The `--start-date` and `--end-date` options must use `YYYY-MM-DD` format. If both are provided, `--start-date` must not be after `--end-date`.

Date filters apply only to exported rows. They do not change the local SQLite cache.

Filtering is inclusive:

- `--start-date 2026-07-01` includes rows whose dataset date column is on or after `2026-07-01`.
- `--end-date 2026-07-15` includes rows whose dataset date column is on or before `2026-07-15`.

For timestamp-based datasets, the exporter applies SQLite `date(<column>)` before comparing, so a value such as `2026-07-15T23:30:00` is included by `--end-date 2026-07-15`.

## Sleep score availability and provenance

`sleep_score` is optional. Raw sleep scores are preferred; an unambiguous main sleep can be enriched with the upstream daily-report score. No scores are locally estimated, and a daily score is not independently calculated for each session. Missing, invalid and zero-default upstream values are unavailable (JSON `null`, CSV empty), not zero measurements.

The additive `sleep_score_source` column is `sleep_record`, `daily_report`, or null for unknown/absent provenance. Database initialization adds the column to older caches without deleting records. A direct offline export of an old, not-yet-initialized cache retains its old columns. The envelope schema remains 1.0; consumers should tolerate additive columns.

A failed/missing optional lookup does not erase a previously known score for unchanged start/end timestamps and nap flag. Such a score is last-known, not proof of a fresh upstream value. A later valid score replaces it, and changed boundaries/nap flags cannot inherit it.

Export reads only the cache. After updating the connector, explicitly re-sync affected sleep dates, then export. For overnight sleep consider widening the date range by a day: MCP main-sleep summaries use local wake date, but export still uses the existing SQLite `date(start_at)` filter (timezone offsets are normalized by SQLite). Restart an existing MCP server after updating its installed package.
