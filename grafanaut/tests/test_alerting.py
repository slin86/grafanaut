"""Alerting resources via the provisioning API."""

import pytest

from grafanaut.entities import ALERTING_ORDER, build_registry
from grafanaut.entities.alerting import (
    REDACTED,
    AlertRuleResource,
    ContactPointResource,
    MuteTimingResource,
    NotificationPolicyResource,
    NotificationTemplateResource,
)
from grafanaut.sync_policy import AlertingPolicy, SyncContext, SyncPolicy
from grafanaut.tests.fake_grafana import FakeGrafana


@pytest.fixture
def ctx():
    return SyncContext(source="old", policy=SyncPolicy())


# --- configuration ---------------------------------------------------
def test_alerting_is_off_by_default():
    policy = AlertingPolicy.from_dict(None)
    assert policy.any_enabled() is False
    assert [type(r).__name__ for r in build_registry(policy)] == [
        "DatasourceResource", "FolderResource", "DashboardResource",
    ]


def test_enabled_true_turns_on_the_safe_set_but_not_the_policy_tree():
    policy = AlertingPolicy.from_dict({"enabled": True})
    assert policy.enabled("alert_rules")
    assert policy.enabled("contact_points")
    assert policy.enabled("mute_timings")
    assert policy.enabled("templates")
    # Replacing the whole tree has to be asked for explicitly.
    assert policy.enabled("notification_policy") is False


def test_policy_tree_can_be_opted_into():
    policy = AlertingPolicy.from_dict({"enabled": True, "notification_policy": True})
    assert policy.enabled("notification_policy")


def test_single_resource_without_enabled_flag():
    policy = AlertingPolicy.from_dict({"contact_points": True})
    assert policy.enabled("contact_points")
    assert policy.enabled("alert_rules") is False


def test_individual_resource_can_be_switched_off():
    policy = AlertingPolicy.from_dict({"enabled": True, "alert_rules": False})
    assert policy.enabled("alert_rules") is False
    assert policy.enabled("contact_points")


def test_typo_in_the_alerting_block_is_reported():
    with pytest.raises(RuntimeError, match="unknown alerting option"):
        AlertingPolicy.from_dict({"enabled": True, "alertrules": True})


def test_registry_order_puts_dependencies_first():
    policy = AlertingPolicy.from_dict({"enabled": True, "notification_policy": True})
    names = [type(r).__name__ for r in build_registry(policy)]
    # Folders before alert rules (rules live in folders), contact points before
    # the policy tree that routes to them.
    assert names.index("FolderResource") < names.index("AlertRuleResource")
    assert names.index("ContactPointResource") < names.index("NotificationPolicyResource")
    assert names[-1] == "NotificationPolicyResource"


def test_alerting_order_covers_every_resource():
    assert set(ALERTING_ORDER) == set(AlertingPolicy.ALL_RESOURCES)


# --- alert rules -----------------------------------------------------
def test_alert_rule_round_trip(tmp_path, ctx):
    source = FakeGrafana()
    source.add_alert_rule("r1", "High error rate", folder_uid="team")
    resource = AlertRuleResource()
    resource.backup(source, str(tmp_path))

    target = FakeGrafana()
    target.add_folder("team", "Team")
    resource.restore(target, str(tmp_path), ctx)

    assert target.alert_rules["r1"]["title"] == "High error rate"
    assert ctx.changes.counts() == {"create": 1}


def test_volatile_fields_are_not_backed_up(tmp_path, ctx):
    source = FakeGrafana()
    source.add_alert_rule("r1", "Rule", updated="2026-01-01", provenance="api")
    resource = AlertRuleResource()
    resource.backup(source, str(tmp_path))

    stored = resource.read_entity_files(str(tmp_path))[0]
    assert "id" not in stored
    assert "updated" not in stored
    assert "provenance" not in stored


def test_alert_rule_without_its_folder_is_refused(tmp_path, ctx):
    source = FakeGrafana()
    source.add_alert_rule("r1", "Rule", folder_uid="missing")
    resource = AlertRuleResource()
    resource.backup(source, str(tmp_path))

    target = FakeGrafana()  # folder "missing" does not exist here
    resource.restore(target, str(tmp_path), ctx)

    assert target.alert_rules == {}
    conflict = ctx.changes.changed()[0]
    assert conflict.action == "conflict"
    assert "missing" in conflict.detail


def test_unchanged_alert_rule_is_not_rewritten(tmp_path, ctx):
    source = FakeGrafana()
    source.add_alert_rule("r1", "Rule", folder_uid="team")
    resource = AlertRuleResource()
    resource.backup(source, str(tmp_path))

    target = FakeGrafana()
    target.add_folder("team", "Team")
    resource.restore(target, str(tmp_path), ctx)

    second = SyncContext(source="old", policy=SyncPolicy())
    target.calls.clear()
    resource.restore(target, str(tmp_path), second)

    assert [c for c in target.calls if c[0] in ("POST", "PUT")] == []
    assert second.changes.counts() == {"unchanged": 1}


def test_provenance_header_keeps_rules_editable(tmp_path):
    source = FakeGrafana()
    source.add_alert_rule("r1", "Rule", folder_uid="team")
    resource = AlertRuleResource()
    resource.backup(source, str(tmp_path))

    target = FakeGrafana()
    target.add_folder("team", "Team")
    resource.restore(
        target, str(tmp_path),
        SyncContext(source="old", policy=SyncPolicy(alerting_editable=True)),
    )
    assert target.last_headers == {"X-Disable-Provenance": "true"}


def test_without_the_header_rules_become_provisioned(tmp_path):
    source = FakeGrafana()
    source.add_alert_rule("r1", "Rule", folder_uid="team")
    resource = AlertRuleResource()
    resource.backup(source, str(tmp_path))

    target = FakeGrafana()
    target.add_folder("team", "Team")
    resource.restore(
        target, str(tmp_path),
        SyncContext(source="old", policy=SyncPolicy(alerting_editable=False)),
    )
    assert target.last_headers is None


# --- contact points --------------------------------------------------
def test_redacted_secrets_are_never_written_to_the_backup(tmp_path):
    source = FakeGrafana()
    source.add_contact_point(
        "cp1", "Ops Slack",
        settings={"url": REDACTED, "recipient": "#ops"},
        secure_fields={"url": True},
    )
    resource = ContactPointResource()
    resource.backup(source, str(tmp_path))

    stored = resource.read_entity_files(str(tmp_path))[0]
    assert "url" not in stored["settings"]
    assert stored["settings"]["recipient"] == "#ops"
    assert stored["_grafanaut_secrets"] == ["url"]


def test_placeholder_never_reaches_the_target(tmp_path, ctx):
    source = FakeGrafana()
    source.add_contact_point(
        "cp1", "Ops Slack",
        settings={"url": REDACTED}, secure_fields={"url": True},
    )
    resource = ContactPointResource()
    resource.backup(source, str(tmp_path))
    resource.restore(FakeGrafana(), str(tmp_path), ctx)

    written = [c for c in ctx.changes.changed()]
    assert written[0].action == "create"
    # The marker is bookkeeping, it must not be sent to the API.
    payload = resource.convert(resource.read_entity_files(str(tmp_path))[0])
    assert "_grafanaut_secrets" not in payload


def test_missing_secrets_are_reported(tmp_path, ctx, caplog):
    source = FakeGrafana()
    source.add_contact_point(
        "cp1", "Ops Slack",
        settings={"url": REDACTED}, secure_fields={"url": True},
    )
    resource = ContactPointResource()
    resource.backup(source, str(tmp_path))

    with caplog.at_level("WARNING"):
        resource.restore(FakeGrafana(), str(tmp_path), ctx)

    assert "Ops Slack: url" in caplog.text


def test_contact_point_without_secrets_reports_nothing(tmp_path, ctx, caplog):
    source = FakeGrafana()
    source.add_contact_point("cp1", "Plain webhook")
    resource = ContactPointResource()
    resource.backup(source, str(tmp_path))

    with caplog.at_level("WARNING"):
        resource.restore(FakeGrafana(), str(tmp_path), ctx)

    assert "set them manually" not in caplog.text.casefold()


# --- mute timings and templates --------------------------------------
def test_mute_timing_name_with_spaces_round_trips(tmp_path, ctx):
    source = FakeGrafana()
    source.mute_timings["Weekends and holidays"] = {
        "name": "Weekends and holidays", "time_intervals": [],
    }
    resource = MuteTimingResource()
    resource.backup(source, str(tmp_path))

    target = FakeGrafana()
    resource.restore(target, str(tmp_path), ctx)

    assert "Weekends and holidays" in target.mute_timings


def test_template_uses_put_for_create(tmp_path, ctx):
    source = FakeGrafana()
    source.templates["default"] = {"name": "default", "template": "{{ define \"x\" }}"}
    resource = NotificationTemplateResource()
    resource.backup(source, str(tmp_path))

    target = FakeGrafana()
    resource.restore(target, str(tmp_path), ctx)

    assert target.templates["default"]["name"] == "default"
    assert [c[0] for c in target.calls if c[0] in ("POST", "PUT")] == ["PUT"]


# --- notification policy tree ----------------------------------------
def test_policy_tree_is_stored_as_a_single_file(tmp_path, ctx):
    source = FakeGrafana()
    source.policy_tree = {"receiver": "ops", "routes": [{"receiver": "ops"}]}
    resource = NotificationPolicyResource()
    resource.backup(source, str(tmp_path))

    assert len(resource.read_entity_files(str(tmp_path))) == 1


def test_policy_tree_replacement_is_announced(tmp_path, ctx, caplog):
    source = FakeGrafana()
    source.policy_tree = {"receiver": "ops"}
    resource = NotificationPolicyResource()
    resource.backup(source, str(tmp_path))

    target = FakeGrafana()
    target.policy_tree = {"receiver": "target-only"}
    with caplog.at_level("WARNING"):
        resource.restore(target, str(tmp_path), ctx)

    assert "ENTIRE notification policy tree" in caplog.text
    assert target.policy_tree["receiver"] == "ops"


def test_unchanged_policy_tree_is_left_alone(tmp_path, ctx):
    source = FakeGrafana()
    source.policy_tree = {"receiver": "ops"}
    resource = NotificationPolicyResource()
    resource.backup(source, str(tmp_path))

    target = FakeGrafana()
    target.policy_tree = {"receiver": "ops"}
    resource.restore(target, str(tmp_path), ctx)

    assert ctx.changes.counts() == {"unchanged": 1}


def test_policy_tree_is_never_a_deletion_candidate(tmp_path):
    resource = NotificationPolicyResource()
    assert resource.diff_local_and_online(FakeGrafana(), str(tmp_path)) == []


def test_dry_run_writes_no_alerting_changes(tmp_path):
    source = FakeGrafana()
    source.add_alert_rule("r1", "Rule", folder_uid="team")
    resource = AlertRuleResource()
    resource.backup(source, str(tmp_path))

    target = FakeGrafana()
    target.add_folder("team", "Team")
    ctx = SyncContext(source="old", policy=SyncPolicy(), dry_run=True)
    resource.restore(target, str(tmp_path), ctx)

    assert target.alert_rules == {}
    assert ctx.changes.counts() == {"create": 1}


def test_typo_is_caught_even_without_enabled():
    with pytest.raises(RuntimeError, match="unknown alerting option"):
        AlertingPolicy.from_dict({"contactpoints": True})
