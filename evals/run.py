#!/usr/bin/env python3
"""`make eval` entry point: runs the HootPR review engine on evals/datasets and writes a report."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "backend")]

from hootpr_evals.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
