"""Command-line interface for AIPME."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from aipme import __version__
from aipme.config import (
    DEFAULT_CONFIG_PATH,
    MANAGED_BY_LABEL,
    MANAGED_BY_SELECTOR,
    load_config,
    load_token,
    read_public_key,
)
from aipme.errors import AipmeError
from aipme.hetzner import HetznerClient, Server

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
)

console = Console()
error_console = Console(stderr=True)

ConfigOption = Annotated[
    Path,
    typer.Option("--config", "-c", help="Path to the configuration file."),
]


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


@contextmanager
def _reporting_errors() -> Iterator[None]:
    """Turn expected failures into one red line and exit code 1.

    Only ``AipmeError`` is caught. Anything else is a bug, and a traceback is
    more useful than a polite message.
    """
    try:
        yield
    except AipmeError as exc:
        error_console.print(f"[bold red]Error:[/bold red] {exc}")
        raise typer.Exit(code=1) from exc


@app.command()
def status() -> None:
    """List the servers AIPME manages."""
    with _reporting_errors():
        token = load_token()
        with HetznerClient(token) as client:
            servers = client.list_servers(label_selector=MANAGED_BY_SELECTOR)

    if not servers:
        console.print(
            f"No servers found with label [bold]{MANAGED_BY_SELECTOR}[/bold]. "
            "Create one with [bold]aipme up[/bold]."
        )
        return

    console.print(_servers_table(servers))


@app.command()
def up(config_path: ConfigOption = DEFAULT_CONFIG_PATH) -> None:
    """Create the server described by the configuration file."""
    with _reporting_errors():
        token = load_token()
        config = load_config(config_path)
        public_key = read_public_key(config.server.ssh_public_key)

        with HetznerClient(token) as client:
            # Server names are unique per project, so checking first makes
            # `up` safe to re-run: no duplicate server, no surprise bill.
            existing = client.find_server_by_name(config.server.name)
            if existing is not None:
                console.print(
                    f"Server [bold]{existing.name}[/bold] already exists - nothing to do."
                )
                console.print(_servers_table([existing]))
                return

            ssh_key = client.ensure_ssh_key(name=config.server.name, public_key=public_key)
            server, action = client.create_server(
                name=config.server.name,
                server_type=config.server.type,
                location=config.server.location,
                image=config.server.image,
                ssh_key_ids=[ssh_key.id],
                labels=MANAGED_BY_LABEL,
            )

            # The API returned straight away; the server is still being built.
            with console.status(f"Creating {server.name} ({config.server.type})..."):
                client.wait_for_action(action)

            # Re-read the server so the IP address and status are current.
            server = client.find_server_by_name(config.server.name) or server

    _print_created(server)


@app.command()
def down(
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Skip the confirmation prompt."),
    ] = False,
) -> None:
    """Delete the servers AIPME manages.

    Servers are found by label, not by the configuration file, so a server
    created with different settings earlier is still cleaned up.
    """
    with _reporting_errors():
        token = load_token()

        with HetznerClient(token) as client:
            servers = client.list_servers(label_selector=MANAGED_BY_SELECTOR)
            if not servers:
                console.print("Nothing to delete - no AIPME servers found.")
                return

            console.print(_servers_table(servers))
            if not yes:
                # Deleting a server is permanent, so the default answer is no.
                typer.confirm(
                    f"Permanently delete {len(servers)} server(s)?",
                    default=False,
                    abort=True,
                )

            for server in servers:
                action = client.delete_server(server.id)
                with console.status(f"Deleting {server.name}..."):
                    client.wait_for_action(action)
                console.print(f"Deleted [bold]{server.name}[/bold].")


def _print_created(server: Server) -> None:
    """Tell the user what exists now and what to do next."""
    console.print(f"Created [bold]{server.name}[/bold] in {server.location}.")
    console.print(_servers_table([server]))
    if server.ipv4:
        console.print(f"Connect with: [bold]ssh root@{server.ipv4}[/bold]")
    console.print(
        "Hetzner bills by the hour - remove it with [bold]aipme down[/bold] when you are done."
    )


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
