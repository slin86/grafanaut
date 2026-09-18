"""Title collisions must never overwrite an object that only exists in the target."""

import pytest

from grafanaut.entities.dashboard import DashboardResource
from grafanaut.entities.folder import FolderResource
from grafanaut.sync_policy import SyncContext, SyncPolicy
from grafanaut.tests.fake_grafana import FakeGrafana


@pytest.fixture
def ctx():
    return SyncContext(
        source="test",
        policy=SyncPolicy(
            lock_folders=False, folder_title_suffix="",
            folder_description="", dashboard_tag="",
        ),
    )


# --- dashboards ------------------------------------------------------
def test_new_dashboard_does_not_absorb_a_target_only_one(ctx):
    # overwrite=true would have overwritten the target's dashboard by title.
    grafana = FakeGrafana()
    grafana.add_dashboard("local-uid", "Betriebszustand", folder_uid="team")
    resource = DashboardResource()

    entity = resource.convert({
        "dashboard": {"uid": "from-test", "title": "Betriebszustand"},
        "meta": {"folderUid": "team"},
    })
    resource.make_update(grafana, entity, ctx)

    assert "from-test" not in grafana.dashboards
    assert grafana.dashboards["local-uid"]["dashboard"]["title"] == "Betriebszustand"
    conflict = ctx.changes.changed()[0]
    assert conflict.action == "conflict"
    assert "local-uid" in conflict.detail


def test_moving_into_a_folder_with_a_name_clash_is_refused(ctx):
    grafana = FakeGrafana()
    grafana.add_dashboard("mine", "Versions", folder_uid="old")
    grafana.add_dashboard("theirs", "Versions", folder_uid="new")
    resource = DashboardResource()

    entity = resource.convert({
        "dashboard": {"uid": "mine", "title": "Versions"},
        "meta": {"folderUid": "new"},
    })
    resource.make_update(grafana, entity, ctx)

    assert grafana.dashboards["mine"]["folderUid"] == "old"
    assert ctx.changes.counts() == {"conflict": 1}


def test_same_title_in_a_different_folder_is_not_a_collision(ctx):
    grafana = FakeGrafana()
    grafana.add_dashboard("other", "MES", folder_uid="somewhere-else")
    resource = DashboardResource()

    entity = resource.convert({
        "dashboard": {"uid": "mine", "title": "MES"},
        "meta": {"folderUid": "team"},
    })
    resource.make_update(grafana, entity, ctx)

    assert grafana.dashboards["mine"]["folderUid"] == "team"


def test_plain_update_of_a_known_uid_needs_no_collision_check(ctx):
    grafana = FakeGrafana()
    grafana.add_dashboard("mine", "Versions", folder_uid="team")
    resource = DashboardResource()

    entity = resource.convert({
        "dashboard": {"uid": "mine", "title": "Versions", "refresh": "1m"},
        "meta": {"folderUid": "team"},
    })
    resource.make_update(grafana, entity, ctx)

    assert not any(call[1] == "/api/search" for call in grafana.calls)
    assert ctx.changes.counts() == {"update": 1}


def test_collision_check_is_case_insensitive(ctx):
    grafana = FakeGrafana()
    grafana.add_dashboard("local-uid", "betriebszustand", folder_uid="team")
    resource = DashboardResource()

    entity = resource.convert({
        "dashboard": {"uid": "from-test", "title": "Betriebszustand"},
        "meta": {"folderUid": "team"},
    })
    resource.make_update(grafana, entity, ctx)

    assert ctx.changes.counts() == {"conflict": 1}


# --- folders ---------------------------------------------------------
def test_new_folder_with_a_clashing_title_is_refused(ctx):
    grafana = FakeGrafana()
    grafana.add_folder("local-uid", "Search-Services")
    resource = FolderResource()

    resource.make_update(
        grafana, {"uid": "from-test", "title": "Search-Services", "parentUid": None}, ctx
    )

    assert "from-test" not in grafana.folders
    assert ctx.changes.counts() == {"conflict": 1}
    assert "local-uid" in ctx.changes.changed()[0].detail


def test_moving_a_folder_into_a_clashing_parent_is_refused(ctx):
    grafana = FakeGrafana()
    grafana.add_folder("parent", "Parent")
    grafana.add_folder("theirs", "Reports", parent_uid="parent")
    grafana.add_folder("mine", "Reports", parent_uid=None)
    resource = FolderResource()

    resource.make_update(
        grafana, {"uid": "mine", "title": "Reports", "parentUid": "parent"}, ctx
    )

    assert grafana.folders["mine"]["parentUid"] is None
    assert ctx.changes.counts() == {"conflict": 1}


def test_same_folder_title_under_a_different_parent_is_fine(ctx):
    grafana = FakeGrafana()
    grafana.add_folder("a", "A")
    grafana.add_folder("b", "B")
    grafana.add_folder("theirs", "Reports", parent_uid="a")
    resource = FolderResource()

    resource.make_update(
        grafana, {"uid": "mine", "title": "Reports", "parentUid": "b"}, ctx
    )

    assert grafana.folders["mine"]["parentUid"] == "b"


def test_unchanged_folder_skips_the_collision_check(ctx):
    grafana = FakeGrafana()
    grafana.add_folder("a", "A")
    resource = FolderResource()
    grafana.calls.clear()

    resource.make_update(grafana, {"uid": "a", "title": "A", "parentUid": None}, ctx)

    assert not any(call[1] == "/api/folders" for call in grafana.calls)
    assert ctx.changes.counts() == {"unchanged": 1}
