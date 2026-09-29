from unittest.mock import MagicMock, patch

import pytest

from grafanaut.auth import (
    OidcTokenProvider,
    StaticTokenProvider,
    build_provider,
    expand,
)
from grafanaut.http_client import GrafanaClient


# --- config parsing --------------------------------------------------
def test_static_token_from_config():
    provider = build_provider("test", {"token": "abc"})
    assert isinstance(provider, StaticTokenProvider)
    assert provider.token() == "abc"


def test_env_var_wins_over_config(monkeypatch):
    monkeypatch.setenv("GRAFANA_TOKEN_TEST", "from-env")
    assert build_provider("test", {"token": "from-config"}).token() == "from-env"


def test_missing_token_is_reported_with_the_env_var_name():
    with pytest.raises(RuntimeError, match="GRAFANA_TOKEN_TEST"):
        build_provider("test", {})


def test_env_placeholders_are_expanded(monkeypatch):
    monkeypatch.setenv("MY_SECRET", "s3cret")
    assert expand("prefix-${MY_SECRET}") == "prefix-s3cret"


def test_unset_placeholder_fails_loudly():
    with pytest.raises(RuntimeError, match="GRAFANAUT_NOT_SET"):
        expand("${GRAFANAUT_NOT_SET}")


def test_oidc_requires_token_url_and_client_id():
    with pytest.raises(RuntimeError, match="auth.token_url"):
        build_provider("old", {"auth": {"type": "oidc", "client_id": "x"}})


def test_unknown_auth_type_is_rejected():
    with pytest.raises(RuntimeError, match="unknown auth.type"):
        build_provider("test", {"auth": {"type": "basic"}})


def test_oidc_secret_can_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("GRAFANA_OIDC_SECRET_OLD", "shh")
    provider = build_provider("old", {
        "auth": {
            "type": "oidc",
            "token_url": "https://keycloak.example.com/token",
            "client_id": "grafanaut",
        },
    })
    assert provider.client_secret == "shh"


# --- token fetching -------------------------------------------------
def _response(payload, status=200):
    response = MagicMock(status_code=status)
    response.json.return_value = payload
    return response


def test_token_is_fetched_and_cached():
    provider = OidcTokenProvider("https://kc/token", "grafanaut", "secret")
    with patch("grafanaut.auth.requests.post",
               return_value=_response({"access_token": "t1", "expires_in": 300})) as post:
        assert provider.token() == "t1"
        assert provider.token() == "t1"
    assert post.call_count == 1


def test_invalidate_forces_a_refetch():
    provider = OidcTokenProvider("https://kc/token", "grafanaut")
    tokens = [
        _response({"access_token": "t1", "expires_in": 300}),
        _response({"access_token": "t2", "expires_in": 300}),
    ]
    with patch("grafanaut.auth.requests.post", side_effect=tokens):
        assert provider.token() == "t1"
        provider.invalidate()
        assert provider.token() == "t2"


def test_expired_token_is_refetched():
    provider = OidcTokenProvider("https://kc/token", "grafanaut")
    tokens = [
        _response({"access_token": "t1", "expires_in": 300}),
        _response({"access_token": "t2", "expires_in": 300}),
    ]
    with patch("grafanaut.auth.requests.post", side_effect=tokens):
        assert provider.token() == "t1"
        provider._expires_at = 0  # pretend it aged out
        assert provider.token() == "t2"


def test_extra_params_reach_the_token_endpoint():
    provider = OidcTokenProvider(
        "https://kc/token", "grafanaut",
        grant_type="urn:ietf:params:oauth:grant-type:token-exchange",
        audience="grafana",
        extra_params={"subject_token": "ci-token"},
    )
    with patch("grafanaut.auth.requests.post",
               return_value=_response({"access_token": "t"})) as post:
        provider.token()
    sent = post.call_args.kwargs["data"]
    assert sent["grant_type"].endswith("token-exchange")
    assert sent["audience"] == "grafana"
    assert sent["subject_token"] == "ci-token"


def test_failed_token_request_does_not_leak_the_secret():
    provider = OidcTokenProvider("https://kc/token", "grafanaut", "top-secret")
    failure = _response({"error": "invalid_client", "error_description": "bad creds"}, 401)
    with patch("grafanaut.auth.requests.post", return_value=failure):
        with pytest.raises(RuntimeError) as excinfo:
            provider.token()
    message = str(excinfo.value)
    assert "invalid_client" in message
    assert "top-secret" not in message


def test_response_without_access_token_is_rejected():
    provider = OidcTokenProvider("https://kc/token", "grafanaut")
    with patch("grafanaut.auth.requests.post", return_value=_response({"foo": "bar"})):
        with pytest.raises(RuntimeError, match="no access_token"):
            provider.token()


# --- client integration ---------------------------------------------
def test_client_retries_once_on_401_with_a_fresh_token():
    provider = OidcTokenProvider("https://kc/token", "grafanaut")
    tokens = [
        _response({"access_token": "expired", "expires_in": 300}),
        _response({"access_token": "fresh", "expires_in": 300}),
    ]
    client = GrafanaClient("https://grafana.example.com", token_provider=provider)

    with patch("grafanaut.auth.requests.post", side_effect=tokens), \
         patch.object(client.session, "request",
                      side_effect=[MagicMock(status_code=401),
                                   MagicMock(status_code=200)]) as request:
        response = client._request("GET", "/api/folders")

    assert response.status_code == 200
    assert request.call_count == 2
    assert request.call_args_list[0].kwargs["headers"]["Authorization"] == "Bearer expired"
    assert request.call_args_list[1].kwargs["headers"]["Authorization"] == "Bearer fresh"


def test_static_token_is_not_retried_on_401():
    # Nothing to refresh, so a second identical request would be pointless.
    client = GrafanaClient("https://grafana.example.com", token="static")
    with patch.object(client.session, "request",
                      return_value=MagicMock(status_code=401)) as request:
        assert client._request("GET", "/api/folders").status_code == 401
    assert request.call_count == 1


def test_extra_headers_are_sent():
    client = GrafanaClient(
        "https://grafana.example.com", token="t",
        extra_headers={"X-Forwarded-Email": "svc@example.com"},
    )
    with patch.object(client.session, "request",
                      return_value=MagicMock(status_code=200)) as request:
        client._request("GET", "/api/folders")
    assert request.call_args.kwargs["headers"]["X-Forwarded-Email"] == "svc@example.com"
