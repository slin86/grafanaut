import requests

class GrafanaClient:
    def __init__(self, url, token):
        self.url = url.rstrip("/")
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

    def exists(self, path):
        response = requests.get(f"{self.url}{path}", headers=self.headers)
        return response.status_code in [200, 204]

    def get(self, path):
        response = requests.get(f"{self.url}{path}", headers=self.headers)
        response.raise_for_status()
        return response.json()

    def post(self, path, data):
        response = requests.post(f"{self.url}{path}", headers=self.headers, json=data)
        return response.json(), response

    def put(self, path, data):
        response = requests.put(f"{self.url}{path}", headers=self.headers, json=data)
        return response.json(), response

    def delete(self, path):
        response = requests.delete(f"{self.url}{path}", headers=self.headers)
        return response.status_code