from decimal import Decimal

import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from app.settings import Settings


def make(**kw: object) -> Settings:
    return Settings(_env_file=None, **kw)  # type: ignore[arg-type]


def test_rejects_live_razorpay_key() -> None:
    with pytest.raises(ValidationError, match="rzp_test_"):
        make(razorpay_key_id="rzp_live_abc")


def test_rejects_empty_razorpay_key() -> None:
    with pytest.raises(ValidationError, match="rzp_test_"):
        make(razorpay_key_id="")


def test_accepts_test_key() -> None:
    assert make(razorpay_key_id="rzp_test_abc").razorpay_key_id == "rzp_test_abc"


def test_secrets_are_redacted_in_repr() -> None:
    s = make(razorpay_key_secret="supersecret", github_webhook_secret="whsecret")
    assert "supersecret" not in repr(s)
    assert "whsecret" not in repr(s)
    assert "supersecret" not in str(s.model_dump())


def test_development_derives_valid_dev_keys() -> None:
    s = make(app_env="development")
    Fernet(s.fernet_key)  # does not raise
    assert len(s.session_key) >= 32
    assert s.using_dev_secrets is True


def test_explicit_secrets_are_not_dev_secrets() -> None:
    s = make(secret_encryption_key=Fernet.generate_key().decode(), session_secret="x" * 48)
    assert s.using_dev_secrets is False


def test_production_requires_secrets() -> None:
    with pytest.raises(ValidationError, match="SECRET_ENCRYPTION_KEY"):
        make(app_env="production")


def test_production_requires_session_secret() -> None:
    with pytest.raises(ValidationError, match="SESSION_SECRET"):
        make(app_env="production", secret_encryption_key=Fernet.generate_key().decode())


def test_invalid_fernet_key_is_rejected() -> None:
    with pytest.raises(ValidationError, match="Fernet"):
        make(secret_encryption_key="not-a-key")


def test_billing_defaults_match_spec() -> None:
    s = make()
    assert s.credits_signup_bonus == Decimal("300")
    assert s.review_hold_max == Decimal("1000") and s.review_min_charge == Decimal("10")
    assert s.chat_hold_max == Decimal("100") and s.chat_min_charge == Decimal("5")
    assert s.finishing_hold_max == Decimal("300") and s.security_hold_max == Decimal("500")
    assert s.finishing_min_charge == Decimal("10") and s.security_min_charge == Decimal("50")
    assert s.review_hold_base == Decimal("100") and s.review_hold_per_line == Decimal("0.4")
    assert s.review_hold_per_file == Decimal("5")
    assert s.credits_review_input_per_1m == Decimal("6000")
    assert s.credits_typical_review == Decimal("100")
    assert s.credits_typical_chat_reply == Decimal("50")
    assert s.rate_limit_reviews_per_hour == 2
    assert s.rate_limit_chat_per_hour == 10
    assert s.credit_pack_credits == 500
    assert s.credit_pack_price_paise == 4900
    assert s.max_purchases_per_org == 2
    assert s.max_credit_balance == Decimal("1000")


def test_billing_configured_requires_real_test_key_and_secret() -> None:
    assert make().billing_configured is False
    assert make(razorpay_key_id="rzp_test_abc").billing_configured is False
    assert make(razorpay_key_id="rzp_test_abc", razorpay_key_secret="s").billing_configured


def test_cookie_secure_follows_api_base_url_and_samesite() -> None:
    # Cookies are set by the API origin.
    assert make(api_base_url="https://api.hootpr.dev").cookie_secure is True
    assert make(api_base_url="http://localhost:8000").cookie_secure is False
    # SameSite=None is only accepted by browsers with Secure.
    assert make(api_base_url="http://localhost:8000", cookie_samesite="none").cookie_secure is True
    assert make().cookie_samesite == "lax"
    with pytest.raises(ValidationError):
        make(cookie_samesite="bogus")


def test_cors_origins_are_app_base_url_plus_extras() -> None:
    s = make(app_base_url="https://app.example.com/", cors_extra_origins=" https://x.dev/, ,")
    assert s.cors_origins == ["https://app.example.com", "https://x.dev"]
    assert make(app_base_url="http://localhost:3000").cors_origins == ["http://localhost:3000"]


def test_gitlab_hook_url_defaults_to_api_base() -> None:
    s = make(api_base_url="https://api.example.com")
    assert s.gitlab_hook_url == "https://api.example.com/api/webhooks/gitlab"
    assert make(gitlab_webhook_url="https://smee.io/x").gitlab_hook_url == "https://smee.io/x"


def test_inline_private_key_wins_over_path() -> None:
    s = make(github_app_private_key="-----BEGIN KEY-----\\nabc\\n-----END KEY-----")
    assert s.github_private_key() == "-----BEGIN KEY-----\nabc\n-----END KEY-----"


def test_private_key_read_from_path(tmp_path: object) -> None:
    from pathlib import Path

    p = Path(str(tmp_path)) / "k.pem"
    p.write_text("PEM")
    assert make(github_app_private_key_path=str(p)).github_private_key() == "PEM"
    assert make(github_app_private_key_path=str(p) + ".missing").github_private_key() == ""


def test_reads_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RATE_LIMIT_REVIEWS_PER_HOUR", "7")
    monkeypatch.setenv("GITHUB_APP_ID", "")  # empty env values are ignored
    s = make()
    assert s.rate_limit_reviews_per_hour == 7
    assert s.github_app_id == ""


def test_phase2_engine_defaults(settings: Settings) -> None:
    s = settings
    assert s.sandbox_backend == "docker"
    assert s.sandbox_network == "hootpr_sandbox_egress"
    assert s.sandbox_clone_depth == 50
    assert s.sandbox_tools_timeout_s == 600
    assert s.sandbox_graph_timeout_s == 300
    assert s.sandbox_orphan_max_age_minutes == 30
    assert s.sandbox_local_tools_dir == ""
    assert s.graph_max_symbols == 20000
    assert s.agent_shell_timeout_s == 20
    assert s.agent_shell_max_output_kb == 16
    assert s.judge_batch_size == 10
    assert s.judge_min_confidence_chill == 0.6
    assert s.judge_min_confidence_assertive == 0.45
    assert s.review_cache_ttl_days == 7


def test_local_sandbox_refused_in_production() -> None:
    with pytest.raises(ValueError, match="SANDBOX_BACKEND=local"):
        make(
            app_env="production",
            secret_encryption_key=Fernet.generate_key().decode(),
            session_secret="s" * 48,
            sandbox_backend="local",
        )


def test_local_sandbox_allowed_outside_production() -> None:
    assert make(app_env="test", sandbox_backend="local").sandbox_backend == "local"


def test_judge_batch_size_capped_at_ten() -> None:
    with pytest.raises(ValueError):
        make(judge_batch_size=11)


def test_phase3_defaults(settings: Settings) -> None:
    s = settings
    assert s.chat_agent_max_steps == 6
    assert s.chat_max_input_tokens == 40000
    assert s.chat_reply_max_chars == 4000
    assert s.chat_thread_max_messages == 10
    assert s.learnings_top_k == 8
    assert s.learnings_min_similarity == 0.25
    assert s.learnings_max_per_chat == 3
    assert s.guidelines_max_files == 50
    assert s.guidelines_max_file_kb == 8
    assert s.guidelines_max_total_kb == 32
    assert s.ast_grep_timeout_s == 120


@pytest.mark.parametrize(
    "field,value",
    [
        ("learnings_top_k", 0),
        ("learnings_top_k", 51),
        ("learnings_min_similarity", 1.5),
        ("chat_max_input_tokens", 10),
        ("ast_grep_timeout_s", 1),
    ],
)
def test_phase3_bounds(field: str, value: object) -> None:
    with pytest.raises(ValueError):
        make(**{field: value})


def test_env_example_documents_phase3_settings() -> None:
    from pathlib import Path

    text = (Path(__file__).resolve().parents[3] / ".env.example").read_text()
    for var in (
        "CHAT_AGENT_MAX_STEPS",
        "CHAT_MAX_INPUT_TOKENS",
        "CHAT_REPLY_MAX_CHARS",
        "CHAT_THREAD_MAX_MESSAGES",
        "LEARNINGS_TOP_K",
        "LEARNINGS_MIN_SIMILARITY",
        "LEARNINGS_MAX_PER_CHAT",
        "GUIDELINES_MAX_FILES",
        "GUIDELINES_MAX_FILE_KB",
        "GUIDELINES_MAX_TOTAL_KB",
        "AST_GREP_TIMEOUT_S",
    ):
        assert f"\n{var}=" in text, var


def test_base_urls_follow_ports_when_unset() -> None:
    s = make(web_port=3300, api_port=8300)
    assert (s.app_base_url, s.api_base_url) == ("http://localhost:3300", "http://localhost:8300")
    s = make(api_port=8300, api_base_url="https://api.example.com")
    assert s.api_base_url == "https://api.example.com"
