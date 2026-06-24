# Quiet Chaos

Quiet Chaos is a bounded, observable traffic noise generator for personal privacy experiments. It is a modern successor to older `noisy`-style crawlers, with explicit rate limits, safe HTTP methods, structured logs, Docker-first operation, a health endpoint, and optional OpenTelemetry.

The default configuration keeps traffic deliberately modest: at most one request per second globally, per-domain cooldowns, GET/HEAD only, no form submission, no login automation, no captcha bypassing, and deny rules for local/private networks.

## Features

- Python 3.12 async runtime using `httpx`.
- Traffic modes for HTTP browsing, DNS lookups, RSS polling, search-like Wikipedia API queries, and static asset HEAD requests.
- Automatic public seed-list refresh from Tranco with a local cache and built-in fallback seeds.
- Structured JSON logs for easy ingestion into Elastic, Loki, or other log tools.
- Built-in `/` health endpoint with runtime counters.
- Optional OpenTelemetry traces via the `otel` extra.
- Non-root Docker image, Compose example, GitHub Actions, Dependabot, Ruff, and pytest.

## Quick Start

Run with Docker Compose:

```bash
docker compose up --build
```

Check health:

```bash
curl http://localhost:8080
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

- `max_requests_per_second = 1.0`
- `per_domain_cooldown_seconds = 30.0`
- `request_timeout_seconds = 8.0`
- `modes = ["http", "dns", "rss", "search", "assets"]`
- `seed_sources` defaults to `https://tranco-list.eu/top-1m.csv.zip`

## Safety Model

Quiet Chaos is designed for low-volume, benign background traffic. It does not try to bypass access controls, automate accounts, submit forms, exploit endpoints, or overwhelm services. Keep request rates conservative and follow the acceptable-use rules for the networks and services you run it against.

## Development

```bash
python -m pip install -e '.[dev]'
ruff check .
ruff format --check .
pytest
```

## License

GPL-3.0-only. See [LICENSE](LICENSE).
