"""Command-line interface for AIPME."""

from datetime import UTC
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from aipme import __version__
from aipme.config import MANAGED_BY_SELECTOR, load_token
from aipme.errors import AipmeError
from aipme.hetzner import HetznerClient, Server

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
)

console = Console()
error_console = Console(stderr=True)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"aipme {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            "-V",
            help="Show the version and exit.",
            callback=_version_callback,
            is_eager=True,
        ),
    ] = False,
) -> None:
    """Provision a Hetzner Cloud server and monitor it with push alerts."""


@app.command()
def status() -> None:
    """List the servers AIPME manages."""
    try:
        token = load_token()
        with HetznerClient(token) as client:
            servers = client.list_servers(label_selector=MANAGED_BY_SELECTOR)
    except AipmeError as exc:
        # Expected failures (no token, API refused us) get one clear line on
        # stderr and a non-zero exit code, so scripts and CI can react to them.
        error_console.print(f"[bold red]Error:[/bold red] {exc}")
        raise typer.Exit(code=1) from exc

    if not servers:
        console.print(
            f"No servers found with label [bold]{MANAGED_BY_SELECTOR}[/bold]. "
            "Create one with [bold]aipme up[/bold]."
        )
        return

    console.print(_servers_table(servers))


def _servers_table(servers: list[Server]) -> Table:
    """Render servers as a table, sorted by name."""
    table = Table(title=f"AIPME servers ({len(servers)})", title_style="bold")
    table.add_column("Name")
    table.add_column("Status")
    table.add_column("IPv4")
    table.add_column("Type")
    table.add_column("Location")
    table.add_column("Created (UTC)")

    for server in sorted(servers, key=lambda server: server.name):
        # Hetzner timestamps carry an offset; normalise so the column header
        # ("Created (UTC)") is honest whatever offset the API sends.
        created = (
            server.created.astimezone(UTC).strftime("%Y-%m-%d %H:%M") if server.created else "?"
        )
        table.add_row(
            server.name,
            _status_markup(server.status),
            server.ipv4 or "-",
            server.server_type,
            server.location,
            created,
        )

    return table


def _status_markup(status: str) -> str:
    """Colour the status so a problem is visible at a glance."""
    colours = {
        "running": "green",
        "initializing": "yellow",
        "starting": "yellow",
        "stopping": "yellow",
        "deleting": "yellow",
        "off": "red",
    }
    colour = colours.get(status, "white")
    return f"[{colour}]{status}[/{colour}]"
