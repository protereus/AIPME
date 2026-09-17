"""Build the cloud-init user data that configures the server on first boot.

Hetzner passes ``user_data`` to cloud-init, which runs it the first time the
server boots. That means no SSH from this machine, no waiting for port 22 and
no configuration drift: the server builds itself from a declarative document.

The document is written as JSON. YAML is a superset of JSON, so a
``#cloud-config`` header followed by JSON is valid cloud-init - which lets us
build it from an ordinary Python dict with no YAML dependency, and makes the
output trivial to assert on in tests.
"""

from __future__ import annotations

import json
from typing import Any

from aipme.errors import ConfigError

# Pinned on purpose: "latest" would make a rebuild next year behave differently.
APACHE_IMAGE = "httpd:2.4"

# Named so the container can be inspected and restarted by name over SSH.
APACHE_CONTAINER_NAME = "aipme-web"

# Hetzner rejects user data larger than 32 KiB.
MAX_USER_DATA_BYTES = 32 * 1024


def build_cloud_config() -> dict[str, Any]:
    """Return the cloud-config document as a plain dict.

    Kept separate from serialisation so tests can inspect the structure
    instead of parsing text.
    """
    return {
        # Refresh the package index first; a stale index is the usual cause of
        # "package not found" on a fresh image.
        "package_update": True,
        # Ubuntu's own Docker package. Simpler and more predictable than
        # piping a vendor install script into a shell.
        "packages": ["docker.io"],
        # Commands run as root, in order. Each is a list rather than a string,
        # so arguments are passed directly instead of going through a shell -
        # no quoting or word-splitting surprises.
        "runcmd": [
            ["systemctl", "enable", "--now", "docker"],
            [
                "docker",
                "run",
                "--detach",
                "--name",
                APACHE_CONTAINER_NAME,
                # Survives both a container crash and a server reboot.
                "--restart",
                "unless-stopped",
                "--publish",
                "80:80",
                APACHE_IMAGE,
            ],
        ],
    }


def build_user_data() -> str:
    """Serialise the cloud-config for the Hetzner ``user_data`` field."""
    document = build_cloud_config()
    user_data = "#cloud-config\n" + json.dumps(document, indent=2)

    size = len(user_data.encode("utf-8"))
    if size > MAX_USER_DATA_BYTES:
        raise ConfigError(
            f"Generated cloud-init user data is {size} bytes, over Hetzner's "
            f"{MAX_USER_DATA_BYTES} byte limit."
        )

    return user_data
