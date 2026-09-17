import json

import pytest

from aipme import cloud_init
from aipme.cloud_init import (
    APACHE_CONTAINER_NAME,
    APACHE_IMAGE,
    build_cloud_config,
    build_user_data,
)
from aipme.errors import ConfigError


def test_cloud_config_installs_docker():
    document = build_cloud_config()

    assert document["package_update"] is True
    assert document["packages"] == ["docker.io"]


def test_cloud_config_starts_docker_before_using_it():
    commands = build_cloud_config()["runcmd"]

    assert commands[0] == ["systemctl", "enable", "--now", "docker"]
    assert commands[1][:2] == ["docker", "run"]


def test_apache_container_survives_reboots_and_crashes():
    docker_run = build_cloud_config()["runcmd"][1]

    assert APACHE_IMAGE in docker_run
    assert "unless-stopped" in docker_run
    assert "80:80" in docker_run
    assert APACHE_CONTAINER_NAME in docker_run


def test_every_command_is_a_list_not_a_string():
    """List form passes arguments directly, avoiding shell quoting surprises."""
    assert all(isinstance(command, list) for command in build_cloud_config()["runcmd"])


def test_image_tag_is_pinned():
    assert APACHE_IMAGE != "httpd:latest"
    assert ":" in APACHE_IMAGE


def test_user_data_is_a_cloud_config_document():
    user_data = build_user_data()

    header, _, body = user_data.partition("\n")
    assert header == "#cloud-config"
    # JSON is valid YAML, so cloud-init accepts this and tests can parse it.
    assert json.loads(body) == build_cloud_config()


def test_user_data_over_the_size_limit_is_rejected(monkeypatch):
    monkeypatch.setattr(cloud_init, "MAX_USER_DATA_BYTES", 10)

    with pytest.raises(ConfigError, match="over Hetzner's"):
        build_user_data()
