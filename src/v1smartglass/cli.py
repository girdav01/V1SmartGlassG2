"""Typer-powered CLI: `v1smartglass run`, `once`, `doctor`."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import typer

from . import config as cfg_mod
from .app import App
from .vision_one import VisionOneClient
from .voice import Intent, parse_intent

app = typer.Typer(add_completion=False, help="Vision One → Even Realities G2 HUD.")


@app.command()
def run(
    config_path: Path | None = typer.Option(None, "--config", "-c", help="Path to config.yaml."),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Connect to the glasses and listen for 'Hey Even ...' voice commands."""
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO)
    settings = cfg_mod.load(config_path)
    asyncio.run(App(settings).run())


@app.command()
def once(
    utterance: str = typer.Argument(..., help="Simulated voice command, e.g. 'Hey Even VisionOne alerts'."),
    config_path: Path | None = typer.Option(None, "--config", "-c"),
) -> None:
    """Fetch + render one frame set for a given utterance, then exit."""
    settings = cfg_mod.load(config_path)
    intent = parse_intent(utterance)
    if intent is Intent.UNKNOWN:
        typer.secho(f"Could not parse intent from: {utterance!r}", fg=typer.colors.RED)
        raise typer.Exit(2)
    asyncio.run(App(settings).run_once(intent))


@app.command()
def doctor(config_path: Path | None = typer.Option(None, "--config", "-c")) -> None:
    """Quick connectivity check for the Vision One API."""

    async def _go() -> None:
        settings = cfg_mod.load(config_path)
        async with VisionOneClient(settings.vision_one) as client:
            alerts = await client.fetch_alerts()
            typer.echo(f"OK — region={settings.vision_one.region}  alerts_in_window={len(alerts)}")

    asyncio.run(_go())


if __name__ == "__main__":
    app()
