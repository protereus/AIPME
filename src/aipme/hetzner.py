"""A small, hand-written client for the parts of the Hetzner Cloud API we use.

Only a handful of endpoints are needed, so a thin wrapper around ``requests``
is easier to read (and to debug) than a full SDK. Every response goes through
one method, ``_request``, which is where authentication, timeouts and error
translation live.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import time
from collections.abc import Callable
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

# Server creation usually finishes in 10-20 seconds; the ceiling is generous
# so a slow location does not fail a working run.
DEFAULT_ACTION_TIMEOUT_SECONDS = 300.0
DEFAULT_POLL_INTERVAL_SECONDS = 2.0


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


@dataclass(frozen=True, slots=True)
class Action:
    """A long-running operation on the Hetzner side.

    Creating or deleting a server returns immediately with an Action whose
    status is usually ``running``. The work happens afterwards, so the client
    has to poll until the status becomes ``success`` or ``error``.
    """

    id: int
    command: str
    status: str
    progress: int
    error_code: str | None
    error_message: str | None

    @property
    def finished(self) -> bool:
        return self.status in ("success", "error")

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> Action:
        error = payload.get("error") or {}
        return cls(
            id=payload["id"],
            command=payload.get("command", "unknown"),
            status=payload.get("status", "running"),
            progress=int(payload.get("progress") or 0),
            error_code=error.get("code"),
            error_message=error.get("message"),
        )


@dataclass(frozen=True, slots=True)
class SshKey:
    """An SSH public key stored in the Hetzner project."""

    id: int
    name: str
    fingerprint: str

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> SshKey:
        return cls(
            id=payload["id"],
            name=payload["name"],
            fingerprint=payload.get("fingerprint", ""),
        )


def public_key_fingerprint(public_key: str) -> str:
    """Return the MD5 fingerprint Hetzner uses to identify an SSH key.

    An OpenSSH public key is ``<type> <base64 blob> [comment]``. The
    fingerprint is the MD5 digest of the raw blob, printed as colon-separated
    hex. MD5 is weak as a hash, but this is an identifier, not a security
    check - it is simply the format the API indexes keys by, which lets us ask
    "is this key already uploaded?" without guessing at names.
    """
    parts = public_key.split()
    if len(parts) < 2:
        raise HetznerError("Malformed SSH public key: expected '<type> <base64 key>'.")
    try:
        blob = base64.b64decode(parts[1], validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HetznerError("Malformed SSH public key: the key body is not valid base64.") from exc

    digest = hashlib.md5(blob, usedforsecurity=False).hexdigest()
    return ":".join(digest[i : i + 2] for i in range(0, len(digest), 2))


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

    def list_servers(
        self,
        *,
        label_selector: str | None = None,
        name: str | None = None,
    ) -> list[Server]:
        """Return all servers, optionally narrowed by label selector or exact name.

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
            if name:
                params["name"] = name

            payload = self._request("GET", "/servers", params=params)
            servers.extend(Server.from_api(entry) for entry in payload.get("servers", []))
            pagination = (payload.get("meta") or {}).get("pagination") or {}
            page = pagination.get("next_page")

        return servers

    def find_server_by_name(self, name: str) -> Server | None:
        """Return the server with this exact name, or ``None``.

        Server names are unique per project, which is what makes ``up`` safe to
        re-run: it can check first instead of creating a duplicate.
        """
        servers = self.list_servers(name=name)
        return servers[0] if servers else None

    def create_server(
        self,
        *,
        name: str,
        server_type: str,
        location: str,
        image: str,
        ssh_key_ids: list[int] | None = None,
        labels: dict[str, str] | None = None,
        user_data: str | None = None,
    ) -> tuple[Server, Action]:
        """Create a server and return it together with the creation Action."""
        body: dict[str, Any] = {
            "name": name,
            "server_type": server_type,
            "location": location,
            "image": image,
            "start_after_create": True,
        }
        if ssh_key_ids:
            body["ssh_keys"] = ssh_key_ids
        if labels:
            body["labels"] = labels
        if user_data:
            body["user_data"] = user_data

        payload = self._request("POST", "/servers", json_body=body)
        return Server.from_api(payload["server"]), Action.from_api(payload["action"])

    def delete_server(self, server_id: int) -> Action:
        """Delete a server and return the deletion Action."""
        payload = self._request("DELETE", f"/servers/{server_id}")
        return Action.from_api(payload["action"])

    def get_action(self, action_id: int) -> Action:
        """Fetch the current state of an Action."""
        payload = self._request("GET", f"/actions/{action_id}")
        return Action.from_api(payload["action"])

    def wait_for_action(
        self,
        action: Action,
        *,
        timeout: float = DEFAULT_ACTION_TIMEOUT_SECONDS,
        poll_interval: float = DEFAULT_POLL_INTERVAL_SECONDS,
        on_progress: Callable[[Action], None] | None = None,
    ) -> Action:
        """Poll an Action until it finishes, then return its final state.

        Raises ``HetznerError`` if the Action fails or the timeout is reached.
        The status is checked *before* sleeping, so an Action that is already
        finished costs no waiting at all.
        """
        deadline = time.monotonic() + timeout
        current = action

        while True:
            if current.status == "success":
                return current
            if current.status == "error":
                reason = current.error_message or current.error_code or "no reason given"
                raise HetznerError(f"Hetzner could not {current.command}: {reason}")
            if time.monotonic() >= deadline:
                raise HetznerError(
                    f"Timed out after {timeout:.0f}s waiting for {current.command} "
                    f"(action {current.id}, last progress {current.progress}%). "
                    "The operation may still finish - check with: aipme status"
                )

            if on_progress is not None:
                on_progress(current)

            time.sleep(poll_interval)
            current = self.get_action(current.id)

    def ensure_ssh_key(self, *, name: str, public_key: str) -> SshKey:
        """Return the project's SSH key for this public key, uploading it if needed.

        The lookup is by fingerprint rather than by name: the same key may
        already be stored under a different name, and uploading a duplicate is
        rejected by the API.
        """
        fingerprint = public_key_fingerprint(public_key)
        payload = self._request("GET", "/ssh_keys", params={"fingerprint": fingerprint})
        existing = payload.get("ssh_keys") or []
        if existing:
            return SshKey.from_api(existing[0])

        created = self._request(
            "POST",
            "/ssh_keys",
            json_body={"name": name, "public_key": public_key},
        )
        return SshKey.from_api(created["ssh_key"])

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
