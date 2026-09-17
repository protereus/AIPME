import json

import pytest
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


CONFIG = """
[server]
name = "aipme-01"
type = "cx23"
location = "nbg1"
image = "ubuntu-24.04"
ssh_public_key = "{key_path}"

[monitor]
cpu_threshold_percent = 85
memory_threshold_percent = 90
cooldown_minutes = 15

[ntfy]
topic = "aipme-secret-topic"
"""

SSH_KEYS_URL = f"{API_BASE_URL}/ssh_keys"
EXISTING_KEY = {"ssh_keys": [{"id": 7, "name": "laptop", "fingerprint": "x"}]}


def _finished_action(action_id, command):
    return {"action": {"id": action_id, "command": command, "status": "success", "progress": 100}}


@pytest.fixture
def project(tmp_path, monkeypatch, public_key):
    """A temporary config file plus public key, with the token set."""
    monkeypatch.setenv(TOKEN_ENV_VAR, "test-token")
    key_path = tmp_path / "id_ed25519.pub"
    key_path.write_text(public_key, encoding="utf-8")
    config_path = tmp_path / "aipme.toml"
    config_path.write_text(CONFIG.format(key_path=key_path.as_posix()), encoding="utf-8")
    return config_path


def _page(servers):
    return {"servers": servers, "meta": {"pagination": {"page": 1, "next_page": None}}}


@responses.activate
def test_up_creates_a_server_and_waits_for_apache(project):
    responses.get(SERVERS_URL, json=_page([]))  # name lookup: nothing yet
    responses.get(
        SSH_KEYS_URL, json={"ssh_keys": [{"id": 7, "name": "laptop", "fingerprint": "x"}]}
    )
    responses.post(
        SERVERS_URL,
        status=201,
        json={
            "server": SERVER,
            "action": _finished_action(1, "create_server")["action"],
        },
    )
    responses.get(SERVERS_URL, json=_page([SERVER]))  # refresh after creation
    responses.get("http://203.0.113.10/", status=200)  # Apache answers

    result = runner.invoke(app, ["up", "--config", str(project)])

    assert result.exit_code == 0, result.output
    assert "Created" in result.output
    assert "ssh root@203.0.113.10" in result.output
    assert "Apache is serving" in result.output

    body = json.loads(responses.calls[2].request.body)
    assert body["labels"] == {"managed-by": "aipme"}
    assert body["ssh_keys"] == [7]
    # cloud-init does the configuring, so the server needs the document at birth.
    assert body["user_data"].startswith("#cloud-config")
    assert "docker.io" in body["user_data"]


@responses.activate
def test_up_no_wait_skips_the_web_check(project):
    responses.get(SERVERS_URL, json=_page([]))
    responses.get(SSH_KEYS_URL, json=EXISTING_KEY)
    responses.post(
        SERVERS_URL,
        status=201,
        json={"server": SERVER, "action": _finished_action(1, "create_server")["action"]},
    )
    responses.get(SERVERS_URL, json=_page([SERVER]))

    result = runner.invoke(app, ["up", "--config", str(project), "--no-wait"])

    assert result.exit_code == 0, result.output
    assert "Apache is serving" not in result.output


@responses.activate
def test_up_reports_a_server_that_never_serves(project, fake_clock):
    fake_clock("aipme.probe")
    responses.get(SERVERS_URL, json=_page([]))
    responses.get(SSH_KEYS_URL, json=EXISTING_KEY)
    responses.post(
        SERVERS_URL,
        status=201,
        json={"server": SERVER, "action": _finished_action(1, "create_server")["action"]},
    )
    responses.get(SERVERS_URL, json=_page([SERVER]))
    responses.get("http://203.0.113.10/", status=503)

    result = runner.invoke(app, ["up", "--config", str(project)])

    assert result.exit_code == 1
    # The server was created, so the output still shows it before the warning.
    assert "Created" in result.output
    assert "did not return HTTP 200" in result.output


@responses.activate
def test_up_is_idempotent(project):
    responses.get(SERVERS_URL, json=_page([SERVER]))

    result = runner.invoke(app, ["up", "--config", str(project)])

    assert result.exit_code == 0
    assert "already exists" in result.output
    # Only the lookup happened: no server was created.
    assert len(responses.calls) == 1


@responses.activate
def test_up_reports_a_failed_creation_action(project, fake_clock):
    fake_clock("aipme.hetzner")
    responses.get(SERVERS_URL, json=_page([]))
    responses.get(
        SSH_KEYS_URL, json={"ssh_keys": [{"id": 7, "name": "laptop", "fingerprint": "x"}]}
    )
    responses.post(
        SERVERS_URL,
        status=201,
        json={
            "server": SERVER,
            "action": {
                "id": 1,
                "command": "create_server",
                "status": "error",
                "progress": 0,
                "error": {"code": "resource_unavailable", "message": "no capacity in nbg1"},
            },
        },
    )

    result = runner.invoke(app, ["up", "--config", str(project)])

    assert result.exit_code == 1
    assert "no capacity in nbg1" in result.output


def test_up_without_config_file_explains_how_to_fix_it(tmp_path, monkeypatch):
    monkeypatch.setenv(TOKEN_ENV_VAR, "test-token")

    result = runner.invoke(app, ["up", "--config", str(tmp_path / "absent.toml")])

    assert result.exit_code == 1
    assert "aipme.example.toml" in result.output


@responses.activate
def test_down_asks_before_deleting(project):
    responses.get(SERVERS_URL, json=_page([SERVER]))

    result = runner.invoke(app, ["down"], input="n\n")

    assert result.exit_code == 1  # aborted
    assert "aipme-01" in result.output
    # The listing happened, the delete did not.
    assert len(responses.calls) == 1


@responses.activate
def test_down_deletes_with_yes(project):
    responses.get(SERVERS_URL, json=_page([SERVER]))
    responses.delete(
        f"{SERVERS_URL}/42",
        json={
            "action": {"id": 2, "command": "delete_server", "status": "success", "progress": 100}
        },
    )

    result = runner.invoke(app, ["down", "--yes"])

    assert result.exit_code == 0
    assert "Deleted" in result.output
    assert responses.calls[1].request.method == "DELETE"


@responses.activate
def test_down_with_nothing_to_delete(project):
    responses.get(SERVERS_URL, json=_page([]))

    result = runner.invoke(app, ["down"])

    assert result.exit_code == 0
    assert "Nothing to delete" in result.output
