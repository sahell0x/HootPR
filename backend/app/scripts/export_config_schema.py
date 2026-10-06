"""Write the `.hootpr.yaml` JSON schema (plan contract C7).

Usage: ``uv run python -m app.scripts.export_config_schema [path]``
(default ``hootpr.v1.schema.json``).
"""

import json
import sys
from pathlib import Path

from app.config.schema import config_json_schema

EXPORT_BASE_URL = "http://localhost:3000"


def main(argv: list[str]) -> None:
    out = Path(argv[1] if len(argv) > 1 else "hootpr.v1.schema.json")
    schema = config_json_schema(EXPORT_BASE_URL)
    out.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main(sys.argv)
