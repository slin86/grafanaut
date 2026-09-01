from grafanaut.entities.dashboard import DashboardResource
from grafanaut.entities.datasource import DatasourceResource
from grafanaut.entities.folder import FolderResource

RESOURCE_REGISTRY = [
    DatasourceResource(),
    FolderResource(),
    DashboardResource(),
]