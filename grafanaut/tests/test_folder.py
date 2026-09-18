import pytest

from grafanaut.entities.folder import FolderResource
from grafanaut.sync_policy import VIEW, SyncContext, SyncPolicy
from grafanaut.tests.fake_grafana import FakeGrafana


@pytest.fixture
def resource():
    return FolderResource()


@pytest.fixture
def ctx():
    return SyncContext(
        source="test",
        policy=SyncPolicy(
            lock_folders=False, folder_title_suffix="",
            folder_description="", dashboard_tag="",
        ),
    )


def test_empty_folders_are_backed_up(resource):
    grafana = FakeGrafana()
    grafana.add_folder("empty", "Empty Folder")
    assert [e["uid"] for e in resource.load_entities(grafana)] == ["empty"]


def test_intermediate_levels_are_backed_up(resource):
    grafana = FakeGrafana()
    grafana.add_folder("a", "A")
    grafana.add_folder("b", "B", parent_uid="a")
    grafana.add_folder("c", "C", parent_uid="b")

    entities = {e["uid"]: e for e in resource.load_entities(grafana)}
    assert set(entities) == {"a", "b", "c"}
    assert entities["c"]["parentUid"] == "b"


def test_restore_order_is_parents_before_children(resource):
    entities = [
        {"uid": "c", "title": "C", "parentUid": "b"},
        {"uid": "a", "title": "A", "parentUid": None},
        {"uid": "b", "title": "B", "parentUid": "a"},
    ]
    assert [e["uid"] for e in resource.restore_order(entities)] == ["a", "b", "c"]
    assert [e["uid"] for e in resource.deletion_order(entities)] == ["c", "b", "a"]


def test_moving_a_folder_uses_the_move_endpoint(resource, ctx):
    grafana = FakeGrafana()
    grafana.add_folder("a", "A")
    grafana.add_folder("child", "Child", parent_uid=None)

    resource.make_update(grafana, {"uid": "child", "title": "Child", "parentUid": "a"}, ctx)

    assert grafana.folders["child"]["parentUid"] == "a"
    assert any(call[0] == "POST" and call[1].endswith("/move") for call in grafana.calls)


def test_moving_a_folder_back_to_root(resource, ctx):
    grafana = FakeGrafana()
    grafana.add_folder("a", "A")
    grafana.add_folder("child", "Child", parent_uid="a")

    resource.make_update(grafana, {"uid": "child", "title": "Child", "parentUid": None}, ctx)

    assert grafana.folders["child"]["parentUid"] is None


def test_unchanged_folder_triggers_no_write(resource, ctx):
    grafana = FakeGrafana()
    grafana.add_folder("a", "A")
    resource.make_update(grafana, {"uid": "a", "title": "A", "parentUid": None}, ctx)
    assert [c for c in grafana.calls if c[0] in ("PUT", "POST")] == []


def test_deleted_folder_is_detected(resource, tmp_path, ctx):
    grafana = FakeGrafana()
    grafana.add_folder("alive", "Alive")
    backup_dir = str(tmp_path)
    resource.write_entity_file({"uid": "alive", "title": "Alive", "parentUid": None}, backup_dir)
    resource.write_entity_file({"uid": "gone", "title": "Gone", "parentUid": None}, backup_dir)

    diff = resource.diff_local_and_online(grafana, backup_dir)
    assert [e["uid"] for e in diff] == ["gone"]


def test_folder_delete_forces_rule_removal(resource, ctx):
    grafana = FakeGrafana()
    grafana.add_folder("gone", "Gone")
    resource.delete(grafana, {"uid": "gone", "title": "Gone"}, ctx)
    assert "gone" not in grafana.folders


# --- sync marking and lockdown ---------------------------------------
def test_synced_folder_is_locked_read_only(resource):
    grafana = FakeGrafana()
    grafana.permissions["a"] = [{"role": "Editor", "permission": 2}]
    ctx = SyncContext(source="test", policy=SyncPolicy())

    resource.make_update(grafana, {"uid": "a", "title": "A", "parentUid": None}, ctx)

    levels = {i.get("role"): i["permission"] for i in grafana.permissions["a"]}
    assert levels == {"Viewer": VIEW, "Editor": VIEW}


def test_lockdown_keeps_explicit_team_grants_but_caps_them(resource):
    grafana = FakeGrafana()
    grafana.add_folder("a", "A")
    grafana.permissions["a"] = [{"teamId": 7, "permission": 4}]
    ctx = SyncContext(source="test", policy=SyncPolicy())

    resource.make_update(grafana, {"uid": "a", "title": "A", "parentUid": None}, ctx)

    team = [i for i in grafana.permissions["a"] if i.get("teamId") == 7]
    assert team == [{"teamId": 7, "permission": VIEW}]


def test_lockdown_can_be_disabled(resource):
    grafana = FakeGrafana()
    grafana.add_folder("a", "A")
    ctx = SyncContext(source="test", policy=SyncPolicy(lock_folders=False))
    resource.make_update(grafana, {"uid": "a", "title": "A", "parentUid": None}, ctx)
    assert grafana.permissions == {}


def test_folder_marking_is_idempotent(resource):
    grafana = FakeGrafana()
    ctx = SyncContext(source="test", policy=SyncPolicy())
    entity = {"uid": "a", "title": "A", "parentUid": None}

    resource.make_update(grafana, entity, ctx)
    assert grafana.folders["a"]["title"] == "A [synced]"
    assert "test" in grafana.folders["a"]["description"]

    resource.make_update(grafana, entity, ctx)
    assert grafana.folders["a"]["title"] == "A [synced]"


def test_dry_run_writes_nothing(resource):
    grafana = FakeGrafana()
    ctx = SyncContext(source="test", policy=SyncPolicy(), dry_run=True)
    resource.make_update(grafana, {"uid": "a", "title": "A", "parentUid": None}, ctx)
    assert grafana.folders == {}


def test_dry_run_does_not_read_permissions_of_a_missing_folder(resource):
    # Regression: a folder that would only be created during the run does not
    # exist yet, reading its permissions produced a 404 error in the log.
    grafana = FakeGrafana()
    ctx = SyncContext(source="test", policy=SyncPolicy(), dry_run=True)

    resource.make_update(grafana, {"uid": "new", "title": "New", "parentUid": None}, ctx)

    assert not any("permissions" in call[1] for call in grafana.calls)
    assert ctx.changes.counts() == {"create": 1}


def test_unchanged_folder_is_reported_as_unchanged(resource):
    grafana = FakeGrafana()
    ctx = SyncContext(source="test", policy=SyncPolicy())
    entity = {"uid": "a", "title": "A", "parentUid": None}

    resource.make_update(grafana, entity, ctx)
    second = SyncContext(source="test", policy=SyncPolicy())
    resource.make_update(grafana, entity, second)

    assert second.changes.counts() == {"unchanged": 1}
    assert second.changes.has_changes() is False
