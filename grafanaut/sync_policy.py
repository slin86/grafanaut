"""Policy for how synced objects are marked and locked down in the targets.

Two related goals:

* Synced dashboards must not be saveable by normal users, and dashboards must
  not be added to or removed from a synced folder. Grafana has no per-dashboard
  "read only" flag that leaves editing intact, so this is done with folder
  permissions: the Viewer and Editor roles are downgraded to View (1) on every
  synced folder, which hides the save button and blocks create/delete inside
  the folder.

  Two caveats that are Grafana behaviour, not grafanaut behaviour:
    - Permissions cannot be set for Admins, they always have access.
    - For users to still be able to *edit* (without saving) you need
      `viewers_can_edit = true` in the [users] section of grafana.ini on the
      target instances. Without it, View permission also removes edit mode.

* Independently of the permissions, synced objects are marked visibly so a
  synced folder is recognisable at a glance even if locking is disabled or
  does not take effect for a given role.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from grafanaut.changes import ChangeLog

VIEW = 1
EDIT = 2
ADMIN = 4


@dataclass
class AlertingPolicy:
    """Which alerting resources take part, read from the `alerting:` block.

    Everything is off by default: alerting was explicitly out of scope for the
    original tool, and turning it on changes what a run touches.

    `notification_policy` is the odd one out. The policy tree is a single
    global object and PUT replaces all of it, so a route that exists only in
    the target is lost. `enabled: true` therefore does NOT include it; it has
    to be asked for by name.
    """

    enabled_resources: frozenset = frozenset()

    # The resources `enabled: true` turns on. The policy tree is deliberately
    # not in this list.
    SAFE_RESOURCES = (
        "alert_rules", "contact_points", "mute_timings", "templates",
    )
    ALL_RESOURCES = SAFE_RESOURCES + ("notification_policy",)

    @classmethod
    def from_dict(cls, raw):
        raw = raw or {}
        # Catch typos before they silently disable a resource someone meant to
        # switch on.
        unknown = set(raw) - set(cls.ALL_RESOURCES) - {"enabled"}
        if unknown:
            raise RuntimeError(
                f"Grafanaut: unknown alerting option(s) {', '.join(sorted(unknown))}"
            )

        if not raw.get("enabled", False):
            # Individual flags still count, so a block naming one resource
            # works without also setting enabled.
            return cls(enabled_resources=frozenset(
                key for key in cls.ALL_RESOURCES if raw.get(key) is True
            ))

        selected = set(cls.SAFE_RESOURCES)
        for key in cls.ALL_RESOURCES:
            if key in raw:
                if raw[key]:
                    selected.add(key)
                else:
                    selected.discard(key)
        return cls(enabled_resources=frozenset(selected))

    def enabled(self, resource):
        return resource in self.enabled_resources

    def any_enabled(self):
        return bool(self.enabled_resources)


@dataclass
class SyncPolicy:
    """Read from the `sync:` block of config.yaml."""

    lock_folders: bool = True
    # Sets "editable": false in the dashboard model. This hides the edit and
    # save controls for everyone including admins, because it is a property of
    # the dashboard and not a permission. It is a guard rail, not a lock:
    # anyone who may write the dashboard can flip the flag back via
    # Settings -> JSON Model or the API. Editors in a locked folder cannot,
    # since they have no write access in the first place.
    dashboards_editable: bool = True
    # Alerting resources are written through the provisioning API, which marks
    # them as provisioned and read-only in the UI. The X-Disable-Provenance
    # header keeps them editable like hand-made ones.
    alerting_editable: bool = True
    folder_title_suffix: str = " [synced]"
    folder_description: str = (
        "Managed by grafanaut, synced from {source}. Local changes are overwritten."
    )
    dashboard_tag: str = "synced:{source}"

    @classmethod
    def from_dict(cls, raw):
        raw = raw or {}
        defaults = cls()
        return cls(
            lock_folders=bool(raw.get("lock_folders", defaults.lock_folders)),
            dashboards_editable=bool(
                raw.get("dashboards_editable", defaults.dashboards_editable)
            ),
            alerting_editable=bool(
                raw.get("alerting_editable", defaults.alerting_editable)
            ),
            folder_title_suffix=_optional(raw, "folder_title_suffix", defaults.folder_title_suffix),
            folder_description=_optional(raw, "folder_description", defaults.folder_description),
            dashboard_tag=_optional(raw, "dashboard_tag", defaults.dashboard_tag),
        )

    def decorate_folder(self, entity, source):
        """Return a copy of the folder with the sync marking applied.

        Idempotent: the suffix is only appended when it is not already there,
        so repeated restores do not stack it up.
        """
        decorated = dict(entity)
        title = entity.get("title", "")
        if self.folder_title_suffix and not title.endswith(self.folder_title_suffix):
            title = f"{title}{self.folder_title_suffix}"
        decorated["title"] = title
        if self.folder_description:
            decorated["description"] = self.folder_description.format(source=source)
        return decorated

    def decorate_dashboard(self, dashboard, source):
        """Apply the sync marking and the edit lock (mutates and returns it)."""
        if not self.dashboards_editable:
            dashboard["editable"] = False

        if not self.dashboard_tag:
            return dashboard
        tag = self.dashboard_tag.format(source=source)
        tags = list(dashboard.get("tags") or [])
        if tag not in tags:
            tags.append(tag)
        dashboard["tags"] = tags
        return dashboard


@dataclass
class SyncContext:
    """Everything a resource needs to know about the current run."""

    source: str
    policy: SyncPolicy = field(default_factory=SyncPolicy)
    dry_run: bool = False
    changes: ChangeLog = field(default_factory=ChangeLog)

    def record(self, resource, action, name, detail=""):
        self.changes.record(resource, action, name, detail)


def _optional(raw, key, default):
    """Allow explicitly disabling a marking with `key:` (null) or an empty string."""
    if key not in raw:
        return default
    return raw[key] or ""
