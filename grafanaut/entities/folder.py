"""Folder resource, including nested folders (Grafana 11+)."""

from __future__ import annotations

from grafanaut import changes
from grafanaut.base_entity import BaseEntity
from grafanaut.logger import setup_logger
from grafanaut.sync_policy import VIEW

logger = setup_logger(__name__)

NAME = "folder"
ENDPOINT = "/api/folders"
PAGE_SIZE = 1000
LOCKED_ROLES = ("Viewer", "Editor")


class FolderResource(BaseEntity):

    # ------------------------------------------------------------------
    # backup
    # ------------------------------------------------------------------
    def load_entities(self, client):
        """Walk the entire folder tree breadth-first.

        The old implementation derived folders from the dashboard search
        (/api/search?type=dash-db), so a folder only existed if it directly
        contained a dashboard. Empty folders, folders holding only subfolders
        and intermediate levels of a nested path were all invisible.

        GET /api/folders returns only the immediate children of the given
        parent (root level when parentUid is omitted), so one request per
        level is required.
        """
        entities, queue, seen = [], [None], set()
        while queue:
            parent_uid = queue.pop(0)
            for item in self._list_children(client, parent_uid):
                uid = item["uid"]
                if uid in seen:
                    continue
                seen.add(uid)
                entities.append({
                    "uid": uid,
                    "title": item["title"],
                    "parentUid": parent_uid,
                    "description": item.get("description", ""),
                })
                queue.append(uid)
        return entities

    @staticmethod
    def _list_children(client, parent_uid):
        page, children = 1, []
        while True:
            path = f"{ENDPOINT}?limit={PAGE_SIZE}&page={page}"
            if parent_uid is not None:
                path += f"&parentUid={parent_uid}"
            batch = client.get(path)
            children.extend(batch)
            if len(batch) < PAGE_SIZE:
                return children
            page += 1

    # ------------------------------------------------------------------
    # identity
    # ------------------------------------------------------------------
    def entity_id(self, entity):
        return entity["uid"]

    def entity_name(self, entity):
        return entity.get("title", entity["uid"])

    def name(self):
        return NAME

    def endpoint(self):
        return ENDPOINT

    def get_entity_path(self, entity):
        return f"{ENDPOINT}/{entity['uid']}"

    def delete_path(self, entity):
        # Without forceDeleteRules the API returns 400 as soon as any alert
        # rule lives in the folder.
        return f"{self.get_entity_path(entity)}?forceDeleteRules=true"

    # ------------------------------------------------------------------
    # ordering
    # ------------------------------------------------------------------
    def restore_order(self, entities):
        """Parents before children, at any depth.

        The old scheme encoded the order in the file name ('0_root_...',
        '1_nested_...'), which only distinguished root from non-root. A level-3
        folder could be created before its level-2 parent, and the API then
        rejects the unknown parentUid.
        """
        by_uid = {e["uid"]: e for e in entities}

        def depth(entity):
            level, seen, current = 0, set(), entity
            while current is not None and current.get("parentUid"):
                if current["uid"] in seen:
                    logger.error(f"Cycle in folder hierarchy at {current['uid']}")
                    break
                seen.add(current["uid"])
                current = by_uid.get(current["parentUid"])
                level += 1
            return level

        return sorted(entities, key=lambda e: (depth(e), e.get("title", "")))

    def deletion_order(self, entities):
        # Deepest first, so a child is removed before its parent.
        return list(reversed(self.restore_order(entities)))

    # ------------------------------------------------------------------
    # restore
    # ------------------------------------------------------------------
    def make_update(self, client, entity, ctx):
        desired = ctx.policy.decorate_folder(entity, ctx.source)
        path = self.get_entity_path(desired)
        exists = client.exists(path)

        current = client.get(path) if exists else None
        if self._blocked_by_collision(client, current, desired, ctx):
            return

        if exists:
            touched = self._rename(client, path, current, desired, ctx)
            touched |= self._move(client, path, current, desired, ctx)
        else:
            self._create(client, desired, ctx)
            touched = True

        if ctx.policy.lock_folders and (exists or not ctx.dry_run):
            # In a dry run a folder that would have just been created does not
            # exist yet, so reading its permissions would only produce a 404.
            touched |= self._lock(client, desired, ctx)

        if not touched:
            self.unchanged(ctx, desired["title"])

    def _blocked_by_collision(self, client, current, desired, ctx):
        """Folder titles must be unique within a parent.

        Creating or moving into a parent that already holds a different folder
        with the same title would fail in the API anyway, but the message is
        unhelpful and the follow-up damage is worse: every dashboard pointing
        at the missing folder fails afterwards. Detect it up front and name
        the folder that is in the way.

        Only checked when the title or the parent actually changes.
        """
        parent = desired.get("parentUid") or None
        if current is not None:
            same_place = (current.get("parentUid") or None) == parent
            if same_place and self.same_title(current.get("title"), desired["title"]):
                return False

        clash = self.find_title_collision(
            client, parent, desired["title"], desired["uid"]
        )
        if clash is None:
            return False

        self.report_conflict(
            ctx, desired["title"],
            f"{parent or 'root'} already holds a different folder titled "
            f"{desired['title']!r} (uid {clash['uid']})",
        )
        return True

    def find_title_collision(self, client, parent_uid, title, own_uid):
        for sibling in self._list_children(client, parent_uid):
            if sibling["uid"] == own_uid:
                continue
            if self.same_title(sibling.get("title"), title):
                return sibling
        return None

    def _create(self, client, desired, ctx):
        parent = desired.get("parentUid") or "root"
        logger.info(f"\t -> creating folder: {desired['title']} [under {parent}]")
        if ctx.dry_run:
            ctx.record(NAME, changes.CREATE, desired["title"], f"under {parent}")
            return
        payload = {"uid": desired["uid"], "title": desired["title"]}
        if desired.get("parentUid"):
            payload["parentUid"] = desired["parentUid"]
        if desired.get("description"):
            payload["description"] = desired["description"]
        body, response = client.post(ENDPOINT, payload)
        self.record_result(ctx, response, body, desired, changes.CREATE,
                           desired["title"], f"under {parent}", "creating")

    def _rename(self, client, path, current, desired, ctx):
        same_title = current.get("title") == desired["title"]
        same_description = (current.get("description") or "") == (desired.get("description") or "")
        if same_title and same_description:
            return False
        detail = (
            "description"
            if same_title
            else f"title: {current.get('title')!r} -> {desired['title']!r}"
        )
        logger.info(f"\t -> updating folder: {current.get('title')} -> {desired['title']} [{detail}]")
        if ctx.dry_run:
            ctx.record(NAME, changes.UPDATE, desired["title"], detail)
            return True
        payload = {"title": desired["title"], "overwrite": True}
        if desired.get("description"):
            payload["description"] = desired["description"]
        body, response = client.put(path, payload)
        self.record_result(ctx, response, body, desired, changes.UPDATE,
                           desired["title"], detail, "renaming")
        return True

    def _move(self, client, path, current, desired, ctx):
        """PUT /api/folders/:uid ignores parentUid -- moving is a separate
        endpoint (POST /api/folders/:uid/move). This is why re-parenting a
        folder previously did nothing at all."""
        current_parent = current.get("parentUid") or None
        desired_parent = desired.get("parentUid") or None
        if current_parent == desired_parent:
            return False
        logger.info(
            f"\t -> moving folder {desired['title']}: "
            f"{current_parent or 'root'} -> {desired_parent or 'root'}"
        )
        detail = f"{current_parent or 'root'} -> {desired_parent or 'root'}"
        if ctx.dry_run:
            ctx.record(NAME, changes.MOVE, desired["title"], detail)
            return True
        body, response = client.post(f"{path}/move", {"parentUid": desired_parent or ""})
        self.record_result(ctx, response, body, desired, changes.MOVE,
                           desired["title"], detail, "moving")
        return True

    # ------------------------------------------------------------------
    # lockdown
    # ------------------------------------------------------------------
    def _lock(self, client, desired, ctx):
        """Downgrade write access on a synced folder to read-only.

        Effect in the UI: no save button on the dashboards inside, and no
        creating or deleting dashboards in the folder. Admins are unaffected,
        Grafana does not allow restricting them.

        POST replaces the whole permission list, so existing user/team grants
        are read first and carried over with their level capped at View
        instead of being wiped.
        """
        uid = desired["uid"]
        try:
            current = client.get(f"{ENDPOINT}/{uid}/permissions")
        except Exception as exc:  # noqa: BLE001 - lockdown must not abort the sync
            logger.error(f"\t\tCould not read permissions of folder {uid}: {exc}")
            ctx.record(NAME, changes.FAILED, desired["title"], "reading permissions")
            return False

        items, changed = [], False
        for permission in current:
            level = permission.get("permission", 0)
            if level > VIEW:
                level = VIEW
                changed = True
            item = {"permission": level}
            if permission.get("userId"):
                item["userId"] = permission["userId"]
            elif permission.get("teamId"):
                item["teamId"] = permission["teamId"]
            elif permission.get("role"):
                item["role"] = permission["role"]
            else:
                continue
            items.append(item)

        for role in LOCKED_ROLES:
            if not any(i.get("role") == role for i in items):
                items.append({"role": role, "permission": VIEW})
                changed = True

        if not changed:
            return False
        logger.info(f"\t -> locking folder (read-only for non-admins): {desired['title']}")
        if ctx.dry_run:
            ctx.record(NAME, changes.LOCK, desired["title"], "revoking write access")
            return True
        body, response = client.post(f"{ENDPOINT}/{uid}/permissions", {"items": items})
        self.record_result(ctx, response, body, desired, changes.LOCK,
                           desired["title"], "revoking write access", "locking")
        return True
