"""Datasource resource.

Note: the API never returns secureJsonData, so backups contain no secrets.
On update Grafana keeps the existing secrets of the target datasource; on
first creation in a fresh target, credentials have to be provisioned
separately.
"""

from __future__ import annotations

from grafanaut import changes
from grafanaut.base_entity import BaseEntity

NAME = "datasource"
ENDPOINT = "/api/datasources"

# Fields the API derives or reports read-only. They differ between instances
# (and between Grafana versions) but cannot be written, so including them in
# the comparison would mark every datasource as changed on every single run.
DERIVED_FIELDS = {
    "id", "orgId", "version", "readOnly", "uid",
    "typeName", "typeLogoUrl", "accessControl", "secureJsonFields",
}


class DatasourceResource(BaseEntity):

    def entity_id(self, entity):
        return entity["uid"]

    def entity_name(self, entity):
        return entity.get("name", entity["uid"])

    def name(self):
        return NAME

    def endpoint(self):
        return ENDPOINT

    def get_entity_path(self, entity):
        return f"{ENDPOINT}/uid/{entity['uid']}"

    def sanitize(self, entity):
        # Keep uid (it is the file name and the identity), drop the rest of the
        # derived fields so they never enter the backup in the first place.
        return {
            key: value for key, value in entity.items()
            if key == "uid" or key not in DERIVED_FIELDS
        }

    def convert(self, data):
        payload = dict(data)
        payload["id"] = None
        return payload

    def describe_difference(self, current, desired):
        return changes.describe_differences(current, desired, DERIVED_FIELDS)
