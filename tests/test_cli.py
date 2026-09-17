import responses
from typer.testing import CliRunner

from aipme import __version__
from aipme.cli import app
from aipme.config import TOKEN_ENV_VAR
from aipme.hetzner import API_BASE_URL

runner = CliRunner()
SERVERS_URL = f"{API_BASE_URL}/servers"

SERVER = {
    "id": 42,
    "name": "aipme-01",
    "status": "running",
    "created": "2026-09-15T20:00:00+00:00",
    "public_net": {"ipv4": {"id": 1, "ip": "203.0.113.10"}},
    "server_type": {"name": "cx23"},
    "location": {"name": "nbg1"},
}
EMPTY_PAGE = {"servers": [], "meta": {"pagination": {"page": 1, "next_page": None}}}


def test_version_flag_prints_version() -> None:
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.output.strip() == f"aipme {__version__}"


def test_no_arguments_shows_help() -> None:
    result = runner.invoke(app, [])

    assert "Usage" in result.output


def test_status_without_token_exits_with_error(monkeypatch) -> None:
    monkeypatch.delenv(TOKEN_ENV_VAR, raising=False)

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 1
    assert TOKEN_ENV_VAR in result.output


@responses.activate
def test_status_lists_servers(monkeypatch) -> None:
    monkeypatch.setenv(TOKEN_ENV_VAR, "test-token")
    responses.get(
        SERVERS_URL,
        json={"servers": [SERVER], "meta": {"pagination": {"page": 1, "next_page": None}}},
    )

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0
    assert "aipme-01" in result.output
    assert "203.0.113.10" in result.output
    assert "cx23" in result.output


@responses.activate
def test_status_with_no_servers_explains_next_step(monkeypatch) -> None:
    monkeypatch.setenv(TOKEN_ENV_VAR, "test-token")
    responses.get(SERVERS_URL, json=EMPTY_PAGE)

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0
    assert "No servers found" in result.output


@responses.activate
def test_status_reports_api_error(monkeypatch) -> None:
    monkeypatch.setenv(TOKEN_ENV_VAR, "bad-token")
    responses.get(
        SERVERS_URL,
        status=401,
        json={"error": {"code": "unauthorized", "message": "unable to authenticate"}},
    )

    result = runner.invoke(app, ["status"])

    assert result.exit_code == 1
    assert "unauthorized" in result.output
