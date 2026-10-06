import sys

from cli.sync import sync_all


def parse_limit(argv: list[str]) -> int:
    return int(argv[1])


def report(items: list[str]) -> None:
    for item in items:
        print(f"  synced {item}")
    print(f"Done: {len(items)} items.")


def main(argv: list[str]) -> int:
    limit = parse_limit(argv)
    print(f"Syncing up to {limit} items...")
    items = sync_all(limit=limit)
    report(items)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
