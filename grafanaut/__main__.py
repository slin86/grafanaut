import argparse
from grafanaut.main import main as grafanaut_main

def main():
    parser = argparse.ArgumentParser(
        description="grafanaut – Backup und Restore Tool für Grafana"
    )
    parser.add_argument(
        "--mode", choices=["backup", "restore", "mirror-deletions", "all"],
        help="Modus: 'backup', 'restore' or 'all'", default="all"
    )
    parser.add_argument(
        "--source", required=True, help="Name of instance to backup"
    )
    parser.add_argument(
        "--targets", nargs="+", help="Target instances, where the backup is restored"
    )
    args = parser.parse_args()

    grafanaut_main(source=args.source, targets=args.targets, mode=args.mode)

if __name__ == "__main__":
    main()