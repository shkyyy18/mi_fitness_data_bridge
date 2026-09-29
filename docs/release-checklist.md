# Release checklist

## Local validation

- [x] Version strings match across `pyproject.toml`, `src/mi_fitness_mcp/__init__.py`, and `server.json`.
- [x] Tests and Ruff pass on supported Python versions.
- [x] Python syntax checks and `git diff --check` pass.
- [x] Wheel builds and installs in an isolated target.
- [x] Both console commands are present in wheel metadata.
- [x] No credential, database, export, log, personal identifier, or real health value is tracked.
- [x] Release screenshots contain synthetic values only.

## Real-account pilot gate

- [x] `mi-fitness-bridge doctor` exits successfully with a locally configured account.
- [x] A bounded 7-day sync succeeds for daily activity and sleep.
- [x] At least one additional device-supported dataset syncs successfully.
- [x] JSON and CSV exports open correctly and contain no credential fields.
- [x] Re-running the same date range is idempotent and does not duplicate records.
- [x] Pilot evidence records only redacted counts, device/region compatibility, and error classes; no personal health values or identifiers are committed.

## GitHub publication

- [x] Create `shkyyy18/mi-fitness-data-bridge` as a public repository.
- [x] Push `main` and the annotated `v0.2.0` tag.
- [x] Confirm CI passes for Python 3.11, 3.12, and 3.13.
- [ ] Enable private vulnerability reporting.
- [ ] Configure branch protection or a ruleset after the first push.
- [x] Publish release notes from `CHANGELOG.md`.

## Post-release observation

- [ ] Record installation and successful-sync reports without default telemetry.
- [ ] Track device/region compatibility Issues.
- [ ] Track external Issues, pull requests, contributors, and downstream integrations.
- [ ] Keep all connector fixes in this repository rather than copying them downstream.

## Validation evidence

- 2026-07-16: 19 tests, Ruff, Python syntax compilation, and `git diff --check` passed.
- 2026-07-16: a fresh wheel was built and installed into an isolated target; wheel metadata contains both `mi-fitness-bridge` and `mi-fitness-mcp`.
- 2026-07-16: tracked-file scanning found no credential, database, export, log, personal identifier, or real health-data artifacts; the tracked demo screenshot is explicitly documented as synthetic.
- 2026-07-16: the public repository, synchronized `main`, annotated `v0.2.0` tag, and successful Python 3.11/3.12/3.13 CI were verified.
- 2026-08-13: v0.3.0 released — 38 tests and Ruff green locally, `main` + annotated `v0.3.0` tag pushed, GitHub Release notes published from `CHANGELOG.md`, main-branch CI green.
- 2026-08-13: real-account pilot passed 6/6 gates — `doctor` OK (region cn, 8 dataset types), bounded 7-day sync (2026-08-07..13) succeeded for daily activity (7 rows), sleep (8 rows), and heart rate (2032 rows); JSON/CSV exports matched sync counts with zero credential-field matches; re-sync was idempotent (no duplicate rows). Evidence recorded with redacted counts only.
- Still open: vulnerability reporting, branch rules, and post-release adoption evidence.

- 2026-09-23: v0.3.2 release candidate — 260 tests, Ruff, Python syntax compilation, `git diff --check`, and sdist/wheel build passed on Python 3.12. Sleep-score daily-report supplementation remains unverified against the Issue reporter's account/device/region; the release notes and Issue response must preserve that caveat.

- 2026-09-29: v0.3.3 release candidate — 297 synthetic/mock tests, Ruff, Python compilation, `git diff --check`, and sdist/wheel build passed locally. An isolated wheel install exposes version 0.3.3, both console commands, 17 public tools and 10 paginated queries; legacy names remain callable but are not advertised. GitHub matrix CI and Glama re-evaluation are separate publication gates; no real-account/device/region validation was performed for this release.
