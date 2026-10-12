# Pins the uv environment outside the project tree: the repo lives on the
# /mnt/c 9p mount, where package I/O is significantly slower than on ext4.
export UV_PROJECT_ENVIRONMENT := /home/abhay/.virtualenvs/general

# Local image name only; CI tags against the registry in vars.ACR_NAME.
IMAGE_NAME := ai-employee

.PHONY: install up down logs api ingest

install:
	uv sync

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f

api:
	uv run uvicorn ai_employee.api.main:app --reload

# SOURCE overrides the default data/documents, e.g. SOURCE=azure://contracts/policies
ingest:
	uv run python -m ai_employee.ingestion.run $(SOURCE)

# --- Quality gates. `make check` is exactly what CI runs. ---
.PHONY: lint format typecheck test check docker-build

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff check --fix .
	uv run ruff format .

typecheck:
	uv run mypy

test:
	uv run pytest

check: lint typecheck test

docker-build:
	docker build -t $(IMAGE_NAME) .
