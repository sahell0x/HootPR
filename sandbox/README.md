# HootPR sandbox image

`hootpr/sandbox` is the per-job analysis image (spec §4.3, §7.3). `make sandbox-image` builds it and
creates the `hootpr_sandbox_egress` network; `docker compose` never runs it and the worker never builds
or pulls it (a missing image fails the review with a refund and "sandbox image missing — run
`make sandbox-image`").

For each review the worker (`backend/app/sandbox/docker.py`) creates one short-lived container through
the `docker-proxy` socket proxy, clones the PR into `/work/repo`, **seals** it (disconnects the network),
runs `build_graph.py` / `run_tools.py` and the agents' read-only shell commands, then always removes it
(`remove(force=True, v=True)`).

## Hardening applied by the worker

| Setting | Value |
|---|---|
| user | `10001:10001` (`sandbox`), `HOME=/tmp` |
| root filesystem | read-only |
| `/tmp` | tmpfs, 64 MB, `nosuid,nodev` |
| `/work` | anonymous volume declared by the image (`VOLUME ["/work"]`), owned by uid 10001, on disk, removed with the container |
| memory | `SANDBOX_MEM_MB` (768) with swap disabled (`memswap_limit == mem_limit`) |
| CPU / pids | `SANDBOX_CPUS` (1.0) / 256 |
| privileges | `cap_drop=ALL`, `no-new-privileges` |
| network | `hootpr_sandbox_egress` only while cloning, then disconnected before any analysis |

Tool caches go to `/work/.hootpr` (`HOOTPR_WORK_CACHE`, `XDG_CACHE_HOME=/work/.hootpr/cache`); tools never
write into `/work/repo`.

## Toolchain (all versions pinned in `Dockerfile` / `package.json`)

| Tool (`.hootpr.yaml` key) | Version | HootPR config (`configs/` → `/opt/hootpr/configs`) |
|---|---|---|
| semgrep (`semgrep`) | 1.178.0 | `semgrep/hootpr.yml`: registry packs from `semgrep-rules.txt`, merged at build time (one copy per rule id, 1,160 rules) |
| gitleaks (`gitleaks`) | 8.30.1 | `gitleaks.toml` (default ruleset; output redacted) |
| trivy (`trivy`) | 0.74.0 | vuln DB + misconfig checks baked in `/opt/trivy-cache` |
| checkov (`checkov`) | 3.3.20 | built-in checks, `--skip-download` |
| ruff (`ruff`) | 0.16.9 | `ruff.toml` |
| eslint (`eslint`) + typescript-eslint 8.71.0, eslint-plugin-security 4.1.0, eslint-plugin-react-hooks 7.1.1, typescript 6.0.3 | 10.11.0 | `eslint.config.mjs` |
| shellcheck (`shellcheck`) | 0.11.0 | `--norc` |
| hadolint (`hadolint`) | 2.15.1 | `hadolint.yaml` |
| actionlint (`actionlint`) | 1.7.12 | `actionlint.yaml` (pyflakes integration off) |
| yamllint (`yamllint`) | 1.38.0 | `yamllint.yaml` |
| markdownlint-cli (`markdownlint`) | 0.49.1 | `markdownlint.json` |
| golangci-lint (`golangci_lint`) + Go | 2.14.0 + go 1.27.1 | `--no-config`, linters govet/errcheck/staticcheck/ineffassign/unused/gosec, `GOPROXY=off` |
| rubocop (`rubocop`) | 1.91.0 | `rubocop.yml` (no `require:`/`plugins:`) |
| phpstan (`phpstan`) | 2.2.16 (`/opt/hootpr/bin/phpstan.phar`, PHP 8.2) | `phpstan.neon` |
| swiftlint (`swiftlint`) | 0.65.1 | `swiftlint.yml` |
| ast-grep, ripgrep, git, jq | 0.45.3, 13.0.0, 2.39.5 | agents' `shell` tool; ast-grep also runs `.hootpr.yaml` AST-grep rules (see below) |
| python3 (venv) + tree-sitter-language-pack | 3.11 + 1.20.0 | 15 grammars baked in `/opt/hootpr/grammars` |

Repository configs that can execute code (`eslint.config.js`, `.rubocop.yml` plugins, `conftest.py`, ...)
are never used: every tool gets an explicit HootPR config. A repository semgrep rule file (`run_tools.py
--semgrep-config`, a repo-relative `.yml` path) is YAML data and is added with a second `--config`.
Tools that auto-load files from their working directory (checkov `.checkov.yaml` external checks,
phpstan `vendor/autoload.php`, rubocop `.rubocop` argument files) run from an empty scratch directory
(also their `HOME`) with absolute file paths, and `RUBOCOP_OPTS`/`RUBYOPT`/`NODE_OPTIONS`-style variables
are never passed through.

`run_tools.py` also takes `--manifest <lockfile>` (lockfiles HootPR never reviews line by line; only trivy
scans them, so a vulnerable dependency bump is still reported) and `--deadline <seconds>` (a global budget:
the engine passes `SANDBOX_TOOLS_TIMEOUT_S - 30`, tools that would run past it are recorded as `timeout`
so the JSON document is always printed before the outer exec timeout).

### Offline data (sealed sandbox)

- **trivy**: `trivy fs --download-db-only` + a `trivy config` warm-up bake the vulnerability DB (~1.4 GB,
  the largest part of the image) and the misconfiguration checks bundle into `/opt/trivy-cache`. Outcome
  of the plan S3 check: trivy opens the DB **in place on the read-only root filesystem** when run with
  `--cache-backend memory` (scan caches stay in memory), so `run_tools.py` never copies it; the copy into
  `/work/.hootpr/trivy-cache` is only used when no baked DB exists (host runs).
- **semgrep**: the packs in `semgrep-rules.txt` are downloaded from the registry at build time and merged by
  `build/merge_semgrep_rules.py`; `run_tools.py` strips the local-path prefix semgrep adds to rule ids.
- **tree-sitter**: tree-sitter-language-pack 1.x downloads grammars on first use, so
  `build/bake_grammars.py` fetches every language in `build_graph.py`'s `EXT_LANG` at build time and the
  image sets `TREE_SITTER_LANGUAGE_PACK_LIBS_DIR=/opt/hootpr/grammars` (read-only, no download at runtime).

Refresh all of them (and every pinned version) by rebuilding: `make sandbox-image`. Bump versions in
`Dockerfile` / `package.json` together and re-run `make test-sandbox`.

Image size: ~2.96 GiB uncompressed (budget < 3 GiB, asserted by `tests/image`); if a trivy DB update
pushes it over, trim the Go toolchain / npm leftovers first — never drop a §7.3 tool.

## AST-grep (phase 3)

`reviews.ast_grep_instructions` (inline rules), `reviews.tools.ast_grep.rule_dirs` / `util_dirs` (rule YAML
read from the PR's **base** commit) and, with `reviews.tools.ast_grep.essential_rules: true`, the
[ast-grep-essentials](https://github.com/coderabbitai/ast-grep-essentials) security pack are run by
`ast-grep` (on `PATH`, from `package.json`) in the sealed sandbox (plan contract C4):

- **Essentials pack**: baked at `/opt/hootpr/ast-grep/essentials/rules/<lang>/security/*.yml` and
  `/opt/hootpr/ast-grep/essentials/utils/` (read-only, world-readable; 184 rules at the current pin).
  The download stage fetches the pinned commit `AST_GREP_ESSENTIALS_REF`; the final stage runs
  `build/sanitize_ast_grep_rules.py`, because upstream names many local utils after code
  (`$DB(..., password="...")`) and ast-grep ≥ 0.4x rejects those ids — a single such file makes
  `ast-grep scan --config` fail for the whole pack. The script renames the ids (and their `matches:`
  references), copies untouched files byte for byte and drops any rule the pinned ast-grep still cannot
  load; the build fails if fewer than 100 rules remain. The sanitized pack passes upstream's own
  `ast-grep test` suite.
- **Bumping the pack**: `git ls-remote https://github.com/coderabbitai/ast-grep-essentials HEAD`, put
  the SHA in `ARG AST_GREP_ESSENTIALS_REF`, `make sandbox-image` (the build log prints
  `ast-grep-essentials: N rules (M util ids fixed, K dropped)`), then `make test-sandbox`.
- **At review time** the backend writes `/work/.hootpr-astgrep/{sgconfig.yml,rules/*.yml,utils/*.yml}`
  (the writable `/work` volume, outside the repo) and runs
  `ast-grep scan --config /work/.hootpr-astgrep/sgconfig.yml --json=stream <changed paths…>` from
  `/work/repo` with no network. Each output line is one JSON match (`file` repo-relative,
  `range.start.line` / `range.end.line` 0-based, `ruleId`, `severity`, `message`). Rules are YAML data;
  nothing from the repository is executed. Remote rule `packages` are not supported.

## Helper scripts (`hootpr_tools/` → `/opt/hootpr/tools`)

`build_graph.py` (tree-sitter code graph) and `run_tools.py` (relevant static tools → normalized findings)
speak the versioned JSON contract C1 in
[`docs/superpowers/plans/2026-09-29-phase-2-review-engine.md`](../docs/superpowers/plans/2026-09-29-phase-2-review-engine.md#c1-sandbox-scripts-produced-by-track-sandbox-consumed-by-backend).
Both use only the standard library (+ tree-sitter-language-pack for the graph), print one JSON document
and exit 0 even when individual files or tools fail.

## Tests

| Command | What runs |
|---|---|
| `make test-sandbox-unit` | `tests/unit`: the scripts (and the build-time rule sanitizer) on the host with fake tool binaries (no image) |
| `make test-sandbox` | builds the image, then `tests/image` (every tool as uid 10001 under the production flags, known findings in the polyglot fixture, graph build, ast-grep inline rules + the essentials pack (`test_ast_grep.py`), repo-config hijack ignored, read-only/sealed checks, size) and the backend's `-m sandbox` tests (a full review in a real sandbox, spec §13) |
| `make test-proxy` | the docker-proxy allowlist, including every call the worker makes for a sandbox |

`sandbox/tests/image` skips itself when Docker or the image is missing.
