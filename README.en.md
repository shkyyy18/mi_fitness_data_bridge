> 中文版：[README.md](README.md)

# Mi Bridge (Mi Fitness Data Bridge)

[![Glama score](https://glama.ai/mcp/servers/shkyyy18/mi_fitness_data_bridge/badges/score.svg)](https://glama.ai/mcp/servers/shkyyy18/mi_fitness_data_bridge)

Local-first data bridge for exporting **your own** Mi Fitness health data to SQLite, JSON, CSV, Python, and MCP-compatible tools.

*Your Mi Fitness app will happily show you your own steps, sleep, and heart rate — but never let you take them anywhere. This bridge puts your own data into a SQLite file on your own disk.*

> **Trademark notice: Xiaomi, Mi Home (米家), and Mi Fitness are trademarks of Xiaomi Corporation. This is an unofficial community project, not affiliated with or endorsed by Xiaomi Corporation.**

> The experimental cloud adapter can stop working when Xiaomi changes private endpoints. Use it only with an account and data you are authorized to access.

## Synthetic demo

![Synthetic Mi Fitness Data Bridge terminal demo](docs/assets/bridge-synthetic-demo.png)

*All health values shown above are synthetic. No credential, account identifier, or personal export is included.*

## Verified demo

Captured on 2026-07-20 on Windows (Python 3.14) against commit on `main`. All data is synthetic; no credentials or network access are involved.

Test suite:

```text
$ python -m pytest -q -p no:cacheprovider
........................................................................ [ 96%]
...                                                                      [100%]
95 passed in 12.99s
```

End-to-end synthetic demo (`examples/synthetic_demo.py` seeds a local SQLite cache with synthetic records, then runs the real JSON/CSV export pipeline):

```text
$ python examples/synthetic_demo.py
Seeded synthetic database: C:\Users\<you>\AppData\Local\Temp\mi-fitness-demo-53el7cfh\mi_fitness.db
  daily_activity: 2026-07-15 .. 2026-07-15 (1 day(s))
  sleep: 2026-07-14 .. 2026-07-14 (1 day(s))
  workouts: 2026-07-15 .. 2026-07-15 (1 day(s))
  body_measurements: 2026-07-15 .. 2026-07-15 (1 day(s))

Export completed
  mi_fitness.json
  daily_activity.csv
  sleep.csv
  workouts.csv
  body_measurements.csv
  heart_rate.csv
  spo2.csv
  stress.csv
  abnormal_heart_beat.csv

JSON envelope:
  schema_version: 1.0
  source: mi_fitness_data_bridge
  records.daily_activity: 1 row(s)
  records.sleep: 1 row(s)
  records.workouts: 1 row(s)
  records.body_measurements: 1 row(s)

Sample sleep row (synthetic):
  start_at=2026-07-14T23:20:00 end_at=2026-07-15T07:05:00
  duration_minutes=465 score=86
  stages=[{"stage": "deep", "minutes": 82}, {"stage": "light", "minutes": 271}, {"stage": "rem", "minutes": 88}, {"stage": "awake", "minutes": 24}]
```

## Merged from health-assistant

The `health-assistant` project (local-first personal health dashboard: Strava, sleep, body composition, meal analysis) has been merged into this repository and its original repo is archived. Absorbed assets live under `docs/health-assistant/`:

- `analytics.py` — dependency-free reference implementation of the training/recovery summary and advice engine (7-day training stats, acute/chronic load ratio, readiness check, daily workout suggestion).
- `coaching_methodology.md` — the explainable cycling-coaching, body-composition, and sports-nutrition methodology behind it.
- `README.md` — the full migration note, including what was intentionally not ported (FastAPI dashboard, Strava OAuth/Webhook plumbing, meal-photo analysis) and why.

## What this project does

- Reads Mi Fitness health data through an experimental China-region cloud adapter.
- Stores normalized records in a local SQLite database.
- Exports portable JSON or CSV without credentials.
- Exposes local MCP query tools for personal automation.
- Provides one reusable connector implementation for downstream projects such as a personal fat-loss advisor.

It deliberately does **not** provide medical advice, weight-loss coaching, hosted account access, or a multi-user cloud service.

## Why this bridge?

| Before | After |
|---|---|
| Your health history lives only inside the Mi Fitness app; the only way to "export" it is screenshots. | `mi-fitness-bridge sync` pulls daily activity, sleep, workouts, body measurements, heart rate, SpO2, and stress into a normalized local SQLite database. |
| Answering "how did I sleep last month?" means scrolling the app day by day. | `mi-fitness-bridge export --format csv --type sleep --start-date ... --end-date ...` writes a spreadsheet-ready CSV filtered to exactly that range. |
| Giving an AI assistant access to your health data means handing credentials to a hosted service. | `mi-fitness-bridge serve` exposes local MCP query tools over your own database; the passToken stays in the OS keyring and exports never contain it. |

## Supported datasets

- Daily activity: steps, distance, active calories and active minutes.
- Sleep sessions and stages.
- Workouts.
- Body measurements: weight and available body-composition fields.
- Heart-rate samples, including resting heart rate when available.
- SpO2, stress, and abnormal-heart-beat events when available for the account/device.

Availability varies by device, account region, firmware, and Xiaomi's upstream service.

## Install

```bash
git clone https://github.com/shkyyy18/mi_fitness_data_bridge.git mi_fitness_data_bridge
cd mi_fitness_data_bridge
python -m venv .venv
```

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

Windows Git Bash:

```bash
source .venv/Scripts/activate
pip install -e ".[dev]"
```

macOS/Linux:

```bash
source .venv/bin/activate
pip install -e '.[dev]'
```

## Configure

The safer interactive path avoids putting the passToken directly into shell history:

```bash
mi-fitness-bridge setup
mi-fitness-bridge doctor
```

Credentials are stored through the local keyring when available. Some fallback keyring implementations may store secrets less securely; review your operating system's keyring behavior before use.

### How to get user_id and passToken

The bridge uses Xiaomi account-level credentials (the same login session as the Mi Home app). Pick one of the two methods:

**Method 1: copy from a browser**

1. Open [account.xiaomi.com](https://account.xiaomi.com) in a browser and sign in with the Xiaomi account used by your Mi Fitness app.
2. Open the developer tools (F12) → Application → Cookies → `https://account.xiaomi.com`.
3. Copy the values of the `userId` and `passToken` cookies and paste them when `mi-fitness-bridge setup` asks.

**Method 2: QR-login tooling**

Log in once by QR code with the open-source [mijia-api](https://github.com/Do1e/mijia-api):

```bash
pip install mijiaAPI
python -c "from mijiaAPI import mijiaAPI; mijiaAPI().login()"   # shows a QR code; scan it with the Mi Home app
```

The session is saved to `~/.config/mijia-api/auth.json` by default (`%USERPROFILE%\.config\mijia-api\auth.json` on Windows); the `userId` and `passToken` in that file work directly with this bridge — account-level Xiaomi credentials work across services, and the adapter exchanges them for a Mi Fitness session (`sid=miothealth`). Note that `auth.json` stores the credentials in plaintext: once they are entered into this bridge (the OS keyring), consider deleting that file.

Notes:

- The passToken expires; if `doctor` reports an authentication failure, simply fetch a fresh one with the steps above.
- For the browser method, sign in from your usual network environment; frequent or unusual-location attempts may trigger Xiaomi's risk control (slider/SMS verification). If that happens, use the QR method instead.
- Cookie names and the login flow above were verified in 2026-08 and may vary by account region, device, or risk-control policy; Xiaomi can also change its private endpoints at any time (see the experimental notice at the top).
- These two values are equivalent to your account login session. Never share them and never commit them to Git.

## Sync

```bash
mi-fitness-bridge sync --start-date 2026-07-01 --end-date 2026-07-15
```

Or sync one dataset:

```bash
mi-fitness-bridge sync --type sleep --start-date 2026-07-01 --end-date 2026-07-15
mi-fitness-bridge sync --type body_measurements --start-date 2026-07-01 --end-date 2026-07-15
```

The database lives in the platform user-data directory (chosen by platformdirs). `sync`, `export`, `serve`, and `doctor` all accept a `--db` option or the `MI_FITNESS_DB_PATH` environment variable; precedence is CLI option > environment variable > default location. Note that platformdirs does not honor `LOCALAPPDATA` on Windows — use one of these two overrides instead:

```bash
mi-fitness-bridge sync --db ./data/mi_fitness.db --start-date 2026-07-01 --end-date 2026-07-15
export MI_FITNESS_DB_PATH=./data/mi_fitness.db
```

Known limitation: an incremental sync without date arguments starts from the timestamp of the last locally stored record, so upstream corrections or backfills to earlier history are not picked up automatically; re-run that range with an explicit earlier `--start-date` when needed (the re-run is idempotent and does not duplicate records).

## Export

Create one portable JSON file:

```bash
mi-fitness-bridge export --format json --output exports/mi_fitness.json
```

Create one CSV file per dataset:

```bash
mi-fitness-bridge export --format csv --output exports/csv
```

Filter by dataset and date:

```bash
mi-fitness-bridge export --format json --type sleep \
  --start-date 2026-07-01 --end-date 2026-07-15 \
  --output exports/sleep.json
```

Exports never contain the saved Xiaomi passToken, but they do include plaintext identifier columns such as `user_id` — treat export files as sensitive personal data. Exported health records are ignored by Git by default.

See [Export format](docs/export-format.md) for the JSON envelope, CSV layout, and inclusive date filtering rules.

## MCP server

The compatibility command remains available:

```bash
mi-fitness-bridge serve
# legacy alias
mi-fitness-mcp serve
```

Available tools include connection status, synchronization, coverage, daily summaries, body measurements, sleep, workouts, heart rate, SpO2, and stress queries, plus the agent-facing `workout_series` tool — it auto-downsamples long workout time series under a hard `max_points` cap (fixed time-bucket means, aggregated in SQLite) and honestly reports `downsampled`, `source_points`, `returned_points`, and `method`, alongside full-resolution stats (avg/min/max/quantiles) and heart-rate time-in-zone. List/summary tools such as `query_workouts` and `get_daily_summary` carry a `data_quality` field (coverage days, missing metrics, last sync time).

Client setup example (MCP configuration JSON for Claude Code / Codex and similar clients):

```json
{
  "mcpServers": {
    "mi-bridge": {
      "command": "mi-fitness-bridge",
      "args": ["serve"]
    }
  }
}
```

Note: `serve` is a stdio service that talks to the client over standard input/output — it is not an HTTP service. Running it directly in a terminal looks like it "hangs"; it is simply waiting for MCP messages from a client, which is normal. In daily use, let your MCP client launch it via the configuration above.

## Use as a Python dependency

The normalized adapter remains available under the compatibility module name:

```python
from mi_fitness_mcp.adapters.mi_fitness_cloud import MiFitnessCloudAdapter
```

Downstream projects should install this package rather than vendor or copy the connector source.

## Privacy and safety

- Keep passTokens, local databases, exports, and logs private.
- Exports contain no passToken but do carry plaintext identifier columns such as `user_id`; they are sensitive personal data too.
- Health data returned by the `query_*` tools flows through the MCP client into the cloud LLM behind it; run this server only over local stdio with a local client, and never wire it into a remote or hosted agent.
- Do not run the bridge as a public credential proxy.
- Do not commit real health data or screenshots containing personal metrics.
- Use synthetic data in bug reports and documentation.
- This software is for personal data access and engineering research, not diagnosis or treatment.

See `SECURITY.md` for responsible reporting and `THIRD_PARTY_NOTICES.md` for provenance.

## Development

```bash
pip install -e '.[dev]'
python -m pytest -q -p no:cacheprovider
python -m ruff check src tests
```

## Release

See `CHANGELOG.md` for version history and `docs/release-checklist.md` for the publication and post-release checks.

## Traction so far

This is a young, single-maintainer project, and we would rather show real numbers than polish:

- **Stars:** 1 — currently the only star across the maintainer's entire GitHub account, and it is on this repository. If this bridge is useful to you, your star genuinely stands out.
- **Traffic (GitHub insights, 14 days ending 2026-07-25):** 36 unique cloners, 2 unique visitors.
- **External contributions:** two outside pull requests merged so far (#3 docs, #7 feature), and #10 is under review. The queue is open and curated; see the [good first issues](https://github.com/shkyyy18/mi_fitness_data_bridge/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22).
- **Test suite:** 75 tests pass locally (`python -m pytest -q -p no:cacheprovider`), verified 2026-08-17 with Python 3.14 on Windows.

The maintainer's sibling project [AgentCron](https://github.com/shkyyy18/cc-autopilot) received its first three external pull requests through exactly this kind of good-first-issue queue; the [first-contribution case study](https://github.com/shkyyy18/cc-autopilot/blob/main/docs/first-contribution-case-study.md) documents what made those tasks approachable. The same design is applied here: small scope, written acceptance criteria, offline-verifiable with synthetic data, and no real health data ever required.

## Related projects

- [garmin-mcp](https://github.com/davidmosiah/garmin-mcp) — local-first MCP server for Garmin data. Shares the `agent-safe-series/v1` contract with this project (field-for-field aligned downsampled time series), so one agent can consume both servers without special-casing.

## Support the project

If this bridge finally let you do something with your own Mi Fitness data — a chart, a backup, an MCP-powered query — a star on [GitHub](https://github.com/shkyyy18/mi_fitness_data_bridge) helps the next person who wants their own data back find it. And if you have ten minutes, a good first issue is the fastest way to make the bridge better.

## License

AGPL-3.0-only (versions up to 2026-08-03 were MIT). See `LICENSE`. Upstream attribution is preserved in `THIRD_PARTY_NOTICES.md`.
