# AI Employee — Enterprise Agentic RAG Platform

### Complete Project Documentation

---

**Owner:** Abhay — AI Engineer
**Document type:** Master project reference (concept, architecture, capabilities, tech stack, roadmap, and setup guide in one place)
**Status:** Living document — in progress, adjust freely as scope is finalized

---

## Status Legend

Every capability, source, tool, and service below is tagged with a status so this document doubles as a decision log — not just a wishlist.

| Tag | Meaning |
|---|---|
| `[Scoped]` | Confirmed for the current build plan |
| `[In Progress]` | Actively being implemented right now |
| `[Planned]` | Candidate capability, listed for completeness — **default status**, not yet committed |
| `[Out of Scope]` | Explicitly excluded for this version |

Unless otherwise marked, assume `[Planned]`.

---

## Table of Contents

1. [About This Document](#1-about-this-document)
2. [Executive Summary](#2-executive-summary)
3. [Problem Statement](#3-problem-statement)
4. [Concept & Definition](#4-concept--definition)
5. [Capabilities](#5-capabilities)
6. [Retrieval Sources](#6-retrieval-sources)
7. [Tools & Agent Actions](#7-tools--agent-actions)
8. [System Architecture](#8-system-architecture)
9. [Ingestion & Indexing Pipeline](#9-ingestion--indexing-pipeline)
10. [Core AI Services](#10-core-ai-services)
11. [Storage](#11-storage)
12. [Databases](#12-databases)
13. [Vector Databases](#13-vector-databases)
14. [Compute & Deployment](#14-compute--deployment)
15. [Security & Access Control](#15-security--access-control)
16. [Networking](#16-networking)
17. [Monitoring & Observability](#17-monitoring--observability)
18. [Messaging & Event Processing](#18-messaging--event-processing)
19. [DevOps & CI/CD](#19-devops--cicd)
20. [Evaluation, Quality & Guardrails](#20-evaluation-quality--guardrails)
21. [Technology Stack](#21-technology-stack)
22. [Compliance & Governance](#22-compliance--governance)
23. [Roadmap](#23-roadmap)
24. [Getting Started (README)](#24-getting-started-readme)
25. [Project Structure](#25-project-structure)
26. [Glossary](#26-glossary)

---

## 1. About This Document

This is the single source of truth for **AI Employee** — replacing separate `README.md` / `ARCHITECTURE.md` files with one complete, well-organized reference. It covers the vision, every capability and integration the platform *could* have (each tagged with a status), the architecture, the technology choices, and a getting-started guide, so the project stays well-documented as it's built out incrementally.

Sections are written to stand alone — skip to whichever is relevant rather than reading top to bottom.

---

## 2. Executive Summary

**AI Employee** is an enterprise agentic RAG platform: an AI system capable of securely accessing company documents, databases, CRMs, APIs, emails, and cloud storage to answer questions, generate reports, automate workflows, and assist employees across departments — using intelligent tool selection and verified knowledge retrieval.

Rather than following one fixed retrieval pipeline, the platform reasons about each request the way a knowledgeable colleague would: deciding what to look up, where to look, and which tools to use. This is the **Agentic RAG** pattern — dynamic tool selection and multi-step reasoning across multiple enterprise sources — as opposed to **Traditional RAG**, which follows a single, developer-defined retrieval path.

This is a flagship personal/portfolio project, built incrementally with documentation as a first-class priority at every stage.

---

## 3. Problem Statement

Large enterprises have information spread across many systems — PDFs, Word documents, SharePoint, Confluence, Notion, SQL databases, CRM/ERP systems, emails, blob storage, internal APIs, wikis, and web sources. Traditional LLMs only know what they were trained on and cannot reach any of it. This leads to:

- **Hallucinations** — confident answers with no grounding
- **Outdated information** — no access to what changed since training
- **Missing company-specific knowledge** — blind to internal docs, policy, and data
- **No access to real-time business data** — can't query live systems
- **Security concerns** — no inherent concept of who is allowed to see what

Retrieval-Augmented Generation (RAG) solves this by retrieving relevant information first and providing it to the LLM as grounded context before generating an answer. Agentic RAG extends this by letting the system *decide* what to retrieve and how, rather than following one fixed path — which is what makes an "AI employee" possible rather than just a search bar with a chat window on top.

---

## 4. Concept & Definition

> An AI employee capable of securely accessing company documents, databases, CRMs, APIs, emails, and cloud storage to answer questions, generate reports, automate workflows, and assist employees across departments using intelligent tool selection and verified knowledge retrieval.

### How this maps to known patterns

| AI Employee framing | Underlying pattern |
|---|---|
| Securely accessing documents, databases, CRMs, APIs, emails, cloud storage | Multiple retrieval sources + tool calling |
| Answer questions, generate reports, automate workflows | Agent multi-step reasoning + tool execution |
| Assist employees across departments | Enterprise copilot / cross-functional use case |
| Intelligent tool selection | Core agentic RAG differentiator — the LLM decides which tool/source to invoke, instead of a fixed pipeline |
| Verified knowledge retrieval | Groundedness/faithfulness, citation accuracy, evaluation guardrails |

### Traditional RAG vs. Agentic RAG

**Traditional RAG** — the retrieval pipeline is predefined by the developer; the LLM does not decide where to search. Fixed workflow, usually a single retrieval source, faster and cheaper to build and maintain. Good fit for FAQ bots, policy assistants, product documentation search.

```
User Question → Vector Search → Retrieve Documents → LLM → Answer
```

**Agentic RAG** — an agent reasons about the problem and decides which tools to use, which databases to search, whether to search the web, whether calculations are needed, and whether multiple retrieval steps are required. Dynamic reasoning, multiple retrieval sources, tool usage, multi-step workflows. Better for business intelligence assistants, enterprise copilots, research assistants — i.e., AI Employee.

```
User: "Compare our Europe sales with current market trends."

Agent reasoning:
✓ Need company sales      → Query SQL Database
✓ Need market trends      → Search Web
✓ Need company strategy   → Search SharePoint
✓ Need calculations       → Execute Python
✓ Combine results         → Final Answer
```

**AI Employee is built as Agentic RAG.** `[Scoped]`

---

## 5. Capabilities

The full set of things AI Employee could do for an organization. Each capability is independent and can be built incrementally.

### Core capabilities

- Answer natural-language questions grounded in company knowledge `[Scoped]`
- Generate reports (structured summaries, comparisons, briefings) `[Planned]`
- Automate multi-step workflows across systems `[Planned]`
- Assist employees across departments (sales, finance, legal, HR, support, engineering) `[Planned]`
- Multi-turn conversational memory within a session `[Planned]`
- Cross-session memory / personalization per user `[Planned]`
- Cite sources for every grounded claim `[Scoped]`
- Refuse or say "I don't know" when context is insufficient `[Scoped]`

### Extended capabilities

- Document summarization (single doc or many) `[Planned]`
- Comparative analysis across multiple sources (e.g., internal data vs. market trend) `[Planned]`
- Scheduled/recurring report generation (daily, weekly digests) `[Planned]`
- Proactive alerts/notifications triggered by data changes `[Planned]`
- Data visualization / chart generation from query results `[Planned]`
- Meeting notes summarization and action-item extraction `[Planned]`
- Email drafting and triage assistance `[Planned]`
- Ticket/ticketing system triage and auto-routing `[Planned]`
- Onboarding assistant (new-hire Q&A over HR/policy docs) `[Planned]`
- Voice interface (speech-to-text in, text-to-speech out) `[Out of Scope]`
- Multi-language support / translation `[Planned]`

---

## 6. Retrieval Sources

What counts as retrieval: fetching relevant information before generation. Any information source can become part of the system — this is the exhaustive candidate list.

### Documents & content
- PDFs `[Scoped]`
- Word documents `[Planned]`
- SharePoint `[Planned]`
- Confluence `[Planned]`
- Notion `[Planned]`
- Wikis `[Planned]`
- Web sources (public web search) `[Planned]`

### Structured data
- SQL databases `[Scoped]`
- CRM systems (Salesforce, HubSpot, etc.) `[Planned]`
- ERP systems `[Planned]`
- Internal REST APIs `[Planned]`
- GraphQL APIs `[Planned]`

### Storage
- Azure Blob Storage `[Planned]`
- AWS S3 `[Planned]`
- Google Cloud Storage `[Out of Scope]`
- OneDrive / Google Drive `[Planned]`

### Communication
- Email systems `[Planned]`
- Chat/Slack/Teams history `[Out of Scope]`

### Knowledge structures
- Knowledge graphs `[Out of Scope]`

---

## 7. Tools & Agent Actions

Every capability becomes a tool the agent can choose to invoke.

- Vector / semantic search `[Scoped]`
- Hybrid search (keyword + vector) `[Planned]`
- SQL query execution `[Scoped]`
- SharePoint / document search `[Planned]`
- Web search `[Planned]`
- REST API calls `[Planned]`
- CRM search / write-back `[Planned]`
- ERP search `[Planned]`
- Python / code execution (for calculations, data transforms) `[Planned]`
- Calculator (lightweight, for simple math without full code execution) `[Planned]`
- Chart/report generation `[Planned]`
- Email send/draft `[Planned]`
- Calendar read/write `[Out of Scope]`
- Final response synthesis with citations `[Scoped]`

---

## 8. System Architecture

Two pipelines: **ingestion** (offline — populates the index) and **serving** (online — answers user queries from that index).

### Ingestion (offline)

```
Sources → Parse → Chunk → Embed → Upsert → Search Index
```

### Serving (online)

```
                          Users
                            │
        ┌───────────────────────────────────┐
        │   Web / Mobile / Teams / Slack     │
        └───────────────────────────────────┘
                            │
              Authentication (SSO / OAuth)
                            │
                  API Gateway / Load Balancer
                            │
              Backend (FastAPI / .NET / Node)
                            │
        ┌───────────────────┴────────────────────┐
        │              AI Agent / RAG             │
        └───────────────────┬────────────────────┘
                            │
          ┌─────────────────┼──────────────────────┐
          │                 │                       │
      Retriever        Tool Calling         Conversation Memory
          │                 │
   ┌──────┴──────┐          │
   │             │          │
Vector Search  Hybrid Search
   │             │
Azure AI Search / Pinecone / Milvus / Weaviate / Qdrant / Chroma / PGVector
   │
   ├─────────────┬──────────────────────┐
   │             │                      │
Blob Storage   SQL DB               Cosmos DB
   │             │                      │
SharePoint    CRM / ERP            APIs / Web
   │
Document Intelligence → Embeddings → LLM → Grounded Response
   │
Application Insights / Logging / Monitoring
```

**Key architectural principle:** authentication proves *who* the user is; it does **not** by itself control *which documents* they can see. Access control is a separate, explicit layer (see [Security & Access Control](#15-security--access-control)).

---

## 9. Ingestion & Indexing Pipeline

A retrieval system is only as good as the data inside it. Documents must be ingested, processed, indexed, and kept fresh as sources change.

```
Source Systems (PDFs / SharePoint / Blob / SQL / APIs / Email)
      │
Change Detection / Triggers (scheduled crawl, webhooks, event queue)
      │
Extraction & Parsing (Document Intelligence / OCR / Tika / Docling)
      │
Cleaning & Normalization (strip boilerplate, dedupe, language detection)
      │
Chunking (size + overlap, structure-aware, per-doc-type)
      │
Metadata Enrichment (source, author, ACLs, timestamps, tags)
      │
Embedding Generation (batched, model-versioned)
      │
Upsert to Vector + Metadata Store
      │
Index (vector + keyword + filters)
```

### Key concerns

| Concern | Description | Status |
|---|---|---|
| Freshness / sync | Incremental updates, not full re-crawls; tombstone removed docs so stale content never surfaces | `[Planned]` |
| Idempotency | Stable document IDs so re-ingestion updates rather than duplicates | `[Scoped]` |
| Chunking strategy | Structure-aware (headings, tables, code) beats naive fixed-size splits; tuned per document type | `[Scoped]` |
| Embedding versioning | Re-embed the corpus when the embedding model changes; track model version per vector | `[Planned]` |
| Backfill & reprocessing | Re-run the pipeline over the full corpus after a parser/chunking change | `[Planned]` |
| Failure handling | Dead-letter queues, retries, per-document error visibility | `[Planned]` |

---

## 10. Core AI Services

| Category | Azure | Generic Alternative | Purpose | Status |
|---|---|---|---|---|
| LLM inference | Azure OpenAI | OpenAI, Anthropic, Gemini, Llama | Core reasoning & generation | `[Scoped]` — Azure OpenAI |
| Vector + Hybrid Search | Azure AI Search | Pinecone, Weaviate, Milvus, Elasticsearch, PGVector | Retrieval index | `[Scoped]` — PGVector |
| Agent orchestration | Azure AI Foundry | LangGraph, CrewAI, PydanticAI, Semantic Kernel | Multi-step reasoning & tool routing | `[Scoped]` — LangGraph |
| Document parsing | Azure AI Document Intelligence | Unstructured.io, Apache Tika, Docling | Turning raw files into structured text | `[Planned]` |
| OCR & Vision | Azure AI Vision | Google Vision, AWS Rekognition | Scanned document / image text extraction | `[Planned]` |
| Speech-to-text | Azure AI Speech | Whisper, Google Speech | Voice input (if voice interface is ever built) | `[Out of Scope]` |
| Translation | Azure Translator | DeepL, Google Translate | Multi-language support | `[Planned]` |

---

## 11. Storage

| Azure | Alternative | Status |
|---|---|---|
| Azure Blob Storage | AWS S3 | `[Planned]` |
| Azure Data Lake | Hadoop HDFS | `[Out of Scope]` |
| Azure Files | NFS | `[Out of Scope]` |
| OneDrive | Google Drive | `[Planned]` |

Purpose: PDFs, Word documents, images, videos, enterprise files.

---

## 12. Databases

| Azure | Alternative | Purpose | Status |
|---|---|---|---|
| Azure SQL Database | PostgreSQL | Structured business data, source queries | `[Scoped]` — PostgreSQL |
| Cosmos DB | MongoDB | Metadata, chat history, flexible documents | `[Scoped]` |
| Azure PostgreSQL | Self-hosted PostgreSQL | Metadata / permissions store | `[Scoped]` |
| Azure MySQL | MySQL | — | `[Out of Scope]` |

Used for: metadata, user profiles, permissions, chat history, structured business data.

---

## 13. Vector Databases

| Option | Status |
|---|---|
| PGVector | `[Scoped]` — primary |
| Azure AI Search | `[Planned]` |
| Pinecone | `[Planned]` |
| Weaviate | `[Planned]` |
| Milvus | `[Planned]` |
| Qdrant | `[Planned]` |
| ChromaDB | `[Planned]` |
| Elasticsearch | `[Out of Scope]` |

Purpose: embeddings, similarity search, hybrid search, semantic search.

---

## 14. Compute & Deployment

| Azure | Status | Generic Alternative | Status |
|---|---|---|---|
| Azure App Service | `[Planned]` | Kubernetes | `[Planned]` |
| Azure Kubernetes Service (AKS) | `[Planned]` | Docker | `[Scoped]` |
| Azure Functions | `[Scoped]` | ECS | `[Out of Scope]` |
| Azure Container Apps | `[Planned]` | Cloud Run | `[Out of Scope]` |
| Azure Virtual Machines | `[Out of Scope]` | Railway / Render | `[Planned]` (local/dev) |

**Local development:** Docker Compose `[Scoped]`.

---

## 15. Security & Access Control

Security is treated as a first-class architectural layer, not an add-on — this is consistently one of the hardest and most under-appreciated parts of enterprise RAG.

### Identity & secrets

| Azure | Generic | Status |
|---|---|---|
| Microsoft Entra ID | OAuth2 / OpenID Connect | `[Scoped]` |
| Azure Key Vault | HashiCorp Vault | `[Planned]` |
| Managed Identity | — | `[Planned]` |
| Azure Firewall | — | `[Out of Scope]` |
| Private Endpoints | — | `[Out of Scope]` |
| Microsoft Defender for Cloud | — | `[Out of Scope]` |
| — | JWT | `[Scoped]` |
| — | RBAC | `[Scoped]` |
| — | LDAP | `[Out of Scope]` |
| — | TLS | `[Scoped]` |

### Document-level security & access trimming

Authentication (SSO/OAuth) proves *who* the user is. It does **not** control *which documents* they're allowed to see in retrieval results. In an enterprise, a user must never receive an answer grounded in a document they lack permission to read — even if that document is the best semantic match.

```
User Query + Identity
      │
Resolve User Groups / Roles (Entra ID / LDAP groups, entitlements)
      │
Retrieval with Security Filter (vector/hybrid search + ACL metadata filter)
      │
Post-Retrieval Trimming (drop any chunk the user cannot access)
      │
Grounded Answer (only from permitted content)
```

| Concern | Description | Status |
|---|---|---|
| ACLs as metadata | Capture each document's access control list at ingestion time, store alongside the vector | `[Scoped]` |
| Security trimming | Apply user's group/role membership as a hard filter *during* retrieval (pre-filter) and re-verify *after* retrieval (post-filter) | `[Scoped]` |
| Permission freshness | Re-sync ACLs so revoked access takes effect quickly | `[Planned]` |
| Least privilege for tools | Each tool (SQL, CRM, ERP) executes under the user's own permissions, not a broad service account | `[Planned]` |
| No leakage via citations or memory | Titles, snippets, citations, and conversation memory never expose inaccessible content | `[Planned]` |
| Auditability | Log which documents grounded each answer, for compliance and incident review | `[Planned]` |

---

## 16. Networking

| Azure | Generic | Status |
|---|---|---|
| Azure Front Door | Cloudflare | `[Out of Scope]` |
| Application Gateway | NGINX / HAProxy | `[Out of Scope]` |
| Azure Load Balancer | Kubernetes Ingress | `[Out of Scope]` |
| Virtual Network | — | `[Out of Scope]` |
| Network Security Groups | — | `[Out of Scope]` |

*Networking hardening is deferred until the platform moves past local/single-tenant development.*

---

## 17. Monitoring & Observability

| Azure | Generic | Status |
|---|---|---|
| Azure Monitor | Grafana | `[Planned]` |
| Application Insights | Prometheus | `[Planned]` |
| Log Analytics | ELK Stack | `[Out of Scope]` |
| — | OpenTelemetry | `[Planned]` |
| — | Datadog | `[Out of Scope]` |

Tracked at minimum: latency per query, cost per query, groundedness sampling, user feedback (thumbs up/down). `[Planned]`

---

## 18. Messaging & Event Processing

| Azure | Generic | Status |
|---|---|---|
| Azure Service Bus | Kafka | `[Out of Scope]` |
| Event Grid | RabbitMQ | `[Out of Scope]` |
| Event Hubs | SQS | `[Out of Scope]` |
| Logic Apps | NATS | `[Out of Scope]` |

*Not needed until ingestion moves from batch/manual to event-driven at scale.*

---

## 19. DevOps & CI/CD

| Azure | Generic | Status |
|---|---|---|
| Azure DevOps | GitHub Actions | `[Scoped]` |
| Azure Container Registry | GitLab CI | `[Out of Scope]` |
| Bicep | Jenkins | `[Out of Scope]` |
| — | Terraform | `[Planned]` |
| — | Docker Hub | `[Planned]` |

---

## 20. Evaluation, Quality & Guardrails

Enterprise RAG must be measured, not just built. Without evaluation, you cannot tell whether a change improved answers or silently broke them. Without guardrails, a grounded system can still produce unsafe or non-compliant output.

### Retrieval quality
- Precision / Recall @ k `[Planned]`
- Context relevance `[Planned]`
- Chunk coverage `[Planned]`

### Generation quality
- Groundedness / faithfulness (every claim supported by retrieved context) `[Scoped]`
- Answer relevance `[Planned]`
- Citation accuracy `[Scoped]`

### Evaluation loop

```
Golden Dataset (curated Q → expected answer / sources)
      │
Automated Eval Runs (offline, on every change)
├── LLM-as-judge scoring
├── Retrieval metrics (precision/recall @ k)
└── Regression comparison vs. baseline
      │
Online Monitoring (production)
├── User feedback (thumbs up/down)
├── Groundedness sampling
└── Latency / cost per query
```

- Golden / regression dataset `[Scoped]`
- LLM-as-judge scoring `[Scoped]`
- Continuous online monitoring `[Planned]`

### Guardrails
- Grounding enforcement — refuse or say "I don't know" rather than invent an answer `[Scoped]`
- Input/output filtering (prompt injection, PII leakage, toxic content) `[Planned]`
- Prompt-injection defense — retrieved content treated as untrusted, cannot override system instructions or trigger unintended tool calls `[Planned]`
- Human-in-the-loop review for high-stakes actions `[Out of Scope]` (no high-stakes write actions in current scope)
- Compliance guardrails (data residency, retention, redaction) `[Out of Scope]`

---

## 21. Technology Stack

### Current stack (this project)

| Layer | Choice | Status |
|---|---|---|
| Orchestration | LangGraph | `[Scoped]` |
| Orchestration (alt. considered) | CrewAI, PydanticAI | `[Planned]` |
| LLM | Azure OpenAI | `[Scoped]` |
| Embeddings | Ollama (nomic-embed) | `[Scoped]` |
| Retrieval | PGVector, hybrid search | `[Scoped]` |
| Identity & Access | Microsoft Entra ID, ACL post-filtering | `[Scoped]` |
| Backend | FastAPI (Python) | `[Scoped]` |
| Data & Storage | PostgreSQL, Cosmos DB, Azure SQL | `[Scoped]` |
| Infra (local) | Docker Compose | `[Scoped]` |
| Infra (cloud) | Azure Functions | `[Planned]` |
| Evaluation | LLM-as-judge, golden dataset | `[Scoped]` |
| Frontend | React | `[Planned]` |

### Reference: Azure-native stack (full option)

Frontend: React, Angular · Backend: FastAPI, ASP.NET Core · Auth: Microsoft Entra ID · Storage: Azure Blob Storage · Parsing: Azure AI Document Intelligence · Embeddings/LLM: Azure OpenAI · Retriever: Azure AI Search · Database: Azure SQL, Cosmos DB · Secrets: Azure Key Vault · Cache: Azure Cache for Redis · Deployment: Azure App Service, AKS · Monitoring: Azure Monitor, Application Insights · CI/CD: Azure DevOps — all `[Planned]` except where noted above as `[Scoped]`.

### Reference: Vendor-agnostic stack (full option)

Frontend: React, Next.js, Angular · Backend: FastAPI, Django, Spring Boot, Node.js · Auth: Auth0, Keycloak, OAuth2 · Storage: AWS S3, MinIO · Parsing: Docling, Unstructured.io, Apache Tika · Embeddings: OpenAI Embeddings, Sentence Transformers, BGE Models · LLM: GPT-4.x, Claude, Gemini, Llama, Mistral · Retriever: Pinecone, Weaviate, Milvus, Qdrant, Elasticsearch · Database: PostgreSQL, MongoDB · Cache: Redis · Deployment: Docker, Kubernetes · Monitoring: Grafana, Prometheus · CI/CD: GitHub Actions, GitLab CI, Jenkins — all `[Planned]` except where noted above as `[Scoped]`.

---

## 22. Compliance & Governance

| Item | Description | Status |
|---|---|---|
| GDPR alignment | Data residency, retention, and redaction rules | `[Out of Scope]` |
| HIPAA | Healthcare data handling | `[Out of Scope]` |
| SOC2 | Security/operational controls | `[Out of Scope]` |
| Audit logs | Which documents grounded each answer | `[Planned]` |
| Data retention policy | How long chat history / logs are kept | `[Planned]` |

*Compliance frameworks are listed for completeness; not a near-term priority for a portfolio-stage build, but the architecture (ACL metadata, audit logging) is designed to make them addable later.*

---

## 23. Roadmap

| Phase | Name | Description | Status |
|---|---|---|---|
| 1 | Single-Source RAG | Ingest one source, prove grounded Q&A end to end | `[Scoped]` |
| 2 | Multi-Source + Tools | Agent selects between structured & unstructured sources | `[Scoped]` |
| 3 | Security Trimming | Entra ID roles + ACL-aware post-retrieval filtering | `[Planned]` |
| 4 | Evaluation Harness | Golden dataset + LLM-as-judge regression scoring | `[Planned]` |
| 5 | Workflow Automation | Report generation & cross-department task execution | `[Planned]` |

Knowledge base and architecture are defined; implementation proceeds incrementally against this roadmap, with documentation updated at each phase.

---

## 24. Getting Started (README)

> This section is a template — fill in as the project scaffolding is created.

### Prerequisites
- Python 3.11+
- Docker & Docker Compose
- Azure OpenAI access (API key / endpoint)
- PostgreSQL (or use the provided Docker Compose service)

### Setup

```bash
git clone <repo-url>
cd ai-employee
cp .env.example .env   # fill in AZURE_OPENAI_KEY, AZURE_OPENAI_ENDPOINT, DATABASE_URL, etc.
docker compose up -d   # starts Postgres (+ PGVector), and any local services
pip install -r requirements.txt
```

### Running locally

```bash
uvicorn app.main:app --reload
```

### Environment variables

| Variable | Purpose |
|---|---|
| `AZURE_OPENAI_KEY` | LLM API access |
| `AZURE_OPENAI_ENDPOINT` | LLM endpoint |
| `DATABASE_URL` | PostgreSQL connection string |
| `ENTRA_CLIENT_ID` / `ENTRA_TENANT_ID` | Identity/auth |

### Running evaluations

```bash
python scripts/run_eval.py --dataset golden_set.json
```

---

## 25. Project Structure

> Proposed layout — adjust as the codebase takes shape.

```
ai-employee/
├── app/
│   ├── main.py              # FastAPI entrypoint
│   ├── agent/                # LangGraph agent + tool definitions
│   ├── retrieval/            # vector search, hybrid search
│   ├── ingestion/            # parsing, chunking, embedding pipeline
│   ├── security/              # ACL resolution, access trimming
│   └── api/                  # routes
├── eval/
│   ├── golden_set.json
│   └── run_eval.py
├── scripts/
├── docker-compose.yml
├── requirements.txt
├── .env.example
└── README.md → points here
```

---

## 26. Glossary

- **RAG (Retrieval-Augmented Generation):** retrieving relevant information before generation, to ground LLM answers in real data.
- **Agentic RAG:** RAG where an agent dynamically decides which tools/sources to use, rather than following one fixed pipeline.
- **Groundedness / Faithfulness:** every claim in a generated answer is supported by retrieved context.
- **ACL (Access Control List):** the set of users/groups permitted to access a given document.
- **Security Trimming:** filtering retrieval results by the requesting user's permissions, both before and after search.
- **Golden Dataset:** a curated set of representative questions with expected answers/sources, used for regression testing.
- **LLM-as-Judge:** using a model to score groundedness, relevance, and correctness at scale.
- **Chunking:** splitting documents into smaller pieces for embedding and retrieval.
- **Embedding:** a vector representation of text used for semantic similarity search.

---

*End of document. This is a living reference — update statuses as decisions are made, and add sections as needed.*
