import pytest

from grafanaut.entities.dashboard import DashboardResource
from grafanaut.sync_policy import SyncContext, SyncPolicy
from grafanaut.tests.fake_grafana import FakeGrafana


@pytest.fixture
def resource():
    return DashboardResource()


def test_root_level_dashboard_does_not_raise(resource):
    # meta without folderUid used to raise KeyError and abort the restore.
    converted = resource.convert({"dashboard": {"uid": "d1", "title": "D"}, "meta": {}})
    assert converted["folderUid"] == ""


def test_backup_file_is_named_by_uid_only(resource, tmp_path):
    entity = {"dashboard": {"uid": "d1", "title": "Old title"}, "meta": {}}
    path = resource.entity_file(entity, str(tmp_path))
    assert path.endswith("d1.json")


def test_rename_does_not_leave_an_orphan_file(resource, tmp_path):
    backup_dir = str(tmp_path)
    resource.write_entity_file(
        resource.sanitize({"dashboard": {"uid": "d1", "title": "Before"}, "meta": {}}), backup_dir
    )
    resource.write_entity_file(
        resource.sanitize({"dashboard": {"uid": "d1", "title": "After"}, "meta": {}}), backup_dir
    )
    files = resource.read_entity_files(backup_dir)
    assert len(files) == 1
    assert files[0]["dashboard"]["title"] == "After"


def test_dashboard_is_moved_to_the_new_folder(resource):
    grafana = FakeGrafana()
    grafana.add_dashboard("d1", "D", folder_uid="old")
    ctx = SyncContext(source="test", policy=SyncPolicy(dashboard_tag=""))

    entity = resource.convert({"dashboard": {"uid": "d1", "title": "D"}, "meta": {"folderUid": "new"}})
    resource.make_update(grafana, entity, ctx)

    assert grafana.dashboards["d1"]["folderUid"] == "new"


def test_synced_dashboard_gets_a_tag(resource):
    grafana = FakeGrafana()
    ctx = SyncContext(source="test", policy=SyncPolicy())

    entity = resource.convert({"dashboard": {"uid": "d1", "title": "D"}, "meta": {}})
    resource.make_update(grafana, entity, ctx)
    resource.make_update(grafana, entity, ctx)

    assert grafana.dashboards["d1"]["dashboard"]["tags"] == ["synced:test"]


def test_sanitize_drops_volatile_fields(resource):
    sanitized = resource.sanitize(
        {"dashboard": {"uid": "d1", "title": "D", "id": 17, "version": 9},
         "meta": {"folderUid": "f1", "updated": "now"}}
    )
    assert "id" not in sanitized["dashboard"]
    assert "version" not in sanitized["dashboard"]
    assert sanitized["meta"] == {"folderUid": "f1", "folderTitle": ""}
