# Grafana Backup & Restore Tool

A flexible, modular backup and restore tool for Grafana, designed to work across multiple instances.  
Supports dashboards, folders (with subfolders from Grafana 11+), data sources, ~~alerting entities (contact points, policies, silences, rules)~~, and stores data in Git-compatible JSON structures.

---

## Features

- Backup, sync deletion and restore of:
  - Dashboards
  - Folders (including nested subfolders)
  - Data sources
  - Other alarm resources could also be backuped, but not wanted yet
- Modular entity system with plugin-style registration
- Subfolder support (Grafana 11+)
- Config-driven (define source and multiple target Grafana instances)
- JSON-based backups, version-control friendly
- API transformations (e.g. remove `id`, fix payloads)
- Python 3.8+

---

## Project Structure
```
grafanaut/
├── config.yaml # Source + target Grafana instances
├── base-entity.py # Base class for all entities
├── entities/ # Python files per entity (modular)
│ ├── folders.py
│ ├── dashboards.py
│ ├── datasources.py
│ └── alert-rules.py
├── main.py # Entry point for backup/restore
├── http_client.py # HTTP client for Grafana API
└── logger.py # Logger wrapper
```

## Requirements
- Python 3.7+
- pip (for installing dependencies)
- Access to a running Grafana instance with API access


---

## Quick Start

### 1. Create a virtual environment & install dependencies

```bash
python3 -m venv venv
source .venv/bin/activate
pip3 install -r requirements.txt 
pip3 install -e .
```

### 2. Create a config.yaml file

You need grafana API tokens with admin privileges for each instance. You also could set token via environment variables.
To do so, you need to set GRAFANA_TOKEN_PROD, GRAFANA_TOKEN_QS, GRAFANA_TOKEN_TEST.

```yaml
instances:
  prod:
    url: https://grafana.geofox.de
    token: [REDACTED]
  test:
    url: https://grafana-test.geofox.de
    token: [REDACTED]
  qs:
    url: https://grafana-qs.geofox.de
    token: [REDACTED]
backup_dir: ../backup
```

### 3. Run the backup command

The backup command will create a directory structure in the `backup_dir` defined in your config.yaml file.

```bash
grafanaut --mode backup --source test
grafanaut --mode backup --source qs
grafanaut --mode backup --source prod
```

### 4. Mirror-Deletions ausführen

The `mirror-deletions` mode ensures that entities which deleted in the source also deleted in the target. Dashboards created in Target will not be deleted.

```bash
grafanaut --mode mirror-deletions --source test --target qs prod
```

### 5. Run the restore command

The restore command will read the backup files from the `backup_dir` and restore them to the target Grafana instance(s).

```bash
grafanaut --mode restore --source test --target qs prod
```

## Security Notes
- All API tokens must have Admin privileges
- Never commit config.yaml with real tokens
- Git-ignore .tokens or .secrets if needed

