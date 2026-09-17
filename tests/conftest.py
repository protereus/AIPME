"""Shared test fixtures."""

import pytest

# A real (throwaway) ed25519 public key, wrapped only to respect the line length.
_PUBLIC_KEY = (
    "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIGvLKbGHXBhkFYFPVYQ0dvYv0pQxRjk1j6CA6gpZBBz9 aipme"
)


@pytest.fixture
def public_key() -> str:
    """An SSH public key in the format the Hetzner API expects."""
    return _PUBLIC_KEY
