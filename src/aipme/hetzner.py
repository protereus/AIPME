"""A small, hand-written client for the parts of the Hetzner Cloud API we use.

Only a handful of endpoints are needed, so a thin wrapper around ``requests``
is easier to read (and to debug) than a full SDK. Every response goes through
one method, ``_request``, which is where authentication, timeouts and error
translation live.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from aipme import __version__
from aipme.errors import HetznerError

API_BASE_URL = "https://api.hetzner.cloud/v1"

# Never leave a request without a timeout: without one, a hung connection
# hangs the CLI for ever.
DEFAULT_TIMEOUT_SECONDS = 30.0

# The API returns at most 50 entries per page.
MAX_PER_PAGE = 50

# Stops a broken "next_page" response from looping for ever.
MAX_PAGES = 50


@dataclass(frozen=True, slots=True)
class Server:
    """The fields of a Hetzner server that AIPME actually uses."""

    id: int
    name: str
    status: str
    ipv4: str | None
    server_type: str
    location: str
    created: datetime | None

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> Server:
        """Build a ``Server`` from one entry of the API's ``servers`` array.

        The API sends far more fields than we need, and a server without a
        public IPv4 address has ``public_net.ipv4 = null``, so the lookups are
        deliberately defensive.
        """
        public_net = payload.get("public_net") or {}
        ipv4 = public_net.get("ipv4") or {}
        created_raw = payload.get("created")

        return cls(
            id=payload["id"],
            name=payload["name"],
            status=payload.get("status", "unknown"),
            ipv4=ipv4.get("ip"),
            server_type=(payload.get("server_type") or {}).get("name", "?"),
            location=(payload.get("location") or {}).get("name", "?"),
            created=_parse_timestamp(created_raw),
        )


def _parse_timestamp(value: object) -> datetime | None:
    """Parse the API's RFC 3339 timestamps, tolerating anything unexpected."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


class HetznerClient:
    """Authenticated access to the Hetzner Cloud API."""

    def __init__(
        self,
        token: str,
        *,
        base_url: str = API_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "User-Agent": f"aipme/{__version__}",
            }
        )

        # Retry only the safe methods. A retried GET is harmless; a retried
        # POST could create a second server, so server creation must fail
        # loudly instead. 429 is Hetzner's rate limit, 5xx is its side failing.
        retry = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET", "DELETE"}),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        self._session.mount("https://", adapter)
        self._session.mount("http://", adapter)

    def close(self) -> None:
        """Close the underlying HTTP connection pool."""
        self._session.close()

    def __enter__(self) -> HetznerClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def list_servers(self, *, label_selector: str | None = None) -> list[Server]:
        """Return all servers, optionally narrowed to a label selector.

        Results are paginated, so this keeps following ``meta.pagination.next_page``
        until the API says there are no more pages.
        """
        servers: list[Server] = []
        page: int | None = 1

        for _ in range(MAX_PAGES):
            if page is None:
                break

            params: dict[str, Any] = {"page": page, "per_page": MAX_PER_PAGE}
            if label_selector:
                params["label_selector"] = label_selector

            payload = self._request("GET", "/servers", params=params)
            servers.extend(Server.from_api(entry) for entry in payload.get("servers", []))
            pagination = (payload.get("meta") or {}).get("pagination") or {}
            page = pagination.get("next_page")

        return servers

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Send one request and return the decoded JSON body.

        Every failure mode - no network, a timeout, an HTTP error, a body that
        is not JSON - is turned into a ``HetznerError`` carrying a message that
        makes sense to whoever ran the command.
        """
        url = f"{self._base_url}{path}"
        try:
            response = self._session.request(
                method,
                url,
                params=params,
                json=json_body,
                timeout=self._timeout,
            )
        except requests.RequestException as exc:
            raise HetznerError(f"Could not reach the Hetzner API at {url}: {exc}") from exc

        if response.status_code >= 400:
            raise HetznerError(_describe_error(response))

        if not response.content:
            return {}

        try:
            body = response.json()
        except ValueError as exc:
            raise HetznerError(
                f"The Hetzner API returned a non-JSON body for {method} {path} "
                f"(HTTP {response.status_code})."
            ) from exc

        if not isinstance(body, dict):
            raise HetznerError(f"Unexpected JSON shape for {method} {path}: expected an object.")

        return body


def _describe_error(response: requests.Response) -> str:
    """Turn an error response into one readable sentence.

    Hetzner replies with ``{"error": {"code": ..., "message": ...}}``. The code
    is for machines, the message for humans, and both are worth showing: the
    code is what you search the docs for.
    """
    code = ""
    message = response.reason or ""
    try:
        error = response.json().get("error") or {}
    except ValueError:
        error = {}
    if isinstance(error, dict):
        code = str(error.get("code", "") or "")
        message = str(error.get("message", "") or message)

    detail = f"Hetzner API error (HTTP {response.status_code}"
    detail += f", {code}): " if code else "): "
    detail += message or "no message returned"

    if response.status_code in (401, 403):
        detail += " - check that HCLOUD_TOKEN is correct and has Read & Write permission."
    elif code == "rate_limit_exceeded":
        detail += " - the request was retried and is still rate limited; try again shortly."

    return detail
