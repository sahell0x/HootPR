import yaml

from app.config.loader import leaf_paths, resolve_config
from app.config.render import render_configuration


def test_leaf_paths() -> None:
    assert leaf_paths({"a": 1, "b": {"c": [1], "d": {}}}) == ["a", "b.c", "b.d"]


def test_provenance_without_inheritance_uses_top_source_only() -> None:
    r = resolve_config(None, {"reviews": {"profile": "assertive"}}, {"reviews": {"poem": True}})
    assert r.source == "repo"
    assert dict(r.provenance) == {"reviews.profile": "repo"}
    assert r.config.reviews.poem is False


def test_provenance_with_inheritance_tracks_each_leaf() -> None:
    r = resolve_config(
        {"inheritance": True, "reviews": {"poem": True}},
        {"reviews": {"profile": "assertive"}},
        {"language": "de-DE", "reviews": {"poem": False}},
    )
    assert dict(r.provenance) == {
        "inheritance": "yaml",
        "reviews.poem": "yaml",
        "reviews.profile": "repo",
        "language": "org",
    }


def test_provenance_after_invalid_top_source_falls_back() -> None:
    r = resolve_config({"reviews": {"profile": "loud"}}, None, {"language": "fr-FR"})
    assert r.source == "org" and dict(r.provenance) == {"language": "org"}


def test_render_configuration_marks_sources_and_round_trips() -> None:
    r = resolve_config(
        {
            "inheritance": True,
            "reviews": {
                "poem": True,
                "path_instructions": [{"path": "src/**", "instructions": "Check auth."}],
            },
        },
        {"reviews": {"profile": "assertive"}},
        {"language": "de-DE"},
    )
    text = render_configuration(r)
    assert text.startswith("# Effective HootPR configuration (source: .hootpr.yaml)\n")
    assert "language: de-DE  # from organization settings\n" in text
    assert "  profile: assertive  # from repository settings\n" in text
    assert "  poem: true  # from .hootpr.yaml\n" in text
    assert "  high_level_summary: true\n" in text  # defaults carry no comment
    assert yaml.safe_load(text) == r.config.model_dump(mode="json")


def test_render_quotes_ambiguous_strings_and_round_trips() -> None:
    r = resolve_config(
        None,
        {
            "tone_instructions": "yes: be # brief\nsecond line",
            "reviews": {"high_level_summary_placeholder": "@hootpr summary"},
        },
        None,
    )
    text = render_configuration(r)
    assert yaml.safe_load(text) == r.config.model_dump(mode="json")


def test_render_default_config() -> None:
    text = render_configuration(resolve_config(None, None, None))
    assert text.startswith("# Effective HootPR configuration (source: defaults)\n")
    assert "# from" not in text
    assert yaml.safe_load(text) == resolve_config(None, None, None).config.model_dump(mode="json")
