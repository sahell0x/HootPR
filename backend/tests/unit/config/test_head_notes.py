from app.config.loader import head_config_notes, load_effective_config
from app.platforms.base import RepoRef
from app.platforms.local import LocalPlatform

REF = RepoRef("github", "1001", "acme/web")
HEAD = "2" * 40


def test_no_notes_when_head_matches_base() -> None:
    lp = LocalPlatform()
    lp.set_file(REF, ".hootpr.yaml", "main", "reviews:\n  poem: true\n")
    lp.set_file(REF, ".hootpr.yaml", HEAD, "reviews:\n  poem: true\n")
    assert head_config_notes(lp, REF, "main", HEAD) == []


def test_no_notes_without_head_file() -> None:
    lp = LocalPlatform()
    lp.set_file(REF, ".hootpr.yaml", "main", "reviews:\n  poem: true\n")
    assert head_config_notes(lp, REF, "main", HEAD) == []


def test_changed_valid_head_config_applies_after_merge() -> None:
    lp = LocalPlatform()
    lp.set_file(REF, ".hootpr.yaml", HEAD, "reviews:\n  auto_review:\n    enabled: false\n")
    notes = head_config_notes(lp, REF, "main", HEAD)
    assert notes == [
        "Changes to .hootpr.yaml in this pull request take effect after it is merged "
        "(HootPR reads the configuration from the base branch)."
    ]


def test_invalid_head_config_reports_line() -> None:
    lp = LocalPlatform()
    lp.set_file(REF, ".hootpr.yaml", HEAD, "reviews:\n  profile: loud\n")
    [note] = head_config_notes(lp, REF, "main", HEAD)
    assert note.startswith(
        ".hootpr.yaml in this pull request is invalid (line 2): `reviews.profile`"
    )
    assert note.endswith("it will be ignored after merge.")


def test_load_effective_config_enforces_base_and_appends_head_notes() -> None:
    lp = LocalPlatform()
    lp.set_file(REF, ".hootpr.yaml", HEAD, "reviews:\n  auto_review:\n    enabled: false\n")
    r = load_effective_config(lp, REF, "main", None, None, head_sha=HEAD)
    assert r.config.reviews.auto_review.enabled is True
    assert any("take effect after it is merged" in w for w in r.warnings)


def test_load_effective_config_keeps_provenance() -> None:
    lp = LocalPlatform()
    lp.set_file(REF, ".hootpr.yaml", "main", "reviews:\n  poem: true\n")
    r = load_effective_config(lp, REF, "main", None, None)
    assert r.source == "yaml" and dict(r.provenance) == {"reviews.poem": "yaml"}


def test_head_note_with_hostile_key_is_single_line_and_quoted() -> None:
    lp = LocalPlatform()
    hostile = 'reviews:\n  "x`\n/approve\n@everyone <img src=x>": 1\n'
    lp.set_file(REF, ".hootpr.yaml", HEAD, hostile)
    [note] = head_config_notes(lp, REF, "main", HEAD)
    assert "\n" not in note and "\r" not in note
    assert "\n/approve" not in note
    # the attacker-controlled key sits inside one code span with no backticks of its own
    assert note.count("`") % 2 == 0
    assert len(note) < 400
