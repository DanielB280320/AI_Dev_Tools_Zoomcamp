# Loopboard task runner. Run `make` on its own for the list of targets.
#
# Ports: the API serves on $(API_PORT) (docs at /docs), the frontend's
# `vite dev` on 8080, which the API's default CORS list allows.
#
# Sign in with the seeded demo account: alex@loopboard.dev / loopboard-demo
# (candidates need no account — they join with a link and a display name).
#
# Data lives in backend/loopboard.db (SQLite) unless LOOPBOARD_DATABASE_URL says
# otherwise; `make db-reset` wipes it and the next start re-seeds the demo data.
#
# For Postgres instead: `make db-up` starts a local container, `make api-pg` and
# `make test-pg` point the API and the suite at it, and `make db-down` stops it.
#
# `make up` runs the whole app in Docker (docker-compose.yaml), and `make e2e`
# runs the Playwright suite in e2e/ against it.

SHELL := bash
.DEFAULT_GOAL := help

BACKEND := backend
FRONTEND := frontend
API_PORT ?= 8000
API_URL := http://localhost:$(API_PORT)

# The local Postgres container, and the URL that reaches it. Override any of
# these to point somewhere else; PG_URL on its own is enough for `api-pg` and
# `test-pg` when the server is not one this Makefile started.
PG_CONTAINER ?= interview-canvas-db
PG_IMAGE ?= postgres:16-alpine
PG_VOLUME ?= interview-canvas-pgdata
PG_USER ?= sdip
PG_PASSWORD ?= sdip
PG_DB ?= sdip
PG_PORT ?= 5432
PG_URL ?= postgresql://$(PG_USER):$(PG_PASSWORD)@localhost:$(PG_PORT)/$(PG_DB)

# The end-to-end suite and the compose stack it drives.
E2E := e2e
COMPOSE := docker compose -f docker-compose.yaml
COMPOSE_E2E := $(COMPOSE) -f docker-compose.e2e.yaml
# `dev` prints the credentials banner once, then suppresses it in the sub-makes.
CREDS ?= 1

.PHONY: help install install-api install-web api web dev test smoke lint format creds docs health db-reset clean \
	db-up db-down db-psql db-wait api-pg test-pg db-reset-pg \
	up down logs e2e e2e-local install-e2e

help: ## List the available targets
	@grep -hE '^[a-z][a-z0-9-]*:.*## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN { FS = ":.*## " } { printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2 }'

install: install-api install-web ## Install both sides' dependencies

install-api: ## Install backend dependencies (uv)
	cd $(BACKEND) && uv sync

install-web: ## Install frontend dependencies (npm)
	cd $(FRONTEND) && npm install

api: ## Run the API with reload (API_PORT=8000)
	@[ "$(CREDS)" = "0" ] || $(MAKE) --no-print-directory creds
	cd $(BACKEND) && uv run uvicorn app.main:app --reload --port $(API_PORT)

api-pg: db-wait ## Run the API against Postgres instead of the SQLite file
	@[ "$(CREDS)" = "0" ] || $(MAKE) --no-print-directory creds
	@echo "  database  $(PG_URL)"
	@echo
	cd $(BACKEND) && LOOPBOARD_DATABASE_URL=$(PG_URL) \
		uv run uvicorn app.main:app --reload --port $(API_PORT)

web: ## Run the frontend dev server
	@[ "$(CREDS)" = "0" ] || $(MAKE) --no-print-directory creds
	cd $(FRONTEND) && npm run dev

dev: ## Run the API and the frontend together; Ctrl-C stops both
	@$(MAKE) --no-print-directory creds
	@trap 'kill 0' EXIT INT TERM; \
		$(MAKE) --no-print-directory api CREDS=0 & \
		$(MAKE) --no-print-directory web CREDS=0 & \
		wait

test: ## Run the backend tests on SQLite (ARGS='-k canvas -vv' to narrow)
	cd $(BACKEND) && uv run pytest $(ARGS)

test-pg: db-wait ## Run the same tests against Postgres (empties PG_DB first)
	cd $(BACKEND) && LOOPBOARD_TEST_DATABASE_URL=$(PG_URL) uv run pytest $(ARGS)

smoke: ## Drive the frontend's API client against a running backend
	node $(FRONTEND)/scripts/smoke-api.mjs

# --------------------------- compose + end to end ----------------------------

up: ## Start the whole app in Docker (Postgres + the app image) on :8000
	$(COMPOSE) up --build -d --wait

down: ## Stop the compose stack (the database volume survives)
	$(COMPOSE) down

logs: ## Follow the app container's logs
	$(COMPOSE) logs -f app

install-e2e: ## Install the end-to-end suite's dependencies (npm)
	cd $(E2E) && npm install

# The container runs the suite from the mounted e2e/node_modules, so it has to
# exist first; this installs it once, and again when the lockfile changes.
$(E2E)/node_modules: $(E2E)/package-lock.json
	cd $(E2E) && npm ci
	@touch $@

e2e: $(E2E)/node_modules ## Run the Playwright suite against the compose stack, in a container
	$(COMPOSE_E2E) run --rm e2e npx playwright test $(ARGS)

e2e-local: $(E2E)/node_modules ## Run the same suite from the host (needs Chromium's system libs)
	cd $(E2E) && npx playwright test $(ARGS)

lint: ## Lint both sides
	cd $(BACKEND) && uvx ruff check app tests
	cd $(FRONTEND) && npm run lint

format: ## Autoformat both sides
	cd $(BACKEND) && uvx ruff format app tests
	cd $(FRONTEND) && npm run format

docs: ## Open the interactive API docs (needs a running API)
	@command -v xdg-open >/dev/null && xdg-open $(API_URL)/docs || echo "$(API_URL)/docs"

creds: ## Print the seeded sign-in credentials
	@echo "  frontend  http://localhost:8080   (opens on /signin)"
	@echo "  api       $(API_URL)   (docs at $(API_URL)/docs)"
	@echo "  sign in   alex@loopboard.dev / loopboard-demo   (also sam@loopboard.dev)"
	@echo "  joining   candidates need no account — just a link and a display name"
	@echo

health: ## Check that the API is up, and how many sessions it holds
	@curl -fsS $(API_URL)/health && echo

db-reset: ## Delete the default SQLite database, so the next start re-seeds
	rm -f $(BACKEND)/loopboard.db $(BACKEND)/loopboard.db-shm $(BACKEND)/loopboard.db-wal

# ------------------------------- Postgres ------------------------------------
# The container these wrap is the one from the README; `db-up` is idempotent,
# so it starts it, resumes it, or says it is already up.

db-up: ## Start the local Postgres container (keeps its volume between runs)
	@if [ -n "$$(docker ps -q -f name='^$(PG_CONTAINER)$$')" ]; then \
		echo "$(PG_CONTAINER) already running on :$(PG_PORT)"; \
	elif [ -n "$$(docker ps -aq -f name='^$(PG_CONTAINER)$$')" ]; then \
		docker start $(PG_CONTAINER); \
	else \
		docker run -d \
			--name $(PG_CONTAINER) \
			-e POSTGRES_USER=$(PG_USER) \
			-e POSTGRES_PASSWORD=$(PG_PASSWORD) \
			-e POSTGRES_DB=$(PG_DB) \
			-p $(PG_PORT):5432 \
			-v $(PG_VOLUME):/var/lib/postgresql/data \
			$(PG_IMAGE); \
	fi
	@$(MAKE) --no-print-directory db-wait

db-wait: ## Block until Postgres is accepting connections
	@for i in $$(seq 1 30); do \
		docker exec $(PG_CONTAINER) pg_isready -U $(PG_USER) -d $(PG_DB) -q && exit 0; \
		sleep 1; \
	done; \
	echo "$(PG_CONTAINER) is not accepting connections — run 'make db-up'" >&2; exit 1

db-down: ## Stop the Postgres container; its data survives in the volume
	-docker stop $(PG_CONTAINER)

db-psql: db-wait ## Open a psql shell on the Postgres database
	docker exec -it $(PG_CONTAINER) psql -U $(PG_USER) -d $(PG_DB)

db-reset-pg: db-wait ## Drop every table in Postgres, so the next start re-seeds
	docker exec $(PG_CONTAINER) psql -U $(PG_USER) -d $(PG_DB) -q \
		-c 'DROP SCHEMA public CASCADE; CREATE SCHEMA public;'
	@echo "Postgres emptied — the next 'make api-pg' re-creates and re-seeds it"

clean: ## Delete Python caches and test artefacts
	find $(BACKEND) -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf $(BACKEND)/.pytest_cache $(BACKEND)/.ruff_cache
	rm -rf $(E2E)/test-results $(E2E)/playwright-report $(E2E)/blob-report
