"""Write the FastAPI OpenAPI schema (the frontend generates ``lib/api-types.ts`` from it).

Usage: ``uv run python -m app.scripts.export_openapi [path]`` (default ``openapi.json``).
Builds the app from default settings without connecting to anything.
"""

import json
import sys
from pathlib import Path
from typing import Any

from app.main import create_app
from app.settings import Settings


def openapi_schema() -> dict[str, Any]:
    app = create_app(Settings(_env_file=None))
    return app.openapi()


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    out = Path(args[0] if args else "openapi.json")
    out.write_text(
        json.dumps(openapi_schema(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    )
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
