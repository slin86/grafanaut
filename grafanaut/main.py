"""Entry point for backup, deletion mirroring and restore."""

from __future__ import annotations

from grafanaut.config import GrafanautConfig
from grafanaut.entities import RESOURCE_REGISTRY
from grafanaut.logger import error_count, setup_logger
from grafanaut.sync_policy import SyncContext

logger = setup_logger(__name__)


def main(source, targets, mode="all", config_path=None, dry_run=False):
    logger.info("Starting Grafanaut...")
    if dry_run:
        logger.info("DRY RUN - no write requests will be sent")

    config = GrafanautConfig.load(config_path, source, targets)
    if mode in ("restore", "mirror-deletions", "all") and not targets:
        raise RuntimeError(f"Grafanaut: mode '{mode}' requires --targets")

    backup_dir = config.backup_dir_for(source)
    ctx = SyncContext(source=source, policy=config.sync, dry_run=dry_run)
    source_client = config.client(source)

    if mode in ("mirror-deletions", "backup", "all"):
        process_backup(source_client, backup_dir)

    if mode in ("mirror-deletions", "all"):
        process_mirror_deletions(config, source_client, backup_dir, targets, ctx)

    if mode in ("restore", "all"):
        process_restore(config, backup_dir, targets, ctx)

    errors = error_count()
    if errors:
        logger.error(f"Grafanaut finished with {errors} error(s)")
        return 1
    logger.info("Grafanaut done!")
    return 0


def process_backup(source_client, backup_dir):
    logger.info(f"Backup into {backup_dir} started")
    for resource in RESOURCE_REGISTRY:
        resource.backup(source_client, backup_dir)
    logger.info("Backup done!")


def process_restore(config, backup_dir, targets, ctx):
    for target in targets:
        logger.info(f"Starting restore of {target}")
        target_client = config.client(target)
        for resource in RESOURCE_REGISTRY:
            resource.restore(target_client, backup_dir, ctx)
        logger.info(f"Restore of {target} done!")


def process_mirror_deletions(config, source_client, backup_dir, targets, ctx):
    logger.info("Mirror Deletions started")
    target_clients = {target: config.client(target) for target in targets}

    # Reverse registry order: dashboards before folders. Deleting a folder
    # cascades into everything inside it, including target-only dashboards
    # that are explicitly not supposed to be removed.
    for resource in reversed(RESOURCE_REGISTRY):
        diff = resource.diff_local_and_online(source_client, backup_dir)
        if not diff:
            continue
        for target, target_client in target_clients.items():
            for item in diff:
                resource.delete(target_client, item, ctx)
            logger.info(f"\tMirror Deletions {ctx.source} -> {target} done!")
        if ctx.dry_run:
            continue
        for item in diff:
            resource.delete_entity_file(item, backup_dir)
            logger.info(f"\tcleaned up backup file for {resource.entity_name(item)}")

    logger.info("Mirror Deletions done!")
