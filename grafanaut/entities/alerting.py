"""Alerting resources via the Grafana provisioning API.

Everything here talks to /api/v1/provisioning. Two things about that API shape
the code:

* There are two JSON formats. The ``/export`` endpoints produce provisioning
  *file* format, which the Grafana docs state cannot be fed back through the
  HTTP API. So backup reads the plain endpoints (GET /alert-rules etc.) and
  restore writes through the matching POST/PUT, which is also what the Grafana
  Terraform provider does.

* Resources written through this API are marked as provisioned and become
  read-only in the UI. The header ``X-Disable-Provenance: true`` keeps them
  editable. Which one is wanted is a policy decision (alerting_editable).

Secrets are the other constraint: Grafana never returns contact point secrets,
it replaces them with a placeholder. Writing that placeholder back would store
the literal string as the password, so those fields are stripped and reported
instead.
"""

from __future__ import annotations

from urllib.parse import quote

from grafanaut import changes
from grafanaut.base_entity import BaseEntity
from grafanaut.logger import setup_logger

logger = setup_logger(__name__)

PROVISIONING = "/api/v1/provisioning"
# Grafana substitutes this for any secret it will not hand out.
REDACTED = "[REDACTED]"
DISABLE_PROVENANCE = {"X-Disable-Provenance": "true"}


class ProvisioningEntity(BaseEntity):
    """Shared plumbing for the provisioning API resources."""

    def headers(self, ctx):
        """Keep the resource editable in the UI when the policy asks for it."""
        if ctx.policy.alerting_editable:
            return dict(DISABLE_PROVENANCE)
        return None

    def entity_name(self, entity):
        return entity.get("title") or entity.get("name") or self.entity_id(entity)

    def sanitize(self, entity):
        sanitized = dict(entity)
        for key in ("id", "orgID", "orgId", "updated", "provenance", "version"):
            sanitized.pop(key, None)
        return sanitized


class AlertRuleResource(ProvisioningEntity):
    """Grafana-managed alert rules, one file per rule uid."""

    def load_entities(self, client):
        return client.get(f"{PROVISIONING}/alert-rules")

    def entity_id(self, entity):
        return entity["uid"]

    def entity_name(self, entity):
        return entity.get("title", entity.get("uid", "?"))

    def name(self):
        return "alert-rules"

    def endpoint(self):
        return f"{PROVISIONING}/alert-rules"

    def get_entity_path(self, entity):
        return f"{PROVISIONING}/alert-rules/{entity['uid']}"

    def describe_difference(self, current, desired):
        return changes.describe_differences(
            current, desired,
            ignored=("id", "orgID", "orgId", "updated", "provenance", "version"),
        )

    def make_update(self, client, entity, ctx):
        """An alert rule lives in a folder, so it can only be restored once
        that folder exists in the target. A missing folder is reported rather
        than left as a raw 400 from the API."""
        folder_uid = entity.get("folderUID") or entity.get("folderUid")
        name = self.entity_name(entity)
        if folder_uid and not client.exists(f"/api/folders/{folder_uid}"):
            self.report_conflict(
                ctx, name, f"target has no folder {folder_uid} for this rule"
            )
            return
        super().make_update(client, entity, ctx)

    def write(self, client, entity, path, action, ctx):
        headers = self.headers(ctx)
        if action == changes.UPDATE:
            return client.put(path, entity, headers=headers)
        return client.post(self.endpoint(), entity, headers=headers)


class ContactPointResource(ProvisioningEntity):
    """Notification receivers.

    Grafana redacts secrets in secureFields/secureSettings, so a restored
    contact point keeps its shape but needs its credentials filled in once, by
    hand, in the target.
    """

    def load_entities(self, client):
        return client.get(f"{PROVISIONING}/contact-points")

    def entity_id(self, entity):
        return entity["uid"]

    def entity_name(self, entity):
        return entity.get("name", entity.get("uid", "?"))

    def name(self):
        return "contact-points"

    def endpoint(self):
        return f"{PROVISIONING}/contact-points"

    def get_entity_path(self, entity):
        return f"{PROVISIONING}/contact-points/{entity['uid']}"

    def sanitize(self, entity):
        """Drop redacted secrets so no placeholder ever reaches a target."""
        sanitized = super().sanitize(entity)
        secure_fields = sanitized.pop("secureFields", None)
        sanitized.pop("secureSettings", None)
        settings = {
            key: value
            for key, value in (sanitized.get("settings") or {}).items()
            if value != REDACTED
        }
        sanitized["settings"] = settings
        if secure_fields:
            # Record which secrets exist so the restore can name them.
            sanitized["_grafanaut_secrets"] = sorted(
                key for key, present in secure_fields.items() if present
            )
        return sanitized

    def convert(self, data):
        payload = dict(data)
        payload.pop("_grafanaut_secrets", None)
        return payload

    def describe_difference(self, current, desired):
        return changes.describe_differences(
            current, desired,
            ignored=("id", "orgID", "orgId", "provenance", "secureFields",
                     "secureSettings", "_grafanaut_secrets"),
        )

    def restore(self, client, backup_dir, ctx):
        """Restore, then warn once about every secret that has to be set by hand."""
        raw_entities = self.read_entity_files(backup_dir)
        logger.info(f"{self.name()} started")
        for raw in raw_entities:
            self.make_update(client, self.convert(raw), ctx)
        self._warn_about_secrets(raw_entities)
        logger.info(f"{self.name()} done!")

    def _warn_about_secrets(self, raw_entities):
        pending = [
            (raw.get("name", raw.get("uid")), raw["_grafanaut_secrets"])
            for raw in raw_entities
            if raw.get("_grafanaut_secrets")
        ]
        if not pending:
            return
        logger.warning(
            f"\t{len(pending)} contact point(s) have secrets that Grafana does not "
            f"export. Set them manually in the target:"
        )
        for name, secrets in pending:
            logger.warning(f"\t\t{name}: {', '.join(secrets)}")

    def write(self, client, entity, path, action, ctx):
        headers = self.headers(ctx)
        if action == changes.UPDATE:
            return client.put(path, entity, headers=headers)
        return client.post(self.endpoint(), entity, headers=headers)


class MuteTimingResource(ProvisioningEntity):
    """Mute timings, identified by name rather than a uid."""

    def load_entities(self, client):
        return client.get(f"{PROVISIONING}/mute-timings")

    def entity_id(self, entity):
        return _slug(entity["name"])

    def entity_name(self, entity):
        return entity["name"]

    def name(self):
        return "mute-timings"

    def endpoint(self):
        return f"{PROVISIONING}/mute-timings"

    def get_entity_path(self, entity):
        return f"{PROVISIONING}/mute-timings/{quote(entity['name'], safe='')}"

    def describe_difference(self, current, desired):
        return changes.describe_differences(
            current, desired, ignored=("provenance", "version"),
        )

    def write(self, client, entity, path, action, ctx):
        headers = self.headers(ctx)
        if action == changes.UPDATE:
            return client.put(path, entity, headers=headers)
        return client.post(self.endpoint(), entity, headers=headers)


class NotificationTemplateResource(ProvisioningEntity):
    """Notification template groups, also keyed by name.

    These have no POST endpoint: PUT creates and updates, so the write path
    does not branch.
    """

    def load_entities(self, client):
        return client.get(f"{PROVISIONING}/templates")

    def entity_id(self, entity):
        return _slug(entity["name"])

    def entity_name(self, entity):
        return entity["name"]

    def name(self):
        return "templates"

    def endpoint(self):
        return f"{PROVISIONING}/templates"

    def get_entity_path(self, entity):
        return f"{PROVISIONING}/templates/{quote(entity['name'], safe='')}"

    def describe_difference(self, current, desired):
        return changes.describe_differences(
            current, desired, ignored=("provenance", "version"),
        )

    def write(self, client, entity, path, action, ctx):
        # PUT is create-or-update here, so both actions take the same route.
        return client.put(path, entity, headers=self.headers(ctx))


class NotificationPolicyResource(ProvisioningEntity):
    """The notification policy tree.

    Unlike everything else this is ONE global object, and PUT replaces the
    whole tree. Any route that exists only in the target is gone afterwards.
    That is why it sits behind its own toggle (sync_notification_policy) which
    defaults to off.
    """

    FILENAME = "policy-tree"

    def load_entities(self, client):
        return [client.get(f"{PROVISIONING}/policies")]

    def entity_id(self, entity):
        return self.FILENAME

    def entity_name(self, entity):
        return "notification policy tree"

    def name(self):
        return "notification-policies"

    def endpoint(self):
        return f"{PROVISIONING}/policies"

    def get_entity_path(self, entity):
        return f"{PROVISIONING}/policies"

    def describe_difference(self, current, desired):
        return changes.describe_differences(
            current, desired, ignored=("provenance", "version"),
        )

    def make_update(self, client, entity, ctx):
        name = self.entity_name(entity)
        detail = self.describe_difference(client.get(self.endpoint()), entity)
        if detail is None:
            self.unchanged(ctx, name)
            return

        logger.warning(
            "\t -> replacing the ENTIRE notification policy tree; routes that "
            "exist only in the target will be lost"
        )
        self.announce(ctx, changes.UPDATE, name, detail, "updating")
        if ctx.dry_run:
            ctx.record(self.name(), changes.UPDATE, name, detail)
            return
        body, response = client.put(
            self.endpoint(), entity, headers=self.headers(ctx)
        )
        self.record_result(
            ctx, response, body, entity, changes.UPDATE, name, detail, "restoring"
        )

    def diff_local_and_online(self, client, backup_dir):
        """A single global object is never "deleted" in the mirroring sense."""
        return []


def _slug(name):
    """A file name that survives a round trip for a name with spaces or slashes."""
    return quote(name, safe="")


ALERTING_RESOURCES = {
    "alert_rules": AlertRuleResource,
    "contact_points": ContactPointResource,
    "mute_timings": MuteTimingResource,
    "templates": NotificationTemplateResource,
    "notification_policy": NotificationPolicyResource,
}
