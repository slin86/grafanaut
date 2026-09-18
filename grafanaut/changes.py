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
# Refused on purpose: writing would have destroyed an object that exists only
# in the target and is not part of the backup.
CONFLICT = "conflict"

# Order used for the summary line. UNCHANGED last, it is the boring one.
ACTIONS = [CREATE, UPDATE, MOVE, LOCK, DELETE, CONFLICT, FAILED, UNCHANGED]


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


# ----------------------------------------------------------------------
# field level diff rendering
# ----------------------------------------------------------------------
MISSING = object()
MAX_VALUE_LEN = 50
MAX_ITEMS = 4


def describe_field(key, current, desired):
    """One short line describing how a single field differs.

    Scalars get their values ('title: \'A\' -> \'B\''), lists of scalars get
    the added/removed elements ('tags: +synced:test'). Deep structures such as
    panels only get a size hint: rendering their diff here would be unreadable,
    and the backup repository already gives an exact diff via git.
    """
    if current is MISSING or desired is MISSING:
        # A key present on only one side: describe both compactly instead of
        # falling through to the list/dict branches with a sentinel.
        return f"{key}: {_summarize(current)} -> {_summarize(desired)}"

    if _is_scalar_list(current) and _is_scalar_list(desired):
        added = [v for v in desired if v not in current]
        removed = [v for v in current if v not in desired]
        parts = [f"+{v}" for v in added] + [f"-{v}" for v in removed]
        if not parts:
            return f"{key}: reordered"
        return f"{key}: {_join(parts)}"

    if isinstance(current, list) or isinstance(desired, list):
        before, after = len(current or []), len(desired or [])
        if before != after:
            return f"{key}: {before} -> {after} entries"
        return f"{key}: {after} entries, content differs"

    if isinstance(current, dict) or isinstance(desired, dict):
        before, after = current or {}, desired or {}
        keys = sorted(
            k for k in set(before) | set(after)
            if before.get(k, MISSING) != after.get(k, MISSING)
        )
        return f"{key}: {_join(keys)}" if keys else f"{key}: content differs"

    return f"{key}: {_render(current)} -> {_render(desired)}"


def _summarize(value):
    if value is MISSING:
        return "<not set>"
    if isinstance(value, list):
        return f"{len(value)} entries"
    if isinstance(value, dict):
        return f"{len(value)} keys"
    return _render(value)


def _is_scalar_list(value):
    return isinstance(value, list) and all(
        isinstance(item, (str, int, float, bool)) for item in value
    )


def _join(items):
    shown = [str(i) for i in items[:MAX_ITEMS]]
    rest = len(items) - len(shown)
    return ", ".join(shown) + (f" (+{rest} more)" if rest > 0 else "")


def _render(value):
    if value is MISSING:
        return "<not set>"
    if value is None:
        return "null"
    text = str(value)
    if len(text) > MAX_VALUE_LEN:
        text = text[:MAX_VALUE_LEN] + "..."
    return repr(text) if isinstance(value, str) else text


def describe_differences(current, desired, ignored=(), max_fields=4):
    """Compare two flat dicts and describe every differing field."""
    keys = (set(current) | set(desired)) - set(ignored)
    described = [
        describe_field(key, current.get(key, MISSING), desired.get(key, MISSING))
        for key in sorted(keys)
        if current.get(key, MISSING) != desired.get(key, MISSING)
    ]
    if not described:
        return None
    if len(described) > max_fields:
        rest = len(described) - max_fields
        described = described[:max_fields] + [f"+{rest} more field(s)"]
    return "; ".join(described)


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
