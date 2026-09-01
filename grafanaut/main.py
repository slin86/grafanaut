import os

from grafanaut.http_client import GrafanaClient
from grafanaut.entities import RESOURCE_REGISTRY
from grafanaut.logger import setup_logger
from grafanaut.config import GrafanautConfig

logger = setup_logger(__name__)

def main(source: str, targets: list[str], mode: str="all"):
    logger.info("Starting Grafanaut...")

    config = get_config(source, targets)
    source_client = create_client(config, source)

    if mode in ("mirror-deletions", "backup", "all"):
        process_backup(source, source_client)

    if mode in ("mirror-deletions", "all"):
        process_mirror_deletions(config, source, source_client, targets)

    if mode in ("restore", "all"):
        process_restore(config, source, targets)

    logger.info("Grafanaut done!")

def get_config(source, targets):
    config = GrafanautConfig()
    return config.load_config(source, targets)

def process_restore(config, source, targets):
    for target in targets:
        logger.info(f"Starting Restore of {target}")
        target_client = create_client(config, target)
        for resource in RESOURCE_REGISTRY:
            resource.restore(target_client, get_backup_folder(source))
        logger.info(f"Restore of {target} done!")

def process_backup(source, source_client):
    logger.info(f"Backup of {source} started")
    for resource in RESOURCE_REGISTRY:
        resource.backup(source_client, get_backup_folder(source))
    logger.info(f"Backup of {source} done!")

def process_mirror_deletions(config, source, source_client, targets):
    logger.info(f"Mirror Deletions started")
    for resource in RESOURCE_REGISTRY:
        diff = resource.diff_local_and_online(source_client, get_backup_folder(source))
        if diff:
            items_for_deletion = []
            for target in targets:
                target_client = create_client(config, target)
                for item in diff:
                    items_for_deletion.append(item)
                    resource.delete(target_client, item)
                logger.info(f"\tMirror Deletions of {source} -> {target} done!")
            for item in items_for_deletion:
                resource.delete_entity_file(item, get_backup_folder(source))
                logger.info("cleaning up item: {item}")


    logger.info(f"Mirror Deletions done!")

def create_client(config, stage):
    token = GrafanautConfig.get_token(config, stage)
    source_client = GrafanaClient(config[stage]["url"], token)
    return source_client

def get_backup_folder(source):
    return os.path.join("backup", source)