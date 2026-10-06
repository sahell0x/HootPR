from app.platforms.diff import build_file_diff
from app.review.anchoring import DiffIndex, fingerprint

PATCH = (
    "@@ -1,3 +1,4 @@\n a = 1\n-b = 2\n+b = 3\n+c = 4\n d = 5\n"
    "@@ -20,2 +21,3 @@\n x = 1\n+y = 2\n z = 3\n"
)


def test_index() -> None:
    d = DiffIndex([build_file_diff("m.py", PATCH, "modified")])
    assert d.has_path("m.py") and not d.has_path("n.py")
    assert d.hunk_of("m.py", 1) == 0 and d.hunk_of("m.py", 4) == 0 and d.hunk_of("m.py", 22) == 1
    assert d.hunk_of("m.py", 10) is None
    assert d.line_text("m.py", 3) == "c = 4"
    assert d.added_lines("m.py") == [2, 3, 22]
    assert d.nearest_added("m.py", 12, within=10) == 3
    assert d.nearest_added("m.py", 40, within=10) is None
    assert "   3  c = 4" in d.excerpt("m.py", 3, 3)
    assert d.excerpt("n.py", 1, 2) == ""


def test_fingerprint_ignores_whitespace_and_line_numbers() -> None:
    assert fingerprint("a.py", "x  =  eval(s)", "security") == fingerprint(
        "a.py", " x = eval(s) ", "security"
    )
    assert fingerprint("a.py", "x = eval(s)", "security") != fingerprint(
        "a.py", "x = eval(s)", "bug"
    )
    assert len(fingerprint("a.py", "", "bug")) == 32


def test_old_side_line_for_context_lines_and_old_path() -> None:
    d = DiffIndex([build_file_diff("m.py", PATCH, "modified")])
    # context lines carry their old-side line; added lines have none
    assert d.old_line("m.py", 1) == 1 and d.old_line("m.py", 4) == 3
    assert d.old_line("m.py", 21) == 20 and d.old_line("m.py", 23) == 21
    assert d.old_line("m.py", 2) is None and d.old_line("m.py", 99) is None
    assert d.old_path("m.py") == "m.py" and d.old_path("n.py") is None
    r = DiffIndex([build_file_diff("new.py", "@@ -1,1 +1,2 @@\n a\n+b\n", "renamed", "old.py")])
    assert r.old_path("new.py") == "old.py" and r.old_line("new.py", 1) == 1
