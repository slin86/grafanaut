# Grafanaut - Grafana Backup & Restore Tool

A modular backup and restore tool for Grafana, designed to keep several
instances in sync. Supports dashboards, folders (including nested subfolders
from Grafana 11+) and data sources, stored as git-friendly JSON.

---

## Features

- Backup, deletion mirroring and restore of dashboards, folders and data sources
- Full nested folder support: the whole tree is walked, including empty folders
- Renames and re-parenting of both folders and dashboards are propagated
- Synced folders are locked read-only in the targets and visibly marked
- Config-driven (one source, several targets)
- `--dry-run` for previewing a run
- Non-zero exit code when anything failed, so CI turns red

---

## Requirements

- Python 3.9+
- A Grafana instance per stage with an admin API token
- Grafana 11+ if you use nested folders

---

## Quick start

### 1. Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

### 2. Create config.yaml

Tokens need admin privileges. They can also come from the environment:
`GRAFANA_TOKEN_PROD`, `GRAFANA_TOKEN_QS`, `GRAFANA_TOKEN_TEST` (the env
variable wins over the config file).

See `config.yaml` in this repository for a commented example. The path can be
overridden with `--config` or the `GRAFANAUT_CONFIG` environment variable.

### 3. Backup

```bash
grafanaut --mode backup --source test
```

Writes `<backup_dir>/test/{folder,dashboards,datasource}/<uid>.json`.
File names are the uid, never the title, so a rename updates a file instead of
creating a second one.

### 4. Mirror deletions

```bash
grafanaut --mode mirror-deletions --source test --targets qs prod
```

Objects that still have a backup file but no longer exist in the source were
deleted since the last run, so they are deleted in the targets as well and the
backup file is removed. Dashboards are processed before folders, because
deleting a folder in Grafana cascades into everything inside it.

### 5. Restore

```bash
grafanaut --mode restore --source test --targets qs prod
```

Add `--dry-run` to any mode to see what would happen without writing.

---

## What changed?

Every object is compared against the current state in the target before
anything is written. Unchanged objects are skipped entirely, which keeps the
version history of the targets clean and makes a dry run show the real delta:

```
[INFO]   -> moving folder Sub [synced]: team -> root
[INFO]   -> updating dashboards: Dash One [folder: sub -> team]
[INFO]   -> updating dashboards: Reports [fields: panels, templating]
[INFO] Restore of qs: 2 update, 1 move, 96 unchanged
[INFO] Would change 3 object(s):
[INFO] 	[restore:qs] move folder 'Sub [synced]' (team -> root)
...
```

A run that changes nothing says so explicitly. `--verbose` also logs the
unchanged objects, `--report changes.json` writes a machine readable summary
that can be kept as a CI artifact:

```bash
grafanaut --mode restore --source test --targets qs --dry-run --report changes.json
```

One caveat on the content comparison: Grafana normalises a dashboard when it
is saved (schema migrations, panel defaults). A dashboard imported from an
older schema version can therefore report differing fields even when nothing
meaningful changed. The folder comparison is exact, the field list is a strong
hint rather than a guarantee.

---

## Sync protection

Synced content should not be edited in the target instances, so grafanaut
applies two things on every restore. Both are configured under `sync:` in
`config.yaml`.

### Locking (`lock_folders: true`)

Grafana has no per-dashboard "read only" flag that leaves editing intact, so
protection is applied at folder level. For every synced folder the Viewer and
Editor roles are set to `View` (permission level 1) via
`POST /api/folders/:uid/permissions`. Result in the UI:

- the save button on dashboards inside the folder is gone
- dashboards cannot be created in or deleted from the folder
- viewing and exporting the dashboard JSON still works

Existing per-user and per-team grants are read first and carried over with
their level capped at `View`, instead of being wiped by the replacing POST.

Two limitations come from Grafana itself:

- **Admins are never restricted.** Grafana does not allow setting permissions
  for admins, they always have access to everything.
- **Alert rules are not covered.** There is an open Grafana issue where a
  folder set to View still allows editors to create and edit alert rules in
  that folder.

To let users still edit panels temporarily without being able to save, set in
`grafana.ini` on each target:

```ini
[users]
viewers_can_edit = true
```

This is a server setting and cannot be applied through the API.

### Marking

So a synced folder stays recognisable even where locking does not apply
(admins, alert rules), synced objects are marked:

- folder title gets a suffix (default `" [synced]"`)
- folder description is set to a sync notice
- every restored dashboard gets a tag (default `synced:<source>`)

All three are idempotent and can be disabled individually by setting them to
an empty value. The marking is applied in the target only, the backup files
keep the original titles and tags from the source.

---

## Security notes

- API tokens need admin privileges
- Never commit `config.yaml` with real tokens
- Data source backups contain no secrets (the API never returns
  `secureJsonData`). Updating an existing data source keeps its stored
  credentials, but a data source created for the first time in a fresh target
  needs its credentials provisioned separately.
