import sys

from cli.sync import sync_all


def main(argv: list[str]) -> int:
    sync_all(limit=10)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
