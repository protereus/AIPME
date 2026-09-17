import pytest

from aipme.config import TOKEN_ENV_VAR, load_token
from aipme.errors import ConfigError


def test_load_token_returns_trimmed_value(monkeypatch):
    monkeypatch.setenv(TOKEN_ENV_VAR, "  secret-token \n")

    assert load_token() == "secret-token"


@pytest.mark.parametrize("value", ["", "   "])
def test_missing_token_raises_with_guidance(monkeypatch, value):
    monkeypatch.setenv(TOKEN_ENV_VAR, value)

    with pytest.raises(ConfigError, match=TOKEN_ENV_VAR):
        load_token()


def test_unset_token_raises(monkeypatch):
    monkeypatch.delenv(TOKEN_ENV_VAR, raising=False)

    with pytest.raises(ConfigError):
        load_token()
