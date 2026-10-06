from app.platforms.diff import build_file_diff, count_changes, parse_patch

PATCH = """@@ -1,3 +1,4 @@ def main():
 import os
-import sys
+import sys  # noqa
+import json
 print(1)
@@ -10 +11,2 @@
-x = 1
+x = 2
+y = 3
\\ No newline at end of file
"""


def test_parses_hunks_and_line_numbers() -> None:
    hunks = parse_patch(PATCH)
    assert len(hunks) == 2
    h = hunks[0]
    assert (h.old_start, h.old_count, h.new_start, h.new_count) == (1, 3, 1, 4)
    assert h.header == "def main():"
    kinds = [(ln.kind, ln.old_line, ln.new_line) for ln in h.lines]
    assert kinds == [
        ("context", 1, 1),
        ("del", 2, None),
        ("add", None, 2),
        ("add", None, 3),
        ("context", 3, 4),
    ]
    h2 = hunks[1]
    assert (h2.old_start, h2.old_count, h2.new_start, h2.new_count) == (10, 1, 11, 2)
    assert [ln.new_line for ln in h2.lines if ln.kind == "add"] == [11, 12]


def test_count_changes() -> None:
    assert count_changes(parse_patch(PATCH)) == (4, 2)


def test_build_file_diff_and_changed_lines() -> None:
    fd = build_file_diff("a.py", PATCH, "modified")
    assert (fd.additions, fd.deletions) == (4, 2)
    assert fd.changed_new_lines() == {2, 3, 11, 12}
    assert fd.is_binary is False


def test_missing_patch_is_binary() -> None:
    fd = build_file_diff("logo.png", None, "added")
    assert fd.is_binary is True
    assert fd.hunks == ()


def test_ignores_git_headers_before_first_hunk() -> None:
    patch = "diff --git a/x b/x\nindex 1..2 100644\n--- a/x\n+++ b/x\n@@ -0,0 +1 @@\n+hi\n"
    fd = build_file_diff("x", patch, "added")
    assert fd.additions == 1 and fd.deletions == 0
