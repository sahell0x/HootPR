from app.merge.issue_refs import IssueRef, parse_issue_refs, parse_issue_url


def refs(text: str, own: str = "acme/api", host: str = "github.com") -> list[IssueRef]:
    return parse_issue_refs(text, own, host)


def test_closing_keywords_and_lists() -> None:
    assert refs("Fixes #12") == [IssueRef(None, 12)]
    assert refs("closes #1, #2 and #3") == [IssueRef(None, 1), IssueRef(None, 2), IssueRef(None, 3)]
    assert refs("Resolved: other/repo#7") == [IssueRef("other/repo", 7)]
    assert refs("implements group/sub/project#3", host="gitlab.com") == [
        IssueRef("group/sub/project", 3)
    ]


def test_own_repo_reference_is_normalized_and_deduplicated() -> None:
    assert refs("fixes acme/api#4 and #4") == [IssueRef(None, 4)]


def test_bare_hash_without_keyword_is_not_linked() -> None:
    assert refs("See PR #12 for context, bumped to v2#3") == []


def test_urls_on_provider_host() -> None:
    assert refs("Context: https://github.com/acme/api/issues/9.") == [IssueRef(None, 9)]
    assert refs("https://github.com/acme/api/pull/9") == []
    assert refs("https://evil.example/acme/api/issues/9") == []
    gl = refs("fixes https://gitlab.com/g/sub/p/-/issues/5", own="g/p", host="gitlab.com")
    assert gl == [IssueRef("g/sub/p", 5)]


def test_code_quotes_and_summary_block_ignored() -> None:
    text = (
        "```\nfixes #1\n```\n`closes #2`\n> fixes #3\n"
        "<!-- hootpr:summary:start -->\nfixes #4\n<!-- hootpr:summary:end -->\nfixes #5"
    )
    assert refs(text) == [IssueRef(None, 5)]


def test_limit() -> None:
    text = "fixes " + ", ".join(f"#{i}" for i in range(1, 20))
    assert len(refs(text)) == 5


def test_parse_issue_url_variants() -> None:
    assert parse_issue_url("https://gitlab.com/g/p/issues/2", "gitlab.com") == IssueRef("g/p", 2)
    assert parse_issue_url("https://github.com/issues/2", "github.com") is None
