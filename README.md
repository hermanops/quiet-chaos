# Quiet Chaos

Quiet Chaos is a bounded, observable traffic noise generator for personal privacy experiments. It is a modern successor to older `noisy`-style crawlers, with explicit rate limits, safe HTTP methods, structured logs, Docker-first operation, a health endpoint, and optional OpenTelemetry.

The default configuration keeps traffic deliberately modest: bounded pacing between actions, GET/HEAD only, no form submission, no login automation, no captcha bypassing, and deny rules for local/private networks.

## Features

- Python 3.12+ async runtime using `httpx`.
- Traffic modes for HTTP browsing, DNS lookups, RSS polling, search-like Wikipedia API queries, and static asset HEAD requests.
- Automatic public seed-list refresh from Tranco with a local cache and built-in fallback seeds.
- Optional cached refresh of real browser user-agent strings.
- Browser-family request headers and bounded visited/failure caches to reduce repetitive traffic.
- Structured JSON logs for easy ingestion into Elastic, Loki, or other log tools.
- Built-in `/` health endpoint with runtime counters.
- Optional OpenTelemetry traces via the `otel` extra.
- Non-root Docker image, Compose example, GitHub Actions, Dependabot, Ruff, and pytest.

## Quick Start

Run on the Docker host with Compose:

```bash
docker compose up --build
```

Check health:

```bash
curl http://localhost:8080
```

Compose binds the health endpoint to localhost by default. Put it behind an authenticated reverse proxy or explicitly change the port binding if remote access is required.

The container runs as `nonroot`, reads `/app/config.toml`, and stores refreshed seed and user-agent caches in the `quiet-chaos-cache` volume mounted at `/home/nonroot/.cache/quiet-chaos`.

For a dedicated Docker host, keep the host config at `/opt/quiet-chaos/config.toml` — [examples/config.srv.toml](examples/config.srv.toml) is an always-on host profile (no `run_for_seconds` cap, diurnal pacing); copy it to that path before the first deploy. From a checkout of this repository, build and run the host template:

```bash
docker compose -f docker-compose.host.yml up -d
```

Useful host checks:

```bash
docker compose ps
docker compose logs -f quiet-chaos
docker inspect --format '{{json .State.Health}}' quiet-chaos-quiet-chaos-1
```

Refresh caches on the Docker host:

```bash
docker compose run --rm quiet-chaos run --config /app/config.toml --cache-dir /home/nonroot/.cache/quiet-chaos --refresh-seeds --once
```

Run locally:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
quiet-chaos run --config examples/config.toml --once
```

Refresh the Tranco seed cache:

```bash
quiet-chaos run --config examples/config.toml --refresh-seeds --once
```

## Configuration

Quiet Chaos uses TOML. Start with [examples/config.toml](examples/config.toml).

Important defaults:

- `request_timeout_seconds = 8.0`
- `modes = ["http", "dns", "rss", "search", "assets"]`
- `seed_sources` defaults to `https://tranco-list.eu/top-1m.csv.zip`
- `user_agent_source.enabled = false` by default; set it to `true` to cache fresh user agents from `useragents.me`
- `pacing.enabled = true` adds small bounded pauses between actions; see `[pacing]` in [examples/config.toml](examples/config.toml) for the tunable parameters
- `stats_log.interval_seconds = 300` emits periodic structured counters for Docker log collection
- `max_request_retries = 1` retries transient network failures once with jittered backoff
- `seed_reinjection_probability = 0.1` occasionally returns to root seeds instead of only following discovered links
- `seed_sources` also supports `kind = "crux_gzip_csv"` for CrUX top-list CSV gzip files

## Safety Model

Quiet Chaos is designed for low-volume, benign background traffic. It does not try to bypass access controls, automate accounts, submit forms, exploit endpoints, or overwhelm services. Keep request rates conservative and follow the acceptable-use rules for the networks and services you run it against.

HTTP traffic, seed downloads, and user-agent downloads reject non-public IPv4
and IPv6 destinations, including redirects. Hostnames must resolve entirely to
public addresses; connections use a checked IP while preserving the original
Host header and TLS hostname to prevent DNS rebinding. Environment HTTP proxies
are not used, since they would bypass these destination checks. Telemetry export
is separately configured and is not subject to this HTTP traffic policy.

The host profile's diurnal pacing follows the container's local timezone, not
necessarily the Docker host's. Verify the image's timezone before relying on the
schedule. For direct local execution, bind the health endpoint to `127.0.0.1`;
the example's `0.0.0.0` binding is intended for Docker with localhost-only port
publishing.

## Development

```bash
python -m pip install -e '.[dev]'
ruff check .
ruff format --check .
semgrep scan --config p/python --config p/security-audit .
pytest
```

## Releases

GitHub Releases mark checked source versions; they do not change deployment. Keep
Dockhand configured to track `main` and build locally using
[docker-compose.host.yml](docker-compose.host.yml). No packages or images are
published to PyPI or GHCR.

To release a version:

1. Update `[project].version` in [pyproject.toml](pyproject.toml) and merge the
	change into `main` through the usual review and CI checks.
2. Update your local `main` and run the checks:

	```bash
	git switch main
	git pull --ff-only origin main
	ruff check .
	ruff format --check .
	pytest
	```

3. Create and push an annotated tag matching the version exactly, prefixed with
	`v`. For the current `0.1.1` version:

	```bash
	git tag -a v0.1.1 -m "Release v0.1.1"
	git push origin v0.1.1
	```

Pushing a `v*` tag runs version validation, Ruff lint and format checks, pytest on
Python 3.12-3.14, and a Docker build without publishing the image. The tag must
equal `v` plus the version in the tagged commit's [pyproject.toml](pyproject.toml).
Only after all checks succeed does CI create a GitHub Release with generated
release notes and GitHub's source archives; no wheel, sdist, or container image
is uploaded. Review the generated notes on GitHub after creation.

If checks fail, no release is created. Fix code failures on `main` and use a new
version and tag; do not move an existing release tag. For a transient CI failure,
rerun the failed jobs on the existing tag. If the release already exists, do not
rerun its creation job; edit its notes on GitHub instead.

## License

GPL-3.0-only. See [LICENSE](LICENSE).
