# MCP tool contracts

The runtime source of truth is `list_tools()` in `src/mi_fitness_mcp/server.py`.
Requires MCP SDK >=1.12.0,<2.0; CI tests the lower bound explicitly.
The server publishes instructions during initialization and descriptions, input
schemas and safety annotations through `tools/list`. These contracts are tested
through the MCP SDK request handlers, not just by inspecting this document.

## Privacy and side effects

- Unofficial/experimental, own-account access only, local stdio only. No public
  server, credential proxy, telemetry or real-account tests are introduced.
- Configure credentials via interactive local CLI `setup`, never tool arguments.
- `get_connection_status` may contact Xiaomi, authenticate and persist rotated
  credentials in the local keyring. It is deliberately **not** marked read-only.
- `sync_data` contacts Xiaomi and writes SQLite/sync watermarks. Ask for user
  consent before syncing. It does not delete the database or edit cloud records.
- `cancel_sync` stops a background MCP job and writes its local job status; it
  does not delete committed records or start new cloud requests. It is not read-only.
- The other 14 tools read local cache, persistent job state or connected-account
  metadata; they do not fetch fresh cloud health records. Their annotations are
  `readOnlyHint=true`, `openWorldHint=false`, `destructiveHint=false`.
- Annotations are hints, not authorization/security enforcement. Sensitive
  results may leave the computer through the chosen MCP client or model.

## Selecting a tool

| Need | Tool | Main result |
| --- | --- | --- |
| Connectivity / authentication | `get_connection_status` | connected, mode, last sync and available types |
| Refresh local cache | `sync_data` | sync ID, counts, per-type results; or accepted ID |
| Poll a job | `get_sync_status` | persistent job state or completed result |
| Stop a background job | `cancel_sync` | terminal status; committed records preserved |
| Browse retained MCP jobs | `query_sync_history` | account-scoped jobs and pagination |
| Minimal connected account metadata | `get_profile` | masked account ID, timezone, empty devices placeholder |
| Daily activity totals | `query_daily_activity` | summaries, data_quality |
| Activity/weight trends | `query_metric_series` | metric, dated series |
| Raw heart-rate measurements | `query_heart_rate` | timestamp, bpm, sample_type |
| Body measurements | `query_body_measurements` | timestamped measurements |
| Raw sleep and main-sleep statistics | `query_sleep` | sessions, count, main_sessions, metrics, data_quality |
| Find workouts and IDs | `query_workouts` | workouts, count, data_quality |
| One workout's heart-rate curve | `query_workout_series` | bounded points, stats, coverage, time_in_zone |
| Oxygen saturation | `query_spo2` | timestamp, spo2_pct |
| Device stress values | `query_stress` | timestamp, stress_score, level |
| Device-reported heartbeat events | `query_abnormal_heart_beat` | event ID, start/end, duration_seconds |
| Available cached dates | `get_data_coverage` | per-type first_date, last_date, days_with_data |

The catalog advertises 17 tools. The former names `get_daily_summary` and
`workout_series` remain callable aliases for `query_daily_activity` and
`query_workout_series`, respectively, but are not advertised as duplicate tools.

MCP job history survives restarts in local SQLite, retaining the latest 500
terminal jobs plus active jobs for each account. It excludes CLI syncs, raw
exception messages, credentials and health payloads. On startup, unfinished
jobs become `interrupted`; they are not automatically resumed. Only one MCP
server may use a given database at a time.

## Dates, limits and errors

Dates are inclusive `YYYY-MM-DD`. The MCP dispatch rejects impossible calendar
dates and reversed ranges before database/cloud handlers execute. Daily summary
accepts `date` or both `start_date` and `end_date`; a valid `date` overrides range
selection. Date strings use stored calendar dates, not automatic caller timezone
conversion. Sleep's raw sessions use start dates while its main-sleep statistics
use local wake dates. Coverage is a per-dataset summary, not proof that every day
or expected sample exists between first/last dates.

Raw heart-rate, oxygen, stress and heartbeat-event queries return the earliest
matches, defaulting to 5000 rows; choose a smaller positive `limit` and narrow
ranges. All record-list queries support `limit`/`offset` pagination (1-5000 rows;
history defaults to 20 and health queries to 5000). Keep filters unchanged,
avoid syncing between pages and pass `data.pagination.next_offset` as `offset`
for subsequent pages; null indicates the end. Counts describe the returned page.
Sleep main-session statistics and data-quality metadata describe the full date
range, not just the page of raw sessions. `query_workout_series` instead has a
separate 400-point default and 500-point maximum.

Tools return JSON **text**. Cache success responses use `status=ok`,
`source=cache`, `generated_at` and a tool-specific `data` object. Handler failures
return `status=error` and `error`; SDK input-schema failures may instead produce
an MCP `isError` result. Check both. No `outputSchema` is advertised because the
current transport response is text, not structured content. Empty/missing values
are not zero measurements or evidence of normal health. Do not diagnose from them.

## Metric-series semantics

- `steps`, `distance_m`, `active_kcal`: daily activity totals.
- `weight_kg`: the latest timestamp-ordered body measurement per stored day.
- `day`: daily values, independent of the aggregation parameter.
- `week`: buckets labeled with Monday; `month`: labeled with the first day.
- `sum`, `avg`, `min`, `max`, `latest`: reduce **daily values** within a bucket.
  `latest` uses the last available day; missing dates are not zero-filled.
- The backward-compatible default reducer is `sum`. Explicitly prefer `avg` or
  `latest` for weight; for raw measurements use `query_body_measurements`.

Synthetic calls (no real account identifiers):

```json
{"name":"query_metric_series","arguments":{"metric":"weight_kg","start_date":"2026-01-01","end_date":"2026-01-31","granularity":"week","aggregation":"latest"}}
{"name":"query_heart_rate","arguments":{"start_date":"2026-01-15","end_date":"2026-01-15","limit":100}}
{"name":"query_workouts","arguments":{"start_date":"2026-01-01","end_date":"2026-01-31","min_duration":20}}
```

Use an ID actually returned by the last query for `query_workout_series`.
