# quiet-chaos — Agent Instructions

Bounded, observable HTTP/DNS traffic noise generator for personal privacy experiments.
See [README.md](../README.md) for project background and [examples/config.toml](../examples/config.toml) for a fully annotated config reference.

---

## Quick Commands

```bash
# Install dev environment (once)
python -m pip install -e '.[dev]'

# Lint / format check
ruff check .
ruff format --check .

# Security scan (required in CI; findings fail)
semgrep scan --config p/python --config p/security-audit --error --strict --metrics off --quiet .

# Tests
pytest

# Run once locally
quiet-chaos run --config examples/config.toml --once
```

**Always run `ruff check .` and `pytest` after any code change.**

> **IMPORTANT**: Never run `uv run pytest` or any `uv run …` command. This repo does not use uv as its runner; doing so regenerates a `uv.lock` that is not tracked and must then be deleted. Use plain `pytest` after installing the dev extras.

---

## Architecture

| Module | Role |
|--------|------|
| `cli.py` | Typer entry point (`run` command) |
| `config.py` | Pydantic v2 `AppConfig`; loads TOML; validates all options |
| `traffic.py` | Core `TrafficGenerator`; orchestrates modes, visited-URL tracking, retries |
| `bounded.py` | `LRUSet` + `FailureCooldown`; memory-bounded tracking |
| `fingerprints.py` | Coherent browser-family `Accept`/`Accept-Language` headers |
| `pacing.py` | Bounded idle + occasional long pauses; optional diurnal weight |
| `seed_sources.py` | Tranco zip, CrUX gzip CSV, or plain-text seed loading; SHA-256-keyed cache |
| `user_agents.py` | Optional cached refresh from useragents.me |
| `safety.py` | `SafetyPolicy`; blocks private/local IPs, only allows http/https |
| `health.py` | `RuntimeStats` + raw HTTP/1.1 health server on port 8080 |
| `telemetry.py` | Optional OpenTelemetry / OTLP; `NullSpan` when disabled |
| `events.py` | `JsonFormatter`; all log attributes prefixed `qc_` |
| `defaults.py` | `DEFAULT_USER_AGENTS`, `DEFAULT_SEED_URLS`, `DEFAULT_DENY_DOMAINS` |

HTTP traffic and source downloads use `SafetyTransport` for checked, pinned public
destinations. DNS mode intentionally uses the system resolver with bounded lifetime,
URL policy checks and public A-answer validation; it does not connect to answers.
Main HTTP bodies are streamed with bounded wire/decoded sizes and decompression;
redirect bodies are closed unread. Health probes and telemetry are separate paths.

---

## Key Conventions

- **Python 3.12**, `from __future__ import annotations` in every file
- **Async throughout**: `asyncio` + `httpx.AsyncClient`; all I/O is `async/await`
- **Ruff**: line-length 100, rules `E/F/I/UP/B/SIM`, double quotes — run `ruff format .` to auto-fix
- **Pydantic v2** for all config; use `model_validator(mode="after")` for cross-field validation
- Only **GET/HEAD** requests — the deny-list check runs before every request
- All request timing is controlled exclusively by `pacing.py` (`PacingConfig`) — there is no separate rate limiter

---

## Testing

- All tests in `tests/`; `asyncio_mode = "auto"` — no `@pytest.mark.asyncio` needed
- Use **factory functions** (`make_generator()`, etc.) instead of fixtures for setup
- Mock HTTP with `httpx.MockTransport`; use `monkeypatch` for simple stubs
- Test HTTP status errors (4xx/5xx) as non-retried failures; only transient transport errors trigger retries

---

## Docker

```bash
docker compose up --build          # default Compose (port 8080)
curl http://localhost:8080         # health check

# Host deployment example
docker compose -f docker-compose.host.yml up -d
```

Container runs as **nonroot**; cache volume mounts at `/home/nonroot/.cache/quiet-chaos`.

---

## Pitfalls

- **Pacing must respect the deadline**: any sleep in `pacing.py` or `traffic.py` must be capped to `min(pause, remaining_seconds)`; uncapped sleeps cause runs to exceed `run_for_seconds`
- **Failure cooldown is per-domain** keyed on `urlparse().hostname` — not per-URL
- **Retry only covers transient errors** (`ConnectError`, `TimeoutException`, `TransportError`) — HTTP 4xx/5xx never retry
- **SHA-256 cache keys** in `seed_sources.py` — do not switch back to Python's `hash()` (not stable across processes)
- **Health server** is raw HTTP/1.1 (no framework) — `health.py` is intentionally simple
- **Health access** defaults to loopback; container configs explicitly bind wildcard. Keep optional `QUIET_CHAOS_HEALTH_TOKEN` authentication and Docker/Compose probes aligned; health errors expose class names only.
- **Diurnal timezone** is runtime-local unless `pacing.timezone` selects an IANA zone. Preserve deadline and maximum-pause caps.
- **Security CI** gates PRs/releases with Semgrep; scheduled/manual pip-audit covers resolved runtime and telemetry dependencies separately from dev tools.
- **Docker host Compose template** (`docker-compose.host.yml`) lives at the repo root (not under `examples/`) specifically so its `build: context: .` doesn't need to traverse out of the file's own directory — Git-based stack deployment tools (Dockhand, Portainer, etc.) commonly sandbox build context to the compose file's directory and reject `..` paths
- **`examples/config.srv.toml` is not auto-loaded** — it's a tracked template for the `docker-compose.host.yml` bind mount at `/opt/quiet-chaos/config.toml`; nothing in the `Dockerfile` or Compose files reads it directly, so it must be copied onto the host manually before each fresh deploy
- **`uv run pytest`** regenerates `uv.lock` (not tracked) — see Quick Commands above
