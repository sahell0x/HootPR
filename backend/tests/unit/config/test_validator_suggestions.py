from app.config.validator import validate_settings, validate_yaml


def test_unknown_key_suggests_closest() -> None:
    v = validate_yaml("reviews:\n  profle: chill\n")
    assert not v.valid
    e = v.errors[0]
    assert (e.line, e.path) == (2, "reviews.profle")
    assert e.message == "unknown key 'profle' (did you mean 'profile'?)"


def test_unknown_nested_key_in_list_item() -> None:
    v = validate_yaml("reviews:\n  path_instructions:\n    - path: a\n      instruction: x\n")
    msgs = [e.message for e in v.errors]
    assert "unknown key 'instruction' (did you mean 'instructions'?)" in msgs


def test_unknown_key_in_inherited_tool_model() -> None:
    issues = validate_settings({"reviews": {"tools": {"ast_grep": {"essentials_rules": True}}}})
    assert issues[0].message == "unknown key 'essentials_rules' (did you mean 'essential_rules'?)"


def test_unknown_top_level_key() -> None:
    issues = validate_settings({"langauge": "en-US"})
    assert issues[0].message == "unknown key 'langauge' (did you mean 'language'?)"


def test_unknown_key_without_close_match() -> None:
    issues = validate_settings({"zzz": 1})
    assert issues[0].message == "unknown key 'zzz'"


def test_other_errors_keep_pydantic_message() -> None:
    issues = validate_settings({"reviews": {"profile": "loud"}})
    assert "chill" in issues[0].message
