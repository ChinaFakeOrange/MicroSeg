# MicroSeg — common tasks. Run `make help` for the list.
.DEFAULT_GOAL := help
COMPOSE := docker compose

.PHONY: help
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

# --------------------------------------------------------------------- local
.PHONY: install
install: ## Install backend + frontend deps locally
	cd backend && pip install -r requirements.txt && pip install -e ".[dev]"
	cd frontend && npm install

.PHONY: api
api: ## Run the API locally (needs a local redis)
	cd backend && uvicorn app.main:app --reload --port 8000

.PHONY: worker
worker: ## Run a Celery worker locally
	cd backend && celery -A app.workers.celery_app.celery_app worker --loglevel=info

.PHONY: web
web: ## Run the Vite dev server
	cd frontend && npm run dev

.PHONY: test
test: ## Run the backend test suite
	cd backend && python -m pytest -q

.PHONY: lint
lint: ## Lint the backend with ruff
	cd backend && ruff check app tests

# -------------------------------------------------------------------- docker
.PHONY: up
up: ## Build and start the CPU stack
	$(COMPOSE) up -d --build

.PHONY: up-gpu
up-gpu: ## Build and start with the GPU worker overlay
	$(COMPOSE) -f docker-compose.yml -f docker-compose.gpu.yml up -d --build

.PHONY: down
down: ## Stop the stack
	$(COMPOSE) down

.PHONY: logs
logs: ## Tail logs
	$(COMPOSE) logs -f --tail=100

.PHONY: ps
ps: ## Show running services
	$(COMPOSE) ps
