# cloudphone — common operations
SHELL := /bin/bash
.DEFAULT_GOAL := help

ENV_FILE := .env

.PHONY: help setup up down logs ps restart install-cli test lint fmt clean nuke doctor phone stop scrcpy

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

phone: ## Start ONE phone for native scrcpy (set PROXY=host:port:user:pass to proxy it)
	./scripts/start-phone.sh

scrcpy: ## Open the phone in scrcpy (install scrcpy if missing)
	command -v scrcpy >/dev/null || sudo apt-get install -y scrcpy
	adb connect localhost:$${ADB_PORT:-5555} && scrcpy -s localhost:$${ADB_PORT:-5555} --no-audio --max-size 1024

stop: ## Stop the phone started by `make phone`
	./scripts/stop-phone.sh

install-cli: ## Install the orchestrator CLI into a local venv (.venv), PEP 668-safe
	python3 -m venv .venv
	./.venv/bin/pip install -q -e ./orchestrator
	@echo "CLI installed. Use it via:  ./.venv/bin/cloudphone --help"
	@echo "or activate:  source .venv/bin/activate  then  cloudphone --help"

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
