# Mi Fitness Data Bridge

A local-first bridge for **your own Mi Fitness health data**. It uses an unofficial, experimental cloud adapter to read data you are authorized to access, normalizes it into a local SQLite database, and makes it available through JSON/CSV exports, Python integration, and local MCP tools.

> **Unofficial and experimental.** This project is not affiliated with, endorsed by, or supported by Xiaomi. Its cloud adapter depends on non-public upstream endpoints, so authentication, connectivity, and individual data types can stop working when Xiaomi changes its services, account-region behavior, device support, or firmware. Use it only with accounts and data you are authorized to access.

![Synthetic Mi Fitness Data Bridge terminal demo](https://raw.githubusercontent.com/shkyyy18/mi-fitness-data-bridge/main/docs/assets/bridge-synthetic-demo.png)

*The screenshot and every example in this README use synthetic data. No credential, account identifier, or personal health export is included.*

## What it does

| Capability | Details |
| --- | --- |
| Local cache | Stores normalized synchronized records in a SQLite database on your machine. |
| Portable exports | Writes one JSON file or one CSV file per dataset; exports never include the saved passToken. |
| Local MCP server | Provides stdio MCP tools for personal automation and local AI workflows. |
| Python integration | Keeps the `mi_fitness_mcp` namespace for compatibility with existing downstream users. |

The default cloud region is `cn`; another region can be supplied during setup. Available records vary by account region, device, firmware, and Xiaomi's upstream service. A successful sync with zero records can simply mean that the account has no records of that type in the requested range.

## Supported data

The adapter, local store, and export layer support:

- **Daily activity** ? steps, distance, active calories, active minutes, and related fields.
- **Sleep** ? sessions and sleep stages.
- **Workouts**.
- **Body measurements** ? weight and any body-composition fields available to the account/device.
- **Heart-rate samples**, including resting heart rate when available.
- **SpO2**, stress, and abnormal-heart-beat events when available.

## Project boundary

This repository is a data connector and local-data foundation. It deliberately does **not** provide:

- Medical diagnosis, treatment, coaching, or weight-loss advice.
- Hosted accounts, shared credentials, public token proxies, or multi-user cloud services.
- A web dashboard, third-party fitness OAuth/webhooks, or meal-photo analysis.

Downstream projects should install this package or consume its local exports instead of copying the connector source.

## Install

**Requirement:** Python 3.11 or newer.

```bash
git clone https://github.com/shkyyy18/mi-fitness-data-bridge.git
cd mi-fitness-data-bridge
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

The primary command is `mi-fitness-bridge`. The older `mi-fitness-mcp` command remains an alias for compatibility.

## Configure and diagnose

Use the interactive setup flow. The passToken prompt does not echo its value, helping keep it out of shell history:

```bash
mi-fitness-bridge setup
mi-fitness-bridge doctor
```

Setup asks for a Mi Fitness `user_id`, `passToken`, and region (default: `cn`). Credentials are saved through the local operating-system keyring when available; review the security characteristics of your active keyring backend before use. Do not put a passToken in a command line, script, issue, log, or screenshot.

`doctor` checks the local configuration, credentials, and database. When credentials are configured, it also checks cloud connectivity. A cloud check can fail because of network or upstream-service changes; existing local data and export operations remain usable without a cloud connection.

## Sync data

Synchronize every supported data type for a date range:

```bash
mi-fitness-bridge sync --start-date 2026-07-01 --end-date 2026-07-15
```

Synchronize a single data type:

```bash
mi-fitness-bridge sync --type sleep --start-date 2026-07-01 --end-date 2026-07-15
mi-fitness-bridge sync --type body_measurements --start-date 2026-07-01 --end-date 2026-07-15
```

`--type` accepts: `daily_activity`, `heart_rate`, `body_measurements`, `sleep`, `workouts`, `spo2`, `stress`, and `abnormal_heart_beat`. The CLI reports added, updated, partial, and failed results by data type.

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

Dates must use `YYYY-MM-DD`, and the start date cannot be later than the end date. Exported health records are sensitive personal data. The default `.gitignore` excludes databases, export directories, and common logs, but you are still responsible for handling, sharing, and backing up those files safely.

## MCP server

Start the local stdio MCP server:

```bash
mi-fitness-bridge serve
# Compatibility alias
mi-fitness-mcp serve
```

It provides these tools:

- `get_connection_status`, `sync_data`, `get_sync_status`, and `get_profile`;
- `get_daily_summary`, `query_metric_series`, and `get_data_coverage`;
- `query_body_measurements`, `query_sleep`, and `query_workouts`;
- `query_heart_rate`, `query_spo2`, `query_stress`, and `query_abnormal_heart_beat`.

The server communicates over standard input/output and is intended to be launched and managed by a local MCP client. Do not expose it as a public service or credential proxy. It does not contact Xiaomi at startup; cloud connections are made on demand by status or synchronization operations.

## Use as a Python dependency

The compatibility package name remains `mi_fitness_mcp`:

```python
from mi_fitness_mcp.adapters.mi_fitness_cloud import MiFitnessCloudAdapter

adapter = MiFitnessCloudAdapter(user_id="your-user-id", pass_token="your-pass-token")
```

Never hard-code real credentials or commit them to source control. Downstream projects should install this package rather than vendor or copy its connector source.

## Synthetic end-to-end demo

The repository includes a demo that uses no network access or real account:

```bash
python examples/synthetic_demo.py
```

It creates a temporary SQLite database with synthetic records, runs the real JSON/CSV export pipeline, and prints a result summary. Use it to verify the local export path or prepare privacy-safe bug reports.

## Development

```bash
pip install -e '.[dev]'
python -m pytest -q -p no:cacheprovider
python -m ruff check src tests
```

Use synthetic data only in issues, tests, documentation, and screenshots. Follow [SECURITY.md](SECURITY.md) for security reporting; see [docs/release-checklist.md](docs/release-checklist.md) for release steps.

## Privacy, provenance, and license

- Keep passTokens, SQLite databases, exports, and logs private.
- Do not commit real health data or screenshots that contain personal metrics.
- This software is for personal data access and engineering research, not diagnosis or treatment.
- See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for upstream provenance and attribution.

Licensed under the MIT License. See [LICENSE](LICENSE).
