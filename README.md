# HootPR

HootPR is an AI code-review platform for **GitHub.com** and **GitLab.com**. When a pull request (PR) or
merge request (MR) is opened or updated, HootPR clones the code into an isolated sandbox, runs static
analysis and security scanners, investigates the change with LLM agents, filters out false positives with
a judge model, and posts a **walkthrough** comment, **inline review comments** with suggested fixes, and a
**check / commit status**.

Developers talk to it in the PR thread (`@hootpr ...`), configure it with `.hootpr.yaml` or the dashboard,
and organizations pay with **credits**. Everything runs from one `docker compose up` on a small VM, and
any OpenAI-compatible LLM provider can be plugged in through `.env`.

> HootPR is a personal portfolio project. Payments run in Razorpay **test mode** only to demonstrate the billing integration — no real money is charged or accepted. Credits are deliberately limited because the AI costs are paid by the author.

HootPR includes sign-in, organizations, GitHub App installation, GitLab bot reviews, webhook ingestion,
credits, rate limits, test-mode billing, an OpenAI-compatible LLM gateway, sandboxed review analysis,
walkthroughs, inline comments, a trace viewer, an eval suite, PR-thread chat, team learnings and the full
`.hootpr.yaml` configuration schema. Design notes live in
[`docs/superpowers/specs/2026-09-28-hootpr-architecture-design.md`](docs/superpowers/specs/2026-09-28-hootpr-architecture-design.md).

---

## 1. Quick start

Prerequisites: **Docker** with **Compose v2** (≥ 2.24). For development also `uv` (Python 3.12), Node 22
and pnpm 10.

```bash
git clone https://github.com/YOUR-USER/hootpr.git && cd hootpr
make init          # creates .env from .env.example with generated SECRET_ENCRYPTION_KEY / SESSION_SECRET, and secrets/
make sandbox-image # builds the per-job analysis image (~3 GB, one-off; the worker never builds or pulls it)
make up            # builds and starts postgres, redis, docker-proxy, api, worker, web
```

Without `make sandbox-image` reviews fail (and are refunded) with "sandbox image missing — run
`make sandbox-image`". Rebuild it now and then to refresh the baked semgrep rules and trivy database.

- Dashboard: <http://localhost:3000> (`WEB_PORT`, `APP_BASE_URL`)
- API: <http://localhost:8000> (`API_PORT`, `API_BASE_URL`; the browser calls it at `API_PUBLIC_URL`)
- API health: `curl localhost:8000/api/health` → `{"status":"ok","checks":{"db":"ok","redis":"ok","docker_proxy":"ok"}}`
  (`docker_proxy` is the worker's heartbeat, refreshed every 30 s; it reads `unknown` until the worker
  has started. Only the worker can reach the Docker socket proxy.)
- The api runs one uvicorn process (`API_WORKERS=1`, ~110 MB) to fit its 192 MB memory limit; raise
  both together if you need more.

A clean clone boots **without any provider keys**; the sign-in buttons, billing and LLM calls start
working once you fill in the keys from sections 3–7.

**Ports already taken?** Postgres and Redis publish no host ports at all, so a local Postgres on 5432 is
fine. If 3000 or 8000 is in use, set other host ports in `.env` (and keep the public URLs in sync):

```dotenv
WEB_PORT=3300
API_PORT=8300
APP_BASE_URL=http://localhost:3300
API_BASE_URL=http://localhost:8300
API_PUBLIC_URL=http://localhost:8300
```

**Separate origins.** The dashboard (`web`, Next.js) and the API (`api`, FastAPI) are separate origins on
separate ports; nothing proxies one through the other. The browser calls the API directly at
`API_PUBLIC_URL`, which the web container reads **per request** (rendered into `window.__HOOTPR__`), so
changing it needs only a restart of `web`, never a rebuild. The API allows CORS with credentials from
exactly `APP_BASE_URL` (plus `CORS_EXTRA_ORIGINS`). Session/CSRF cookies are set by the API origin with
`COOKIE_SAMESITE` (`lax` default; `none` forces `Secure`) and optional `COOKIE_DOMAIN`; the dashboard gets
the CSRF token from `/api/auth/csrf` (or `/api/me`) and echoes it in `X-CSRF-Token`.

| Dev URL | Serves | Setting |
|---|---|---|
| `http://localhost:3000` | dashboard pages | `APP_BASE_URL`, `WEB_PORT` |
| `http://localhost:8000` | `/api/*` (incl. OAuth callbacks, GitHub setup, webhooks), `/schema/*` | `API_BASE_URL` = `API_PUBLIC_URL`, `API_PORT` |

`localhost:3000` and `localhost:8000` are the same *site* (ports don't matter for SameSite), so
`COOKIE_SAMESITE=lax` works there. In production, route an app domain to `web:3000` and an API domain to
`api:8000` with your own reverse proxy (e.g. `app.example.com` / `api.example.com`; HootPR ships no nginx
config) and set `APP_BASE_URL`, `API_BASE_URL`, `API_PUBLIC_URL` accordingly — two subdomains of one
registrable domain are same-site, so `lax` still works.

Both ports are published on all interfaces (Postgres, Redis and the Docker socket proxy stay internal);
firewall them or put your own reverse proxy in front. Other useful commands: `make logs`, `make ps`, `make down`,
`make migrate` (migrations also run automatically when `api` starts), `make help`.

**Without docker.** The root `.env` is the single config file for both modes: `WEB_PORT` / `API_PORT`
drive the compose ports *and* the local dev servers, and the backend reads the root `.env` even when run
from `backend/`. `make dev-api` runs uvicorn (`--reload`) on `0.0.0.0:$API_PORT`; `make dev-web` runs
`next dev` on `0.0.0.0:$WEB_PORT` with `API_PUBLIC_URL` from `.env` (default `http://localhost:$API_PORT`).
Postgres/Redis publish no host ports, so for `dev-api` point `DATABASE_URL` / `REDIS_URL` at instances the
host can reach.

## 2. Public URL in development (Cloudflare Tunnel)

GitHub, GitLab and Razorpay cannot reach `localhost`, and OAuth callbacks need a public URL. In
development HootPR runs two Cloudflare **quick tunnels** (no account, no token) — one for the dashboard,
one for the API:

```bash
make tunnel
```

It starts the stack plus two `cloudflared` processes (your installed one if present, logs/pids in
`.cloudflared-{web,api}.*`; otherwise the `tunnel`/`tunnel-web` containers), reads both
`https://<random>.trycloudflare.com` URLs, writes `APP_BASE_URL=<web>`, `API_BASE_URL=API_PUBLIC_URL=<api>`
and `COOKIE_SAMESITE=none` (two trycloudflare hosts are cross-site) into `.env`, recreates `api`, `worker`
and `web` without rebuilding, and prints the exact provider URLs to paste — all on the **API** URL:

| Where | URL |
|---|---|
| GitHub App webhook | `<api>/api/webhooks/github` |
| GitHub App callback | `<api>/api/auth/github/callback` |
| GitHub App setup URL | `<api>/api/github/setup` |
| GitHub App homepage | `<web>` |
| GitLab OAuth redirect | `<api>/api/auth/gitlab/callback` |
| Razorpay webhook | `<api>/api/webhooks/razorpay` |

GitLab project hooks use `{API_BASE_URL}/api/webhooks/gitlab` automatically; after a URL change press
**Sync** on the repos page (or wait for the hourly sync) to re-register them.

The URLs stay the same while the tunnels keep running (`make up` / rebuilds don't touch them).
`make tunnel-stop` stops both, and the next `make tunnel` gives new URLs, so update the provider URLs
above again. With an `https://` `API_BASE_URL` (or `COOKIE_SAMESITE=none`), cookies are `Secure`.
Browsers that block third-party cookies entirely (e.g. Safari) need same-site domains instead of two
trycloudflare hosts — use a named tunnel.

**Optional, stable URL:** if you have a domain on Cloudflare, create a named tunnel (Zero Trust →
Networks → Tunnels), route one public hostname to `http://web:3000` and another to `http://api:8000`, put
its token in `CLOUDFLARE_TUNNEL_TOKEN`, and set `APP_BASE_URL` (web hostname) and `API_BASE_URL` /
`API_PUBLIC_URL` (API hostname) yourself.

**Alternative: smee.io.** `make dev` starts the `smee` relay instead (set `SMEE_URL`,
`SMEE_GITLAB_URL` + `GITLAB_WEBHOOK_URL`, optionally `SMEE_RAZORPAY_URL`). smee only relays
webhooks; OAuth sign-in then stays on `localhost`.

## 3. Create the GitHub App

HootPR is a GitHub App (user sign-in uses the App's user authorization).

**Option A: from the manifest.** Edit [`deploy/github-app-manifest.json`](deploy/github-app-manifest.json):
set `hook_attributes.url` to `{API_BASE_URL}/api/webhooks/github` (your tunnel hostname), replace `http://localhost:3000` with your `APP_BASE_URL`
in `redirect_url` and `http://localhost:8000` with your `API_BASE_URL` in `callback_urls` and `setup_url`, and set `url`/`name` (App names are globally unique).
Then register it with GitHub's
[“Register a GitHub App from a manifest”](https://docs.github.com/en/apps/sharing-github-apps/registering-a-github-app-from-a-manifest)
flow for your account or organization. The manifest requests the repository and organization permissions
HootPR needs to review pull requests and post results.

**Option B: manually.** GitHub → Settings → Developer settings → GitHub Apps → **New GitHub App**:

| Field | Value |
|---|---|
| Homepage URL | `{APP_BASE_URL}` |
| Callback URL | `{API_BASE_URL}/api/auth/github/callback` |
| Expire user authorization tokens | **on** (HootPR asks the user to sign in again when the token expires) |
| Request user authorization (OAuth) during installation | off |
| Setup URL | `{API_BASE_URL}/api/github/setup`, with **Redirect on update** on |
| Webhook URL | `{API_BASE_URL}/api/webhooks/github` (the tunnel hostname in dev) |
| Webhook secret | a long random string |
| Repository permissions, read-only | Actions, Metadata, Discussions, Merge queues |
| Repository permissions, read & write | Checks, Contents, Commit statuses, Issues, Pull requests, Workflows |
| Organization permissions, read-only | Members |
| Events | Pull request, Pull request review, Pull request review comment, Pull request review thread, Issue comment, Issues, Check run, Push, Workflow run |

(`installation` and `installation_repositories` events are always delivered to GitHub Apps.)

**Then, for either option:**

1. On the App page → **Generate a private key** and save it as `secrets/github_app.pem`, readable by the containers (`chmod 644 secrets/github_app.pem`; mounted read-only
   at `/run/secrets/github_app.pem`; alternatively paste it inline into `GITHUB_APP_PRIVATE_KEY` with `\n` escapes).
2. Generate a **client secret**.
3. Fill in `.env`:
   ```dotenv
   GITHUB_APP_ID=123456
   GITHUB_APP_SLUG=your-app-slug          # from https://github.com/apps/<slug>
   GITHUB_OAUTH_CLIENT_ID=Iv23...          # the App's Client ID
   GITHUB_OAUTH_CLIENT_SECRET=...
   GITHUB_WEBHOOK_SECRET=...
   ```
4. `make up` again, sign in, pick your account/org and click **Install on GitHub**.

## 4. Create the GitLab OAuth application (sign-in)

GitLab.com → avatar → **Edit profile** → **Applications** → **Add new application**:

- Redirect URI: `{API_BASE_URL}/api/auth/gitlab/callback`
- Confidential: **yes**
- Scopes: `read_user`, `read_api`

Copy the Application ID and Secret into `GITLAB_OAUTH_CLIENT_ID` / `GITLAB_OAUTH_CLIENT_SECRET`.
Self-managed GitLab: also set `GITLAB_BASE_URL`.

## 5. GitLab bot user (reviews on GitLab)

HootPR comments on GitLab as a separate bot account:

1. Create a separate GitLab.com account (e.g. `yourname-hootpr`).
2. Add it as **Developer** (or higher) to the group or projects to review.
3. As the bot, create a **personal access token** with scopes `api`, `read_api`, `read_user` (a group access
   token with Developer role also works).
4. In the HootPR dashboard, open your GitLab org → **Settings → GitLab bot**, paste the token (it is
   validated and stored **encrypted in the database**, never in `.env`), then select the projects. HootPR
   installs a project webhook on each one (pointing at `GITLAB_WEBHOOK_URL`) with its own random secret.

## 6. Razorpay test keys (credits)

1. Create a Razorpay account and switch the dashboard to **Test mode**.
2. Settings → **API Keys** → generate a **test** key pair and set:
   ```dotenv
   RAZORPAY_KEY_ID=rzp_test_...
   RAZORPAY_KEY_SECRET=...
   ```
   Live keys (`rzp_live_…`) are rejected: the API refuses to start. Until `RAZORPAY_KEY_SECRET` is set,
   billing endpoints answer `503 billing_not_configured`.
3. Optional webhook (credits a purchase even if the browser tab is closed): Settings → **Webhooks** →
   URL = `{API_BASE_URL}/api/webhooks/razorpay` (the tunnel hostname in dev), events
   `payment.captured` and `order.paid`, secret → `RAZORPAY_WEBHOOK_SECRET`.
4. Test payment details: card `4100 2800 0000 1007` (Indian Visa; Mastercard `5500 6700 0000 1002`), any future expiry, any CVV; UPI `success@razorpay`.

Defaults: 300 free credits per org, packs of 500 credits for ₹49 (test), at most 2 purchases per org
and a balance cap of 1,000 (all configurable in `.env`). Jobs are metered by AI usage in whole
credits: a review typically costs about 100 credits, a chat reply about 50
(see `docs/token-metered-billing.md`).

## 7. LLM providers

Each role (`review`, `cheap`, `embed`) has its own OpenAI-compatible endpoint, key, model and prices:

```dotenv
LLM_CHEAP_BASE_URL=https://api.openai.com/v1   # any OpenAI-compatible base URL (OpenRouter, Groq, vLLM, Ollama, ...)
LLM_CHEAP_API_KEY=sk-...
LLM_CHEAP_MODEL=gpt-5-nano
```

`make llm-smoke ROLE=cheap` (or `review` / `embed`) sends one metered request through the gateway and
prints the tokens and cost. Request/response excerpts are logged up to 8 KB (`LLM_LOG_FULL=true` logs
everything).

## 8. Review engine

Every review runs the stages of spec §7 as a **LangGraph `StateGraph`** (`review_graph` in
`backend/app/review/engine.py`); finishing touches self-correct through LangGraph test ↔ agent repair
loops. Diagrams and design notes: [docs/agent-orchestration.md](docs/agent-orchestration.md). Each stage
is recorded in the review's trace:

1. **Config**: `.hootpr.yaml` from the PR's base branch merged with the dashboard settings.
2. **Diff & filter**: lockfiles, generated/vendored/binary files and `path_filters` are dropped; a PR with
   nothing left is skipped and refunded; oversized PRs are trimmed to the size budget.
3. **Sandbox**: a fresh hardened container (768 MB, 1 CPU, read-only, non-root, no capabilities) clones
   the head commit over the egress network, then is **sealed** (network disconnected) before analysis
   and always destroyed afterwards.
4. **Code graph**: tree-sitter symbols, calls, imports and inheritance for the changed files and their
   neighbours (`sandbox/hootpr_tools/build_graph.py`).
5. **Static tools**: only the tools relevant to the changed files (semgrep, gitleaks, trivy, checkov, ruff,
   eslint, shellcheck, hadolint, actionlint, yamllint, markdownlint, golangci-lint, rubocop, phpstan,
   swiftlint) with HootPR-owned configs. Their findings are evidence for the agents, never posted raw.
6. **Context pack**: diff, graph neighbourhood, tool findings, PR description and learnings, all wrapped
   as untrusted input.
7. **Triage** (`cheap` model), **plan** (`review` model): which files need a deep look, grouped into tasks.
8. **Agents** (`review` model): tool-using investigators (`read_file`, `find_*`, `shell` in the sealed
   sandbox) with a step budget; each reports candidate findings.
9. **Judge** (`review` model): deterministic checks (anchored in the diff, not duplicated) then an LLM
   verdict with a confidence threshold per profile (`chill` / `assertive`).
10. **Summarize** (`cheap` model) and **post**: one review with inline comments (suggested fixes, "Prompt
    for AI Agents"), the walkthrough comment, the PR description summary and the check / commit status.
    Incremental reviews only look at commits since the last reviewed SHA.

**Trace tab.** The dashboard's review page has a **Findings** tab (posted, moved to the walkthrough, or
dropped by the judge with the reason) and a **Trace** tab: the stage timeline, tasks and agent steps,
every LLM call with tokens, cost and request/response excerpts, every static-tool run, and the judge's
verdicts.

**Evals.** `make eval` runs the engine in-process over the hand-made cases in `evals/datasets` (Python,
TypeScript, Go, including clean PRs; nothing is posted anywhere) and reports precision, recall, comment
count and cost:

```bash
make eval EVAL_ARGS="--fake-llm"                             # no keys: oracle fake LLM, pipeline check
make eval MODEL_REVIEW=gpt-5 MODEL_CHEAP=gpt-5-nano          # real models from .env (override per run)
make eval EVAL_ARGS="--cases py-sql-injection --sandbox docker"
```

Reports go to `evals/reports/` (Markdown committed, JSON gitignored); the latest results table is in
[`evals/README.md`](evals/README.md).

**Resources.** One sandbox at a time (768 MB, swap disabled) next to the 256 MB worker keeps a review
inside the t3.small budget (spec §11.3). Code graphs and tool results are cached per commit for 7 days.
Engine limits (files/lines per review, tasks, comments, agent steps and tokens, sandbox memory/CPU,
timeouts, judge thresholds, cache TTL) are settings documented in [`.env.example`](.env.example).

## 9. Chat & config

**Commands.** Mention the bot (`@<GITHUB_APP_SLUG>` on GitHub, the GitLab bot user on GitLab; written
`@hootpr` below) in a PR/MR comment. The text after the mention must be exactly one of these phrases,
otherwise it is a free-form question:

| Command | Effect | Cost |
|---|---|---|
| `@hootpr review` / `@hootpr full review` | incremental review since the last reviewed commit / full review from the base | metered (~100 credits) |
| `@hootpr pause` / `@hootpr resume` | stop / restart automatic reviews on this PR | free |
| `@hootpr resolve` | resolve every open HootPR review thread (top-level comment only) | free |
| `@hootpr approve` | resolve, then approve when `reviews.request_changes_workflow` is on (top-level comment only) | free |
| `@hootpr summary` | regenerate the "Summary by HootPR" description block (fills `high_level_summary_placeholder` / `auto_title_placeholder`) | metered (~50 credits) |
| `@hootpr generate sequence diagram` | Mermaid sequence diagram of the change | metered (~50 credits) |
| `@hootpr configuration` (`config`) | effective configuration as YAML, each value annotated with where it came from | free |
| `@hootpr rate limit` (`limits`, `quota`) | remaining reviews/chat replies this hour and credit balance | free |
| `@hootpr help` | this table | free |
| `@hootpr ignore` (PR description only) | never review this PR | free |
| anything else | the chat agent answers (can read files and run read-only commands in a sealed sandbox) | metered (~50 credits) |

Replies inside a HootPR review thread need no mention (`chat.auto_reply`, default on). Chat replies have
their own hourly rate limit.

**Learnings.** Tell HootPR a preference in a thread ("we use `print()` for CLI output here, don't flag it")
and the chat agent stores it as a *learning* (credential-redacted, embedded with `LLM_EMBED_MODEL`,
optionally limited to a path glob). The next reviews retrieve the most relevant learnings (top-k by
similarity, `LEARNINGS_TOP_K`) and list them under "Learnings used" in the walkthrough. Learnings never
override security rules. View, edit and delete them on the dashboard at `/o/<org>/learnings`; opting out
(`knowledge_base.opt_out`) deletes them. Code guideline files (`CLAUDE.md`, `AGENTS.md`,
`.cursor/rules/`, `.github/copilot-instructions.md`, ...) are detected automatically, read from the base
branch only.

**`.hootpr.yaml`.** Configuration is merged as defaults ← organization settings ← repository settings ←
`.hootpr.yaml` from the PR's **base** branch (a PR cannot change how it is reviewed; an invalid or changed
head file gets a note with line numbers in the walkthrough). It covers profile/tone/language, path
filters, `path_instructions`, `ast_grep_instructions` + ast-grep rule directories and the
ast-grep-essentials pack (see [`sandbox/README.md`](sandbox/README.md)), per-tool
switches, `request_changes_workflow` (blocking comments request changes; resolving them all approves),
chat and knowledge-base options. The JSON schema is served at `<API_BASE_URL>/schema/hootpr.v1.json`
(committed as `backend/hootpr.v1.schema.json`, regenerated by `make api-types`); add this first line for
editor autocomplete and validation:

```yaml
# yaml-language-server: $schema=http://localhost:8000/schema/hootpr.v1.json
reviews:
  profile: assertive
  path_instructions:
    - path: "src/api/**"
      instructions: "Every handler must validate its input."
```

The dashboard's repository and organization settings pages are forms generated from the same schema.

## 10. Development

| Command | What it does |
|---|---|
| `make test` | backend (`pytest`), sandbox scripts, eval suite and frontend (`vitest`) tests |
| `make test-backend` / `make test-web` | one side only |
| `make test-e2e` | Playwright critical flows |
| `make lint` / `make typecheck` | ruff + eslint / mypy strict + tsc |
| `make api-types` | export the backend OpenAPI schema + `.hootpr.yaml` JSON schema and regenerate frontend types |
| `make sandbox-image` | build the per-job sandbox image and the `hootpr_sandbox_egress` network |
| `make test-sandbox-unit` | sandbox helper scripts on the host (no image needed) |
| `make test-sandbox` | build the image, run every tool in it and a full review in a real sandbox |
| `make test-evals` | eval-suite unit tests + a full fake-LLM eval run |
| `make test-proxy` | verify the Docker socket proxy allowlist, including every call the worker makes for a sandbox |
| `make eval` | review-quality eval suite (`MODEL_REVIEW=... MODEL_CHEAP=... EVAL_ARGS=...`) |

Backend integration tests start their own Postgres (pgvector) and Redis with **testcontainers** on random
ports (Docker required). To reuse long-lived test services instead, run `make test-services` (the compose
`test` profile, random `127.0.0.1` ports; see them with `docker compose port postgres-test 5432`) and
export the printed `TEST_DATABASE_URL` / `TEST_REDIS_URL`; `make test-services-down` removes them.

Secrets live **only** in `.env` and `secrets/` (both gitignored). `.env.example` documents every setting.

## 11. Architecture

See the [architecture spec](docs/superpowers/specs/2026-09-28-hootpr-architecture-design.md). Services
(memory limits sized for a 2 GB t3.small, spec §11.3):

- `postgres` (pgvector, 256 MB) · `redis` (64 MB, `noeviction`) — no host ports
- `api` FastAPI (192 MB, 2 uvicorn workers) — OAuth, dashboard API, webhooks, billing
- `worker` Celery with embedded beat (384 MB, concurrency 1) — review pipeline
- `web` Next.js dashboard (192 MB) — separate origin; the browser calls `api` directly at `API_PUBLIC_URL`
- `docker-proxy` socket proxy (32 MB) — only containers/networks/exec, on an internal network
- `sandbox` per-job analysis image (768 MB per job; built by `make sandbox-image`, never run by compose)
- `tunnel` / `tunnel-web` (tunnel profile, dev only) — Cloudflare quick tunnels for the API and the dashboard
- `smee` (dev profile only) — alternative webhook relay

## 12. Deploy (production)

Production is the same compose stack plus [`docker-compose.prod.yml`](docker-compose.prod.yml), built on
the server from this checkout. It forces `APP_ENV=production` (the API refuses to start with empty
secrets), disables dev relays, and adds a nightly `backup` service. Every service has
`restart: unless-stopped` and a memory limit. The dashboard (`web`, `WEB_PORT`) and the API (`api`,
`API_PORT`) are published on their own ports; put your own reverse proxy / TLS in front, e.g.
`app.example.com → :WEB_PORT` and `api.example.com → :API_PORT`. Postgres, Redis and the Docker proxy are
never published.

### 12.1 First install

```bash
git clone https://github.com/<owner>/<repo>.git hootpr && cd hootpr
make init                                   # .env with generated SECRET_ENCRYPTION_KEY / SESSION_SECRET
# copy secrets/github_app.pem here, then:
chmod 644 secrets/github_app.pem            # the containers run as a non-root user
nano .env                                   # values below
make prod-up                                # builds the sandbox image (first time, ~3 GB) + all images, starts everything
```

### 12.2 `.env` (production values)

```dotenv
APP_BASE_URL=https://app.example.com
API_BASE_URL=https://api.example.com
API_PUBLIC_URL=https://api.example.com
COOKIE_SAMESITE=lax                          # app./api. subdomains of one domain are same-site
WEB_PORT=3000
API_PORT=8000
POSTGRES_PASSWORD=<long random>              # before the FIRST start: it initializes the database
# GitHub App / GitLab OAuth / Razorpay (test) / LLM keys — same as in sections 3–7
```

Secrets live only in `.env` / `secrets/`, never in git.

### 12.3 Provider URLs

| Where | Setting | Value |
|---|---|---|
| GitHub App | Homepage URL | `https://app.example.com` |
| GitHub App | Callback URL | `https://api.example.com/api/auth/github/callback` |
| GitHub App | Setup URL (Redirect on update) | `https://api.example.com/api/github/setup` |
| GitHub App | Webhook URL (active, same secret) | `https://api.example.com/api/webhooks/github` |
| GitLab OAuth app | Redirect URI | `https://api.example.com/api/auth/gitlab/callback` |
| GitLab project hooks | (automatic) | `https://api.example.com/api/webhooks/gitlab` — press **Sync** on the repos page after a URL change |
| Razorpay (test mode) | Webhook URL (`payment.captured`) | `https://api.example.com/api/webhooks/razorpay` |

### 12.4 Operate

```bash
make deploy        # git pull, rebuild the sandbox image if sandbox/ changed, rebuild + restart, prune old images
make prod-ps       # status (api healthcheck = /api/health: DB, Redis, docker-proxy)
make prod-logs     # follow logs
make prod-down     # stop (volumes kept)
make sandbox-image # rebuild the sandbox image (also refreshes semgrep/trivy/gitleaks rule data)
```

Migrations run automatically when `api` starts (`alembic upgrade head`).

### 12.5 Backups

The `backup` service runs `pg_dump -Fc` every night at `BACKUP_HOUR_UTC` (default 03:00) into the
`hootpr_backups` Docker volume and deletes dumps older than `BACKUP_KEEP_DAYS` (7).

```bash
make backup                                      # dump now
make restore                                     # list dumps
make restore FILE=hootpr-20261001T030000Z.dump   # restore (safety dump first; stops api/worker meanwhile)
```
