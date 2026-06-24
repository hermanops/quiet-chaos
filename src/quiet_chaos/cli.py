from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Annotated

import typer

from quiet_chaos.config import load_config
from quiet_chaos.events import configure_logging
from quiet_chaos.health import RuntimeStats, start_health_server
from quiet_chaos.rate_limit import RateLimiter
from quiet_chaos.seed_sources import SeedStore
from quiet_chaos.telemetry import Telemetry
from quiet_chaos.traffic import TrafficGenerator

app = typer.Typer(no_args_is_help=True, add_completion=False)
LOGGER = logging.getLogger(__name__)


@app.callback()
def main() -> None:
    """Generate bounded, observable background traffic noise."""


@app.command()
def run(
    config: Annotated[
        Path | None,
        typer.Option("--config", "-c", help="Path to a TOML configuration file."),
    ] = None,
    cache_dir: Annotated[
        Path,
        typer.Option("--cache-dir", help="Directory for downloaded seed source caches."),
    ] = Path(".cache/quiet-chaos"),
    refresh_seeds: Annotated[
        bool,
        typer.Option(
            "--refresh-seeds",
            help="Ignore cached public seed lists and fetch fresh data.",
        ),
    ] = False,
    once: Annotated[
        bool,
        typer.Option("--once", help="Run one traffic action and exit."),
    ] = False,
) -> None:
    """Run the traffic noise generator."""
    asyncio.run(_run(config, cache_dir, refresh_seeds, once))


async def _run(config_path: Path | None, cache_dir: Path, refresh_seeds: bool, once: bool) -> None:
    config = load_config(config_path)
    configure_logging(config.log_level, config.json_logs)

    stats = RuntimeStats.start()
    telemetry = Telemetry(config.telemetry.enabled, config.telemetry.service_name)
    telemetry.setup()

    seed_store = SeedStore(config, cache_dir)
    seeds = await seed_store.load(refresh=refresh_seeds)
    LOGGER.info("seed urls loaded", extra={"qc_seed_count": len(seeds)})

    health_server = None
    if config.health.enabled and not once:
        health_server = await start_health_server(config.health.host, config.health.port, stats)
        LOGGER.info(
            "health endpoint started",
            extra={"qc_host": config.health.host, "qc_port": config.health.port},
        )

    generator = TrafficGenerator(
        config=config,
        seeds=seed_store,
        rate_limiter=RateLimiter(
            config.max_requests_per_second,
            config.per_domain_cooldown_seconds,
        ),
        stats=stats,
        telemetry=telemetry,
    )

    if once:
        import httpx

        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=config.request_timeout_seconds,
        ) as client:
            await generator.run_once(client)
        return

    try:
        await generator.run_forever(stop_after_seconds=config.run_for_seconds)
    finally:
        if health_server is not None:
            health_server.close()
            await health_server.wait_closed()


if __name__ == "__main__":
    app()
