import argparse
import sys

from grafanaut.main import main as grafanaut_main


def main():
    parser = argparse.ArgumentParser(
        description="grafanaut - backup and restore tool for Grafana"
    )
    parser.add_argument(
        "--mode",
        choices=["backup", "restore", "mirror-deletions", "all"],
        default="all",
        help="Which stage to run",
    )
    parser.add_argument("--source", required=True, help="Instance to back up")
    parser.add_argument(
        "--targets", nargs="+", help="Instances the backup is restored into"
    )
    parser.add_argument("--config", help="Path to config.yaml (env: GRAFANAUT_CONFIG)")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Log what would change without sending write requests",
    )
    args = parser.parse_args()

    sys.exit(
        grafanaut_main(
            source=args.source,
            targets=args.targets,
            mode=args.mode,
            config_path=args.config,
            dry_run=args.dry_run,
        )
    )


if __name__ == "__main__":
    main()
