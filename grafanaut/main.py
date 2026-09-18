"""Entry point for backup, deletion mirroring and restore."""

from __future__ import annotations

from dataclasses import replace

from grafanaut.changes import ChangeLog, write_report
from grafanaut.config import GrafanautConfig
from grafanaut.entities import RESOURCE_REGISTRY
from grafanaut.logger import error_count, setup_logger
from grafanaut.sync_policy import SyncContext

logger = setup_logger(__name__)


def main(source, targets, mode="all", config_path=None, dry_run=False, report=None):
    logger.info("Starting Grafanaut...")
    if dry_run:
        logger.info("DRY RUN - no write requests will be sent")

    config = GrafanautConfig.load(config_path, source, targets)
    if mode in ("restore", "mirror-deletions", "all") and not targets:
        raise RuntimeError(f"Grafanaut: mode '{mode}' requires --targets")

    backup_dir = config.backup_dir_for(source)
    ctx = SyncContext(source=source, policy=config.sync, dry_run=dry_run)
    source_client = config.client(source)
    changelogs = []

    if mode in ("mirror-deletions", "backup", "all"):
        process_backup(source_client, backup_dir)

    if mode in ("mirror-deletions", "all"):
        changelogs += process_mirror_deletions(
            config, source_client, backup_dir, targets, ctx
        )

    if mode in ("restore", "all"):
        changelogs += process_restore(config, backup_dir, targets, ctx)

    report_changes(changelogs, report, dry_run)

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
    changelogs = []
    for target in targets:
        logger.info(f"Starting restore of {target}")
        target_ctx = replace(ctx, changes=ChangeLog(target=f"restore:{target}"))
        target_client = config.client(target)
        for resource in RESOURCE_REGISTRY:
            resource.restore(target_client, backup_dir, target_ctx)
        logger.info(f"Restore of {target}: {target_ctx.changes.summary()}")
        changelogs.append(target_ctx.changes)
    return changelogs


def process_mirror_deletions(config, source_client, backup_dir, targets, ctx):
    logger.info("Mirror Deletions started")
    target_clients = {target: config.client(target) for target in targets}
    changelogs = {
        target: replace(ctx, changes=ChangeLog(target=f"delete:{target}"))
        for target in targets
    }

    # Reverse registry order: dashboards before folders. Deleting a folder
    # cascades into everything inside it, including target-only dashboards
    # that are explicitly not supposed to be removed.
    for resource in reversed(RESOURCE_REGISTRY):
        diff = resource.diff_local_and_online(source_client, backup_dir)
        if not diff:
            continue
        for target, target_client in target_clients.items():
            for item in diff:
                resource.delete(target_client, item, changelogs[target])
            logger.info(f"\tMirror Deletions {ctx.source} -> {target} done!")
        if ctx.dry_run:
            continue
        for item in diff:
            resource.delete_entity_file(item, backup_dir)
            logger.info(f"\tcleaned up backup file for {resource.entity_name(item)}")

    for target, target_ctx in changelogs.items():
        logger.info(f"Mirror Deletions {target}: {target_ctx.changes.summary()}")
    logger.info("Mirror Deletions done!")
    return [c.changes for c in changelogs.values()]


def report_changes(changelogs, report_path, dry_run):
    """Final verdict, so a run says whether it changed anything at all."""
    changed = [c for log in changelogs for c in log.changed()]
    if changed:
        prefix = "Would change" if dry_run else "Changed"
        logger.info(f"{prefix} {len(changed)} object(s):")
        for change in changed:
            logger.info(f"\t[{change.target}] {change}")
    else:
        logger.info("No changes - all targets already match the backup")

    if report_path:
        write_report(report_path, changelogs)
        logger.info(f"Report written to {report_path}")
