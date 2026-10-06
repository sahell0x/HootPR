from collections import Counter
from pathlib import Path

import pytest

from hootpr_evals.case import DATASETS, Case, load_cases, materialize, validate_case

CASES = load_cases(DATASETS) if DATASETS.is_dir() else []


def test_dataset_size_and_coverage() -> None:
    assert len(CASES) >= 12
    langs = Counter(c.meta.language for c in CASES)
    assert all(langs[lang] >= 3 for lang in ("python", "typescript", "go")), langs
    clean = {c.meta.language for c in CASES if c.meta.kind == "clean"}
    assert clean == {"python", "typescript", "go"}
    reversed_cves = [c for c in CASES if c.meta.kind == "cve_reversed"]
    assert len(reversed_cves) >= 2 and all("CVE-" in c.meta.source for c in reversed_cves)
    assert {i.category for c in CASES for i in c.issues} >= {"security", "bug", "performance"}


@pytest.mark.parametrize("case", CASES, ids=[c.id for c in CASES])
def test_case_is_valid(case: Case, tmp_path: Path) -> None:
    assert validate_case(case, materialize(case, tmp_path)) == []
