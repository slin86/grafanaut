import json
import os

from grafanaut.base_entity import BaseEntity
from grafanaut.logger import setup_logger

logger = setup_logger(__name__)
NAME = "dashboards"
ENDPOINT_POST = "/api/dashboards/db"

class DashboardResource(BaseEntity):
    def load_entities(self, client):
        dashboards = client.get("/api/search?query=&type=dash-db")
        entities = []
        for item in dashboards:
            uid = item['uid']
            entities.append(client.get(f"/api/dashboards/uid/{uid}"))
        return entities

    def entity_name(self, entity):
        return f"{entity['dashboard']['title']}_{entity['dashboard']['uid']}"

    def name(self):
        return NAME

    def endpoint(self):
        return ENDPOINT_POST

    def convert(self, data):
        data['dashboard']['id'] = None
        return {
            "dashboard": data["dashboard"],
            "folderUid": data["meta"]["folderUid"],
            "overwrite": True
        }

    def get_entity_path(self, entity):
        return f"/api/dashboards/uid/{entity['dashboard']['uid']}"

    def make_update(self, client, entity):
        logger.info(f"\t -> creating {self.name()}: {self.entity_name(entity)}")
        body, response = client.post(self.endpoint(), entity)
        if response.status_code > 399:
            logger.error(f"\t\tError restoring {self.name()} {self.entity_name(entity)}: {response.status_code}: {body}")

    def diff_local_and_online(self, client, backup_dir):
        folder = os.path.join(backup_dir, self.name())
        if not os.path.exists(folder):
            logger.error(f"Backup folder {folder} does not exist")
            return
        entities = []
        for filename in sorted(os.listdir(folder)):
            with open(os.path.join(folder, filename)) as f:
                entity = self.convert(json.load(f))
                entity_path = self.get_entity_path(entity)
                if not client.exists(entity_path):
                    entities.append(entity)
        if entities:
            logger.info(f"\t{len(entities)} deleted {self.name()} found")
        return entities