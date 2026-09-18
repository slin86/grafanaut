"""Collects what a run actually changed, per target.

Without this the restore log looks identical whether it rewrote everything or
nothing: every object produced a '-> updating' line because the code posted
unconditionally. The point of a dry run is to see the delta, so every resource
now compares against the current state in the target and records the outcome.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

CREATE = "create"
UPDATE = "update"
MOVE = "move"
LOCK = "lock"
DELETE = "delete"
UNCHANGED = "unchanged"
FAILED = "failed"

# Order used for the summary line. UNCHANGED last, it is the boring one.
ACTIONS = [CREATE, UPDATE, MOVE, LOCK, DELETE, FAILED, UNCHANGED]


@dataclass
class Change:
    target: str
    resource: str
    action: str
    name: str
    detail: str = ""

    def __str__(self):
        suffix = f" ({self.detail})" if self.detail else ""
        return f"{self.action} {self.resource} '{self.name}'{suffix}"


@dataclass
class ChangeLog:
    target: str = ""
    changes: list = field(default_factory=list)

    def record(self, resource, action, name, detail=""):
        self.changes.append(Change(self.target, resource, action, name, detail))

    def counts(self):
        counts = {}
        for change in self.changes:
            counts[change.action] = counts.get(change.action, 0) + 1
        return counts

    def has_changes(self):
        return any(c.action not in (UNCHANGED,) for c in self.changes)

    def summary(self):
        counts = self.counts()
        parts = [f"{counts[a]} {a}" for a in ACTIONS if counts.get(a)]
        return ", ".join(parts) if parts else "nothing to do"

    def changed(self):
        return [c for c in self.changes if c.action != UNCHANGED]


def write_report(path, changelogs):
    """Machine readable report, useful as a CI artifact."""
    payload = {
        log.target: {
            "summary": log.counts(),
            "changes": [asdict(c) for c in log.changed()],
        }
        for log in changelogs
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write("\n")
