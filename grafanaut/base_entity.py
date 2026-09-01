import os, json
from abc import ABC, abstractmethod
from grafanaut.logger import setup_logger

logger = setup_logger(__name__)

class BaseEntity(ABC):
    @abstractmethod
    def entity_name(self, entity): pass

    @abstractmethod
    def name(self): pass

    @abstractmethod
    def endpoint(self): pass

    @abstractmethod
    def convert(self, data): pass

    @abstractmethod
    def get_entity_path(self, entity): pass

    def backup(self, client, backup_dir):
        logger.info(f"{self.name()} started")
        entities = self.load_entities(client)
        for entity in entities:
            logger.info(f"\t -> loading {self.name()} {self.entity_name(entity)}")
            self.write_entity_file(entity, backup_dir)
        logger.info(f"{self.name()} done!")

    def load_entities(self, client):
        return client.get(self.endpoint())

    def write_entity_file(self, entity, backup_dir):
        name = self.entity_name(entity)
        path = os.path.join(backup_dir, self.name(), f"{name}.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(entity, f, indent=2)

    def delete_entity_file(self, entity, backup_dir):
        name = self.entity_name(entity)
        path = os.path.join(backup_dir, self.name(), f"{name}.json")
        if os.path.exists(path):
            os.remove(path)

    def restore(self, client, backup_dir):
        logger.info(f"{self.name()} started")
        folder = os.path.join(backup_dir, self.name())
        for filename in sorted(os.listdir(folder)):
            with open(os.path.join(folder, filename)) as f:
                data = self.convert(json.load(f))
                self.make_update(client, data)
        logger.info(f"{self.name()} done!")

    def make_update(self, client, entity):
        entity_path = self.get_entity_path(entity)

        if client.exists(entity_path):
            logger.info(f"\t -> updating {self.name()}: {self.entity_name(entity)}")
            body, response = client.put(entity_path, entity)
        else:
            logger.info(f"\t -> creating {self.name()}: {self.entity_name(entity)}")
            body, response = client.post(self.endpoint(), entity)

        if response.status_code > 399:
            logger.error(f"\t\tError restoring {self.name()} {self.entity_name(entity)}: {response.status_code}: {body}")

    def delete(self, client, entity):
        entity_path = self.get_entity_path(entity)
        logger.info(f"\t -> deleting {self.name()}: {self.entity_name(entity)}{entity_path}")
        response = client.delete(entity_path)
        if response > 499:
            logger.error(f"\t\tError deleting {self.name()} {entity_path}: {response.status_code}")

    def diff_local_and_online(self, client, backup_dir):
        return None