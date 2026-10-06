// A trimmed copy of contract C7 (backend `HootPRConfig.model_json_schema()`), with `$defs`/`$ref`
// exactly as Pydantic emits them and properties in model field order (what `/api/schema/hootpr.v1.json`
// serves). tests/unit/schema-form-real.test.ts walks the real exported file.
const mode = (what: string) => ({
  default: "warning",
  description: `${what}. off: skip the check; warning: report it; error: report it and fail the check.`,
  enum: ["off", "warning", "error"],
  title: "Mode",
  type: "string",
});

export const configSchema = {
  $id: "http://localhost:3000/schema/hootpr.v1.json",
  $schema: "https://json-schema.org/draft/2020-12/schema",
  title: "HootPR configuration",
  type: "object",
  additionalProperties: false,
  $defs: {
    PathInstruction: {
      additionalProperties: false,
      properties: {
        path: { description: "Glob of files these instructions apply to.", minLength: 1, title: "Path", type: "string" },
        instructions: { description: "Additional review instructions for the matching files.", maxLength: 20000,
          title: "Instructions", type: "string" },
      },
      required: ["path", "instructions"],
      title: "PathInstruction",
      type: "object",
    },
    AstGrepRule: {
      additionalProperties: false,
      properties: {
        id: { description: "Unique rule id, shown with each match.", pattern: "^[A-Za-z0-9_-]{1,64}$", title: "Id", type: "string" },
        language: { description: "ast-grep language name, e.g. python, typescript, go.", maxLength: 32, minLength: 1,
          title: "Language", type: "string" },
        message: { description: "Instruction HootPR's reviewer receives for every match.", maxLength: 1000, minLength: 1,
          title: "Message", type: "string" },
        severity: { default: "warning", description: "Hint for how serious a match is.",
          enum: ["hint", "info", "warning", "error"], title: "Severity", type: "string" },
        rule: { additionalProperties: true, description: "ast-grep rule object (pattern, kind, regex, inside, has, all, any, not, ...).",
          minProperties: 1, title: "Rule", type: "object" },
        files: { description: "Optional globs limiting the files this rule applies to.", items: { type: "string" },
          title: "Files", type: "array" },
      },
      required: ["id", "language", "message", "rule"],
      title: "AstGrepRule",
      type: "object",
    },
    AutoReview: {
      additionalProperties: false,
      properties: {
        enabled: { default: true, description: "Automatically review pull requests.", title: "Enabled", type: "boolean" },
        labels: { description: "Only review PRs with one of these labels; prefix a label with ! to skip PRs that carry it.",
          items: { type: "string" }, title: "Labels", type: "array" },
      },
      title: "AutoReview",
      type: "object",
    },
    SemgrepTool: {
      additionalProperties: false,
      properties: {
        enabled: { default: true, description: "Enable this feature.", title: "Enabled", type: "boolean" },
        config_file: { default: "", description: "Path to a Semgrep config file in the repository.", title: "Config File", type: "string" },
      },
      title: "SemgrepTool",
      type: "object",
    },
    AstGrepTool: {
      additionalProperties: false,
      properties: {
        enabled: { default: true, description: "Enable this feature.", title: "Enabled", type: "boolean" },
        rule_dirs: { description: "Repository directories with ast-grep rule YAML files (read from the base branch).",
          items: { type: "string" }, title: "Rule Dirs", type: "array" },
        util_dirs: { description: "Repository directories with ast-grep utility rules.", items: { type: "string" },
          title: "Util Dirs", type: "array" },
        essential_rules: { default: false, description: "Also apply the ast-grep-essentials security rule pack.",
          title: "Essential Rules", type: "boolean" },
      },
      title: "AstGrepTool",
      type: "object",
    },
    Tools: {
      additionalProperties: false,
      properties: {
        semgrep: { $ref: "#/$defs/SemgrepTool", description: "Run Semgrep on changed files." },
        ast_grep: { $ref: "#/$defs/AstGrepTool", description: "AST-grep instructions (syntax-aware review rules)." },
      },
      title: "Tools",
      type: "object",
    },
    TitleCheck: {
      additionalProperties: false,
      properties: {
        mode: mode("Pull request title check"),
        requirements: { anyOf: [{ type: "string" }, { type: "null" }], default: null,
          description: "Extra requirements the PR title must satisfy.", title: "Requirements" },
      },
      title: "TitleCheck",
      type: "object",
    },
    PreMergeChecks: {
      additionalProperties: false,
      properties: {
        title: { $ref: "#/$defs/TitleCheck", description: "Check that the PR title is descriptive." },
      },
      title: "PreMergeChecks",
      type: "object",
    },
    Reviews: {
      additionalProperties: false,
      properties: {
        profile: { default: "chill", description: "Review profile: chill reports fewer, higher-confidence issues; assertive also reports nitpicks.",
          enum: ["chill", "assertive"], title: "Profile", type: "string" },
        request_changes_workflow: { default: false, description: "Approve the PR once all HootPR blocking comments are resolved; request changes while any are open.",
          title: "Request Changes Workflow", type: "boolean" },
        poem: { default: false, description: "Add a short poem to the walkthrough.", title: "Poem", type: "boolean" },
        auto_review: { $ref: "#/$defs/AutoReview", description: "When HootPR reviews automatically." },
        path_filters: { description: "Globs of files to include in the review; prefix with ! to exclude.",
          items: { type: "string" }, title: "Path Filters", type: "array" },
        path_instructions: { description: "Extra review instructions for files matching a glob.",
          items: { $ref: "#/$defs/PathInstruction" }, title: "Path Instructions", type: "array" },
        ast_grep_instructions: { description: "Inline ast-grep rules; code that matches a rule gets the rule's message as an extra review instruction.",
          items: { $ref: "#/$defs/AstGrepRule" }, title: "Ast Grep Instructions", type: "array" },
        tools: { $ref: "#/$defs/Tools", description: "Static analysis and security tools." },
        pre_merge_checks: { $ref: "#/$defs/PreMergeChecks", description: "Checks run before the PR is merged." },
      },
      title: "Reviews",
      type: "object",
    },
    Chat: {
      additionalProperties: false,
      properties: {
        auto_reply: { default: true, description: "Reply to comments in threads HootPR started without requiring an @hootpr mention.",
          title: "Auto Reply", type: "boolean" },
      },
      title: "Chat",
      type: "object",
    },
    LearningsSetting: {
      additionalProperties: false,
      properties: {
        scope: { default: "auto", description: "Which learnings apply: local (this repository), global (whole organization) or auto.",
          enum: ["local", "global", "auto"], title: "Scope", type: "string" },
      },
      title: "LearningsSetting",
      type: "object",
    },
    KnowledgeBase: {
      additionalProperties: false,
      properties: {
        opt_out: { default: false, description: "Opt out of the knowledge base: HootPR stores no learnings and deletes existing ones.",
          title: "Opt Out", type: "boolean" },
        learnings: { $ref: "#/$defs/LearningsSetting", description: "Team preferences HootPR learns from chat and applies in reviews." },
      },
      title: "KnowledgeBase",
      type: "object",
    },
  },
  properties: {
    language: { default: "en-US", description: "Language of HootPR's comments (ISO code, e.g. en-US).", title: "Language", type: "string" },
    tone_instructions: { default: "", description: "Custom tone for HootPR's comments (at most 250 characters).", maxLength: 250,
      title: "Tone Instructions", type: "string" },
    inheritance: { default: false, description: "Merge this configuration with repository, organization and default settings instead of replacing them.",
      title: "Inheritance", type: "boolean" },
    reviews: { $ref: "#/$defs/Reviews", description: "Review settings." },
    chat: { $ref: "#/$defs/Chat", description: "Chat settings." },
    knowledge_base: { $ref: "#/$defs/KnowledgeBase", description: "Knowledge base settings." },
  },
} satisfies Record<string, unknown>;
