# PROJECT_GUIDE.md

## Project scope

- Stable path: `D:\AIWork\repos\mi_fitness_data_bridge`.
- This project is the single implementation for reading a user's own Mi Fitness health data and exporting it to local standard formats.
- It is infrastructure only: no fat-loss coaching, medical advice, personal dashboard, or business-specific analytics.

## Working rules

1. Read the workspace rules, `AGENTS.md`, and `README.md` before editing.
2. Never commit Xiaomi credentials, passTokens, SQLite databases, exported health data, logs, or personal identifiers.
3. Keep all credential handling local; do not add a hosted credential proxy or multi-user token service.
4. The cloud adapter is unofficial and experimental. Preserve the non-affiliation and instability warnings.
5. This directory is the single source of truth for the Mi Fitness connector. Downstream projects must depend on it instead of copying its source.
6. Preserve upstream MIT attribution and record material changes.
7. Run tests and syntax checks after code changes.
