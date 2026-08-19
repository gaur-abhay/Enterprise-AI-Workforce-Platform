# Enterprise-AI-Workforce-Platform

An enterprise AI platform that securely connects to enterprise knowledge, databases, APIs, and business applications to answer questions, automate workflows, and assist employees with verified information.

## Status

🚧 **Under Development**

This project is currently under active development. Features, architecture, integrations, and documentation will continue to evolve as development progresses.

Full design reference: [`AI_Employee_Documentation.md`](docs/AI_Employee_Documentation.md).
Build walkthrough and rationale: [`IMPLEMENTATION.md`](docs/IMPLEMENTATION.md).

### Progress

| Step | Item | Status |
|---|---|---|
| 1 | Docker Compose foundation (Postgres + PGVector, Ollama) | Scaffolded |
| 2 | Ingestion pipeline (chunk → embed → index) | Built, partially verified |
| 3 | `search_documents` tool | Built, partially verified |
| 4 | LangGraph agent (agent node → tool node → loop) | Built, partially verified |
| 5 | FastAPI `/chat` endpoint | Not started |
| 6 | End-to-end smoke test | Not started |

## Prerequisites

- Python 3.12+ and [uv](https://docs.astral.sh/uv/)
- Docker and Docker Compose
- Azure OpenAI access (required from step 4 onwards)

## Setup

```bash
cp .env.example .env      # set POSTGRES_PASSWORD and, later, the Azure OpenAI values
make install              # uv sync
make up                   # start Postgres (+ PGVector) and Ollama
docker exec -it ai-employee-ollama ollama pull nomic-embed-text
```

Verify the stack:

```bash
docker exec -it ai-employee-postgres psql -U aiemployee -d ai_employee -c "\dx"
curl http://localhost:11434/api/embeddings -d '{"model":"nomic-embed-text","prompt":"test"}'
```

The first should list `vector` as an installed extension; the second should return an embedding array.

## Environment

The uv environment is kept outside the repository at `/home/<user>/.virtualenvs/general`, pinned by `UV_PROJECT_ENVIRONMENT` in the `Makefile`, because the repository sits on a Windows mount where package I/O is slow under WSL. Use the `make` targets, or export the variable before running `uv` directly.

## Configuration

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | PostgreSQL connection string used by the application |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | Compose service credentials |
| `POSTGRES_PORT` / `OLLAMA_PORT` | Host port mappings, override on conflict |
| `OLLAMA_BASE_URL` / `EMBEDDING_MODEL` / `EMBEDDING_DIM` | Embedding service and model |
| `AZURE_OPENAI_*` | LLM endpoint, key, deployment, and API version |

## Project structure

```
├── docker-compose.yml       # Postgres (PGVector) + Ollama
├── init.sql                 # enables the vector extension on first init
├── Makefile                 # environment pin and common targets
├── pyproject.toml           # uv project definition
├── data/documents/          # ingestion input
└── src/ai_employee/
    ├── config.py            # settings loaded from the environment
    ├── agent/               # LangGraph agent and prompts
    ├── tools/               # agent tool definitions
    ├── ingestion/           # parsing, chunking, embedding, indexing
    └── api/                 # FastAPI application
```

## Make targets

| Target | Action |
|---|---|
| `make install` | Sync dependencies into the uv environment |
| `make up` / `make down` | Start / stop the Docker Compose stack |
| `make logs` | Follow container logs |
| `make api` | Run the FastAPI app with reload |
| `make ingest` | Run the ingestion pipeline |

---

## Copyright

© 2026 Abhay Gaur. All rights reserved.

This repository is publicly available for portfolio and demonstration purposes. No permission is granted to copy, redistribute, modify, or use this code or its contents without prior written permission.