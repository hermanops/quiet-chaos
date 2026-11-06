# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Detailed agent instructions already live in [.github/AGENTS.md](.github/AGENTS.md) (commands, architecture table, conventions, pitfalls) — read that file first. The notes below are a quick-reference summary plus anything not already covered there.

## Commands

```bash
# Install dev environment (once)
python -m pip install -e '.[dev]'

# Lint / format
ruff check .
ruff format --check .   # ruff format . to auto-fix

# Security scan (also gates CI)
semgrep scan --config p/python --config p/security-audit --error --strict --metrics off --quiet .

# Tests (whole suite)
pytest
# Single file / test
pytest tests/test_traffic.py
pytest tests/test_traffic.py::test_name -v

# Run the app once locally
quiet-chaos run --config examples/config.toml --once
```

**Always run `ruff check .` and `pytest` after any code change.**

> Never run `uv run pytest` or any `uv run …` command — this repo does not use uv as its runner; it would regenerate an untracked `uv.lock`. Use plain `pytest` after installing the dev extras.

CI (`.github/workflows/ci.yml`) runs `ruff check`, `ruff format --check`, `pytest`, a Docker build and blocking Semgrep. Scheduled/manual `.github/workflows/security.yml` audits resolved runtime and telemetry dependencies with pip-audit.

## Architecture

Quiet Chaos is a single-process async traffic generator: `TrafficGenerator.run_forever()` (`traffic.py`) loops, picking a random `TrafficMode` (http/dns/rss/search/assets) each iteration, then pacing before the next action. Everything is `asyncio` + `httpx.AsyncClient`; there is no multi-process or queue-based architecture to reason about.

See `.github/AGENTS.md` for the full module-by-module architecture table. Key flow to know:

- `cli.py` (Typer) → loads `config.py` (`AppConfig`, Pydantic v2, TOML-backed) → constructs `TrafficGenerator` with a `SeedStore` (`seed_sources.py`), `RuntimeStats` (`health.py`), and `Telemetry` (`telemetry.py`).
- Traffic/source HTTP requests pass through `SafetyPolicy` and `SafetyTransport` (`safety.py`) for method, scheme and checked/pinned public destinations, including redirects. DNS mode intentionally queries the system resolver with bounded lifetime and checks URL policy and all A answers. Local health probes and optional telemetry are separate paths.
- Main response bodies have wire and decoded byte limits with bounded gzip/deflate decoding; redirect bodies are closed unread. Oversize and safety errors never retry.
- `LRUSet` (visited URLs) and `FailureCooldown` (per-domain, keyed on `urlparse().hostname`) in `bounded.py` keep memory bounded and steer traffic away from dead/failing domains.
- `pacing.py` computes the inter-action sleep; `traffic.py._pause_between_actions` caps it to the remaining run deadline — any new sleep added to the request loop must respect `run_for_seconds` the same way.
- There is no separate rate limiter — all request timing is controlled exclusively through `PacingConfig` (`pacing.py`).

## Conventions

- Python 3.12, `from __future__ import annotations` in every module.
- Async throughout — no sync I/O in the request path.
- Pydantic v2 for config; cross-field validation via `model_validator(mode="after")` (see `PacingConfig`, `AppConfig` in `config.py`).
- Tests use factory functions (e.g. `make_generator()`) instead of pytest fixtures, and `httpx.MockTransport` for HTTP mocking (`asyncio_mode = "auto"`, no `@pytest.mark.asyncio` needed).
