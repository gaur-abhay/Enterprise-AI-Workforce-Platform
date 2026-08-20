# Pins the uv environment outside the project tree: the repo lives on the
# /mnt/c 9p mount, where package I/O is significantly slower than on ext4.
export UV_PROJECT_ENVIRONMENT := /home/abhay/.virtualenvs/general

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