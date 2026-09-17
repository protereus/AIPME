"""Configuration and secrets.

The API token is a secret, so it is read from the environment rather than from
``aipme.toml``: files get committed by accident, environment variables do not.
"""

import os

from aipme.errors import ConfigError

TOKEN_ENV_VAR = "HCLOUD_TOKEN"

# Every server AIPME creates carries this label. Listing and deleting then ask
# the API "which servers are mine?" instead of keeping a local state file that
# could go stale or get deleted.
MANAGED_BY_LABEL = {"managed-by": "aipme"}
MANAGED_BY_SELECTOR = "managed-by=aipme"


def load_token() -> str:
    """Return the Hetzner API token, or raise ``ConfigError`` explaining how to set it."""
    token = os.environ.get(TOKEN_ENV_VAR, "").strip()
    if not token:
        raise ConfigError(
            f"{TOKEN_ENV_VAR} is not set. Create a Read & Write API token in the "
            "Hetzner Cloud Console (Security -> API tokens), put it in .env, and run "
            "commands with: uv run --env-file .env aipme ..."
        )
    return token
