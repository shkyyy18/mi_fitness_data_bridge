# TDQS remediation — 2026-09-21

## Observed evidence (not a self-assigned replacement score)

The supplied screenshot shows Glama TDQS **C, 2.6/5**, covering 15 tools,
scored **2026-08-13 19:35** (timezone not stated in the screenshot).
This is a third-party MCP tool-description assessment, not GitHub's overall
code/security/reliability rating.

On 2026-09-21 the public Glama schema still displayed the short tool descriptions
and `query_metric_series`'s schema history reported first observation at v0.3.0
on August 13. The online per-tool grades were:

- A: `workout_series`.
- B: `get_profile`.
- D: `query_metric_series`, `query_body_measurements`, `query_workouts`, `get_data_coverage`.
- C: the other nine tools.

The `query_metric_series` detail page reported **1.3/5**: behavior 1, conciseness 2,
completeness 1, parameters 1, purpose 2, usage guidelines 1. Its explanation
identified absent parameter/response/behavior guidance and a description that
merely repeated the name. The screenshot's four set-level dimensions (4/4/4/5)
therefore do not describe the individual-tool weaknesses. We have not inferred
an undocumented formula for the 2.6 overall score.

Public evidence locations:

- https://glama.ai/mcp/servers/shkyyy18/mi_fitness_data_bridge
- https://glama.ai/mcp/servers/shkyyy18/mi_fitness_data_bridge/schema
- https://glama.ai/mcp/servers/shkyyy18/mi_fitness_data_bridge/tools/query_metric_series
- https://glama.ai/mcp/servers/shkyyy18/mi_fitness_data_bridge/admin

## Changes

1. Replace name-only descriptions across the 15-tool catalog with purpose,
   neighboring-tool distinctions, effects, prerequisites, response shapes,
   limitations and units; describe all 46 top-level input parameters.
2. Add honest MCP safety annotations and server-level privacy/workflow guidance.
   The connection health check can authenticate and persist a token, so it is
   not mislabeled as offline/read-only.
3. Encode input constraints and reject impossible/reversed calendar dates before
   dispatch. Keep all existing tool names and successful response shapes.
4. Fix two contract/implementation mismatches found during review: weight series
   previously queried activity summaries (which have no weight), and `latest`
   week/month aggregation previously fell back to sum. Add synthetic regressions.
5. Add SDK wire-catalog, validation and cached-response shape regressions; explain
   limits and response/error handling in `mcp-tool-contracts.md`. Require SDK
   >=1.12.0,<2.0 and add a minimum-SDK CI job so older installations do not
   silently miss schema validation or fail on the new metadata API.

No real credentials, databases, exported health records or logs were read, copied,
or uploaded for this work. Existing unrelated README edits were left untouched
and are not part of the remediation commit. No tool renaming, remote deployment,
telemetry, repository visibility change or history rewrite was performed.

## Validation and external refresh

- Pre-change baseline: 206 tests passed locally.
- Full suite on installed MCP 1.30.0: **260 passed** (54 new cases).
- Full suite using an isolated MCP 1.12.0 import target: **260 passed**; one
  pytest plugin import-order warning, no test failures. CI separately installs
  the lower-bound SDK into a clean environment.
- Final focused tool-contract/metric regression rerun: **54 passed**.
- Ruff (`src tests scripts`), Python compileall and `git diff --check`: passed.
- Wheel built successfully, installed to an isolated target and imported;
  account-free tools/list smoke confirmed 15 tools with annotations.
- CI now includes Python 3.11/3.12/3.13 plus a minimum-MCP-1.12.0 job. Remote
  outcomes must be checked against the pushed commit; local passes alone do not
  assert a remote pass.
- GitHub publication does not itself prove a new Glama inspection or score.
- The Glama admin page currently requires GitHub sign-in in this browser. No
  third-party OAuth authorization or credential sharing was performed.
- After the remediation commit is pushed, the repository owner should open Glama
  Admin and request the available refresh/re-inspection action. Verify that the
  catalog contains the new descriptions and annotations before checking TDQS.
- Do not claim an A grade or a new numeric score until Glama actually reports it.
