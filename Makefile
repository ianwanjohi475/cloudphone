# cloudphone — common operations
SHELL := /bin/bash
.DEFAULT_GOAL := help

ENV_FILE := .env

.PHONY: help setup up down logs ps restart install-cli test lint fmt clean nuke doctor

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

$(ENV_FILE):
	@cp .env.example .env && echo "Created .env from template — edit it, then re-run."

setup: ## Load host kernel modules (binder/ashmem) — needs sudo
	sudo ./scripts/setup-host.sh

doctor: ## Check host prerequisites (kernel modules, docker, kvm)
	./scripts/doctor.sh

up: $(ENV_FILE) ## Build images and start the base stack (1 phone + web)
	docker compose up -d --build
	@echo "Dashboard:  http://localhost:$${DASHBOARD_PORT:-8080}"
	@echo "ws-scrcpy:  http://localhost:$${SCRCPY_PORT:-8000}"

down: ## Stop the stack (keeps data)
	docker compose down

restart: ## Restart the base stack
	docker compose restart

ps: ## List running cloudphone containers
	docker ps --filter "name=cloudphone-" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

logs: ## Tail logs (use S=redroid-0 to scope to one service)
	docker compose logs -f $(S)

install-cli: ## Install the orchestrator CLI into the current Python env
	pip install -e ./orchestrator

test: ## Run the Python test suite
	cd orchestrator && python -m pytest -q

lint: ## Static checks
	cd orchestrator && ruff check . && python -m pyflakes cloudphone || true

fmt: ## Format Python
	cd orchestrator && ruff format .

clean: ## Remove stopped containers and dangling images
	docker compose down --remove-orphans
	docker image prune -f

nuke: ## DANGER: stop everything and delete all phone data
	docker compose down -v --remove-orphans
	rm -rf $${DATA_ROOT:-./data}/*
