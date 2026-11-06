# Changelog

All notable changes to Quiet Chaos are documented here.

## [Unreleased]

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

[Unreleased]: https://github.com/hermanops/quiet-chaos/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/hermanops/quiet-chaos/compare/v0.1.3...v0.2.0