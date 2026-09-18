from unittest.mock import MagicMock, patch

import pytest

import grafanaut.main as main_mod
from grafanaut.sync_policy import SyncContext, SyncPolicy


@pytest.fixture
def ctx():
    return SyncContext(source="test", policy=SyncPolicy())


@pytest.fixture
def mock_logger():
    with patch("grafanaut.main.logger") as logger:
        yield logger


def test_process_backup_calls_resource_backup(monkeypatch, mock_logger):
    resource = MagicMock()
    monkeypatch.setattr(main_mod, "RESOURCE_REGISTRY", [resource])
    main_mod.process_backup(MagicMock(), "backup/source")
    resource.backup.assert_called_once()


def test_process_restore_calls_resource_restore(monkeypatch, mock_logger, ctx):
    resource = MagicMock()
    monkeypatch.setattr(main_mod, "RESOURCE_REGISTRY", [resource])
    config = MagicMock()
    main_mod.process_restore(config, "backup/source", ["target"], ctx)
    resource.restore.assert_called_once()


def test_process_mirror_deletions_deletes_in_every_target(monkeypatch, mock_logger, ctx):
    resource = MagicMock()
    resource.diff_local_and_online.return_value = ["entity1", "entity2"]
    monkeypatch.setattr(main_mod, "RESOURCE_REGISTRY", [resource])

    config = MagicMock()
    source_client = MagicMock()

    main_mod.process_mirror_deletions(
        config, source_client, "backup/source", ["target1", "target2"], ctx
    )

    resource.diff_local_and_online.assert_called_once_with(source_client, "backup/source")
    assert resource.delete.call_count == 4
    # Each backup file is removed exactly once, not once per target.
    assert resource.delete_entity_file.call_count == 2


def test_mirror_deletions_runs_dashboards_before_folders(monkeypatch, mock_logger, ctx):
    order = []
    dashboards, folders = MagicMock(name="dashboards"), MagicMock(name="folders")
    for resource, label in ((folders, "folder"), (dashboards, "dashboard")):
        resource.diff_local_and_online.side_effect = (
            lambda *_, _label=label: order.append(_label) or []
        )
    monkeypatch.setattr(main_mod, "RESOURCE_REGISTRY", [folders, dashboards])

    main_mod.process_mirror_deletions(
        MagicMock(), MagicMock(), "backup/source", ["t"], ctx
    )

    assert order == ["dashboard", "folder"]


def test_restore_without_targets_is_rejected(monkeypatch, mock_logger):
    monkeypatch.setattr(main_mod.GrafanautConfig, "load", classmethod(lambda *a, **k: MagicMock()))
    with pytest.raises(RuntimeError, match="requires --targets"):
        main_mod.main("source", targets=None, mode="restore")


def test_dry_run_still_records_changes_for_the_summary(tmp_path):
    from grafanaut.entities.datasource import DatasourceResource
    from grafanaut.tests.fake_grafana import FakeGrafana

    resource, grafana = DatasourceResource(), FakeGrafana()
    ctx = SyncContext(source="test", policy=SyncPolicy(), dry_run=True)

    resource.make_update(grafana, {"uid": "ds1", "name": "Prometheus"}, ctx)

    assert ctx.changes.counts() == {"create": 1}
