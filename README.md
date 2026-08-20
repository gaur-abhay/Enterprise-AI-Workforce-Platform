# Enterprise-AI-Workforce-Platform

An enterprise AI platform that securely connects to enterprise knowledge, databases, APIs, and business applications to answer questions, automate workflows, and assist employees with verified information.

## Status

🚧 **Under Development**

This project is currently under active development. Features, architecture, integrations, and documentation will continue to evolve as development progresses.

Full design reference: `Ask Owner.`
Build walkthrough and rationale: [`IMPLEMENTATION.md`](docs/IMPLEMENTATION.md).

### Progress

| Step | Item | Status |
|---|---|---|
| 1 | Docker Compose foundation (Postgres + PGVector, Ollama) | Scaffolded |
| 2 | Ingestion pipeline (chunk → embed → index) | Built, partially verified |
| 3 | `search_documents` tool | Built, partially verified |
| 4 | LangGraph agent (agent node → tool node → loop) | Built, partially verified |
| 5 | FastAPI `/chat` endpoint | Built, partially verified |
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
| `LLM_PROVIDER` | `azure_openai` or `gemini` |
| `EMBEDDING_PROVIDER` | `ollama` or `gemini` |
| `EMBEDDING_DIM` | Vector width; must match the active embedding model |
| `OLLAMA_BASE_URL` / `EMBEDDING_MODEL` | Local embedding service and model |
| `AZURE_OPENAI_*` | Endpoint, key, deployment, and API version |
| `GOOGLE_API_KEY` / `GEMINI_*` | Gemini key and model names |

### Providers

The chat model and the embedding model are chosen independently, so a free Gemini key is
enough to run the whole system without Azure or a local Ollama:

```bash
LLM_PROVIDER=gemini
EMBEDDING_PROVIDER=gemini
GOOGLE_API_KEY=...
```

Get a key at [aistudio.google.com/apikey](https://aistudio.google.com/apikey).

Switching the *embedding* provider requires re-indexing, because vectors from different
models are not comparable — this is true of every vector store, not just this one. Every
chunk records the model that produced it and retrieval only searches chunks matching the
active model, so a switch returns no results rather than wrong ones. Run `make ingest` after
switching: documents already indexed under a different model are re-embedded automatically,
without needing `--force`.

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

## Usage

Index documents placed in `data/documents/`:

```bash
make ingest                                              # or: --force to re-index
```

Ask a question from the command line:

```bash
uv run python -m ai_employee.agent.runner "what is the home office stipend?" --show-tools
```

Or over HTTP:

```bash
make api
curl -s localhost:8000/health

curl -s localhost:8000/chat -H 'content-type: application/json' \
  -d '{"message": "what is the home office stipend?"}'
```

`/chat` returns `answer`, a `thread_id`, the `sources` the model was shown, and the
`tool_calls` it made. Pass the `thread_id` back to continue the same conversation; omit it to
start a new one. Interactive docs are at `/docs`.

---

## Copyright

© 2026 Abhay Gaur. All rights reserved.

This repository is publicly available for portfolio and demonstration purposes. No permission is granted to copy, redistribute, modify, or use this code or its contents without prior written permission.
