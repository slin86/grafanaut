"""Dashboard resource."""

from __future__ import annotations

import json

from grafanaut import changes
from grafanaut.base_entity import BaseEntity
from grafanaut.logger import setup_logger

logger = setup_logger(__name__)

# Fields Grafana maintains itself, never a reason to push a new version.
VOLATILE_FIELDS = {"id", "version"}
MAX_REPORTED_FIELDS = 5

NAME = "dashboards"
ENDPOINT_POST = "/api/dashboards/db"
PAGE_SIZE = 1000


class DashboardResource(BaseEntity):

    def load_entities(self, client):
        return [
            client.get(f"/api/dashboards/uid/{item['uid']}")
            for item in self._search(client)
        ]

    @staticmethod
    def _search(client):
        """/api/search is capped at 1000 results, so page through it."""
        page, found = 1, []
        while True:
            batch = client.get(
                f"/api/search?query=&type=dash-db&limit={PAGE_SIZE}&page={page}"
            )
            found.extend(batch)
            if len(batch) < PAGE_SIZE:
                return found
            page += 1

    def entity_id(self, entity):
        return entity["dashboard"]["uid"]

    def entity_name(self, entity):
        return entity["dashboard"].get("title", self.entity_id(entity))

    def name(self):
        return NAME

    def endpoint(self):
        return ENDPOINT_POST

    def get_entity_path(self, entity):
        return f"/api/dashboards/uid/{self.entity_id(entity)}"

    def sanitize(self, entity):
        """Keep only what a restore needs. Dropping id/version stops the
        backup from churning in git on every save in the source."""
        dashboard = dict(entity["dashboard"])
        dashboard.pop("id", None)
        dashboard.pop("version", None)
        meta = entity.get("meta") or {}
        return {
            "dashboard": dashboard,
            "meta": {
                "folderUid": meta.get("folderUid") or "",
                "folderTitle": meta.get("folderTitle") or "",
            },
        }

    def convert(self, data):
        dashboard = dict(data["dashboard"])
        dashboard["id"] = None
        meta = data.get("meta") or {}
        return {
            "dashboard": dashboard,
            # Root level dashboards have no folderUid in meta at all -- the
            # previous direct key access raised KeyError and aborted the whole
            # dashboard restore from that file onwards.
            "folderUid": meta.get("folderUid") or "",
            "overwrite": True,
        }

    def make_update(self, client, entity, ctx):
        """Create, update or move. /api/dashboards/db does all three: the uid
        decides create vs update, and a different folderUid moves it.

        The target is read first so an unchanged dashboard is skipped instead
        of posting a new version on every run. That keeps the version history
        of the target clean and makes a dry run show the actual delta.
        """
        name = self.entity_name(entity)
        payload = dict(entity)
        payload["dashboard"] = ctx.policy.decorate_dashboard(
            dict(entity["dashboard"]), ctx.source
        )
        payload["message"] = f"grafanaut sync from {ctx.source}"

        path = self.get_entity_path(entity)
        if client.exists(path):
            detail = self.describe_difference(client.get(path), payload)
            if detail is None:
                self.unchanged(ctx, name)
                return
            action, verb = changes.UPDATE, "updating"
        else:
            detail, action, verb = "", changes.CREATE, "creating"

        self.announce(ctx, action, name, detail, verb)
        if ctx.dry_run:
            ctx.record(self.name(), action, name, detail)
            return
        body, response = client.post(self.endpoint(), payload)
        self.record_result(ctx, response, body, entity, action, name, detail, verb)

    def describe_difference(self, current, desired):
        """Compare the target's dashboard against what we would push.

        Caveat: Grafana normalises a dashboard on save (schema migrations,
        panel defaults), so a dashboard that was imported from an older schema
        can report differing keys even though nothing meaningful changed. The
        folder comparison is exact, the content comparison is a strong hint.
        """
        reasons = []

        current_folder = (current.get("meta") or {}).get("folderUid") or ""
        desired_folder = desired.get("folderUid") or ""
        if current_folder != desired_folder:
            reasons.append(
                f"folder: {current_folder or 'root'} -> {desired_folder or 'root'}"
            )

        differing = _differing_keys(current.get("dashboard") or {}, desired["dashboard"])
        if differing:
            reasons.append("fields: " + ", ".join(differing))

        return ", ".join(reasons) if reasons else None


def _differing_keys(current, desired):
    """Top level dashboard keys whose value differs, ignoring volatile ones."""
    keys = (set(current) | set(desired)) - VOLATILE_FIELDS
    differing = sorted(
        key for key in keys
        if json.dumps(current.get(key), sort_keys=True, default=str)
        != json.dumps(desired.get(key), sort_keys=True, default=str)
    )
    if len(differing) > MAX_REPORTED_FIELDS:
        return differing[:MAX_REPORTED_FIELDS] + [f"+{len(differing) - MAX_REPORTED_FIELDS} more"]
    return differing
