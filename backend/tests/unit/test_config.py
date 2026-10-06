from app.config.loader import deep_merge, load_effective_config, resolve_config
from app.config.schema import HootPRConfig, config_json_schema
from app.config.validator import validate_settings, validate_yaml
from app.platforms.base import PullRequest, RepoRef
from app.platforms.local import LocalPlatform


def test_defaults_match_spec() -> None:
    c = HootPRConfig()
    assert c.language == "en-US" and c.inheritance is False
    assert c.reviews.profile == "chill" and c.reviews.poem is False
    assert c.reviews.auto_review.enabled is True and c.reviews.auto_review.drafts is False
    assert c.reviews.auto_review.ignore_title_keywords == ["WIP", "DO NOT MERGE"]
    assert c.reviews.auto_review.auto_pause_after_reviewed_commits == 5
    assert c.reviews.tools.phpstan.level == 5 and c.reviews.tools.semgrep.enabled
    assert c.knowledge_base.learnings.scope == "auto" and c.chat.auto_reply is True
    assert c.reviews.pre_merge_checks.docstrings.mode == "off"
    assert c.reviews.disable_cache is False


def test_deep_merge_rules() -> None:
    parent = {"a": {"x": 1, "y": [1, 2]}, "s": "p", "keep": True}
    child = {"a": {"y": [2, 3], "z": 0}, "s": "c"}
    assert deep_merge(parent, child) == {
        "a": {"x": 1, "y": [1, 2, 3], "z": 0},
        "s": "c",
        "keep": True,
    }
    assert parent == {"a": {"x": 1, "y": [1, 2]}, "s": "p", "keep": True}  # not mutated


def test_highest_source_wins_without_inheritance() -> None:
    r = resolve_config(
        {"reviews": {"profile": "assertive"}}, {"reviews": {"poem": True}}, {"language": "fr-FR"}
    )
    assert r.source == "yaml"
    assert r.config.reviews.profile == "assertive"
    assert r.config.reviews.poem is False and r.config.language == "en-US"


def test_inheritance_merges_all_levels() -> None:
    r = resolve_config(
        {
            "inheritance": True,
            "reviews": {"profile": "assertive", "auto_review": {"labels": ["x"]}},
        },
        {"reviews": {"poem": True, "auto_review": {"labels": ["y"]}}},
        {"language": "fr-FR"},
    )
    c = r.config
    assert (c.reviews.profile, c.reviews.poem, c.language) == ("assertive", True, "fr-FR")
    assert c.reviews.auto_review.labels == ["y", "x"]


def test_inheritance_stops_at_parent_without_inheritance_flag_is_not_required() -> None:
    # CodeRabbit: `inheritance: true` on the child pulls in every lower level.
    r = resolve_config(
        None, {"inheritance": True, "reviews": {"poem": True}}, {"language": "de-DE"}
    )
    assert r.source == "repo" and r.config.language == "de-DE" and r.config.reviews.poem is True


def test_invalid_source_falls_back_with_warning() -> None:
    r = resolve_config({"reviews": {"profile": "angry"}}, {"reviews": {"poem": True}}, None)
    assert r.source == "repo" and r.config.reviews.poem is True
    assert r.warnings and "yaml" in r.warnings[0]


def test_no_sources_gives_defaults() -> None:
    r = resolve_config(None, {}, None)
    assert r.source == "default" and r.config == HootPRConfig()


def test_validate_yaml_reports_line_numbers() -> None:
    text = "language: en-US\nreviews:\n  profile: angry\n  poem: true\n"
    v = validate_yaml(text)
    assert not v.valid
    assert v.errors[0].path == "reviews.profile" and v.errors[0].line == 3


def test_validate_yaml_unknown_key_and_syntax() -> None:
    v = validate_yaml("reviewz: {}\n")
    assert not v.valid and v.errors[0].path == "reviewz" and v.errors[0].line == 1
    bad = validate_yaml("reviews: [\n")
    assert not bad.valid and bad.errors[0].line is not None
    assert validate_yaml("").valid  # empty file == defaults
    assert not validate_yaml("- a\n- b\n").valid


def test_validate_yaml_line_inside_list() -> None:
    text = "reviews:\n  path_instructions:\n    - path: a\n      instructions: x\n    - path: b\n"
    v = validate_yaml(text)
    assert not v.valid
    assert v.errors[0].path == "reviews.path_instructions.1.instructions"
    assert v.errors[0].line == 5


def test_yaml_off_is_accepted_as_mode() -> None:
    # YAML 1.1 parses bare `off` as False; the spec example writes `mode: off`.
    v = validate_yaml("reviews:\n  pre_merge_checks:\n    title:\n      mode: off\n")
    assert v.valid and v.config is not None
    assert v.config.reviews.pre_merge_checks.title.mode == "off"


def test_validate_yaml_size_limit() -> None:
    v = validate_yaml("language: en-US\n" + "#" * (65 * 1024))
    assert not v.valid and "64 KB" in v.errors[0].message


def test_validate_settings_dict() -> None:
    assert validate_settings({"reviews": {"poem": True}}) == []
    assert validate_settings({"reviews": {"poem": "maybe"}})[0].path == "reviews.poem"


def test_load_effective_config_reads_base_branch() -> None:
    lp = LocalPlatform()
    repo = RepoRef("github", "1", "acme/web")
    lp.add_pull_request(
        repo, PullRequest(1, "t", "", "a", "open", False, "main", "f", "b", "h", (), ""), []
    )
    lp.set_file(repo, ".hootpr.yaml", "main", "reviews:\n  poem: true\n")
    lp.set_file(repo, ".hootpr.yaml", "f", "reviews:\n  auto_review:\n    enabled: false\n")
    r = load_effective_config(lp, repo, "main", {}, {})
    assert r.source == "yaml" and r.config.reviews.poem is True
    assert r.config.reviews.auto_review.enabled is True  # head-branch file is not enforced


def test_load_effective_config_invalid_yaml_falls_back() -> None:
    lp = LocalPlatform()
    repo = RepoRef("github", "1", "acme/web")
    lp.set_file(repo, ".hootpr.yaml", "main", "reviews:\n  profile: angry\n")
    r = load_effective_config(lp, repo, "main", {"reviews": {"poem": True}}, {})
    assert r.source == "repo" and r.config.reviews.poem is True
    assert r.warnings and "line 2" in r.warnings[0]


def test_json_schema_has_id_and_forbids_extra() -> None:
    schema = config_json_schema("http://localhost:3000")
    assert schema["$id"].endswith("hootpr.v1.json")
    assert schema["additionalProperties"] is False
