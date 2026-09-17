import textwrap

import pytest

from aipme.config import TOKEN_ENV_VAR, load_config, load_token, read_public_key
from aipme.errors import ConfigError

VALID_CONFIG = """
[server]
name = "aipme-01"
type = "cx23"
location = "nbg1"
image = "ubuntu-24.04"
ssh_public_key = "~/.ssh/id_ed25519.pub"

[monitor]
cpu_threshold_percent = 85
memory_threshold_percent = 90
cooldown_minutes = 15

[ntfy]
topic = "aipme-secret-topic"
"""


def write_config(tmp_path, content=VALID_CONFIG):
    path = tmp_path / "aipme.toml"
    path.write_text(textwrap.dedent(content), encoding="utf-8")
    return path


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


def test_load_config_parses_every_section(tmp_path):
    config = load_config(write_config(tmp_path))

    assert config.server.name == "aipme-01"
    assert config.server.type == "cx23"
    assert config.monitor.cpu_threshold_percent == 85
    assert config.monitor.cooldown_minutes == 15
    assert config.ntfy.topic == "aipme-secret-topic"
    # "~" is expanded so the path can be opened directly.
    assert "~" not in str(config.server.ssh_public_key)


def test_missing_file_points_at_the_example(tmp_path):
    with pytest.raises(ConfigError, match="aipme.example.toml"):
        load_config(tmp_path / "absent.toml")


def test_invalid_toml_is_reported(tmp_path):
    path = tmp_path / "aipme.toml"
    path.write_text("[server\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="not valid TOML"):
        load_config(path)


def test_missing_section_is_reported(tmp_path):
    path = write_config(tmp_path, VALID_CONFIG.split("[ntfy]")[0])

    with pytest.raises(ConfigError, match=r"\[ntfy\]"):
        load_config(path)


def test_unknown_section_is_rejected(tmp_path):
    path = write_config(tmp_path, VALID_CONFIG + "\n[typo]\nkey = 1\n")

    with pytest.raises(ConfigError, match="typo"):
        load_config(path)


def test_typo_in_key_is_rejected(tmp_path):
    path = write_config(tmp_path, VALID_CONFIG.replace("cooldown_minutes", "cooldown_mins"))

    with pytest.raises(ConfigError, match="cooldown_mins"):
        load_config(path)


def test_threshold_out_of_range_is_rejected(tmp_path):
    path = write_config(
        tmp_path, VALID_CONFIG.replace("cpu_threshold_percent = 85", "cpu_threshold_percent = 150")
    )

    with pytest.raises(ConfigError, match="between 1 and 100"):
        load_config(path)


def test_threshold_must_be_a_whole_number(tmp_path):
    path = write_config(
        tmp_path, VALID_CONFIG.replace("cpu_threshold_percent = 85", "cpu_threshold_percent = true")
    )

    with pytest.raises(ConfigError, match="whole number"):
        load_config(path)


def test_invalid_server_name_is_rejected(tmp_path):
    path = write_config(
        tmp_path, VALID_CONFIG.replace('name = "aipme-01"', 'name = "not a hostname"')
    )

    with pytest.raises(ConfigError, match="valid hostname"):
        load_config(path)


def test_empty_string_is_rejected(tmp_path):
    path = write_config(
        tmp_path, VALID_CONFIG.replace('topic = "aipme-secret-topic"', 'topic = ""')
    )

    with pytest.raises(ConfigError, match="non-empty string"):
        load_config(path)


def test_read_public_key_strips_whitespace(tmp_path, public_key):
    path = tmp_path / "id_ed25519.pub"
    path.write_text(f"{public_key}\n", encoding="utf-8")

    assert read_public_key(path) == public_key


def test_read_public_key_refuses_a_private_key(tmp_path):
    path = tmp_path / "id_ed25519"
    path.write_text("-----BEGIN OPENSSH PRIVATE KEY-----\nabc\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="private"):
        read_public_key(path)


def test_read_public_key_reports_a_missing_file(tmp_path):
    with pytest.raises(ConfigError, match="ssh-keygen"):
        read_public_key(tmp_path / "absent.pub")


def test_read_public_key_rejects_unrelated_content(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("hello", encoding="utf-8")

    with pytest.raises(ConfigError, match="does not look like an SSH public key"):
        read_public_key(path)
