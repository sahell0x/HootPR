"""`.hootpr.yaml` schema v1 (spec §9.2, phase-3 spec §7).

Every field carries a ``description`` so the published JSON schema (``/schema/hootpr.v1.json``)
gives editor tooltips and the dashboard can render forms from it (phase-3 R22, plan contract C7).
"""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

SCHEMA_ID = "hootpr.v1.json"
Scope = Literal["local", "global", "auto"]
AstGrepSeverity = Literal["hint", "info", "warning", "error"]


def _yaml_off(value: Any) -> Any:
    """YAML 1.1 loads a bare ``off`` as ``False``; the spec writes ``mode: off``."""
    return "off" if value is False else value


Mode = Annotated[Literal["off", "warning", "error"], BeforeValidator(_yaml_off)]

_MODE = "off: skip the check; warning: report it; error: report it and fail the check."


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Toggle(_Strict):
    enabled: bool = Field(default=True, description="Enable this feature.")


class OffToggle(_Strict):
    enabled: bool = Field(default=False, description="Enable this feature.")


class PathInstruction(_Strict):
    path: str = Field(min_length=1, description="Glob of files these instructions apply to.")
    instructions: str = Field(
        max_length=20000, description="Additional review instructions for the matching files."
    )


class AutoReview(_Strict):
    enabled: bool = Field(default=True, description="Automatically review pull requests.")
    auto_incremental_review: bool = Field(
        default=True, description="Automatically review new commits pushed to a reviewed PR."
    )
    auto_pause_after_reviewed_commits: int = Field(
        default=5,
        ge=0,
        description=(
            "Pause automatic reviews after this many reviewed commits (0 never pauses). "
            "Resume with @hootpr resume."
        ),
    )
    drafts: bool = Field(default=False, description="Review draft pull requests.")
    base_branches: list[str] = Field(
        default_factory=list,
        description=(
            "Regular expressions of extra base branches to review; the default branch is "
            "always reviewed."
        ),
    )
    labels: list[str] = Field(
        default_factory=list,
        description=(
            "Only review PRs with one of these labels; prefix a label with ! to skip PRs "
            "that carry it."
        ),
    )
    ignore_title_keywords: list[str] = Field(
        default_factory=lambda: ["WIP", "DO NOT MERGE"],
        description="Skip PRs whose title contains any of these keywords (case-insensitive).",
    )
    ignore_usernames: list[str] = Field(
        default_factory=list, description="Skip PRs opened by these usernames."
    )
    description_keyword: str = Field(
        default="",
        description="When set, only review PRs whose description contains this keyword.",
    )


class CustomRecipe(_Strict):
    name: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9 _.-]*$",
        description="Recipe name used in @hootpr run <name> (case-insensitive).",
    )
    instructions: str = Field(
        min_length=1, max_length=10000, description="What HootPR should change in the pull request."
    )
    enabled: bool = Field(default=True, description="Enable this recipe.")


class FinishingTouches(_Strict):
    docstrings: Toggle = Field(
        default_factory=Toggle, description="Allow @hootpr generate docstrings."
    )
    unit_tests: Toggle = Field(
        default_factory=Toggle, description="Allow @hootpr generate unit tests."
    )
    autofix: Toggle = Field(default_factory=Toggle, description="Allow @hootpr autofix.")
    simplify: Toggle = Field(default_factory=Toggle, description="Allow @hootpr simplify.")
    fix_ci: Toggle = Field(default_factory=Toggle, description="Allow @hootpr fix ci.")
    ci_analysis: Toggle = Field(
        default_factory=Toggle,
        description="Comment an analysis of failed CI jobs (GitHub Actions / GitLab pipelines).",
    )
    merge_conflicts: Toggle = Field(
        default_factory=Toggle, description="Allow @hootpr resolve merge conflict."
    )
    custom: list[CustomRecipe] = Field(
        default_factory=list,
        description="Named custom finishing touches, run with @hootpr run <name>.",
    )


class TitleCheck(_Strict):
    mode: Mode = Field(default="warning", description=f"Pull request title check. {_MODE}")
    requirements: str = Field(
        default="", description="Extra requirements the PR title must satisfy."
    )


class ModeOnly(_Strict):
    mode: Mode = Field(default="warning", description=f"Check mode. {_MODE}")


class DocstringCheck(_Strict):
    mode: Mode = Field(default="off", description=f"Docstring coverage check. {_MODE}")
    threshold: int = Field(
        default=80, ge=0, le=100, description="Minimum docstring coverage percentage."
    )


class CustomCheck(_Strict):
    name: str = Field(min_length=1, description="Name of the custom pre-merge check.")
    mode: Mode = Field(default="warning", description=f"Check mode. {_MODE}")
    instructions: str = Field(description="What the check verifies, in natural language.")


class PreMergeChecks(_Strict):
    title: TitleCheck = Field(
        default_factory=TitleCheck, description="Check that the PR title is descriptive."
    )
    description: ModeOnly = Field(
        default_factory=ModeOnly, description="Check that the PR description is complete."
    )
    docstrings: DocstringCheck = Field(
        default_factory=DocstringCheck, description="Check docstring coverage of changed code."
    )
    issue_assessment: ModeOnly = Field(
        default_factory=ModeOnly,
        description="Check that the PR addresses the linked issues.",
    )
    custom_checks: list[CustomCheck] = Field(
        default_factory=list, description="Custom pre-merge checks written in natural language."
    )


class SemgrepTool(Toggle):
    config_file: str = Field(
        default="", description="Path to a Semgrep config file in the repository."
    )


class PhpstanTool(Toggle):
    level: int = Field(default=5, ge=0, le=9, description="PHPStan rule level (0-9).")


class AstGrepRule(_Strict):
    id: str = Field(
        pattern=r"^[A-Za-z0-9_-]{1,64}$", description="Unique rule id, shown with each match."
    )
    language: str = Field(
        min_length=1,
        max_length=32,
        description="ast-grep language name, e.g. python, typescript, go.",
    )
    message: str = Field(
        min_length=1,
        max_length=1000,
        description="Instruction HootPR's reviewer receives for every match.",
    )
    severity: AstGrepSeverity = Field(
        default="warning", description="Hint for how serious a match is."
    )
    rule: dict[str, Any] = Field(
        min_length=1,
        description=(
            "ast-grep rule object (pattern, kind, regex, inside, has, all, any, not, ...)."
        ),
    )
    files: list[str] = Field(
        default_factory=list,
        description="Optional globs limiting the files this rule applies to.",
    )


class AstGrepTool(Toggle):
    rule_dirs: list[str] = Field(
        default_factory=list,
        description=(
            "Repository directories with ast-grep rule YAML files (read from the base branch)."
        ),
    )
    util_dirs: list[str] = Field(
        default_factory=list, description="Repository directories with ast-grep utility rules."
    )
    essential_rules: bool = Field(
        default=False, description="Also apply the ast-grep-essentials security rule pack."
    )


def _tool(name: str) -> Any:
    return Field(default_factory=Toggle, description=f"Run {name} on changed files.")


class Tools(_Strict):
    semgrep: SemgrepTool = Field(
        default_factory=SemgrepTool, description="Run Semgrep on changed files."
    )
    gitleaks: Toggle = _tool("Gitleaks (secret scanning)")
    trivy: Toggle = _tool("Trivy (dependency and IaC scanning)")
    checkov: Toggle = _tool("Checkov (infrastructure-as-code scanning)")
    ruff: Toggle = _tool("Ruff (Python)")
    eslint: Toggle = _tool("ESLint (JavaScript/TypeScript)")
    shellcheck: Toggle = _tool("ShellCheck (shell scripts)")
    hadolint: Toggle = _tool("Hadolint (Dockerfiles)")
    actionlint: Toggle = _tool("actionlint (GitHub Actions workflows)")
    yamllint: Toggle = _tool("yamllint (YAML)")
    markdownlint: Toggle = _tool("markdownlint (Markdown)")
    golangci_lint: Toggle = _tool("golangci-lint (Go)")
    rubocop: Toggle = _tool("RuboCop (Ruby)")
    phpstan: PhpstanTool = Field(
        default_factory=PhpstanTool, description="Run PHPStan (PHP) on changed files."
    )
    swiftlint: Toggle = _tool("SwiftLint (Swift)")
    ast_grep: AstGrepTool = Field(
        default_factory=AstGrepTool,
        description="AST-grep instructions (syntax-aware review rules).",
    )


class SlopDetection(_Strict):
    enabled: bool = Field(
        default=True,
        description=(
            'Flag low-quality or AI-generated "slop" pull requests (boilerplate text, unrelated '
            "churn, calls to symbols that do not exist, huge unreviewable diffs)."
        ),
    )
    label: str = Field(
        default="slop",
        max_length=50,
        description="Label added to flagged pull requests (empty: add no label).",
    )


class PostMergeRecipe(_Strict):
    name: str = Field(min_length=1, max_length=64, description="Name of the post-merge action.")
    instructions: str = Field(
        min_length=1,
        max_length=10000,
        description="What HootPR should write after the merge (posted as a comment).",
    )
    enabled: bool = Field(default=True, description="Enable this post-merge action.")


class PostMergeActions(_Strict):
    follow_up_issue: OffToggle = Field(
        default_factory=OffToggle,
        description="Open an issue listing HootPR comments that were still unresolved at merge.",
    )
    changelog: OffToggle = Field(
        default_factory=OffToggle,
        description="Draft a changelog entry for the merged pull request (posted as a comment).",
    )
    custom: list[PostMergeRecipe] = Field(
        default_factory=list,
        description="Custom post-merge actions written in natural language.",
    )


class Reviews(_Strict):
    profile: Literal["chill", "assertive"] = Field(
        default="chill",
        description=(
            "Review profile: chill reports fewer, higher-confidence issues; assertive also "
            "reports nitpicks."
        ),
    )
    request_changes_workflow: bool = Field(
        default=False,
        description=(
            "Approve the PR once all HootPR blocking comments are resolved; request changes "
            "while any are open."
        ),
    )
    high_level_summary: bool = Field(
        default=True, description="Write a high-level summary into the PR description."
    )
    high_level_summary_placeholder: str = Field(
        default="@hootpr summary",
        description="Text in the PR description that HootPR replaces with its summary.",
    )
    auto_title_placeholder: str = Field(
        default="@hootpr",
        description="Text in the PR title that HootPR replaces with a generated title.",
    )
    review_status: bool = Field(
        default=True,
        description="Post a review status message when a review is skipped or paused.",
    )
    commit_status: bool = Field(
        default=True, description="Set a commit status while the review is in progress."
    )
    collapse_walkthrough: bool = Field(
        default=False, description="Collapse the walkthrough comment by default."
    )
    changed_files_summary: bool = Field(
        default=True, description="Include the changes table in the walkthrough."
    )
    sequence_diagrams: bool = Field(
        default=True, description="Include sequence diagrams in the walkthrough."
    )
    estimate_code_review_effort: bool = Field(
        default=True, description="Estimate the code review effort in the walkthrough."
    )
    assess_linked_issues: bool = Field(
        default=True, description="Assess whether the PR resolves its linked issues."
    )
    related_prs: bool = Field(
        default=True, description="List possibly related pull requests in the walkthrough."
    )
    poem: bool = Field(default=False, description="Add a short poem to the walkthrough.")
    disable_cache: bool = Field(
        default=False, description="Do not reuse cached code graphs or tool results."
    )
    path_filters: list[str] = Field(
        default_factory=list,
        description="Globs of files to include in the review; prefix with ! to exclude.",
    )
    path_instructions: list[PathInstruction] = Field(
        default_factory=list, description="Extra review instructions for files matching a glob."
    )
    ast_grep_instructions: list[AstGrepRule] = Field(
        default_factory=list,
        description=(
            "Inline ast-grep rules; code that matches a rule gets the rule's message as an "
            "extra review instruction."
        ),
    )
    abort_on_close: bool = Field(
        default=True, description="Abort an in-progress review when the PR is closed."
    )
    auto_review: AutoReview = Field(
        default_factory=AutoReview, description="When HootPR reviews automatically."
    )
    finishing_touches: FinishingTouches = Field(
        default_factory=FinishingTouches,
        description="Commands that generate code for the PR (docstrings, unit tests, ...).",
    )
    pre_merge_checks: PreMergeChecks = Field(
        default_factory=PreMergeChecks, description="Checks run before the PR is merged."
    )
    slop_detection: SlopDetection = Field(
        default_factory=SlopDetection, description="Detect low-quality (slop) pull requests."
    )
    post_merge_actions: PostMergeActions = Field(
        default_factory=PostMergeActions,
        description="Actions HootPR runs when a pull request is merged.",
    )
    tools: Tools = Field(default_factory=Tools, description="Static analysis and security tools.")

    @model_validator(mode="after")
    def _unique_rule_ids(self) -> "Reviews":
        ids = [r.id for r in self.ast_grep_instructions]
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        if dupes:
            raise ValueError(f"duplicate ast_grep_instructions id: {', '.join(dupes)}")
        return self


class Chat(_Strict):
    auto_reply: bool = Field(
        default=True,
        description=(
            "Reply to comments in threads HootPR started without requiring an @hootpr mention."
        ),
    )


class ScopeSetting(_Strict):
    scope: Scope = Field(
        default="auto",
        description=(
            "local: this repository only; global: the whole organization; auto: local for "
            "public repositories, global for private ones."
        ),
    )


class LearningsSetting(ScopeSetting):
    scope: Scope = Field(
        default="auto",
        description=(
            "Which learnings apply: local (this repository), global (whole organization) or "
            "auto (local for public repositories, global for private)."
        ),
    )


class CodeGuidelines(_Strict):
    enabled: bool = Field(
        default=True,
        description="Read coding guideline files from the base branch and apply them in reviews.",
    )
    file_patterns: list[str] = Field(
        default_factory=list,
        description=(
            "Extra glob patterns of guideline files, added to the built-in list "
            "(CLAUDE.md, AGENTS.md, .cursorrules, ...)."
        ),
    )


class McpSetting(_Strict):
    usage: Literal["auto", "enabled", "disabled"] = Field(
        default="auto", description="Use connected MCP servers as review context."
    )


class LinkedRepository(_Strict):
    repository: str = Field(
        min_length=1, description="Full name of a linked repository (owner/name)."
    )
    instructions: str = Field(
        default="", description="How the linked repository relates to this one."
    )


class KnowledgeBase(_Strict):
    opt_out: bool = Field(
        default=False,
        description=(
            "Opt out of the knowledge base: HootPR stores no learnings and deletes existing ones."
        ),
    )
    learnings: LearningsSetting = Field(
        default_factory=LearningsSetting,
        description="Team preferences HootPR learns from chat and applies in reviews.",
    )
    code_guidelines: CodeGuidelines = Field(
        default_factory=CodeGuidelines,
        description="Coding guideline files (CLAUDE.md, AGENTS.md, .cursorrules, ...).",
    )
    issues: ScopeSetting = Field(
        default_factory=ScopeSetting, description="Use issues as review context."
    )
    pull_requests: ScopeSetting = Field(
        default_factory=ScopeSetting, description="Use past pull requests as review context."
    )
    mcp: McpSetting = Field(default_factory=McpSetting, description="MCP server integration.")
    web_search: OffToggle = Field(
        default_factory=OffToggle, description="Search the web for review context."
    )
    linked_repositories: list[LinkedRepository] = Field(
        default_factory=list, description="Other repositories used as review context."
    )


class DocstringGen(_Strict):
    language: str = Field(default="en-US", description="Language of generated docstrings.")
    path_instructions: list[PathInstruction] = Field(
        default_factory=list, description="Extra docstring instructions for files matching a glob."
    )


class UnitTestGen(_Strict):
    path_instructions: list[PathInstruction] = Field(
        default_factory=list,
        description="Extra unit test instructions for files matching a glob.",
    )


class CodeGeneration(_Strict):
    docstrings: DocstringGen = Field(
        default_factory=DocstringGen, description="Docstring generation settings."
    )
    unit_tests: UnitTestGen = Field(
        default_factory=UnitTestGen, description="Unit test generation settings."
    )


class LabelingInstruction(_Strict):
    label: str = Field(min_length=1, max_length=100, description="Label name.")
    instructions: str = Field(
        min_length=1, max_length=2000, description="When HootPR should suggest this label."
    )


class IssueLabeling(_Strict):
    labeling_instructions: list[LabelingInstruction] = Field(
        default_factory=list,
        description="Labels HootPR may suggest and when (default: all repository labels).",
    )
    auto_apply_labels: bool = Field(
        default=False, description="Apply suggested labels instead of only suggesting them."
    )


class IssueEnrichment(_Strict):
    auto_enrich: Toggle = Field(
        default_factory=Toggle,
        description=(
            "Comment on new issues with possible duplicates, suggested labels and suggested "
            "assignees."
        ),
    )
    labeling: IssueLabeling = Field(
        default_factory=IssueLabeling, description="Label suggestions for new issues."
    )


class HootPRConfig(_Strict):
    model_config = ConfigDict(extra="forbid", title="HootPR configuration")
    language: str = Field(
        default="en-US", description="Language of HootPR's comments (ISO code, e.g. en-US)."
    )
    tone_instructions: str = Field(
        default="",
        max_length=250,
        description="Custom tone for HootPR's comments (at most 250 characters).",
    )
    inheritance: bool = Field(
        default=False,
        description=(
            "Merge this configuration with repository, organization and default settings "
            "instead of replacing them."
        ),
    )
    early_access: bool = Field(default=False, description="Enable early-access features.")
    reviews: Reviews = Field(default_factory=Reviews, description="Review settings.")
    chat: Chat = Field(default_factory=Chat, description="Chat settings.")
    knowledge_base: KnowledgeBase = Field(
        default_factory=KnowledgeBase, description="Knowledge base settings."
    )
    issue_enrichment: IssueEnrichment = Field(
        default_factory=IssueEnrichment, description="Issue enrichment settings."
    )
    code_generation: CodeGeneration = Field(
        default_factory=CodeGeneration, description="Code generation settings."
    )


def config_json_schema(base_url: str) -> dict[str, Any]:
    """The published JSON schema; ``$id`` points at this deployment (phase-3 R22)."""
    schema = HootPRConfig.model_json_schema()
    schema["$id"] = f"{base_url.rstrip('/')}/schema/{SCHEMA_ID}"
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    return schema
