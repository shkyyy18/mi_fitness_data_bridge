# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Security

- Removed the `--user-id` / `--pass-token` flags from `mi-fitness-bridge setup`; credentials are now only accepted through the interactive prompt, so a passToken can no longer end up in shell history.
- The Xiaomi login redirect `location` (server-controlled input) is validated against an allowlist of Xiaomi-owned HTTPS hosts (`*.xiaomi.com`, `*.mi.com`) before it is followed, closing an SSRF/credential-leak vector.
- `setup` and `doctor` print a prominent warning when the active keyring backend stores secrets weakly or not at all (fail/null/plaintext backends); the flow is not blocked.
- On POSIX, the SQLite database file is created with `0600`, its directory with `0700`, and export files with `0600` (unchanged on Windows, where ACLs apply).

### Fixed

- `workout_series` no longer filters heart-rate samples by a `workout` sample_type the cloud adapter never writes (it only stores passive/active/resting), which made the filtered query always empty. The series now uses every sample inside the activity window, and `data_quality.sample_type` reports the types actually observed (`None` when the window is empty).
- Version strings aligned at 0.3.1 across `pyproject.toml`, `src/mi_fitness_mcp/__init__.py`, and `server.json`; the release checklist now includes a version-consistency check.

### Changed

- List queries (`query_heart_rate`, `query_spo2`, `query_stress`, `query_abnormal_heart_beat`) push `limit` down to SQL `LIMIT` instead of loading the full table and slicing in Python, and default to a hard cap of 5000 rows when no limit is given.
- `query_sleep` preserves its raw start-date session list and adds a wake-date main-sleep summary with coverage, missing-date, duplicate-session, nap, score-availability, and invalid-record quality metadata; missing dates are never averaged as zero sleep.
- Project renamed to 米桥 / Mi Bridge; README GitHub links point to the new `shkyyy18/mi-bridge` repository name, and the trademark disclaimer is a standalone prominent line.
- The MIT license text of upstream author Aleksej Kubulashvili is preserved in a NOTICE block at the top of `LICENSE`, with the license history (MIT before 2026-08-03, AGPL-3.0-only after) stated in the README.
- Dropped the unused `click` and `rich` dependencies.
- The issue-template security contact link now points at `SECURITY.md` (private vulnerability reporting is not enabled on the repository yet).

## [0.3.1] - 2026-08-13

### Added

- `--db` option and `MI_FITNESS_DB_PATH` environment variable to override the SQLite database location for `sync`, `export`, `serve`, and `doctor`; precedence is CLI option > environment variable > default platform location. This enables test and multi-database isolation, which the platformdirs default cannot provide (it ignores `LOCALAPPDATA` on Windows).
- "How to get user_id and passToken" guidance in the README configuration sections (browser-cookie method and QR-login tooling), referenced from `doctor` output when no configuration file is found.
- Git Bash virtualenv activation command in the installation instructions.
- Export-sensitivity note in `docs/export-format.md` and the README privacy sections: exports contain no passToken but do carry plaintext `user_id` identifier columns and must be handled as sensitive personal data.
- Warn after successful CLI exports when selected datasets contain zero rows; exported JSON/CSV bytes are unchanged (#7, thanks @pollychen-lab).

### Changed

- `load_config()` no longer writes a default `config.json` on first run; configuration is persisted only by the explicit `setup` command.
- README test-suite counts updated to the current 46 tests.

## [0.3.0] - 2026-08-13

### Added

- Agent-safe `workout_series` MCP tool: auto-downsamples workout time series under a hard `max_points` cap (default 400, max 500) using fixed time-bucket means aggregated in SQLite, reports honest `downsampled`/`source_points`/`returned_points`/`method` metadata, and always includes full-resolution stats (avg/min/max/quantiles) and heart-rate time-in-zone.
- `data_quality` field (coverage days, missing metrics, last sync time) on `query_workouts` and `get_daily_summary` responses.
- Synthetic 3-hour ride fixture (10,800 1 Hz heart-rate points with known ground-truth stats) and regression tests for the downsampling pipeline.
- `workout_series` contract `agent-safe-series/v1`: top-level `start_time`, `t_unit` (`seconds_from_start`), `unit`, `contract_version`, and `requested_resolution_seconds` (alongside the effective `resolution_seconds`); `stats.percentile_method` (`linear_interpolation`); `time_in_zone.reference_source` (`activity_recorded_max` / `observed_max` / `caller_provided`); `data_quality.actual_samples`, `data_quality.sample_interval_seconds`, and `data_quality.coverage_anchor`.
- Optional `reference_max_hr` input on `workout_series` so agents can normalize time-in-zone against a consistent reference when comparing activities.
- Duration-anchored coverage in `workout_series`: `expected_samples` is computed from the activity's nominal duration (workout `duration_minutes`, else the recorded start/end), so samples missing at the start or end of an activity surface as `coverage_ratio < 1.0` instead of looking like a shorter, fully-sampled workout; falls back to the first-to-last sample span (`coverage_anchor: "sample_span"`) when no nominal duration is recorded.
- Garmin-layout counterpart of the synthetic 3-hour ride fixture (`tests/garmin_fixtures.py`, `metricDescriptors`/`activityDetailMetrics` shape) plus cross-format regression tests proving both layouts yield identical stats and downsampled points, including a sensor-gap scenario (garmin-mcp issue #19).

### Changed

- **Breaking:** `workout_series` `points[].t` is now a numeric offset in seconds from `start_time` instead of an ISO timestamp string.

- Hide passToken entry in the interactive setup flow.
- Close the experimental cloud adapter reliably after CLI diagnostics and synchronization.
- Use `cn` consistently as the default cloud region.
- Reject malformed or reversed export date ranges before reading the local database.
- Apply configured HTTP limits, retries, pagination, sync chunking, and operation timeouts to CLI diagnostics and synchronization.
- Reject invalid synchronization lookback and chunk sizes instead of risking non-terminating chunk loops.
- Report partial and failed CLI synchronization results accurately instead of displaying them as successful.
- Return a non-zero process status when diagnostics are not ready or any synchronization is partial/failed.

## [0.2.0] - 2026-07-15

### Added

- Independent `mi-fitness-data-bridge` package and repository boundary.
- SQLite, JSON, CSV, Python, and MCP-compatible access paths.
- Dataset/date-filtered `export` command.
- `mi-fitness-bridge` command with the `mi-fitness-mcp` compatibility alias.
- Local keyring setup and diagnostic commands.
- Security, contribution, CI, and third-party attribution documentation.
- Synthetic release screenshot with no credentials or personal health data.

### Changed

- Preserved the `mi_fitness_mcp` Python namespace for downstream compatibility.
- Clarified that the Xiaomi cloud adapter is unofficial and experimental.

[0.3.1]: https://github.com/shkyyy18/mi-fitness-data-bridge/releases/tag/v0.3.1
[0.3.0]: https://github.com/shkyyy18/mi-fitness-data-bridge/releases/tag/v0.3.0
[0.2.0]: https://github.com/shkyyy18/mi-fitness-data-bridge/releases/tag/v0.2.0
