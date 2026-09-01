from grafanaut.base_entity import BaseEntity

NAME = "datasource"
ENDPOINT = "/api/datasources"

class DatasourceResource(BaseEntity):
    def get_entity_path(self, entity):
        return f"{ENDPOINT}/uid/{entity['uid']}"

    def entity_name(self, entity):
        return entity['name']

    def name(self):
        return NAME

    def endpoint(self):
        return ENDPOINT

    def convert(self, data):
        data['id'] = None
        return data