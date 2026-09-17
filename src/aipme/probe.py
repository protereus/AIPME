"""Wait for the newly provisioned server to serve its web page.

The Hetzner action finishing only means the virtual machine exists. cloud-init
then has to install Docker and pull the Apache image, which takes a minute or
two. The only honest way to know it worked is to ask the server itself.
"""

from __future__ import annotations

import time

import requests

from aipme.errors import AipmeError

DEFAULT_WAIT_TIMEOUT_SECONDS = 300.0
DEFAULT_WAIT_INTERVAL_SECONDS = 5.0

# Short per-request timeout: while the server boots, connections hang rather
# than being refused, and a long timeout would blur the polling interval.
REQUEST_TIMEOUT_SECONDS = 5.0


def wait_for_http_ok(
    url: str,
    *,
    timeout: float = DEFAULT_WAIT_TIMEOUT_SECONDS,
    interval: float = DEFAULT_WAIT_INTERVAL_SECONDS,
) -> None:
    """Poll ``url`` until it answers 200, or raise ``AipmeError`` on timeout.

    Connection errors are expected here, not exceptional: the port is closed
    until Docker publishes it. Anything that is not a 200 simply means "not
    ready yet", so the loop keeps the last outcome and reports it if time runs
    out - that description is what makes a failure debuggable.
    """
    deadline = time.monotonic() + timeout
    last_outcome = "no response yet"

    while True:
        try:
            response = requests.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
            if response.status_code == 200:
                return
            last_outcome = f"HTTP {response.status_code}"
        except requests.RequestException as exc:
            last_outcome = type(exc).__name__

        if time.monotonic() >= deadline:
            raise AipmeError(
                f"{url} did not return HTTP 200 within {timeout:.0f}s (last: {last_outcome}). "
                "The server exists and is still running. Check cloud-init on it with: "
                "journalctl -u cloud-final  or  cat /var/log/cloud-init-output.log"
            )

        time.sleep(interval)
