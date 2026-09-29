"""Configuration loading."""

from __future__ import annotations

import os

import yaml

from grafanaut.auth import build_provider, expand
from grafanaut.http_client import GrafanaClient
from grafanaut.logger import setup_logger
from grafanaut.sync_policy import AlertingPolicy, SyncPolicy

logger = setup_logger(__name__)

DEFAULT_CONFIG_PATH = "config.yaml"
DEFAULT_BACKUP_DIR = "backup"


class GrafanautConfig:
    def __init__(self, instances, backup_dir, sync, alerting):
        self.instances = instances
        self.backup_dir = backup_dir
        self.sync = sync
        self.alerting = alerting

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
            alerting=AlertingPolicy.from_dict(raw.get("alerting")),
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
        """The current bearer token for an instance.

        Kept for callers that only want the token; the client itself holds the
        provider so an OIDC token can be refreshed mid-run.
        """
        return build_provider(stage, self.instances[stage]).token()

    def client(self, stage):
        settings = self.instances[stage]
        if not settings.get("url"):
            raise RuntimeError(f"Grafanaut: no url configured for '{stage}'")
        return GrafanaClient(
            expand(settings["url"]),
            token_provider=build_provider(stage, settings),
            extra_headers={
                key: expand(value)
                for key, value in (settings.get("headers") or {}).items()
            },
        )

    def backup_dir_for(self, source):
        return os.path.join(self.backup_dir, source)
