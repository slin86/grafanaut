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
