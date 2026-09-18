from unittest.mock import MagicMock, patch

import pytest

from grafanaut.http_client import GrafanaApiError, GrafanaClient


def _client():
    return GrafanaClient("https://grafana.example.com/", "token")


@pytest.mark.parametrize("status", [200, 204])
def test_exists_true(status):
    client = _client()
    with patch.object(client, "_request", return_value=MagicMock(status_code=status)):
        assert client.exists("/api/folders/a") is True


def test_exists_false_only_on_404():
    client = _client()
    with patch.object(client, "_request", return_value=MagicMock(status_code=404)):
        assert client.exists("/api/folders/a") is False


@pytest.mark.parametrize("status", [401, 403, 429, 500])
def test_exists_raises_instead_of_reporting_deleted(status):
    # A 403 silently returning False used to delete live objects in the targets.
    client = _client()
    with patch.object(client, "_request", return_value=MagicMock(status_code=status, text="nope")):
        with pytest.raises(GrafanaApiError):
            client.exists("/api/folders/a")
