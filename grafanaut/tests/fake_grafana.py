"""In-memory stand-in for a Grafana instance, good enough to exercise the
folder tree, moves, permissions and dashboard restore paths."""

from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse

from grafanaut.http_client import GrafanaApiError


class FakeResponse:
    def __init__(self, status_code=200, body=None):
        self.status_code = status_code
        self._body = body if body is not None else {}

    @property
    def text(self):
        return json.dumps(self._body)


class FakeGrafana:
    def __init__(self):
        self.folders = {}       # uid -> {uid, title, parentUid, description}
        self.dashboards = {}    # uid -> {dashboard, folderUid}
        self.datasources = {}
        self.permissions = {}   # folder uid -> items
        self.calls = []

    # -- helpers -------------------------------------------------------
    @staticmethod
    def _split(path):
        parsed = urlparse(path)
        return parsed.path, {k: v[0] for k, v in parse_qs(parsed.query).items()}

    def add_folder(self, uid, title, parent_uid=None, description=""):
        self.folders[uid] = {
            "uid": uid, "title": title,
            "parentUid": parent_uid, "description": description,
        }

    def add_dashboard(self, uid, title, folder_uid="", tags=None):
        self.dashboards[uid] = {
            "dashboard": {"uid": uid, "title": title, "tags": tags or [], "version": 1},
            "folderUid": folder_uid,
        }

    # -- client interface ---------------------------------------------
    def exists(self, path):
        route, _ = self._split(path)
        if route.startswith("/api/folders/"):
            return route.split("/")[3] in self.folders
        if route.startswith("/api/dashboards/uid/"):
            return route.split("/")[4] in self.dashboards
        if route.startswith("/api/datasources/uid/"):
            return route.split("/")[4] in self.datasources
        raise GrafanaApiError("GET", path, 500, "unknown route")

    def get(self, path):
        route, query = self._split(path)
        self.calls.append(("GET", route, query))

        if route == "/api/folders":
            parent = query.get("parentUid")
            return [
                dict(f) for f in self.folders.values()
                if (f["parentUid"] or None) == (parent or None)
            ]
        if route.endswith("/permissions"):
            return list(self.permissions.get(route.split("/")[3], []))
        if route.startswith("/api/folders/"):
            return dict(self.folders[route.split("/")[3]])
        if route == "/api/search":
            return [{"uid": uid} for uid in self.dashboards]
        if route.startswith("/api/dashboards/uid/"):
            record = self.dashboards[route.split("/")[4]]
            return {
                "dashboard": dict(record["dashboard"]),
                "meta": {"folderUid": record["folderUid"]} if record["folderUid"] else {},
            }
        if route == "/api/datasources":
            return list(self.datasources.values())
        raise GrafanaApiError("GET", path, 404, "not found")

    def post(self, path, data):
        route, _ = self._split(path)
        self.calls.append(("POST", route, data))

        if route == "/api/folders":
            self.add_folder(data["uid"], data["title"],
                            data.get("parentUid"), data.get("description", ""))
            return {}, FakeResponse(200)
        if route.endswith("/move"):
            uid = route.split("/")[3]
            self.folders[uid]["parentUid"] = data.get("parentUid") or None
            return {}, FakeResponse(200)
        if route.endswith("/permissions"):
            self.permissions[route.split("/")[3]] = data["items"]
            return {}, FakeResponse(200)
        if route == "/api/dashboards/db":
            uid = data["dashboard"]["uid"]
            self.dashboards[uid] = {
                "dashboard": dict(data["dashboard"]),
                "folderUid": data.get("folderUid", ""),
            }
            return {}, FakeResponse(200)
        return {}, FakeResponse(404, {"message": "not found"})

    def put(self, path, data):
        route, _ = self._split(path)
        self.calls.append(("PUT", route, data))
        if route.startswith("/api/folders/"):
            folder = self.folders[route.split("/")[3]]
            folder["title"] = data["title"]
            if "description" in data:
                folder["description"] = data["description"]
            # Deliberately ignores parentUid, exactly like the real API.
            return {}, FakeResponse(200)
        return {}, FakeResponse(404, {"message": "not found"})

    def delete(self, path):
        route, _ = self._split(path)
        self.calls.append(("DELETE", route, {}))
        uid = route.split("/")[-1]
        for store in (self.folders, self.dashboards, self.datasources):
            if uid in store:
                del store[uid]
                return {}, FakeResponse(200)
        return {}, FakeResponse(404, {"message": "not found"})
