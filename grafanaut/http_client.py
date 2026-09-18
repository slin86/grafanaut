"""Thin Grafana REST API client.

The important behavioural rule lives in exists(): only a 404 means "this
object is gone". Every other error status raises, because exists() drives
the deletion logic in mirror-deletions mode -- a 403 or a 500 that silently
returned False would delete live dashboards in the target instances.
"""

from __future__ import annotations

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

DEFAULT_TIMEOUT = 30


class GrafanaApiError(RuntimeError):
    def __init__(self, method, url, status_code, body):
        super().__init__(f"{method} {url} failed with {status_code}: {body}")
        self.status_code = status_code
        self.body = body


class GrafanaClient:
    def __init__(self, url, token, timeout=DEFAULT_TIMEOUT):
        self.url = url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
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

    def _request(self, method, path, data=None):
        return self.session.request(
            method, f"{self.url}{path}", json=data, timeout=self.timeout
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

    def post(self, path, data):
        response = self._request("POST", path, data)
        return _body(response), response

    def put(self, path, data):
        response = self._request("PUT", path, data)
        return _body(response), response

    def delete(self, path):
        response = self._request("DELETE", path)
        return _body(response), response


def _body(response):
    """Return the parsed body, or the raw text for empty/non-JSON responses."""
    try:
        return response.json()
    except ValueError:
        return response.text
