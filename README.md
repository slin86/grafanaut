# Grafanaut - Grafana Backup & Restore Tool

A modular backup and restore tool for Grafana, designed to keep several
instances in sync. Supports dashboards, folders (including nested subfolders
from Grafana 11+) and data sources, stored as git-friendly JSON.

---

## Features

- Backup, deletion mirroring and restore of dashboards, folders and data sources
- Optional alerting support: alert rules, contact points, mute timings,
  notification templates and the notification policy tree
- Full nested folder support: the whole tree is walked, including empty folders
- Renames and re-parenting of both folders and dashboards are propagated
- Synced folders are locked read-only in the targets and visibly marked
- Static Grafana tokens or OIDC (Keycloak), for instances behind a gateway
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

Any string in the config may reference an environment variable as `${VAR}`, so
a config file kept in git never has to contain a secret.

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

How much detail a field gets depends on how readable it can be:

| Field shape | Reported as |
| --- | --- |
| Scalar (title, uid, url) | `title: 'Aufzug Services' -> 'Aufzug Services v2'` |
| List of scalars (tags) | `tags: +synced:test, -draft` |
| Key on one side only | `basicAuthUser: 'svc' -> <not set>` |
| Nested object (jsonData) | `jsonData: timeout, tlsSkipVerify` |
| Deep list (panels, templating) | `panels: 12 -> 14 entries` |

Deep structures deliberately get only a size hint. Rendering a panel diff in a
log line is unreadable, and the backup directory is a git repository -- for the
exact change, `git diff` on `<backup_dir>/<source>/dashboards/<uid>.json` is
the right tool.

One caveat on the content comparison: Grafana normalises a dashboard when it
is saved (schema migrations, panel defaults). A dashboard imported from an
older schema version can therefore report differing fields even when nothing
meaningful changed. The folder comparison is exact, the field list is a strong
hint rather than a guarantee.

---

## Authentication

Each instance picks its own mode in the `auth:` block.

### Static token (default)

A Grafana service account token, from the config or from
`GRAFANA_TOKEN_<STAGE>`. This is what a plain `token:` line means.

### OIDC (`type: oidc`)

For an instance behind a gateway such as Ambassador that validates a Keycloak
token before the request reaches Grafana. Grafanaut fetches an access token
from the token endpoint and sends it as the bearer token:

```yaml
instances:
  old:
    url: https://grafana-old.example.com
    auth:
      type: oidc
      token_url: https://keycloak.example.com/realms/<realm>/protocol/openid-connect/token
      client_id: grafanaut
      client_secret: ${KEYCLOAK_CLIENT_SECRET}   # or GRAFANA_OIDC_SECRET_OLD
```

The token is cached and refetched shortly before it expires, and a `401` is
retried once with a fresh token, so a long restore does not die halfway
through. A static token is never retried, since there is nothing to refresh.

`grant_type` defaults to `client_credentials`. Because `scope`, `audience` and
`extra_params` are passed through verbatim, other flows work without code
changes — for example RFC 8693 token exchange with a GitLab CI id token:

```yaml
      grant_type: urn:ietf:params:oauth:grant-type:token-exchange
      audience: grafana
      extra_params:
        subject_token: ${CI_JOB_JWT_V2}
        subject_token_type: urn:ietf:params:oauth:token-type:jwt
```

A failed token request logs the provider's `error` and `error_description` and
never the request body, so the client secret stays out of the CI log.

Whichever mode is used, the token still needs admin privileges **in Grafana**:
getting past the gateway is not the same as being allowed to write.

---

## Alerting

Off by default. `enabled: true` in the `alerting:` block turns on alert rules,
contact points, mute timings and notification templates; each can also be set
on its own. `--alerting` and `--no-alerting` override the config for a single
run, which is what a one-off import from another instance needs:

```bash
grafanaut --mode backup --source old --alerting
grafanaut --mode restore --source old --targets test --alerting --dry-run
```

Restore order is dependency-driven: contact points and templates first, then
mute timings, then alert rules (which need their folder to exist), and the
policy tree last.

### Editability

Resources written through the provisioning API are marked as provisioned and
become **read-only in the Grafana UI**. `sync.alerting_editable: true` (the
default) sends `X-Disable-Provenance: true` so they behave like hand-made
rules. Setting it to `false` leaves them locked, which also closes the gap
where an editor can still change alert rules inside a folder whose permissions
are otherwise read-only.

### Contact point secrets

Grafana never exports contact point secrets — webhook URLs, tokens, passwords
come back as `[REDACTED]`. Writing that placeholder back would store the
literal string as the credential, so grafanaut strips those fields and lists
what has to be set by hand in the target:

```
[WARNING] 	1 contact point(s) have secrets that Grafana does not export.
          Set them manually in the target:
[WARNING] 		Ops Slack: url
```

Everything else about the contact point is restored, so this is a one-time
manual step per secret, not per run. The warning repeats on later runs because
grafanaut cannot tell whether the secret was filled in.

### Notification policy tree

Deliberately **not** included by `enabled: true`; it needs
`notification_policy: true`. Unlike every other resource it is a single global
object, and `PUT /api/v1/provisioning/policies` replaces the whole tree — any
route that exists only in the target is gone afterwards. When it does run, the
replacement is logged as a warning.

### Not covered

Data-source-managed (Mimir/Loki) alert rules go through a different API and are
not handled. Alert rule *state* (silences, current firing state) is runtime
data and is not backed up.

---

## Name collisions

A dashboard or folder that is new to a target, or that moves into a different
folder, can run into an object of the same name that exists only in that
target. Grafanaut refuses to write in that case and reports a `conflict`:

```
[ERROR] 		CONFLICT, skipping dashboards Betriebszustand: folder team already
        holds a different dashboard titled 'Betriebszustand' (uid abc123)
```

This matters most for dashboards. `overwrite: true` tells Grafana to overwrite
a dashboard with the same *title in the folder*, not only one with the same
uid, so writing into a collision would silently absorb the target's own
dashboard. For folders the API would reject the write anyway, but detecting it
up front produces a usable message and avoids the follow-up failures of every
dashboard pointing at the folder that was never created.

Conflicts are logged as errors, so the run ends with exit code 1 and the
pipeline turns red. Resolve them by renaming one of the two objects, or by
giving the target object the uid from the source if they are meant to be the
same dashboard.

The check runs only where a collision is possible: on creation and on a folder
change. A plain in-place update of a known uid cannot collide and costs no
extra request.

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

### Read-only dashboards (`dashboards_editable: false`)

Writes `"editable": false` into every restored dashboard. Grafana then hides
the edit and save controls.

Unlike the folder permissions this applies to **everyone, admins included**,
because `editable` is a field of the dashboard model rather than a permission.
For the same reason it is a guard rail and not a lock: anyone who is allowed
to write the dashboard can set the flag back through Settings -> JSON Model or
the API. Editors inside a locked folder cannot, they have no write access at
all; admins can.

If someone does flip it back, the next run reports it and puts it back:

```
-> updating dashboards: GTI Dashboard [editable: True -> False]
```

The two mechanisms answer different questions and are meant to be combined:

| | `lock_folders` | `dashboards_editable: false` |
| --- | --- | --- |
| Mechanism | Folder permissions | Dashboard JSON field |
| Applies to admins | No | Yes |
| Can be undone by the user | No (editors) | Yes (anyone who may write) |
| Blocks add/delete in folder | Yes | No |
| Survives without re-sync | Yes | Restored on every run |

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
