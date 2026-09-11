> 中文版：[README.md](README.md)

# Mi Bridge (Mi Fitness Data Bridge)

[![Glama score](https://glama.ai/mcp/servers/shkyyy18/mi_fitness_data_bridge/badges/score.svg)](https://glama.ai/mcp/servers/shkyyy18/mi_fitness_data_bridge)

A simple way to **export your Mi Fitness and related Xiaomi-device data to your own computer**. Save activity, sleep, heart-rate, weight, and other available records as SQLite, JSON, or CSV, then use ChatGPT, Claude, Gemini, or another large language model to analyze, compare, and summarize them. Python integration and a local MCP server are included so programs and local AI tools can read the data.

> **Unofficial and experimental.** This project is not affiliated with, endorsed by, or supported by Xiaomi. Xiaomi, Mi Home, and Mi Fitness are trademarks of Xiaomi Corporation. The adapter relies on non-public upstream endpoints, so authentication, connectivity, or individual data types can stop working when Xiaomi changes its services, account-region behavior, devices, firmware, or authentication. Use it only with accounts and data you are authorized to access.

![Synthetic Mi Fitness Data Bridge terminal demo](docs/assets/bridge-synthetic-demo.png)

*The screenshot and every example in this README use synthetic data. No credential, account identifier, or real health export is included.*

> **In one sentence:** Export your Xiaomi health data to your own computer, then let an AI model help analyze changes over time.

## What it does

| Capability | Details |
| --- | --- |
| Local cache | Stores normalized synchronized records in a SQLite database on your machine. |
| Portable exports | Writes JSON or CSV files for backup, personal analysis, or use with an AI model; exports never include the saved `passToken`. |
| Local MCP server | Provides stdio tools for personal automation and local AI workflows. |
| Python integration | Keeps the `mi_fitness_mcp` namespace for compatibility with existing downstream users. |

The default cloud region is `cn`; another region can be supplied during setup. Available records vary by account region, device, firmware, and Xiaomi's upstream service. A successful sync with zero records can simply mean that the account has no records of that type in the requested range.

## Supported data

- **Daily activity**: steps, distance, active calories, active minutes, and related fields.
- **Sleep**: sessions and sleep stages.
- **Workouts**.
- **Body measurements**: weight and body-composition fields available to the account/device.
- **Heart-rate samples**, including resting heart rate when available.
- **SpO2**, stress, and abnormal-heart-beat events when available.

Daily-activity steps are aggregated by local minute. When a phone, band, or watch sends overlapping records for one minute, the bridge retains the larger single record instead of adding them, to avoid double-counting across devices. This is a best-effort compatibility rule for a non-public upstream format; totals can still differ from later server-side corrections shown in the app.

## Project boundary

This repository is a data connector and local-data foundation. It deliberately does **not** provide:

- Medical diagnosis, treatment, coaching, or weight-loss advice.
- Hosted accounts, shared credentials, public token proxies, or multi-user cloud services.
- A web dashboard, third-party fitness OAuth/webhooks, or meal-photo analysis.

Downstream projects should install this package or consume its local exports instead of copying the connector source.

## Install

**Requirement:** Python 3.11 or newer.

```bash
git clone https://github.com/shkyyy18/mi_fitness_data_bridge.git
cd mi_fitness_data_bridge
python -m venv .venv
```

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
pip install -e .
```

macOS/Linux:

```bash
source .venv/bin/activate
pip install -e .
```

For development dependencies:

```bash
pip install -e '.[dev]'
```

The primary command is `mi-fitness-bridge`. The older `mi-fitness-mcp` command remains a compatibility alias.

## Configure and diagnose

Use the interactive setup flow. The `passToken` prompt does not echo its value, helping keep it out of shell history:

```bash
mi-fitness-bridge setup
mi-fitness-bridge doctor
```

Setup asks for a Mi Fitness `user_id`, `passToken`, and region (default: `cn`). Credentials are saved through the local operating-system keyring when available; review the security characteristics of your active keyring backend before use. Do **not** put a `passToken` in a command line, script, issue, log, or screenshot. `setup` does not accept `--user-id` or `--pass-token` command-line flags.

`doctor` checks local configuration, credentials, and the database. When credentials are configured, it also checks cloud connectivity. A cloud check can fail because of network or upstream-service changes; existing local data and export operations remain usable without a cloud connection.

`sync`, `export`, `serve`, and `doctor` accept `--db` and support the `MI_FITNESS_DB_PATH` environment variable. Precedence is: command-line option > environment variable > configured/default path.

## Sync data

Synchronize every supported data type for a date range:

```bash
mi-fitness-bridge sync --start-date 2026-07-01 --end-date 2026-07-15
```

Synchronize one data type:

```bash
mi-fitness-bridge sync --type sleep --start-date 2026-07-01 --end-date 2026-07-15
mi-fitness-bridge sync --type body_measurements --start-date 2026-07-01 --end-date 2026-07-15
```

`--type` accepts: `daily_activity`, `heart_rate`, `body_measurements`, `sleep`, `workouts`, `spo2`, `stress`, and `abnormal_heart_beat`. The CLI reports added, updated, partial, and failed results by data type. Re-running an explicit date range is idempotent and does not duplicate stored records. If Xiaomi later corrects earlier history, re-run that earlier range with an explicit `--start-date`.

## Export local data

Export one portable JSON file:

```bash
mi-fitness-bridge export --format json --output exports/mi_fitness.json
```

Export CSV files (one per dataset):

```bash
mi-fitness-bridge export --format csv --output exports/csv
```

Filter an export by dataset and date:

```bash
mi-fitness-bridge export --format json --type sleep \
  --start-date 2026-07-01 --end-date 2026-07-15 \
  --output exports/sleep.json
```

Dates must use `YYYY-MM-DD`, and the start date cannot be later than the end date. JSON is UTF-8; CSV is `utf-8-sig` (with BOM), so Excel can open Chinese text correctly. Exported health records are sensitive personal data and can contain a plaintext `user_id`. The default `.gitignore` excludes databases, export directories, and common logs, but you remain responsible for storing, sharing, and backing up those files safely.

See the [export-format reference](docs/export-format.md) for the JSON envelope, CSV layout, and inclusive date-filtering rules.

## MCP server

Start the local stdio MCP server:

```bash
mi-fitness-bridge serve
# Compatibility alias
mi-fitness-mcp serve
```

Available tools are `get_connection_status`, `sync_data`, `get_sync_status`, `get_profile`, `get_daily_summary`, `query_metric_series`, `get_data_coverage`, `query_body_measurements`, `query_sleep`, `query_workouts`, `workout_series`, `query_heart_rate`, `query_spo2`, `query_stress`, and `query_abnormal_heart_beat`.

The server communicates over standard input/output and is intended to be launched and managed by a local MCP client. When run directly in a terminal, it appears to "hang" because it is waiting for MCP messages. It does not contact Xiaomi at startup; cloud connections are made only on demand by status or synchronization operations. Do not expose it as a public service or credential proxy.

Example client configuration:

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

## Use as a Python dependency

The compatibility package name remains `mi_fitness_mcp`:

```python
from mi_fitness_mcp.adapters.mi_fitness_cloud import MiFitnessCloudAdapter
```

Never hard-code real credentials or commit them to source control. Downstream projects should install this package rather than vendor or copy its connector source.

## Synthetic end-to-end demo

The repository includes a demo that uses no network access or real account:

```bash
python examples/synthetic_demo.py
```

It creates a temporary SQLite database with synthetic records and runs the real JSON/CSV export pipeline. Use it to verify the local export path or prepare privacy-safe bug reports.

## Development

```bash
pip install -e '.[dev]'
python -m pytest -q -p no:cacheprovider
python -m ruff check src tests
```

Use synthetic data only in issues, tests, documentation, and screenshots. Follow [SECURITY.md](SECURITY.md) for security reporting; see [docs/release-checklist.md](docs/release-checklist.md) for release steps.

## Privacy, provenance, and license

- Keep `passToken`s, SQLite databases, exports, and logs private.
- Do not commit real health data or screenshots that contain personal metrics.
- Health data returned by `query_*` MCP tools flows through the MCP client you use. Run the server only through a local stdio client, never through a remote or hosted proxy.
- This software is for personal data access and engineering research, not diagnosis or treatment.
- See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for upstream provenance and MIT attribution.

The current version is licensed under **AGPL-3.0-only**; versions published before 2026-08-03 were MIT. See [LICENSE](LICENSE).
