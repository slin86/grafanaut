"""Shared behaviour for every backed-up Grafana resource type."""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod

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
        if client.exists(path):
            logger.info(f"\t -> updating {self.name()}: {self.entity_name(entity)}")
            if ctx.dry_run:
                return
            body, response = client.put(path, entity)
        else:
            logger.info(f"\t -> creating {self.name()}: {self.entity_name(entity)}")
            if ctx.dry_run:
                return
            body, response = client.post(self.endpoint(), entity)
        self.check(response, body, entity, "restoring")

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

    def delete(self, client, entity, ctx=None):
        path = self.delete_path(entity)
        logger.info(f"\t -> deleting {self.name()}: {self.entity_name(entity)} ({path})")
        if ctx is not None and ctx.dry_run:
            return
        body, response = client.delete(path)
        if response.status_code == 404:
            logger.info(f"\t\talready gone: {self.entity_name(entity)}")
            return
        self.check(response, body, entity, "deleting")

    # ------------------------------------------------------------------
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
