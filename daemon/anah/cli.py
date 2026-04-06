"""CLI for ANAH daemon control and status."""

import asyncio
import logging
import sys

import click
import uvicorn
from rich.console import Console
from rich.table import Table
from rich.live import Live

from anah.config import load_config
from anah.daemon import AnahDaemon
from anah.db import Database

console = Console()


@click.group()
def cli():
    """ANAH — Autonomous Needs-Aware Hierarchy"""
    pass


@cli.command()
@click.option("--config", default="config.json", help="Path to config file")
@click.option("--log-level", default=None, help="Override log level")
def run(config, log_level):
    """Start the ANAH daemon."""
    cfg = load_config(config)
    level = log_level or cfg.daemon.log_level
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    daemon = AnahDaemon(cfg)

    async def _run():
        try:
            await daemon.start()
        except KeyboardInterrupt:
            await daemon.stop()

    asyncio.run(_run())


@cli.command()
@click.option("--config", default="config.json", help="Path to config file")
@click.option("--host", default="127.0.0.1", help="API server host")
@click.option("--port", default=8420, help="API server port")
def serve(config, host, port):
    """Start the dashboard API server."""
    console.print(f"[bold cyan]ANAH API[/] starting on http://{host}:{port}")
    uvicorn.run("anah.api:app", host=host, port=port, reload=True)


@cli.command()
@click.option("--config", default="config.json", help="Path to config file")
def status(config):
    """Show current hierarchy status."""
    cfg = load_config(config)

    async def _status():
        db = Database(cfg.daemon.db_path)
        await db.connect()

        hierarchy = await db.get_hierarchy()
        actions = await db.get_recent_actions(limit=10)

        table = Table(title="ANAH Hierarchy Status", border_style="dim")
        table.add_column("Level", style="bold", width=6)
        table.add_column("Name", width=30)
        table.add_column("Status", width=12)
        table.add_column("Last Check", width=20)

        status_colors = {
            "healthy": "green",
            "degraded": "yellow",
            "critical": "red",
            "suspended": "dim",
            "unknown": "dim white",
        }

        import time
        for level in hierarchy:
            color = status_colors.get(level["status"], "white")
            last_check = level.get("last_check")
            if last_check:
                age = time.time() - last_check
                if age < 60:
                    check_str = f"{age:.0f}s ago"
                elif age < 3600:
                    check_str = f"{age/60:.0f}m ago"
                else:
                    check_str = f"{age/3600:.1f}h ago"
            else:
                check_str = "never"

            table.add_row(
                f"L{level['level']}",
                level["name"],
                f"[{color}]{level['status']}[/{color}]",
                check_str,
            )

        console.print(table)

        if actions:
            console.print()
            action_table = Table(title="Recent Actions", border_style="dim")
            action_table.add_column("Time", width=10)
            action_table.add_column("Level", width=6)
            action_table.add_column("Type", width=12)
            action_table.add_column("Description", width=40)
            action_table.add_column("Status", width=10)

            for action in actions[:10]:
                age = time.time() - action["timestamp"]
                if age < 60:
                    time_str = f"{age:.0f}s ago"
                elif age < 3600:
                    time_str = f"{age/60:.0f}m ago"
                else:
                    time_str = f"{age/3600:.1f}h ago"

                level_str = f"L{action['level']}" if action["level"] else "—"
                action_table.add_row(time_str, level_str, action["action_type"], action["description"], action["status"])

            console.print(action_table)

        await db.close()

    asyncio.run(_status())


if __name__ == "__main__":
    cli()
