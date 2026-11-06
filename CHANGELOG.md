# Changelog

All notable changes to Quiet Chaos are documented here.

## [Unreleased]

## [0.3.0] - 2026-11-06

### Added

- Optional trend discovery using Cloudflare Radar, Tranco, and Cisco Umbrella, with optional CrUX and Majestic sources; snapshots are auditable, daily pools deterministic, and replay offline.
- `quiet-chaos trends` commands for inspecting and replaying saved trend snapshots.
- Persistent UTC-day request and response-body budgets with per-registrable-domain caps and 429/503 backoff.

### Changed

- Trend pools join seed selection automatically when enabled; HTTPS is required and budgets cover all generated HTTP and DNS traffic.

## [0.2.0] - 2026-11-06

### Added

- Configurable limits for streamed HTTP responses and downloaded source files, including bounded decompression.
- Optional IANA timezone selection for diurnal pacing.

### Security

- Optional bearer-token authentication and host validation for the health endpoint.
- Strict Semgrep CI scanning and a scheduled/manual audit of runtime and telemetry dependencies.

### Changed

- Health statistics no longer include the last requested URL.
- Host deployments inherit built-in seed URLs and search topics when those lists are not explicitly configured.
- Health response statistics include observed response body bytes.

### Fixed

- Missing RSS feed paths are handled gracefully.
- Health requests are bounded and validated, and container probes use the same optional token as the server.

[Unreleased]: https://github.com/hermanops/quiet-chaos/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/hermanops/quiet-chaos/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/hermanops/quiet-chaos/compare/v0.1.3...v0.2.0