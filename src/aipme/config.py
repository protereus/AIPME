"""Configuration and secrets.

Settings live in ``aipme.toml`` (parsed with the standard library's ``tomllib``),
while the API token comes from the environment. Files get committed by accident;
environment variables do not.

Everything is validated up front. Catching a typo here costs a second; catching
it after a server has been created costs money and confusion.
"""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aipme.errors import ConfigError

TOKEN_ENV_VAR = "HCLOUD_TOKEN"
DEFAULT_CONFIG_PATH = Path("aipme.toml")

# Every server AIPME creates carries this label. Listing and deleting then ask
# the API "which servers are mine?" instead of keeping a local state file that
# could go stale or get deleted.
MANAGED_BY_LABEL = {"managed-by": "aipme"}
MANAGED_BY_SELECTOR = "managed-by=aipme"

# Hetzner requires server names to be valid hostnames (RFC 1123). Checking it
# here gives a clearer message than the API's rejection would.
HOSTNAME_PATTERN = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class ServerConfig:
    name: str
    type: str
    location: str
    image: str
    ssh_public_key: Path


@dataclass(frozen=True, slots=True)
class MonitorConfig:
    cpu_threshold_percent: int
    memory_threshold_percent: int
    cooldown_minutes: int


@dataclass(frozen=True, slots=True)
class NtfyConfig:
    topic: str


@dataclass(frozen=True, slots=True)
class Config:
    server: ServerConfig
    monitor: MonitorConfig
    ntfy: NtfyConfig


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


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> Config:
    """Read and validate ``aipme.toml``."""
    try:
        raw = path.read_bytes()
    except FileNotFoundError as exc:
        raise ConfigError(
            f"No configuration file at {path}. Copy aipme.example.toml to {path} and edit it."
        ) from exc
    except OSError as exc:
        raise ConfigError(f"Could not read {path}: {exc}") from exc

    try:
        data = tomllib.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"{path} is not valid TOML: {exc}") from exc

    _reject_unknown(data, {"server", "monitor", "ntfy"}, where=str(path))

    server_table = _table(data, "server", path)
    monitor_table = _table(data, "monitor", path)
    ntfy_table = _table(data, "ntfy", path)

    _reject_unknown(
        server_table,
        {"name", "type", "location", "image", "ssh_public_key"},
        where=f"{path} [server]",
    )
    _reject_unknown(
        monitor_table,
        {"cpu_threshold_percent", "memory_threshold_percent", "cooldown_minutes"},
        where=f"{path} [monitor]",
    )
    _reject_unknown(ntfy_table, {"topic"}, where=f"{path} [ntfy]")

    name = _string(server_table, "name", "server")
    if not HOSTNAME_PATTERN.match(name):
        raise ConfigError(
            f"server.name '{name}' is not a valid hostname: use letters, digits and "
            "hyphens only, starting and ending with a letter or digit."
        )

    server = ServerConfig(
        name=name,
        type=_string(server_table, "type", "server"),
        location=_string(server_table, "location", "server"),
        image=_string(server_table, "image", "server"),
        ssh_public_key=Path(_string(server_table, "ssh_public_key", "server")).expanduser(),
    )
    monitor = MonitorConfig(
        cpu_threshold_percent=_int(monitor_table, "cpu_threshold_percent", "monitor", 1, 100),
        memory_threshold_percent=_int(monitor_table, "memory_threshold_percent", "monitor", 1, 100),
        cooldown_minutes=_int(monitor_table, "cooldown_minutes", "monitor", 0, 1440),
    )
    ntfy = NtfyConfig(topic=_string(ntfy_table, "topic", "ntfy"))

    return Config(server=server, monitor=monitor, ntfy=ntfy)


def read_public_key(path: Path) -> str:
    """Read an SSH *public* key, with a guard against the commonest mistake.

    Pointing this at ``id_ed25519`` instead of ``id_ed25519.pub`` would upload a
    private key to a third party, so that case is refused loudly.
    """
    try:
        content = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError as exc:
        raise ConfigError(
            f"SSH public key not found at {path}. Generate one with: "
            'ssh-keygen -t ed25519 -C "aipme"'
        ) from exc
    except OSError as exc:
        raise ConfigError(f"Could not read {path}: {exc}") from exc

    if "PRIVATE KEY" in content:
        raise ConfigError(
            f"{path} looks like a *private* key. Point server.ssh_public_key at the "
            "matching .pub file instead."
        )
    if not content.startswith(("ssh-", "ecdsa-", "sk-")):
        raise ConfigError(f"{path} does not look like an SSH public key.")

    return content


def _table(data: dict[str, Any], name: str, path: Path) -> dict[str, Any]:
    section = data.get(name)
    if section is None:
        raise ConfigError(f"{path} is missing the [{name}] section.")
    if not isinstance(section, dict):
        raise ConfigError(f"{path}: [{name}] must be a section, not a single value.")
    return section


def _reject_unknown(table: dict[str, Any], allowed: set[str], *, where: str) -> None:
    """Fail on keys we do not understand, so typos cannot be silently ignored."""
    unknown = sorted(set(table) - allowed)
    if unknown:
        raise ConfigError(
            f"{where}: unknown key(s) {', '.join(unknown)}. Allowed: {', '.join(sorted(allowed))}."
        )


def _string(table: dict[str, Any], key: str, section: str) -> str:
    value = table.get(key)
    if value is None:
        raise ConfigError(f"[{section}] is missing '{key}'.")
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"[{section}] '{key}' must be a non-empty string.")
    return value.strip()


def _int(table: dict[str, Any], key: str, section: str, minimum: int, maximum: int) -> int:
    value = table.get(key)
    if value is None:
        raise ConfigError(f"[{section}] is missing '{key}'.")
    # bool is a subclass of int in Python, so it has to be excluded explicitly.
    if not isinstance(value, int) or isinstance(value, bool):
        raise ConfigError(f"[{section}] '{key}' must be a whole number.")
    if not minimum <= value <= maximum:
        raise ConfigError(f"[{section}] '{key}' must be between {minimum} and {maximum}.")
    return value
