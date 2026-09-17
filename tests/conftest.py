"""Shared test fixtures."""

from __future__ import annotations

import pytest

# A real (throwaway) ed25519 public key, wrapped only to respect the line length.
_PUBLIC_KEY = (
    "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIGvLKbGHXBhkFYFPVYQ0dvYv0pQxRjk1j6CA6gpZBBz9 aipme"
)


@pytest.fixture
def public_key() -> str:
    """An SSH public key in the format the Hetzner API expects."""
    return _PUBLIC_KEY


class FakeClock:
    """A stand-in for the ``time`` module, so waiting code can be tested instantly.

    Replacing the module object (rather than patching ``time.sleep`` itself)
    keeps the fake local to the module under test: the real ``time`` module is
    shared with requests, urllib3 and Rich, and patching it globally makes
    unrelated code misbehave.
    """

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def fake_clock(monkeypatch):
    """Return a factory that swaps a module's ``time`` for a controllable fake."""

    def install(module_path: str) -> FakeClock:
        clock = FakeClock()
        monkeypatch.setattr(f"{module_path}.time", clock)
        return clock

    return install
