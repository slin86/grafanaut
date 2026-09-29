"""Thin Grafana REST API client.

The important behavioural rule lives in exists(): only a 404 means "this
object is gone". Every other error status raises, because exists() drives
the deletion logic in mirror-deletions mode -- a 403 or a 500 that silently
returned False would delete live dashboards in the target instances.

Authentication comes from a token provider (see grafanaut.auth), so an OIDC
access token that expires mid-run is refetched transparently.
"""

from __future__ import annotations

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from grafanaut.auth import StaticTokenProvider
from grafanaut.logger import setup_logger

logger = setup_logger(__name__)

DEFAULT_TIMEOUT = 30


class GrafanaApiError(RuntimeError):
    def __init__(self, method, url, status_code, body):
        super().__init__(f"{method} {url} failed with {status_code}: {body}")
        self.status_code = status_code
        self.body = body


class GrafanaClient:
    def __init__(self, url, token=None, timeout=DEFAULT_TIMEOUT,
                 token_provider=None, extra_headers=None):
        self.url = url.rstrip("/")
        self.timeout = timeout
        # A plain token string is still accepted, mostly so tests and callers
        # that do not care about OIDC stay simple.
        self.token_provider = token_provider or StaticTokenProvider(token)
        self.extra_headers = dict(extra_headers or {})
        self.session = requests.Session()
        self.session.headers.update({
            "Content-Type": "application/json",
            "Accept": "application/json",
        })
        # Retry transient failures so a hiccup is not mistaken for a deletion.
        retry = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=[429, 502, 503, 504],
            allowed_methods=["GET", "DELETE"],
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self.session.mount("http://", HTTPAdapter(max_retries=retry))

    def _request(self, method, path, data=None, headers=None):
        """Send the request, retrying once on 401 with a freshly fetched token.

        A gateway in front of Grafana rejects an expired OIDC token with 401.
        Refetching once turns that into a hiccup instead of a failed run; a
        static token cannot be refreshed, so it is not retried.
        """
        response = self._send(method, path, data, headers)
        if response.status_code == 401 and self.token_provider.invalidate():
            logger.info(f"Got 401 on {method} {path}, retrying with a fresh token")
            response = self._send(method, path, data, headers)
        return response

    def _send(self, method, path, data, headers):
        merged = {
            "Authorization": f"Bearer {self.token_provider.token()}",
            **self.extra_headers,
            **(headers or {}),
        }
        return self.session.request(
            method, f"{self.url}{path}", json=data,
            headers=merged, timeout=self.timeout,
        )

    def exists(self, path):
        """True if the object exists, False only on an explicit 404.

        Any other error status raises, so an auth or availability problem
        aborts the run instead of being interpreted as "deleted".
        """
        response = self._request("GET", path)
        if response.status_code == 404:
            return False
        if response.status_code >= 400:
            raise GrafanaApiError("GET", path, response.status_code, response.text)
        return True

    def get(self, path):
        response = self._request("GET", path)
        if response.status_code >= 400:
            raise GrafanaApiError("GET", path, response.status_code, response.text)
        return response.json()

    def post(self, path, data, headers=None):
        response = self._request("POST", path, data, headers)
        return _body(response), response

    def put(self, path, data, headers=None):
        response = self._request("PUT", path, data, headers)
        return _body(response), response

    def delete(self, path, headers=None):
        response = self._request("DELETE", path, headers=headers)
        return _body(response), response


def _body(response):
    """Return the parsed body, or the raw text for empty/non-JSON responses."""
    try:
        return response.json()
    except ValueError:
        return response.text
