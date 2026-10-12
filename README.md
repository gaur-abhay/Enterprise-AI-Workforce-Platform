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
| 7 | CI/CD (gates on PR, build → ACR → App Service on merge) | Built, unverified until first run |

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
| `AZURE_STORAGE_*` | Blob Storage ingestion source — see [Document sources](#document-sources) |
| `LOG_LEVEL` / `LOG_FORMAT` | Application log level, and `text` or `json` — see [Logging](#logging) |

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

### Document sources

Documents come from either the local filesystem or an Azure Blob Storage container. The
ingestion CLI takes one source argument: a path, or an `azure://CONTAINER/PREFIX` URI.

```bash
make ingest                                        # data/documents/
make ingest SOURCE=/path/to/handbook.pdf           # a single file
make ingest SOURCE=azure://corp-docs               # a whole container
make ingest SOURCE=azure://corp-docs/policies/hr   # blobs under one prefix
make ingest SOURCE=azure://                        # AZURE_STORAGE_CONTAINER + _PREFIX
```

Authenticate the container in one of two ways:

| Variable | Use |
|---|---|
| `AZURE_STORAGE_CONNECTION_STRING` | Simplest for local testing. Embeds the account key, so it grants the whole account. |
| `AZURE_STORAGE_ACCOUNT_URL` | Entra ID via `DefaultAzureCredential`. Preferred everywhere else. |

The connection string wins if both are set. `DefaultAzureCredential` does not require the
application to run on Azure: it resolves a managed identity when there is one, otherwise the
`AZURE_TENANT_ID` / `AZURE_CLIENT_ID` / `AZURE_CLIENT_SECRET` service principal, otherwise
your local `az login` session. Whichever identity it lands on needs the **Storage Blob Data
Reader** role — Owner or Contributor on the storage account covers the management plane only,
and blob listing still returns 403.

Blobs are matched by extension (`.pdf`, `.md`, `.txt`) and downloaded to a temporary file
that is deleted as soon as the document has been parsed. Documents are identified by
`azure://<account>/<container>/<blob>`, so the same container name in two storage accounts
stays distinct, and re-ingesting updates the existing rows rather than duplicating them.

### Incremental ingestion

Re-running is cheap: the ETag returned by the blob listing is compared against the one
recorded at index time, so an unchanged blob is never downloaded at all. A run over an
unchanged container costs one listing call and nothing else.

| Blob state | Downloaded? | Re-embedded? | Reported |
|---|---|---|---|
| ETag matches the indexed copy | No | No | `skipped — unchanged at source` |
| ETag moved, bytes identical | Yes | No | `skipped — content unchanged` |
| Content actually changed | Yes | Yes | `indexed` |
| Deleted from the container | — | — | `pruned`, with `--prune` |

The ETag is only an optimisation; the SHA-256 of the content is still the authority on
whether a document changed. That matters because a copy, a re-upload, or a metadata edit
moves the ETag without changing a byte — those cost a download but not an embedding pass,
and the new ETag is recorded so the next run skips outright. Switching embedding provider
still re-embeds everything regardless of either check, since vectors from different models
are not comparable.

Deletions are not handled by default. Removing a blob leaves its rows indexed, and the agent
will keep citing a document that no longer exists — pass `--prune` to reconcile:

```bash
uv run python -m ai_employee.ingestion.run azure://corp-docs --prune
```

Pruning is bounded by the source's own listing scope, so a run over `azure://corp-docs/policies`
can only ever delete documents under that prefix. It is opt-in because an empty or partial
listing — a mistyped prefix, a credential that lost its role — would otherwise clear the index.

## Project structure

```
├── .github/workflows/ci.yml # quality gates, then build and deploy
├── Dockerfile               # runtime image for App Service
├── docker-compose.yml       # Postgres (PGVector) + Ollama
├── init.sql                 # enables the vector extension on first init
├── Makefile                 # environment pin and common targets
├── pyproject.toml           # uv project definition, lint/type/test config
├── data/documents/          # ingestion input
├── tests/                   # unit tests
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
| `make ingest` | Run the ingestion pipeline; `SOURCE=` overrides the input |
| `make lint` | Ruff lint and format check |
| `make format` | Apply Ruff fixes and formatting |
| `make typecheck` | Mypy over `src/ai_employee` |
| `make test` | Run the unit tests |
| `make check` | Lint, types, and tests — exactly what CI runs |
| `make docker-build` | Build the runtime image locally |

## Usage

Index documents placed in `data/documents/`, or point at a blob container:

```bash
make ingest                                # or: SOURCE=azure://corp-docs/policies
```

Re-runs skip documents whose content is unchanged; pass `--force` to re-index anyway:

```bash
uv run python -m ai_employee.ingestion.run azure://corp-docs --force
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

`/chat` returns `answer`, a `thread_id`, a `request_id`, the `sources` the model was shown,
and the `tool_calls` it made. Pass the `thread_id` back to continue the same conversation;
omit it to start a new one. Interactive docs are at `/docs`.

### Citations

The agent cites inline — document name and page next to each claim — and every passage it was
shown comes back in `sources`, with enough detail to check the claim against the stored
document:

| Field | |
|---|---|
| `source` / `title` | File name and document title. `source` is what the answer cites. |
| `uri` | Where the document actually lives: a path, or `azure://account/container/blob` |
| `document_id` / `chunk_id` | Row identity, for linking or fetching the original |
| `page` / `chunk_index` | Position within the document |
| `indexed_at` | When the document was last indexed, so a stale answer is recognisable |
| `content` | The passage itself, so a client can show what a claim rests on |
| `score` | Cosine similarity, higher is more relevant |

`sources` is what was *retrieved*, not what was cited — the model may use a subset. Treat it
as an audit trail rather than a bibliography.

### Logging

Every entrypoint configures logging on start. `LOG_LEVEL` applies to this application's
loggers only; third-party SDKs stay at WARNING, so `LOG_LEVEL=DEBUG` does not bury a run in
Azure and HTTP client traffic. `LOG_FORMAT=json` emits one object per line for a log shipper.

Each request or CLI run binds a correlation id that prefixes every line it produces:

```
00:40:36 INFO [3552ff0aadae] ai_employee.retrieval: search 'Doc2' top_k=5 -> 2 hits, best 0.590
```

The API takes that id from an inbound `x-request-id` header when one is present, returns it in
the response header and in the `/chat` body, so a user reporting a bad answer can name the
exact turn to look up.

Retrieval is logged at INFO — the query, hit count, and best score — because a retrieval trace
that is off by default is not an audit trail. Note that this puts search queries and user
questions in the logs, alongside document content: they inherit the sensitivity of the indexed
corpus, and need the same retention policy.

## CI/CD

One workflow, [`.github/workflows/ci.yml`](.github/workflows/ci.yml), with two jobs.

| Trigger | What runs |
|---|---|
| Pull request to `develop` | `quality`: Ruff lint, Ruff format check, Mypy, pytest |
| Push to `develop` | `quality`, then `deploy` if it passes |

`deploy` builds the image, pushes it to ACR under two tags, and restarts the web app:

- `dev-latest` — the mutable tag the web app is pinned to.
- `<commit-sha>` — immutable, so any build can be identified and rolled back to.

Because the web app always points at `dev-latest`, deploying is a push plus a restart: App
Service re-pulls the tag on restart. To roll back, retag a known-good SHA as `dev-latest`
and restart again:

```bash
az acr import --name <registry> --source <registry>.azurecr.io/ai-employee:<sha> \
  --image ai-employee:dev-latest --force
az webapp restart --name <webapp> --resource-group <group>
```

Run the same gates locally before pushing with `make check`.

### Repository configuration

Set these under *Settings → Secrets and variables → Actions*.

| Variable | Example | Purpose |
|---|---|---|
| `ACR_NAME` | `aiemployeeacr` | Registry name, without `.azurecr.io` |
| `AZURE_WEBAPP_NAME` | `ai-employee-dev` | Web app to restart |
| `AZURE_RESOURCE_GROUP` | `rg-ai-employee` | Its resource group |
| `AZURE_WEBAPP_URL` | `https://ai-employee-dev.azurewebsites.net` | Optional; enables the post-deploy health check |

| Secret | Purpose |
|---|---|
| `AZURE_CLIENT_ID` | App registration used by the federated credential |
| `AZURE_TENANT_ID` | Directory the app registration lives in |
| `AZURE_SUBSCRIPTION_ID` | Subscription holding the registry and web app |

### Azure setup

Authentication is OIDC, so no long-lived credential is stored in GitHub. Once, to create
the app registration and trust this repository:

```bash
az ad app create --display-name ai-employee-github --query appId -o tsv   # -> APP_ID
az ad sp create --id "$APP_ID"

az ad app federated-credential create --id "$APP_ID" --parameters '{
  "name": "develop",
  "issuer": "https://token.actions.githubusercontent.com",
  "subject": "repo:gaur-abhay/Enterprise-AI-Workforce-Platform:ref:refs/heads/develop",
  "audiences": ["api://AzureADTokenExchange"]
}'
```

The `deploy` job names the `dev` environment, so add a second federated credential with
subject `repo:<owner>/<repo>:environment:dev` if you enable environment protection rules.

Grant the service principal only what the pipeline uses:

```bash
az role assignment create --assignee "$APP_ID" --role AcrPush \
  --scope $(az acr show --name <registry> --query id -o tsv)

az role assignment create --assignee "$APP_ID" --role "Website Contributor" \
  --scope $(az webapp show --name <webapp> --resource-group <group> --query id -o tsv)
```

### Web app settings

The container reads its configuration from the environment — nothing is baked into the
image. Set the same variables listed under [Configuration](#configuration) as app settings,
plus:

| Setting | Value | Why |
|---|---|---|
| `WEBSITES_PORT` | `8000` | Port the container listens on |
| `DOCKER_ENABLE_CI` | `false` | The workflow controls deployment; leave ACR webhooks off |

Point the web app at `<registry>.azurecr.io/ai-employee:dev-latest` once, and give it a
managed identity with `AcrPull` on the registry so it can pull without admin credentials.

> `/health` reports each dependency separately and returns 503 when any is down. The
> post-deploy step in the workflow prints its response but does not fail on a 503 — a
> missing `GOOGLE_API_KEY` is a configuration problem, not a failed rollout.

---

## Copyright

© 2026 Abhay Gaur. All rights reserved.

This repository is publicly available for portfolio and demonstration purposes. No permission is granted to copy, redistribute, modify, or use this code or its contents without prior written permission.
