from grafanaut.entities.alerting import (
    ALERTING_RESOURCES,
    AlertRuleResource,
    ContactPointResource,
    MuteTimingResource,
    NotificationPolicyResource,
    NotificationTemplateResource,
)
from grafanaut.entities.dashboard import DashboardResource
from grafanaut.entities.datasource import DatasourceResource
from grafanaut.entities.folder import FolderResource

# Restore order: datasources and folders have to exist before the dashboards
# that reference them. Deletion walks this list in reverse.
CORE_REGISTRY = [
    DatasourceResource(),
    FolderResource(),
    DashboardResource(),
]

# Kept as a module level name because it is the documented entry point and the
# tests patch it. build_registry() is what respects the configuration.
RESOURCE_REGISTRY = CORE_REGISTRY

# Alerting resources come last: alert rules reference folders, and contact
# points have to exist before the policy tree that routes to them.
ALERTING_ORDER = [
    "contact_points",
    "templates",
    "mute_timings",
    "alert_rules",
    "notification_policy",
]


def build_registry(alerting=None):
    """The resources to process, in restore order.

    ``alerting`` is the resolved AlertingPolicy (see sync_policy); None or a
    policy with everything disabled gives the plain core registry.
    """
    registry = list(CORE_REGISTRY)
    if alerting is None:
        return registry
    for key in ALERTING_ORDER:
        if alerting.enabled(key):
            registry.append(ALERTING_RESOURCES[key]())
    return registry


__all__ = [
    "ALERTING_ORDER",
    "ALERTING_RESOURCES",
    "CORE_REGISTRY",
    "RESOURCE_REGISTRY",
    "AlertRuleResource",
    "ContactPointResource",
    "DashboardResource",
    "DatasourceResource",
    "FolderResource",
    "MuteTimingResource",
    "NotificationPolicyResource",
    "NotificationTemplateResource",
    "build_registry",
]
