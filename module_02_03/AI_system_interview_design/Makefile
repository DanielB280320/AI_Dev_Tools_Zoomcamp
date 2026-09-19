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

SHELL := bash
.DEFAULT_GOAL := help

BACKEND := backend
FRONTEND := frontend
API_PORT ?= 8000
API_URL := http://localhost:$(API_PORT)
# `dev` prints the credentials banner once, then suppresses it in the sub-makes.
CREDS ?= 1

.PHONY: help install install-api install-web api web dev test smoke lint format creds docs health db-reset clean

help: ## List the available targets
	@grep -hE '^[a-z][a-z-]*:.*## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN { FS = ":.*## " } { printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2 }'

install: install-api install-web ## Install both sides' dependencies

install-api: ## Install backend dependencies (uv)
	cd $(BACKEND) && uv sync

install-web: ## Install frontend dependencies (npm)
	cd $(FRONTEND) && npm install

api: ## Run the API with reload (API_PORT=8000)
	@[ "$(CREDS)" = "0" ] || $(MAKE) --no-print-directory creds
	cd $(BACKEND) && uv run uvicorn app.main:app --reload --port $(API_PORT)

web: ## Run the frontend dev server
	@[ "$(CREDS)" = "0" ] || $(MAKE) --no-print-directory creds
	cd $(FRONTEND) && npm run dev

dev: ## Run the API and the frontend together; Ctrl-C stops both
	@$(MAKE) --no-print-directory creds
	@trap 'kill 0' EXIT INT TERM; \
		$(MAKE) --no-print-directory api CREDS=0 & \
		$(MAKE) --no-print-directory web CREDS=0 & \
		wait

test: ## Run the backend tests (ARGS='-k canvas -vv' to narrow)
	cd $(BACKEND) && uv run pytest $(ARGS)

smoke: ## Drive the frontend's API client against a running backend
	node $(FRONTEND)/scripts/smoke-api.mjs

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

clean: ## Delete Python caches and test artefacts
	find $(BACKEND) -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf $(BACKEND)/.pytest_cache $(BACKEND)/.ruff_cache
