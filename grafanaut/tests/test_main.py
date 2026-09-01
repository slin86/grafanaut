import pytest
from unittest.mock import patch, MagicMock

import grafanaut.main as main_mod

@pytest.fixture
def mock_logger():
    with patch("grafanaut.main.logger") as logger:
        yield logger

def test_get_config_calls_load_config():
    with patch("grafanaut.main.GrafanautConfig") as MockConfig:
        instance = MockConfig.return_value
        instance.load_config.return_value = {"foo": "bar"}
        result = main_mod.get_config("source", ["target"])
        instance.load_config.assert_called_once_with("source", ["target"])
        assert result == {"foo": "bar"}

def test_create_client_uses_get_token_and_GrafanaClient():
    config = {"stage": {"url": "http://test"}}
    with patch("grafanaut.main.GrafanautConfig.get_token", return_value="tok") as get_token, \
         patch("grafanaut.main.GrafanaClient") as MockClient:
        client = main_mod.create_client(config, "stage")
        get_token.assert_called_once_with(config, "stage")
        MockClient.assert_called_once_with("http://test", "tok")
        assert client == MockClient.return_value

def test_process_backup_calls_entity_backup(monkeypatch, mock_logger):
    entity = MagicMock()
    monkeypatch.setattr(main_mod, "ENTITY_REGISTRY", [entity])
    client = MagicMock()
    main_mod.process_backup("source", client)
    entity.backup.assert_called_once()

def test_process_restore_calls_entity_restore(monkeypatch, mock_logger):
    entity = MagicMock()
    monkeypatch.setattr(main_mod, "ENTITY_REGISTRY", [entity])
    config = {"target": {"url": "url"}}
    with patch("grafanaut.main.create_client", return_value=MagicMock()):
        main_mod.process_restore(config, "source", ["target"])
    entity.restore.assert_called_once()

def test_main_runs_backup_and_restore(monkeypatch, mock_logger):
    monkeypatch.setattr(main_mod, "get_config", lambda s, t: {"foo": "bar"})
    monkeypatch.setattr(main_mod, "create_client", lambda c, s: MagicMock())
    monkeypatch.setattr(main_mod, "process_backup", MagicMock())
    monkeypatch.setattr(main_mod, "process_restore", MagicMock())
    main_mod.main("source", ["target"], mode="all")
    main_mod.process_backup.assert_called_once()
    main_mod.process_restore.assert_called_once()

def test_process_mirror_deletions_executes_deletions(monkeypatch):
    # setup
    mock_resource = MagicMock()
    mock_resource.diff_local_and_online.return_value = ["entity1", "entity2"]
    mock_resource.delete = MagicMock()

    monkeypatch.setattr(main_mod, "RESOURCE_REGISTRY", [mock_resource])

    mock_client = MagicMock()
    monkeypatch.setattr(main_mod, "create_client", lambda config, target: mock_client)

    monkeypatch.setattr(main_mod, "get_backup_folder", lambda source: "backup/source")

    # given
    config = {"target1": {"url": "url1"}, "target2": {"url": "url2"}}
    source = "source"
    source_client = MagicMock()
    targets = ["target1", "target2"]

    # when
    main_mod.process_mirror_deletions(config, source, source_client, targets)

    # then
    mock_resource.diff_local_and_online.assert_called_once_with(source_client, "backup/source")
    assert mock_resource.delete.call_count == 4