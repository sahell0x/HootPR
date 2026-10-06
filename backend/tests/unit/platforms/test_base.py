from app.platforms.base import CloneCredentials, ensure_marker, replace_marked_block


def test_replace_marked_block_appends_when_missing() -> None:
    out = replace_marked_block("Hello", "hootpr:summary", "S1")
    assert out == "Hello\n\n<!-- hootpr:summary:start -->\nS1\n<!-- hootpr:summary:end -->"


def test_replace_marked_block_replaces_existing() -> None:
    first = replace_marked_block("Hello", "hootpr:summary", "S1")
    second = replace_marked_block(first, "hootpr:summary", "S2")
    assert "S1" not in second and second.count("hootpr:summary:start") == 1
    assert second.startswith("Hello")


def test_ensure_marker() -> None:
    assert ensure_marker("body", "<!-- m -->") == "<!-- m -->\nbody"
    assert ensure_marker("<!-- m -->\nbody", "<!-- m -->") == "<!-- m -->\nbody"


def test_clone_credentials_repr_hides_token() -> None:
    c = CloneCredentials(
        url="https://github.com/a/b.git", username="x-access-token", token="ghs_secret"
    )
    assert "ghs_secret" not in repr(c)


def test_replace_marked_block_swaps_placeholder_once() -> None:
    text = "Intro\n\n@hootpr summary\n\nMore @hootpr summary"
    out = replace_marked_block(text, "hootpr:summary", "S", placeholder="@hootpr summary")
    assert out == (
        "Intro\n\n<!-- hootpr:summary:start -->\nS\n<!-- hootpr:summary:end -->"
        "\n\nMore @hootpr summary"
    )
    again = replace_marked_block(out, "hootpr:summary", "T", placeholder="@hootpr summary")
    assert "<!-- hootpr:summary:start -->\nT\n<!-- hootpr:summary:end -->" in again
    assert again.count("hootpr:summary:start") == 1


def test_replace_marked_block_appends_without_placeholder() -> None:
    assert replace_marked_block("Body", "m", "S", placeholder="@x") == (
        "Body\n\n<!-- m:start -->\nS\n<!-- m:end -->"
    )
