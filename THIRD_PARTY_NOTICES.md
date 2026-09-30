# Third-party notices and provenance

This project was extracted from the MIT-licensed `binglua/mi-fitness-mcp-cn` code used by the local Health Assistant. That project states that it is based on `kubulashvili/mi-fitness-mcp` and adds China-region Mi Fitness cloud support.

The original MIT copyright notice for Aleksej Kubulashvili is preserved in `LICENSE`.

Material changes in this repository include:

- Repositioning the package as a reusable local health-data bridge.
- Adding portable JSON and CSV exports.
- Adding public-project security, contribution, CI, and privacy documentation.
- Retaining the `mi_fitness_mcp` Python module and `mi-fitness-mcp` command as compatibility interfaces.

The FDS workout-detail protocol module (`src/mi_fitness_mcp/adapters/fds.py`) is an independent implementation informed by the decompiled-APK protocol notes and MIT-licensed reference code of [kevinkwee/Mi-Fitness-Sync](https://github.com/kevinkwee/Mi-Fitness-Sync) (suffix construction, AES-CBC parameters, per-second record channel tables and GPS record layout). That project's MIT license terms are acknowledged here; no code was copied verbatim beyond protocol constants required for interoperability.

No Xiaomi source code, logo, or official SDK is included. The cloud adapter is an unofficial community implementation.
