"""Configuration loading."""

from __future__ import annotations

import os

import yaml

from grafanaut.http_client import GrafanaClient
from grafanaut.logger import setup_logger
from grafanaut.sync_policy import SyncPolicy

logger = setup_logger(__name__)

DEFAULT_CONFIG_PATH = "config.yaml"
DEFAULT_BACKUP_DIR = "backup"


class GrafanautConfig:
    def __init__(self, instances, backup_dir, sync):
        self.instances = instances
        self.backup_dir = backup_dir
        self.sync = sync

    @classmethod
    def load(cls, path=None, source=None, targets=None):
        path = path or os.environ.get("GRAFANAUT_CONFIG") or DEFAULT_CONFIG_PATH
        logger.info(f"Loading configuration from {path}")
        raw = cls.read_config(path)
        config = cls(
            instances=raw.get("instances") or {},
            # backup_dir was documented in the README but previously ignored.
            backup_dir=raw.get("backup_dir") or DEFAULT_BACKUP_DIR,
            sync=SyncPolicy.from_dict(raw.get("sync")),
        )
        config.validate(source, targets)
        return config

    @staticmethod
    def read_config(path):
        if not os.path.exists(path):
            raise RuntimeError(f"Grafanaut: config file '{path}' not found")
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def validate(self, source, targets):
        if source is not None and source not in self.instances:
            raise RuntimeError(f"Grafanaut: No configuration found for '{source}'")
        for target in targets or []:
            if target not in self.instances:
                raise RuntimeError(f"Grafanaut: No configuration found for '{target}'")
            if target == source:
                raise RuntimeError(f"Grafanaut: '{target}' is both source and target")

    def get_token(self, stage):
        env_var = f"GRAFANA_TOKEN_{stage.upper()}"
        token = os.environ.get(env_var) or self.instances[stage].get("token")
        if not token:
            raise RuntimeError(
                f"Grafanaut: No token for '{stage}' (set {env_var} or config.yaml)"
            )
        return token

    def client(self, stage):
        return GrafanaClient(self.instances[stage]["url"], self.get_token(stage))

    def backup_dir_for(self, source):
        return os.path.join(self.backup_dir, source)
