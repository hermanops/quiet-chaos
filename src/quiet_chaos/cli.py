from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated

import typer

from quiet_chaos.budget import DailyBudget
from quiet_chaos.config import load_config
from quiet_chaos.events import configure_logging
from quiet_chaos.health import RuntimeStats, health_token_from_env, start_health_server
from quiet_chaos.safety import SafetyPolicy, SafetyTransport
from quiet_chaos.seed_sources import SeedStore
from quiet_chaos.telemetry import Telemetry
from quiet_chaos.traffic import TrafficGenerator
from quiet_chaos.trend_sources import TrendStore
from quiet_chaos.user_agents import UserAgentStore

app = typer.Typer(no_args_is_help=True, add_completion=False)
LOGGER = logging.getLogger(__name__)


@app.callback()
def main() -> None:
    """Generate bounded, observable background traffic noise."""


@app.command("trends")
def trends(
    config: Annotated[Path | None, typer.Option("--config", "-c")] = None,
    cache_dir: Annotated[Path, typer.Option("--cache-dir")] = Path(".cache/quiet-chaos"),
    snapshot: Annotated[Path | None, typer.Option("--snapshot")] = None,
    day: Annotated[str | None, typer.Option("--date")] = None,
) -> None:
    """Inspect or replay a trend snapshot without generating traffic."""
    settings = load_config(config)
    configure_logging(settings.log_level, settings.json_logs)
    store = TrendStore(settings, cache_dir)
    selected_day = date.fromisoformat(day) if day else datetime.now(UTC).date()
    result = store.replay(snapshot) if snapshot else asyncio.run(store.refresh())
    if result is None:
        raise typer.Exit(code=1)
    typer.echo(
        json.dumps(
            {
                "snapshot_hash": result["snapshot_hash"],
                "date": selected_day.isoformat(),
                "origins": store.pool(result, selected_day),
                "candidates": result["candidates"],
            },
            indent=2,
        )
    )


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
    health_token = health_token_from_env() if config.health.enabled and not once else None
    configure_logging(config.log_level, config.json_logs)

    stats = RuntimeStats.start()
    telemetry = Telemetry(config.telemetry.enabled, config.telemetry.service_name)
    telemetry.setup()

    trend_store = TrendStore(config, cache_dir) if config.trend_sources.enabled else None
    trend_snapshot = await trend_store.refresh() if trend_store else None
    observations = trend_snapshot["sources"] if trend_snapshot else {} if trend_store else None
    seed_store = SeedStore(config, cache_dir)
    seeds = await seed_store.load(refresh=refresh_seeds, trend_observations=observations)
    stats.seeds_loaded = len(seeds)
    LOGGER.info("seed urls loaded", extra={"qc_seed_count": len(seeds)})

    user_agents = await UserAgentStore(config, cache_dir).load(refresh=refresh_seeds)
    config.user_agents = user_agents
    stats.user_agents_loaded = len(user_agents)
    LOGGER.info("user agents loaded", extra={"qc_user_agent_count": len(user_agents)})

    health_server = None
    if config.health.enabled and not once:
        health_server = await start_health_server(
            config.health.host,
            config.health.port,
            stats,
            allowed_hosts=config.health.allowed_hosts,
            token=health_token,
        )
        LOGGER.info(
            "health endpoint started",
            extra={"qc_host": config.health.host, "qc_port": config.health.port},
        )

    budget = (
        DailyBudget(cache_dir / "trends" / "budget.sqlite3", config.trend_sources)
        if trend_store
        else None
    )
    generator = TrafficGenerator(
        config=config,
        seeds=seed_store,
        stats=stats,
        telemetry=telemetry,
        trend_store=trend_store,
        trend_snapshot=trend_snapshot,
        budget=budget,
    )

    if once:
        import httpx

        async with httpx.AsyncClient(
            follow_redirects=True,
            transport=SafetyTransport(SafetyPolicy(config.deny_domains)),
            trust_env=False,
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
