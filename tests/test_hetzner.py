import pytest
import requests
import responses

from aipme.errors import HetznerError
from aipme.hetzner import API_BASE_URL, HetznerClient

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
