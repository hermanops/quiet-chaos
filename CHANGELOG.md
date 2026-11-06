# Changelog

All notable changes to Quiet Chaos are documented here.

## [Unreleased]

## [0.5.0] - 2026-11-06

### Changed

- Raise default daily trend budgets to 10 requests per registrable domain, 500 requests total, and 100 MiB of response body bytes.
- Existing explicit budget overrides remain unchanged; restore the previous defaults with `daily_domain_requests = 3`, `daily_requests = 100`, and `daily_response_bytes = 26214400`.

### Fixed

- Check out the repository in the release workflow so it can read the changelog when creating release notes.

## [0.4.0] - 2026-11-06

### Changed

- Enable trend discovery by default, including provider refreshes at startup and HTTPS-only budgeted generated traffic; set `trend_sources.enabled = false` to opt out.
- Enable trend discovery in both example profiles and omit the global CrUX seed CSV that exceeds the decompression limit.

### Fixed

- Prepare a nonroot-writable cache mountpoint for fresh Docker volumes.
- Parse only the requested ranking ZIP rows within the decompression limit so the default Cisco Umbrella source can be used.
- Populate GitHub Release notes from the matching dated changelog section.

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

[Unreleased]: https://github.com/hermanops/quiet-chaos/compare/v0.5.0...HEAD
[0.5.0]: https://github.com/hermanops/quiet-chaos/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/hermanops/quiet-chaos/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/hermanops/quiet-chaos/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/hermanops/quiet-chaos/compare/v0.1.3...v0.2.0