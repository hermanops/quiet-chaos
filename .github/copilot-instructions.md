# Copilot instructions

Quiet Chaos is a Python 3.12+ async traffic generator. See [README.md](../README.md) for user-facing setup and [examples/config.toml](../examples/config.toml) for the annotated configuration reference.

## Commands

```bash
# Install the package and development tools
python -m pip install -e '.[dev]'

# Lint and check formatting
ruff check .
ruff format --check .

# Run the full test suite
pytest

# Run one test file or one test
pytest tests/test_traffic.py
pytest tests/test_traffic.py::test_name -v

# Optional security scan (not run in CI)
semgrep scan --config p/python --config p/security-audit --quiet .

# Run one local traffic iteration
quiet-chaos run --config examples/config.toml --once
```

CI runs Ruff lint, Ruff format check, and pytest on Python 3.12-3.14, plus a Docker build. After code changes, run `ruff check .` and `pytest`. Do not use `uv run`: this repository uses plain `pytest`, and `uv` can generate an untracked `uv.lock`.

## Architecture

- `cli.py` loads TOML through `config.py` (`AppConfig`, Pydantic v2), initializes seed storage, runtime stats, and telemetry, then runs `TrafficGenerator` in `traffic.py`.
- `TrafficGenerator` chooses among HTTP, DNS, RSS, search, and asset modes. HTTP uses `httpx.AsyncClient`; DNS resolution runs via `asyncio.to_thread`. `seed_sources.py` supplies cached or fallback URLs, while `user_agents.py` optionally refreshes cached browser user agents.
- Every HTTP request goes through `SafetyPolicy.is_allowed_url()` in `safety.py`. Keep this as the safety gate: only HTTP/HTTPS URLs that pass the deny-domain and local/private-address checks are allowed, and request methods are restricted to GET and HEAD.
- `bounded.py` provides the visited-URL LRU and per-domain failure cooldown. Retries in `traffic.py` are for transient transport/time-out errors only; HTTP status errors are not retried.
- `pacing.py` computes inter-action pauses. `traffic.py` caps pauses to the remaining run deadline; preserve this when changing sleeps so bounded runs do not overrun.
- `health.py` exposes runtime counters through a small raw HTTP/1.1 health server. `telemetry.py` makes tracing optional, and `events.py` formats structured logs with `qc_`-prefixed attributes.
- Compose publishes the health endpoint on localhost only by default; preserve that boundary unless remote access is deliberately configured.

## Repository conventions

- Python modules use `from __future__ import annotations`; async I/O is the default in the request path.
- Configuration is TOML validated by Pydantic v2. Use `model_validator(mode="after")` for cross-field constraints.
- Ruff targets Python 3.12, uses a 100-character line length, selects `E`, `F`, `I`, `UP`, `B`, and `SIM`, and formats with double quotes.
- Tests live in `tests/`; pytest's `asyncio_mode = "auto"` means async tests do not need an explicit asyncio marker. Prefer test factory functions for setup, `httpx.MockTransport` for HTTP behavior, and `monkeypatch` for simple stubs.
- Cache keys for seed sources use SHA-256 so they remain stable across processes. Failure cooldowns are keyed by hostname, not full URL.
- `examples/config.srv.toml` is a host-deployment template, not an automatically loaded config; the host Compose setup expects it to be copied to `/opt/quiet-chaos/config.toml`.
