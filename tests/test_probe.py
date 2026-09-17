import pytest
import requests
import responses

from aipme.errors import AipmeError
from aipme.probe import wait_for_http_ok

URL = "http://203.0.113.10/"


@responses.activate
def test_returns_as_soon_as_the_page_answers(fake_clock):
    clock = fake_clock("aipme.probe")
    responses.get(URL, status=200)

    wait_for_http_ok(URL, timeout=60, interval=5)

    assert len(responses.calls) == 1
    # A server that is ready costs no waiting at all.
    assert clock.sleeps == []


@responses.activate
def test_tolerates_refused_connections_while_the_server_boots(fake_clock):
    clock = fake_clock("aipme.probe")
    responses.get(URL, body=requests.ConnectionError("connection refused"))
    responses.get(URL, status=502)
    responses.get(URL, status=200)

    wait_for_http_ok(URL, timeout=60, interval=5)

    assert len(responses.calls) == 3
    assert clock.sleeps == [5, 5]


@responses.activate
def test_timeout_reports_the_last_outcome_and_where_to_look(fake_clock):
    fake_clock("aipme.probe")
    responses.get(URL, status=503)

    with pytest.raises(AipmeError) as excinfo:
        wait_for_http_ok(URL, timeout=30, interval=10)

    message = str(excinfo.value)
    assert "HTTP 503" in message
    assert "cloud-init-output.log" in message
    # The server is not deleted on a timeout, and the message says so.
    assert "still running" in message
