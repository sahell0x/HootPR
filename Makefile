# HootPR developer commands. Recipes use relative paths: the repo path may contain spaces.
SHELL := /bin/bash
COMPOSE := docker compose
ROLE ?= cheap
# Values from the ROOT .env (single source of truth for ports, docker and non-docker runs).
envget = $(shell grep -E '^$(1)=' .env 2>/dev/null | tail -1 | cut -d= -f2-)
WEB_PORT := $(or $(call envget,WEB_PORT),3000)
API_PORT := $(or $(call envget,API_PORT),8000)
API_PUBLIC_URL := $(or $(call envget,API_PUBLIC_URL),http://localhost:$(API_PORT))

.PHONY: help init up dev dev-api dev-web down logs ps migrate test test-backend test-web test-e2e lint typecheck \
        sandbox-image test-sandbox-unit test-sandbox test-evals llm-smoke api-types eval test-proxy \
        test-services test-services-down

help: ## list targets
	@grep -E '^[a-z-]+:.*##' Makefile | sed 's/:.*##/ —/'

init: ## create .env with generated secrets and the secrets/ folder
	@mkdir -p secrets
	@if [ ! -f .env ]; then \
	  cp .env.example .env; \
	  key=$$(python3 -c "import base64,os;print(base64.urlsafe_b64encode(os.urandom(32)).decode())"); \
	  sess=$$(python3 -c "import secrets;print(secrets.token_urlsafe(48))"); \
	  sed -i "s|^SECRET_ENCRYPTION_KEY=.*|SECRET_ENCRYPTION_KEY=$$key|; s|^SESSION_SECRET=.*|SESSION_SECRET=$$sess|" .env; \
	  chmod 600 .env; \
	  echo "created .env (fill in provider keys; see README)"; \
	else echo ".env exists; leaving it alone"; fi

up: ## build and start the stack
	$(COMPOSE) up -d --build

dev: ## start with the smee webhook relay (foreground)
	$(COMPOSE) --profile dev up --build

dev-api: ## run the API outside docker on 0.0.0.0:API_PORT with --reload (Settings read the root .env)
	cd backend && uv run uvicorn --factory app.main:create_app --reload --host 0.0.0.0 --port $(API_PORT)

dev-web: ## run the dashboard outside docker (next dev) on 0.0.0.0:WEB_PORT, calling API_PUBLIC_URL
	cd frontend && API_PUBLIC_URL="$(API_PUBLIC_URL)" pnpm dev -p $(WEB_PORT) -H 0.0.0.0

tunnel: ## start the stack + two Cloudflare quick tunnels (web + api; host cloudflared if installed); writes the URLs into .env
	./deploy/tunnel.sh

tunnel-stop: ## stop the quick tunnels (next `make tunnel` gets new URLs)
	@for f in .cloudflared-web.pid .cloudflared-api.pid .cloudflared.pid; do \
	  if [ -f $$f ]; then kill $$(cat $$f) 2>/dev/null || true; rm -f $$f; echo "stopped $$f"; fi; done
	-$(COMPOSE) --profile tunnel --profile tunnel-named stop tunnel tunnel-web tunnel-named

down: ## stop the stack
	$(COMPOSE) --profile dev --profile tunnel --profile tunnel-named down

logs: ## follow logs
	$(COMPOSE) logs -f --tail=200

ps: ## list running services
	$(COMPOSE) ps

migrate: ## apply database migrations
	$(COMPOSE) run --rm api alembic upgrade head

test: test-backend test-sandbox-unit test-evals test-web ## all unit + integration tests (no sandbox image needed)

test-backend: ## backend tests (testcontainers; Docker required)
	cd backend && uv run pytest -q

test-web: ## frontend unit tests
	cd frontend && pnpm test

test-e2e: ## Playwright critical flows
	cd frontend && pnpm test:e2e

test-services: ## start throwaway Postgres/Redis (test profile) and print TEST_* exports
	@$(COMPOSE) --profile test up -d --wait postgres-test redis-test >/dev/null 2>&1
	@echo "export TEST_DATABASE_URL=postgresql+psycopg://hootpr:hootpr@$$($(COMPOSE) port postgres-test 5432)/hootpr_test"
	@echo "export TEST_REDIS_URL=redis://$$($(COMPOSE) port redis-test 6379)/0"

test-services-down: ## remove the test profile containers
	$(COMPOSE) --profile test rm -sfv postgres-test redis-test

lint: ## ruff + eslint
	cd backend && uv run ruff check . && uv run ruff format --check .
	cd sandbox && uv run --project ../backend ruff check . && uv run --project ../backend ruff format --check .
	cd frontend && pnpm lint

typecheck: ## mypy strict + tsc
	cd backend && uv run mypy app
	cd frontend && pnpm typecheck

sandbox-image: ## build the per-job sandbox image (~3 GB, baked rule DBs) and its egress network
	docker build -t $${SANDBOX_IMAGE:-hootpr/sandbox:latest} sandbox
	docker network inspect hootpr_sandbox_egress >/dev/null 2>&1 || docker network create hootpr_sandbox_egress

test-sandbox-unit: ## sandbox helper scripts on the host (no image)
	uv run --project backend --with 'tree-sitter-language-pack>=0.9' pytest -q sandbox/tests/unit

test-sandbox: sandbox-image ## scripts + tools in the real image, then a full review in a real sandbox (spec §13)
	uv run --project backend pytest -q sandbox/tests/image
	cd backend && HOOTPR_SANDBOX_TESTS=1 uv run pytest -q -m sandbox -s

test-evals: ## eval-suite unit tests + a full fake-LLM eval run
	cd evals && uv run --project ../backend pytest -q

llm-smoke: ## one metered LLM call through the gateway (ROLE=review|cheap|embed)
	$(COMPOSE) run --rm api python -m app.llm.smoke --role $(ROLE)

api-types: ## regenerate frontend types from the backend OpenAPI schema + the .hootpr.yaml JSON schema
	cd backend && uv run python -m app.scripts.export_openapi openapi.json
	cd backend && uv run python -m app.scripts.export_config_schema hootpr.v1.schema.json
	cd frontend && pnpm gen:api

eval: ## review-quality eval suite (spec §14): MODEL_REVIEW=... MODEL_CHEAP=... EVAL_ARGS="--cases py-sql-injection"
	cd evals && $(if $(MODEL_REVIEW),LLM_REVIEW_MODEL=$(MODEL_REVIEW)) $(if $(MODEL_CHEAP),LLM_CHEAP_MODEL=$(MODEL_CHEAP)) \
	  uv run --project ../backend python run.py $(EVAL_ARGS)

test-proxy: ## verify the docker socket proxy allowlist
	bash deploy/tests/test_docker_proxy.sh

# ---------------- production (run on the server; see README → Deploy) ----------------
PROD := docker compose -f docker-compose.yml -f docker-compose.prod.yml

.PHONY: prod-up deploy prod-down prod-logs prod-ps backup restore

prod-up: ## (server) build and start the production stack (web on WEB_PORT, api on API_PORT)
	@docker network inspect hootpr_sandbox_egress >/dev/null 2>&1 || docker network create hootpr_sandbox_egress
	@docker image inspect $${SANDBOX_IMAGE:-hootpr/sandbox:latest} >/dev/null 2>&1 || $(MAKE) --no-print-directory sandbox-image
	$(PROD) up -d --build --remove-orphans

deploy: ## (server) git pull, rebuild the sandbox image if sandbox/ changed, rebuild + restart, prune old images
	@old=$$(git rev-parse HEAD); git pull --ff-only; \
	if ! git diff --quiet $$old HEAD -- sandbox; then $(MAKE) --no-print-directory sandbox-image; fi
	@$(MAKE) --no-print-directory prod-up
	docker image prune -f

prod-down: ## (server) stop the production stack (volumes are kept)
	$(PROD) down

prod-logs: ## (server) follow production logs
	$(PROD) logs -f --tail=200

prod-ps: ## (server) list production services
	$(PROD) ps

backup: ## (server) take a pg_dump now into the `backups` volume (nightly runs automatically)
	$(PROD) exec -T backup sh /backup/backup.sh once

restore: ## (server) restore a dump: make restore FILE=hootpr-<ts>.dump (no FILE = list dumps)
	bash deploy/restore.sh $(FILE)
