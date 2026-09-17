import json

import pytest
import requests
import responses

from aipme.errors import HetznerError
from aipme.hetzner import API_BASE_URL, Action, HetznerClient, public_key_fingerprint

SERVERS_URL = f"{API_BASE_URL}/servers"


def _server_payload(server_id: int = 42, name: str = "aipme-01", ipv4: str | None = "10.0.0.1"):
    return {
        "id": server_id,
        "name": name,
        "status": "running",
        "created": "2026-09-15T20:00:00+00:00",
        "public_net": {"ipv4": {"id": 1, "ip": ipv4} if ipv4 else None},
        "server_type": {"name": "cx23"},
        "location": {"name": "nbg1"},
        "labels": {"managed-by": "aipme"},
    }


def _page(servers, next_page=None):
    return {
        "servers": servers,
        "meta": {"pagination": {"page": 1, "per_page": 50, "next_page": next_page}},
    }


@pytest.fixture
def client():
    with HetznerClient("test-token") as hetzner_client:
        yield hetzner_client


@responses.activate
def test_list_servers_sends_token_and_selector(client):
    responses.get(SERVERS_URL, json=_page([_server_payload()]))

    servers = client.list_servers(label_selector="managed-by=aipme")

    assert len(servers) == 1
    assert servers[0].name == "aipme-01"
    assert servers[0].ipv4 == "10.0.0.1"
    assert servers[0].server_type == "cx23"
    assert servers[0].location == "nbg1"

    request = responses.calls[0].request
    assert request.headers["Authorization"] == "Bearer test-token"
    assert "label_selector=managed-by%3Daipme" in request.url


@responses.activate
def test_list_servers_follows_pagination(client):
    responses.get(SERVERS_URL, json=_page([_server_payload(1, "a")], next_page=2))
    responses.get(SERVERS_URL, json=_page([_server_payload(2, "b")]))

    names = [server.name for server in client.list_servers()]

    assert names == ["a", "b"]
    assert len(responses.calls) == 2


@responses.activate
def test_server_without_public_ipv4(client):
    responses.get(SERVERS_URL, json=_page([_server_payload(ipv4=None)]))

    assert client.list_servers()[0].ipv4 is None


@responses.activate
def test_unauthorized_error_mentions_the_token(client):
    responses.get(
        SERVERS_URL,
        status=401,
        json={"error": {"code": "unauthorized", "message": "unable to authenticate"}},
    )

    with pytest.raises(HetznerError) as excinfo:
        client.list_servers()

    message = str(excinfo.value)
    assert "unauthorized" in message
    assert "unable to authenticate" in message
    assert "HCLOUD_TOKEN" in message


@responses.activate
def test_error_without_json_body_still_raises(client):
    responses.get(SERVERS_URL, status=500, body="<html>gateway</html>")

    with pytest.raises(HetznerError, match="HTTP 500"):
        client.list_servers()


@responses.activate
def test_network_failure_is_wrapped(client):
    responses.get(SERVERS_URL, body=requests.ConnectionError("name resolution failed"))

    with pytest.raises(HetznerError, match="Could not reach the Hetzner API"):
        client.list_servers()


@responses.activate
def test_non_json_success_body_is_rejected(client):
    responses.get(SERVERS_URL, status=200, body="not json")

    with pytest.raises(HetznerError, match="non-JSON body"):
        client.list_servers()


ACTIONS_URL = f"{API_BASE_URL}/actions"
SSH_KEYS_URL = f"{API_BASE_URL}/ssh_keys"


def _action(status="running", action_id=1, command="create_server", error=None):
    return {
        "id": action_id,
        "command": command,
        "status": status,
        "progress": 0 if status == "running" else 100,
        "error": error,
    }


@responses.activate
def test_create_server_sends_expected_body(client):
    responses.post(
        SERVERS_URL,
        status=201,
        json={"server": _server_payload(), "action": _action(), "next_actions": []},
    )

    server, action = client.create_server(
        name="aipme-01",
        server_type="cx23",
        location="nbg1",
        image="ubuntu-24.04",
        ssh_key_ids=[7],
        labels={"managed-by": "aipme"},
        user_data="#cloud-config\n",
    )

    assert server.name == "aipme-01"
    assert action.status == "running"

    body = json.loads(responses.calls[0].request.body)
    assert body == {
        "name": "aipme-01",
        "server_type": "cx23",
        "location": "nbg1",
        "image": "ubuntu-24.04",
        "start_after_create": True,
        "ssh_keys": [7],
        "labels": {"managed-by": "aipme"},
        "user_data": "#cloud-config\n",
    }


@responses.activate
def test_delete_server_returns_action(client):
    responses.delete(
        f"{SERVERS_URL}/42",
        json={"action": _action(status="running", command="delete_server")},
    )

    action = client.delete_server(42)

    assert action.command == "delete_server"


@responses.activate
def test_wait_for_action_returns_immediately_when_finished(client):
    finished = client.wait_for_action(Action.from_api(_action(status="success")))

    assert finished.status == "success"
    # No polling request was needed, and therefore no sleeping.
    assert len(responses.calls) == 0


@responses.activate
def test_wait_for_action_polls_until_success(client, monkeypatch):
    monkeypatch.setattr("aipme.hetzner.time.sleep", lambda _seconds: None)
    responses.get(f"{ACTIONS_URL}/1", json={"action": _action(status="running")})
    responses.get(f"{ACTIONS_URL}/1", json={"action": _action(status="success")})

    finished = client.wait_for_action(
        Action.from_api(_action(status="running")),
        poll_interval=0,
    )

    assert finished.status == "success"
    assert len(responses.calls) == 2


@responses.activate
def test_wait_for_action_raises_on_action_error(client):
    failed = Action.from_api(
        _action(status="error", error={"code": "resource_limit_exceeded", "message": "no capacity"})
    )

    with pytest.raises(HetznerError, match="no capacity"):
        client.wait_for_action(failed)


@responses.activate
def test_wait_for_action_times_out(client, monkeypatch):
    monkeypatch.setattr("aipme.hetzner.time.sleep", lambda _seconds: None)
    clock = iter([0.0, 0.0, 999.0])
    monkeypatch.setattr("aipme.hetzner.time.monotonic", lambda: next(clock))
    responses.get(f"{ACTIONS_URL}/1", json={"action": _action(status="running")})

    with pytest.raises(HetznerError, match="Timed out"):
        client.wait_for_action(Action.from_api(_action(status="running")), poll_interval=0)


@responses.activate
def test_find_server_by_name_filters_on_name(client):
    responses.get(SERVERS_URL, json=_page([_server_payload()]))

    server = client.find_server_by_name("aipme-01")

    assert server is not None
    assert "name=aipme-01" in responses.calls[0].request.url


@responses.activate
def test_find_server_by_name_returns_none_when_absent(client):
    responses.get(SERVERS_URL, json=_page([]))

    assert client.find_server_by_name("aipme-01") is None


def test_public_key_fingerprint_is_colon_separated_md5(public_key):
    fingerprint = public_key_fingerprint(public_key)

    assert len(fingerprint) == 47
    assert fingerprint.count(":") == 15


@pytest.mark.parametrize("bad_key", ["ssh-ed25519", "ssh-ed25519 not-base64!!"])
def test_public_key_fingerprint_rejects_malformed_keys(bad_key):
    with pytest.raises(HetznerError, match="Malformed SSH public key"):
        public_key_fingerprint(bad_key)


@responses.activate
def test_ensure_ssh_key_reuses_an_existing_key(client, public_key):
    responses.get(
        SSH_KEYS_URL,
        json={"ssh_keys": [{"id": 7, "name": "laptop", "fingerprint": "aa:bb"}]},
    )

    key = client.ensure_ssh_key(name="aipme-01", public_key=public_key)

    assert key.id == 7
    assert key.name == "laptop"
    # Looked up by fingerprint, so a key stored under another name is still found.
    assert "fingerprint=" in responses.calls[0].request.url
    assert len(responses.calls) == 1


@responses.activate
def test_ensure_ssh_key_uploads_when_missing(client, public_key):
    responses.get(SSH_KEYS_URL, json={"ssh_keys": []})
    responses.post(
        SSH_KEYS_URL,
        status=201,
        json={"ssh_key": {"id": 9, "name": "aipme-01", "fingerprint": "cc:dd"}},
    )

    key = client.ensure_ssh_key(name="aipme-01", public_key=public_key)

    assert key.id == 9
    body = json.loads(responses.calls[1].request.body)
    assert body == {"name": "aipme-01", "public_key": public_key}
