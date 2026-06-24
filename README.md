# Quiet Chaos

Quiet Chaos is a bounded, observable traffic noise generator for personal privacy experiments. It is a modern successor to older `noisy`-style crawlers, with explicit rate limits, safe HTTP methods, structured logs, Docker-first operation, a health endpoint, and optional OpenTelemetry.

The default configuration keeps traffic deliberately modest: bounded pacing between actions, GET/HEAD only, no form submission, no login automation, no captcha bypassing, and deny rules for local/private networks.

## Features

- Python 3.12 async runtime using `httpx`.
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

## Development

```bash
python -m pip install -e '.[dev]'
ruff check .
ruff format --check .
semgrep scan --config p/python --config p/security-audit .
pytest
```

## License

GPL-3.0-only. See [LICENSE](LICENSE).
