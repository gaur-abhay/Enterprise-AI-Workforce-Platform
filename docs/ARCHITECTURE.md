# Prototype Architecture

Companion to [SCOPE.md](SCOPE.md). Mermaid diagrams render on GitHub.

## Overview

The one structural fact to read off this: **the API never runs an agent turn.** It accepts,
normalises, enqueues, and acknowledges. Everything that thinks happens in the worker. That
is what makes approvals, scheduling, and long autonomous work possible at all.

```
          Employee (Teams)                 Admin (browser)
                 │ @mention                       │ HTTPS
                 ▼                                ▼
      ┌──────────────────────┐        ┌──────────────────────┐
      │  Azure Bot Service   │        │   Admin UI (HTMX)    │
      └──────────┬───────────┘        └──────────┬───────────┘
                 │                               │
    ═════════════▼═══════════════════════════════▼═════════════
                         API  process
      Teams adapter  ·  REST API  ·  Admin routes
      validate → build TurnContext → enqueue → ACK fast
    ═════════════════════════┬═════════════════════════════════
                             ▼
                   ┌───────────────────┐
                   │  Task queue       │   Postgres,
                   │  (SKIP LOCKED)    │   SKIP LOCKED
                   └─────────┬─────────┘
                             ▼
    ═════════════════════════════════════════════════════════════
                        WORKER  process
      ┌──────────────────────────────────────────────────────┐
      │ Agent runtime (LangGraph)   ◄──► Tool dispatcher     │
      │   agent node ↔ tool node          policy · creds     │
      │                                   · audit            │
      │ Memory manager   Approval manager   Scheduler        │
      └───────┬───────────────────┬──────────────────┬───────┘
              │                   │                  │ fires
              ▼                   ▼                  ▼
      Knowledge layer       Action tools        writes task
      hybrid retrieval      search · read       (timing only)
      rerank · filter       · write
    ═════════════════════════════════════════════════════════════
              │                   │
              ▼                   ▼
      ┌───────────────┐   ┌──────────────────────────────┐
      │  Postgres     │   │  External systems            │
      │  control      │   │  Blob · Graph · SQL · CRM    │
      │  knowledge    │   │  LLM · embeddings · Entra    │
      │  execution    │   └──────────────────────────────┘
      │  + vault      │
      └───────────────┘

              Worker replies proactively ──► Teams
```

## Components

```mermaid
flowchart TB
    subgraph people["People"]
        EMP["Employee<br/>in Teams"]
        ADM["Admin<br/>in browser"]
    end

    subgraph channels["Channels"]
        BOT["Azure Bot Service"]
        WEB["Admin UI<br/>Jinja2 + HTMX"]
    end

    subgraph api["API process — never runs a turn"]
        TA["Teams adapter<br/>validate JWT, normalise activity"]
        RST["REST endpoints"]
        ADR["Admin routes"]
    end

    Q[("Task queue<br/>Postgres SKIP LOCKED")]

    subgraph worker["Worker process"]
        CON["Task consumer"]
        AGT["Agent runtime<br/>LangGraph"]
        DIS["Tool dispatcher<br/>policy · credentials · audit"]
        APR["Approval manager<br/>suspend / resume"]
        MEM["Memory manager"]
        SCH["Scheduler<br/>APScheduler — timing only"]
    end

    subgraph caps["Capability layers"]
        RET["Knowledge: retrieval<br/>hybrid · rerank · pre-filter"]
        ING["Knowledge: ingestion<br/>load · extract · chunk · embed"]
        TLS["Action tools<br/>search · live read · write"]
    end

    subgraph stores["Stores"]
        CTL[("Control<br/>tenants · employee · grants<br/>connections · schedules")]
        KNW[("Knowledge<br/>documents · chunks<br/>pgvector")]
        EXE[("Execution<br/>turns · checkpoints<br/>approvals · audit")]
        VLT[("Secrets vault")]
    end

    subgraph ext["External"]
        SRC["Document sources<br/>Blob · directories · SharePoint"]
        LLM["LLM + embeddings<br/>Azure OpenAI / Gemini"]
        TGT["Tool targets<br/>Graph · SQL · CRM · APIs"]
        IDP["Entra ID"]
    end

    EMP --> BOT --> TA
    ADM --> WEB --> ADR
    TA --> Q
    RST --> Q
    ADR --> Q
    SCH --> Q
    Q --> CON --> AGT
    AGT <--> DIS
    AGT <--> MEM
    DIS --> APR
    DIS --> TLS
    AGT --> RET
    RET --> KNW
    ING --> KNW
    SRC --> ING
    ING --> LLM
    AGT --> LLM
    RET --> LLM
    DIS --> VLT
    TLS --> TGT
    APR --> EXE
    AGT --> EXE
    DIS --> CTL
    SCH --> CTL
    WEB --> IDP
    CON -. "proactive reply" .-> BOT
```

## Flow 1 — an interactive turn

Note where the acknowledgement happens. Teams requires a fast response; the real answer
arrives later on a separate outbound call.

```mermaid
sequenceDiagram
    actor EMP as Employee
    participant BOT as Bot Service
    participant API as API
    participant Q as Task queue
    participant W as Worker
    participant R as Retrieval
    participant M as Model

    EMP->>BOT: "@AI what is our refund policy?"
    BOT->>API: POST /api/messages (Activity)
    API->>API: validate JWT, build TurnContext
    API->>Q: enqueue task
    API-->>BOT: 200 OK (fast ACK)

    Q->>W: claim task (SKIP LOCKED)
    W->>M: agent step
    M-->>W: tool call: search_documents
    W->>R: query + tenant_id + actor_principals
    R-->>W: passages (pre-filtered by ACL)
    W->>M: agent step with passages
    M-->>W: answer + citations
    W->>BOT: proactive reply
    BOT->>EMP: answer with sources
```

## Flow 2 — approval, suspend and resume

This is the seam that is hardest to retrofit. The turn stops, is persisted, and continues
in a **different process** — possibly hours later.

```mermaid
sequenceDiagram
    actor EMP as Employee
    participant W as Worker
    participant D as Dispatcher
    participant EXE as Execution store
    participant ADM as Approvals UI
    actor APP as Approver

    EMP->>W: "email the summary to the client"
    W->>D: tool call: send_email
    D->>D: side_effect_class = write<br/>policy: approval required
    D->>EXE: write pending approval
    W->>EXE: checkpoint turn state
    W-->>EMP: "waiting for approval"
    Note over W: worker is now free —<br/>no process is blocked

    APP->>ADM: open approvals inbox
    ADM->>APP: show exact action + inputs
    APP->>ADM: approve
    ADM->>EXE: mark approved, enqueue resume

    EXE->>W: resume task (any worker)
    W->>EXE: load checkpoint
    W->>D: execute send_email
    D->>EXE: write audit record
    W-->>EMP: "sent"
```

## Flow 3 — a scheduled run, nobody present

The scheduler only decides *when*. It writes a task and the worker runs it down the same
path an interactive turn takes, so the two cannot drift apart.

```mermaid
sequenceDiagram
    participant SCH as Scheduler
    participant CTL as Control store
    participant Q as Task queue
    participant W as Worker
    participant IDP as Entra ID
    participant BOT as Bot Service
    actor EMP as Employee

    SCH->>CTL: due schedules?
    CTL-->>SCH: "Monday revenue report"
    SCH->>IDP: re-resolve creator's principals
    IDP-->>SCH: current groups
    Note over SCH,IDP: re-resolved, not snapshotted —<br/>a leaver's automations stop working
    SCH->>Q: enqueue task (trigger = schedule)

    Q->>W: claim task
    W->>W: run turn (actor = creator, no live caller)
    W->>BOT: proactive post to target conversation
    BOT->>EMP: report appears in channel
    W->>CTL: write run history
```

## Flow 4 — the knowledge layer

```mermaid
flowchart LR
    subgraph sources["Sources"]
        D1["Local / mounted<br/>directories"]
        D2["Azure Blob"]
        D3["SharePoint, Drive<br/>(later)"]
    end

    subgraph ingest["Ingestion"]
        LD["Load<br/>PDF · MD · TXT"]
        MD["Extract metadata<br/>title · dates · headings"]
        CH["Chunk<br/>structure-aware<br/>parent / child"]
        EM["Embed<br/>batch · retry"]
        IX["Index<br/>+ ACLs, + tenant_id"]
    end

    subgraph store["Store"]
        PG[("documents · chunks<br/>pgvector HNSW<br/>+ tsvector")]
    end

    subgraph retrieve["Retrieval"]
        QR["Rewrite query"]
        HY["Hybrid search<br/>dense + lexical, RRF"]
        FL["Pre-filter<br/>tenant + ACL"]
        RR["Rerank"]
        CA["Assemble context<br/>parent expansion<br/>dedupe · budget"]
    end

    EVAL["Evaluation harness<br/>retrieval · groundedness · end-to-end"]

    D1 --> LD
    D2 --> LD
    D3 --> LD
    LD --> MD --> CH --> EM --> IX --> PG
    QR --> HY
    FL --> HY
    PG --> HY --> RR --> CA
    CA --> EVAL
    PG --> EVAL
```

Pre-filtering is drawn as an input to the search, not a step after it. Filtering HNSW
results afterwards destroys recall — you search the whole index, get ten neighbours, and
discard nine as other tenants'.

## What crosses which boundary

| Boundary | Carries | Must not carry |
|---|---|---|
| Channel adapter → API | Normalised `TurnContext` | Teams-specific activity shapes |
| API → queue | Task + `TurnContext` | Anything requiring the HTTP request to stay open |
| Dispatcher → tool | Resolved credential, validated inputs | — |
| Tool → model | Results only | **Credentials, ever** |
| Retrieval → model | Passages the actor is entitled to | Any chunk outside the actor's ACL |
| Actor memory → channel reply | — | Private per-user memory in a shared channel |

`TurnContext` is the contract that makes the four entry points interchangeable. If Teams
concepts leak past the adapter, adding Slack later stops being cheap.

Every store access is tenant-scoped, with Postgres RLS as the enforcement rather than
developer discipline — one forgotten `WHERE` is otherwise a cross-tenant leak.