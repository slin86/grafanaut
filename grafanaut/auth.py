"""Authentication against Grafana.

Two modes, chosen per instance in config.yaml:

* ``token`` - a Grafana service account token, sent as a static bearer token.
* ``oidc``  - an access token fetched from an OIDC provider such as Keycloak.
              Needed when Grafana sits behind a gateway (Ambassador) that
              validates the token before the request reaches Grafana at all.

The OIDC side is deliberately generic: grant type, scope, audience and extra
form parameters all come from the configuration. That covers the client
credentials grant, the password grant and RFC 8693 token exchange (for example
with a GitLab CI id token as subject_token) without this module needing to
know about any of them.

Tokens are cached until shortly before they expire and refetched on demand, so
a long restore does not die halfway through with a 401.
"""

from __future__ import annotations

import os
import re
import time

import requests

from grafanaut.logger import setup_logger

logger = setup_logger(__name__)

DEFAULT_TIMEOUT = 30
# Refresh this many seconds before the token actually expires.
EXPIRY_LEEWAY = 60
# Used when the provider does not send expires_in.
DEFAULT_LIFETIME = 300

_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


class StaticTokenProvider:
    """A Grafana service account token straight from the configuration."""

    kind = "token"

    def __init__(self, token):
        self._token = token

    def token(self):
        return self._token

    def invalidate(self):
        """Nothing to refresh - a static token stays wrong if it is wrong."""
        return False


class OidcTokenProvider:
    """Fetches and caches an access token from an OIDC token endpoint."""

    kind = "oidc"

    def __init__(self, token_url, client_id, client_secret=None,
                 grant_type="client_credentials", scope=None, audience=None,
                 extra_params=None, timeout=DEFAULT_TIMEOUT):
        self.token_url = token_url
        self.client_id = client_id
        self.client_secret = client_secret
        self.grant_type = grant_type
        self.scope = scope
        self.audience = audience
        self.extra_params = extra_params or {}
        self.timeout = timeout
        self._token = None
        self._expires_at = 0.0

    def token(self):
        if self._token and time.monotonic() < self._expires_at:
            return self._token
        return self._fetch()

    def invalidate(self):
        """Drop the cached token so the next call fetches a fresh one."""
        self._token = None
        self._expires_at = 0.0
        return True

    def _fetch(self):
        data = {"grant_type": self.grant_type, "client_id": self.client_id}
        if self.client_secret:
            data["client_secret"] = self.client_secret
        if self.scope:
            data["scope"] = self.scope
        if self.audience:
            data["audience"] = self.audience
        data.update(self.extra_params)

        logger.info(f"Requesting OIDC token from {self.token_url}")
        response = requests.post(self.token_url, data=data, timeout=self.timeout)
        if response.status_code >= 400:
            # Never echo the request body, it carries the client secret.
            raise RuntimeError(
                f"Grafanaut: OIDC token request to {self.token_url} failed with "
                f"{response.status_code}: {_safe_error(response)}"
            )

        payload = response.json()
        if not payload.get("access_token"):
            raise RuntimeError(
                f"Grafanaut: OIDC response from {self.token_url} has no access_token"
            )
        self._token = payload["access_token"]
        lifetime = int(payload.get("expires_in") or DEFAULT_LIFETIME)
        self._expires_at = time.monotonic() + max(lifetime - EXPIRY_LEEWAY, 5)
        return self._token


def build_provider(stage, settings):
    """Create the token provider for one instance from its config block."""
    auth = settings.get("auth") or {}
    kind = auth.get("type", "token")

    if kind == "token":
        token = (
            os.environ.get(f"GRAFANA_TOKEN_{stage.upper()}")
            or expand(auth.get("token"))
            or expand(settings.get("token"))
        )
        if not token:
            raise RuntimeError(
                f"Grafanaut: No token for '{stage}' "
                f"(set GRAFANA_TOKEN_{stage.upper()} or token in config.yaml)"
            )
        return StaticTokenProvider(token)

    if kind == "oidc":
        missing = [key for key in ("token_url", "client_id") if not auth.get(key)]
        if missing:
            raise RuntimeError(
                f"Grafanaut: auth.{', auth.'.join(missing)} missing for '{stage}'"
            )
        secret = (
            os.environ.get(f"GRAFANA_OIDC_SECRET_{stage.upper()}")
            or expand(auth.get("client_secret"))
        )
        return OidcTokenProvider(
            token_url=expand(auth["token_url"]),
            client_id=expand(auth["client_id"]),
            client_secret=secret,
            grant_type=auth.get("grant_type", "client_credentials"),
            scope=expand(auth.get("scope")),
            audience=expand(auth.get("audience")),
            extra_params={
                key: expand(value)
                for key, value in (auth.get("extra_params") or {}).items()
            },
        )

    raise RuntimeError(
        f"Grafanaut: unknown auth.type {kind!r} for '{stage}' (use 'token' or 'oidc')"
    )


def expand(value):
    """Replace ${VAR} with the environment variable of that name.

    Lets the config reference a secret without containing it, which matters for
    a file that lives in git.
    """
    if not isinstance(value, str):
        return value

    def replace(match):
        name = match.group(1)
        resolved = os.environ.get(name)
        if resolved is None:
            raise RuntimeError(f"Grafanaut: environment variable {name} is not set")
        return resolved

    return _ENV_PATTERN.sub(replace, value)


def _safe_error(response):
    """The OIDC error detail, without dragging a token or secret into the log."""
    try:
        payload = response.json()
    except ValueError:
        return "<non-JSON response>"
    detail = ", ".join(
        f"{key}={payload[key]}"
        for key in ("error", "error_description")
        if key in payload
    )
    return detail or "<no error detail>"
