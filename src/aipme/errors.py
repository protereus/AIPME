"""Exception types shared across AIPME.

Everything that can go wrong in a *predictable* way raises an ``AipmeError``.
The CLI catches that one type, prints the message and exits with status 1, so
the user sees a clear sentence instead of a Python traceback. Anything that is
*not* an ``AipmeError`` is a bug, and a traceback is the right response to it.
"""


class AipmeError(Exception):
    """Base class for expected, user-facing failures."""


class ConfigError(AipmeError):
    """Configuration is missing or invalid."""


class HetznerError(AipmeError):
    """The Hetzner Cloud API could not be reached, or answered with an error."""
