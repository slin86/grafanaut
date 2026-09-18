"""Dashboard resource."""

from __future__ import annotations

from grafanaut.base_entity import BaseEntity
from grafanaut.logger import setup_logger

logger = setup_logger(__name__)

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
        """Always POST. /api/dashboards/db creates or updates by uid, and
        moving between folders is done by sending a different folderUid with
        overwrite=true."""
        payload = dict(entity)
        payload["dashboard"] = ctx.policy.decorate_dashboard(
            dict(entity["dashboard"]), ctx.source
        )
        payload["message"] = f"grafanaut sync from {ctx.source}"
        logger.info(f"\t -> restoring {self.name()}: {self.entity_name(entity)}")
        if ctx.dry_run:
            return
        body, response = client.post(self.endpoint(), payload)
        self.check(response, body, entity, "restoring")
