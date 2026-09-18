"""Datasource resource.

Note: the API never returns secureJsonData, so backups contain no secrets.
On update Grafana keeps the existing secrets of the target datasource; on
first creation in a fresh target, credentials have to be provisioned
separately.
"""

from __future__ import annotations

import json

from grafanaut.base_entity import BaseEntity

NAME = "datasource"
ENDPOINT = "/api/datasources"


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
        sanitized = dict(entity)
        # Numeric ids differ per instance and only create git noise.
        sanitized.pop("id", None)
        sanitized.pop("orgId", None)
        sanitized.pop("version", None)
        return sanitized

    def convert(self, data):
        payload = dict(data)
        payload["id"] = None
        return payload

    def describe_difference(self, current, desired):
        ignored = {"id", "orgId", "version", "readOnly", "typeLogoUrl"}
        keys = (set(current) | set(desired)) - ignored
        differing = sorted(
            key for key in keys
            if json.dumps(current.get(key), sort_keys=True, default=str)
            != json.dumps(desired.get(key), sort_keys=True, default=str)
        )
        if not differing:
            return None
        return "fields: " + ", ".join(differing[:5])
