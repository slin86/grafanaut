from grafanaut.entities.dashboard import DashboardResource
from grafanaut.entities.datasource import DatasourceResource
from grafanaut.entities.folder import FolderResource

# Restore order: datasources and folders have to exist before the dashboards
# that reference them. Deletion walks this list in reverse.
RESOURCE_REGISTRY = [
    DatasourceResource(),
    FolderResource(),
    DashboardResource(),
]

__all__ = [
    "RESOURCE_REGISTRY",
    "DashboardResource",
    "DatasourceResource",
    "FolderResource",
]
