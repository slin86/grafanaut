"""Shared behaviour for every backed-up Grafana resource type."""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod

from grafanaut import changes
from grafanaut.logger import setup_logger

logger = setup_logger(__name__)


class BaseEntity(ABC):

    # ------------------------------------------------------------------
    # identity
    # ------------------------------------------------------------------
    @abstractmethod
    def entity_id(self, entity) -> str:
        """Stable identifier used as the backup file name.

        This must be something that never changes over the lifetime of an
        object, i.e. the uid. Putting the title in the file name creates an
        orphaned file on every rename, which then fights with the current
        file during restore and is never cleaned up by mirror-deletions
        (because the uid still exists online).
        """

    @abstractmethod
    def entity_name(self, entity) -> str:
        """Human readable label, used for log output only."""

    @abstractmethod
    def name(self) -> str:
        """Sub directory inside the backup directory."""

    @abstractmethod
    def endpoint(self) -> str:
        """Collection endpoint, used for listing and creating."""

    @abstractmethod
    def get_entity_path(self, entity) -> str:
        """Instance endpoint of a single object."""

    def delete_path(self, entity) -> str:
        return self.get_entity_path(entity)

    def sanitize(self, entity):
        """Strip volatile fields before writing to disk (keeps git diffs small)."""
        return entity

    def convert(self, data):
        """Transform a backup record into an API payload."""
        return data

    # ------------------------------------------------------------------
    # backup
    # ------------------------------------------------------------------
    def backup(self, client, backup_dir):
        logger.info(f"{self.name()} started")
        for entity in self.load_entities(client):
            logger.info(f"\t -> loading {self.name()} {self.entity_name(entity)}")
            self.write_entity_file(self.sanitize(entity), backup_dir)
        logger.info(f"{self.name()} done!")

    def load_entities(self, client):
        return client.get(self.endpoint())

    def entity_file(self, entity, backup_dir):
        return os.path.join(backup_dir, self.name(), f"{self.entity_id(entity)}.json")

    def write_entity_file(self, entity, backup_dir):
        path = self.entity_file(entity, backup_dir)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(entity, f, indent=2, sort_keys=True, ensure_ascii=False)
            f.write("\n")

    def delete_entity_file(self, entity, backup_dir):
        path = self.entity_file(entity, backup_dir)
        if os.path.exists(path):
            os.remove(path)

    def read_entity_files(self, backup_dir):
        folder = os.path.join(backup_dir, self.name())
        if not os.path.isdir(folder):
            logger.warning(f"No backup directory {folder}, skipping {self.name()}")
            return []
        entities = []
        for filename in sorted(os.listdir(folder)):
            if not filename.endswith(".json"):
                continue
            with open(os.path.join(folder, filename), encoding="utf-8") as f:
                entities.append(json.load(f))
        return entities

    # ------------------------------------------------------------------
    # restore
    # ------------------------------------------------------------------
    def restore(self, client, backup_dir, ctx):
        logger.info(f"{self.name()} started")
        entities = [self.convert(raw) for raw in self.read_entity_files(backup_dir)]
        for entity in self.restore_order(entities):
            self.make_update(client, entity, ctx)
        logger.info(f"{self.name()} done!")

    def restore_order(self, entities):
        """Hook for resources with ordering constraints (see FolderResource)."""
        return entities

    def make_update(self, client, entity, ctx):
        path = self.get_entity_path(entity)
        name = self.entity_name(entity)

        if client.exists(path):
            detail = self.describe_difference(client.get(path), entity)
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
        body, response = self.write(client, entity, path, action, ctx)
        self.record_result(ctx, response, body, entity, action, name, detail, "restoring")

    def write(self, client, entity, path, action, ctx):
        """Perform the actual write. Overridden where extra headers or a
        different endpoint choice are needed (see the alerting resources)."""
        if action == changes.UPDATE:
            return client.put(path, entity)
        return client.post(self.endpoint(), entity)

    def describe_difference(self, current, desired):
        """Return a short description of what differs, or None when the object
        is already in the wanted state. Returning "" means "differs, no detail"."""
        return ""

    # ------------------------------------------------------------------
    # change reporting
    # ------------------------------------------------------------------
    def announce(self, ctx, action, name, detail, verb):
        suffix = f" [{detail}]" if detail else ""
        logger.info(f"\t -> {verb} {self.name()}: {name}{suffix}")

    def unchanged(self, ctx, name):
        ctx.record(self.name(), changes.UNCHANGED, name)
        logger.debug(f"\t    unchanged {self.name()}: {name}")

    def record_result(self, ctx, response, body, entity, action, name, detail, verb):
        if self.check(response, body, entity, verb):
            ctx.record(self.name(), action, name, detail)
        else:
            ctx.record(self.name(), changes.FAILED, name, f"{verb}: {response.status_code}")

    # ------------------------------------------------------------------
    # deletion mirroring
    # ------------------------------------------------------------------
    def diff_local_and_online(self, client, backup_dir):
        """Objects that still have a backup file but no longer exist online.

        The backup directory is never pruned during backup, so a leftover file
        means the object was deleted in the source since the last run. This is
        implemented once here -- previously only DashboardResource had it and
        every other resource silently returned None, which is why deleted
        folders were never mirrored.
        """
        deleted = []
        for raw in self.read_entity_files(backup_dir):
            entity = self.convert(raw)
            if not client.exists(self.get_entity_path(entity)):
                deleted.append(entity)
        if deleted:
            logger.info(f"\t{len(deleted)} deleted {self.name()} found")
        return self.deletion_order(deleted)

    def deletion_order(self, entities):
        return entities

    def delete(self, client, entity, ctx):
        path = self.delete_path(entity)
        logger.info(f"\t -> deleting {self.name()}: {self.entity_name(entity)} ({path})")
        if ctx.dry_run:
            ctx.record(self.name(), changes.DELETE, self.entity_name(entity))
            return
        body, response = client.delete(path)
        if response.status_code == 404:
            logger.info(f"\t\talready gone: {self.entity_name(entity)}")
            return
        self.record_result(
            ctx, response, body, entity, changes.DELETE,
            self.entity_name(entity), "", "deleting",
        )

    # ------------------------------------------------------------------
    def report_conflict(self, ctx, name, detail):
        """A write was refused to protect an object that only exists in the
        target. Logged as an error so the run ends with a non-zero exit code."""
        logger.error(f"\t\tCONFLICT, skipping {self.name()} {name}: {detail}")
        ctx.record(self.name(), changes.CONFLICT, name, detail)

    @staticmethod
    def same_title(left, right):
        """Grafana treats titles case insensitively when checking uniqueness."""
        return (left or "").strip().casefold() == (right or "").strip().casefold()

    def check(self, response, body, entity, action):
        """Log any 4xx/5xx. The previous threshold was >499, which swallowed
        every 400 ('folder not found', 'rules still attached', ...)."""
        if response.status_code >= 400:
            logger.error(
                f"\t\tError {action} {self.name()} {self.entity_name(entity)}: "
                f"{response.status_code}: {body}"
            )
            return False
        return True
