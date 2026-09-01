from grafanaut.base_entity import BaseEntity

NAME = "folder"
ENDPOINT = "/api/folders"

class FolderResource(BaseEntity):
    def load_entities(self, client):
        folder = client.get("/api/search?query=&type=dash-db")
        entities = []

        for item in folder:
            if 'folderUid' not in item:
                continue
            detail = client.get(f"/api/folders/{item['folderUid']}")
            entities.append({
                "title": detail['title'],
                "uid": detail['uid'],
                "parentUid": detail.get('parentUid'), # This value is nullable for root folders
            })
        return entities

    def entity_name(self, entity):
        # Magic to load root folders first
        if entity['parentUid'] is None:
            return f"0_root_{entity['title']}_{entity['uid']}"
        return f"1_nested_{entity['title']}_{entity['uid']}"

    def name(self):
        return NAME

    def endpoint(self):
        return ENDPOINT

    def convert(self, data):
        data['overwrite'] = True
        return data

    def get_entity_path(self, entity):
        return f"{ENDPOINT}/{entity['uid']}"
