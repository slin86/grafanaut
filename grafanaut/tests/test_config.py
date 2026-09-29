"""Configuration loading, including the shipped example file."""

import pathlib

import pytest

from grafanaut.auth import OidcTokenProvider, StaticTokenProvider
from grafanaut.config import GrafanautConfig

EXAMPLE = pathlib.Path(__file__).resolve().parents[2] / "config.yaml"


def write(tmp_path, body):
    path = tmp_path / "config.yaml"
    path.write_text(body, encoding="utf-8")
    return str(path)


def test_shipped_example_parses(monkeypatch):
    # The example references ${KEYCLOAK_CLIENT_SECRET}; nothing resolves it
    # until a client is built, so loading must work without it.
    config = GrafanautConfig.load(str(EXAMPLE))
    assert {"prod", "test", "qs", "old"} <= set(config.instances)
    assert config.sync.lock_folders is True
    assert config.alerting.any_enabled() is False


def test_example_oidc_instance_builds_a_provider(monkeypatch):
    monkeypatch.setenv("KEYCLOAK_CLIENT_SECRET", "shh")
    config = GrafanautConfig.load(str(EXAMPLE))
    client = config.client("old")
    assert isinstance(client.token_provider, OidcTokenProvider)
    assert client.token_provider.client_secret == "shh"
    assert client.url == "https://grafana-old.example.com"


def test_token_instance_builds_a_static_provider(tmp_path):
    path = write(tmp_path, """
instances:
  test:
    url: https://grafana-test.example.com/
    token: abc
""")
    client = GrafanautConfig.load(path).client("test")
    assert isinstance(client.token_provider, StaticTokenProvider)
    # Trailing slash is stripped so paths do not end up doubled.
    assert client.url == "https://grafana-test.example.com"


def test_extra_headers_are_expanded(tmp_path, monkeypatch):
    monkeypatch.setenv("SVC_MAIL", "svc@example.com")
    path = write(tmp_path, """
instances:
  test:
    url: https://grafana-test.example.com
    token: abc
    headers:
      X-Forwarded-Email: ${SVC_MAIL}
""")
    client = GrafanautConfig.load(path).client("test")
    assert client.extra_headers == {"X-Forwarded-Email": "svc@example.com"}


def test_instance_without_url_is_rejected(tmp_path):
    path = write(tmp_path, """
instances:
  test:
    token: abc
""")
    with pytest.raises(RuntimeError, match="no url configured"):
        GrafanautConfig.load(path).client("test")


def test_alerting_block_is_read(tmp_path):
    path = write(tmp_path, """
instances:
  test:
    url: https://grafana-test.example.com
    token: abc
alerting:
  enabled: true
  notification_policy: true
""")
    alerting = GrafanautConfig.load(path).alerting
    assert alerting.enabled("alert_rules")
    assert alerting.enabled("notification_policy")


def test_missing_config_file_is_reported(tmp_path):
    with pytest.raises(RuntimeError, match="not found"):
        GrafanautConfig.load(str(tmp_path / "nope.yaml"))


def test_source_cannot_also_be_a_target(tmp_path):
    path = write(tmp_path, """
instances:
  test:
    url: https://grafana-test.example.com
    token: abc
""")
    with pytest.raises(RuntimeError, match="both source and target"):
        GrafanautConfig.load(path, source="test", targets=["test"])
