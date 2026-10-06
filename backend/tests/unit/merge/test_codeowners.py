from app.merge.codeowners import owners_for, parse_codeowners, paths_in_text, user_owners

CODEOWNERS = """
# comment
*            @alice
*.py         @py-dev @org/python-team
/docs/       @docs-writer
src/api/**   @bob
[GitLab Section]
build        @builder
"""


def test_last_match_wins() -> None:
    rules = parse_codeowners(CODEOWNERS)
    assert owners_for(rules, "README.md") == ("@alice",)
    assert owners_for(rules, "app/main.py") == ("@py-dev", "@org/python-team")
    assert owners_for(rules, "docs/guide.md") == ("@docs-writer",)
    assert owners_for(rules, "other/docs/guide.md") == ("@alice",)  # /docs/ is anchored
    assert owners_for(rules, "src/api/v1/routes.ts") == ("@bob",)
    assert owners_for(rules, "tools/build/x.sh") == ("@builder",)  # unanchored name


def test_user_owners_skip_teams_and_emails() -> None:
    assert user_owners(["@a", "@org/team", "x@y.com", "@"]) == ["a"]


def test_paths_in_text() -> None:
    text = "Crash in src/api/routes.py when calling `app/main.py`; see https://x.io/a/b and v1.2.3"
    assert paths_in_text(text) == ["src/api/routes.py", "app/main.py"]
