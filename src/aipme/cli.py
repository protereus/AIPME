"""Command-line interface for AIPME."""

from typing import Annotated

import typer

from aipme import __version__

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
)


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
