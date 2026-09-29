"""In-memory stand-in for a Grafana instance, good enough to exercise the
folder tree, moves, permissions and dashboard restore paths."""

from __future__ import annotations

import json
from urllib.parse import parse_qs, unquote, urlparse

from grafanaut.http_client import GrafanaApiError

PROVISIONING = "/api/v1/provisioning"


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
        # alerting (provisioning API)
        self.alert_rules = {}      # uid -> rule
        self.contact_points = {}   # uid -> contact point
        self.mute_timings = {}     # name -> timing
        self.templates = {}        # name -> template
        self.policy_tree = {"receiver": "default"}
        self.calls = []
        # Headers of the most recent write, so tests can assert on
        # X-Disable-Provenance.
        self.last_headers = None

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

    def add_alert_rule(self, uid, title, folder_uid="team", **extra):
        self.alert_rules[uid] = {
            "uid": uid, "title": title, "folderUID": folder_uid,
            "condition": "A", "id": 7, "provenance": "", **extra,
        }

    def add_contact_point(self, uid, name, settings=None, secure_fields=None):
        self.contact_points[uid] = {
            "uid": uid, "name": name, "type": "webhook",
            "settings": settings or {"url": "https://hooks.example.com/x"},
            "secureFields": secure_fields or {},
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
        if route.startswith(f"{PROVISIONING}/alert-rules/"):
            return route.rsplit("/", 1)[1] in self.alert_rules
        if route.startswith(f"{PROVISIONING}/contact-points/"):
            return route.rsplit("/", 1)[1] in self.contact_points
        if route.startswith(f"{PROVISIONING}/mute-timings/"):
            return unquote(route.rsplit("/", 1)[1]) in self.mute_timings
        if route.startswith(f"{PROVISIONING}/templates/"):
            return unquote(route.rsplit("/", 1)[1]) in self.templates
        if route == f"{PROVISIONING}/policies":
            return True
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
            wanted = (query.get("query") or "").casefold()
            hits = []
            for uid, record in self.dashboards.items():
                title = record["dashboard"].get("title", "")
                if wanted and wanted not in title.casefold():
                    continue
                hits.append({
                    "uid": uid,
                    "title": title,
                    "folderUid": record["folderUid"],
                    "type": "dash-db",
                })
            return hits
        if route.startswith("/api/dashboards/uid/"):
            record = self.dashboards[route.split("/")[4]]
            return {
                "dashboard": dict(record["dashboard"]),
                "meta": {"folderUid": record["folderUid"]} if record["folderUid"] else {},
            }
        if route == "/api/datasources":
            return list(self.datasources.values())

        # --- provisioning (alerting) ---
        if route == f"{PROVISIONING}/alert-rules":
            return [dict(r) for r in self.alert_rules.values()]
        if route.startswith(f"{PROVISIONING}/alert-rules/"):
            return dict(self.alert_rules[route.rsplit("/", 1)[1]])
        if route == f"{PROVISIONING}/contact-points":
            return [dict(c) for c in self.contact_points.values()]
        if route.startswith(f"{PROVISIONING}/contact-points/"):
            return dict(self.contact_points[route.rsplit("/", 1)[1]])
        if route == f"{PROVISIONING}/mute-timings":
            return [dict(t) for t in self.mute_timings.values()]
        if route.startswith(f"{PROVISIONING}/mute-timings/"):
            return dict(self.mute_timings[unquote(route.rsplit("/", 1)[1])])
        if route == f"{PROVISIONING}/templates":
            return [dict(t) for t in self.templates.values()]
        if route.startswith(f"{PROVISIONING}/templates/"):
            return dict(self.templates[unquote(route.rsplit("/", 1)[1])])
        if route == f"{PROVISIONING}/policies":
            return dict(self.policy_tree)

        raise GrafanaApiError("GET", path, 404, "not found")

    def post(self, path, data, headers=None):
        route, _ = self._split(path)
        self.calls.append(("POST", route, data))
        self.last_headers = headers

        if route == f"{PROVISIONING}/alert-rules":
            self.alert_rules[data["uid"]] = dict(data)
            return {}, FakeResponse(200)
        if route == f"{PROVISIONING}/contact-points":
            self.contact_points[data["uid"]] = dict(data)
            return {}, FakeResponse(200)
        if route == f"{PROVISIONING}/mute-timings":
            self.mute_timings[data["name"]] = dict(data)
            return {}, FakeResponse(200)

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

    def put(self, path, data, headers=None):
        route, _ = self._split(path)
        self.calls.append(("PUT", route, data))
        self.last_headers = headers

        if route.startswith(f"{PROVISIONING}/alert-rules/"):
            self.alert_rules[route.rsplit("/", 1)[1]] = dict(data)
            return {}, FakeResponse(200)
        if route.startswith(f"{PROVISIONING}/contact-points/"):
            self.contact_points[route.rsplit("/", 1)[1]] = dict(data)
            return {}, FakeResponse(200)
        if route.startswith(f"{PROVISIONING}/mute-timings/"):
            self.mute_timings[unquote(route.rsplit("/", 1)[1])] = dict(data)
            return {}, FakeResponse(200)
        if route.startswith(f"{PROVISIONING}/templates/"):
            self.templates[unquote(route.rsplit("/", 1)[1])] = dict(data)
            return {}, FakeResponse(200)
        if route == f"{PROVISIONING}/policies":
            # Replaces the whole tree, exactly like the real API.
            self.policy_tree = dict(data)
            return {}, FakeResponse(200)

        if route.startswith("/api/folders/"):
            folder = self.folders[route.split("/")[3]]
            folder["title"] = data["title"]
            if "description" in data:
                folder["description"] = data["description"]
            # Deliberately ignores parentUid, exactly like the real API.
            return {}, FakeResponse(200)
        return {}, FakeResponse(404, {"message": "not found"})

    def delete(self, path, headers=None):
        route, _ = self._split(path)
        self.calls.append(("DELETE", route, {}))
        self.last_headers = headers
        key = unquote(route.split("/")[-1])
        for store in (self.folders, self.dashboards, self.datasources,
                      self.alert_rules, self.contact_points,
                      self.mute_timings, self.templates):
            if key in store:
                del store[key]
                return {}, FakeResponse(200)
        return {}, FakeResponse(404, {"message": "not found"})
