# Prototype Scope

Status: agreed 2026-10-07. Supersedes the step-based progress table in the README for
anything beyond step 5.

## Purpose

Prove that an autonomous AI coworker, living in Microsoft Teams, can be built on an
architecture that holds up under enterprise permission and governance requirements — and
demonstrate real depth in Agentic RAG specifically.

This is a **proof of architecture, not a product**, with one deliberate exception: the
knowledge layer goes deep (see below). Everything else is a thin slice.

Inspired by Viktor (viktor.com). Not an attempt to replicate its surface area — Viktor has
3,200+ integrations and runs model-written code in a per-workspace sandbox. We match
neither.

## The scoping principle: seams, not features

A *seam* is a boundary where two parts of the system must agree on a contract. Components
can be rewritten in an afternoon; a seam that ten things depend on cannot. Breadth is not
the risk — nobody doubts a fourth connector can be added. The risk lives at the joints.

Four seams, each proven with the thinnest possible slice:

| # | Seam | Proven by |
|---|---|---|
| 1 | Identity flows end to end | One tenant, two users, one tool: the caller's identity reaches both a vector-search filter and a tool credential |
| 2 | A turn suspends and resumes | One approval-gated tool: turn pauses, resumes hours later in a different process |
| 3 | A turn runs with nobody present | One scheduled task, result delivered proactively |
| 4 | Tenants cannot see each other | A test asserting cross-tenant reads fail |

**The exception.** The knowledge layer is not scoped by this principle. It is the capability
being demonstrated, it is the only layer with a measurable quality axis, and re-indexing a
corpus is far more expensive than redeploying code. It gets depth; the other layers get
seams.

## Architecture

### Three planes

| Plane | Holds | Character |
|---|---|---|
| Control | tenants, users, employee config, connections, tool grants, policies, schedules | Low traffic, high consequence |
| Knowledge | documents, chunks, embeddings | Per-tenant, batch-written, read-heavy |
| Execution | turns, checkpoints, approvals, audit, task queue | Stateful, long-running, bursty |

### The central contract

Four entry points — Teams mention, REST call, schedule fire, event trigger — normalise into
one envelope. The agent core never learns which channel it came from.

```
TurnContext:
  tenant_id
  employee_id         # the workspace's coworker
  actor               # who asked; "system" for scheduled runs
  actor_principals    # groups, for ACL filtering
  conversation_ref    # where to reply, proactively if needed
  trigger             # mention | schedule | event | api
  correlation_id
```

This is the seam-1 contract. Channel specifics must not leak past the adapter.

### Deployment shape

Three processes, one image, different entrypoints:

- **api** — accepts requests, ACKs fast, enqueues. Never runs a turn.
- **worker** — pulls tasks, runs turns, posts results. Hosts the scheduler.
- **scheduler** — APScheduler inside the worker for now; a separate service when it needs
  to scale.

## Tenancy and onboarding

### Tenant = workspace

Two levels, not three: a **tenant** is one customer organisation, which is the same thing as
one Teams workspace — they are not separate concepts. **Users** belong to a tenant. One
employee per tenant, shared by everyone.

There are no per-user workspaces. A single user owning a private coworker is where this
generalises later; it is not in the prototype.

The tenant is keyed on the **Entra tenant ID**, so the identity provider supplies the tenant
boundary. A user cannot land in the wrong tenant by accident.

### Two kinds of connection

The word was overloaded, and the distinction is the one that resolves most confusion about
whose credentials are whose:

| | `source_connection` | `user_connection` |
|---|---|---|
| Scope | Tenant | User |
| Holds | Blob container, directory path | OAuth token for an action tool |
| Created by | Org admin | Each person, for themselves |
| Feeds | The shared knowledge base | That person's tool calls |
| On the person leaving | Unaffected | Revoked |

The rule: **knowledge sources are tenant-level integrations; per-user credentials belong to
action tools.** Anything pre-indexed uses a tenant credential and captures permissions as
metadata. Anything queried live *as a person* uses that person's credential — which is why
mail is an action tool and documents are a knowledge source.

The documents are the customer's. They connect their own container; we index it. We are not
hosting storage for them.

### Tenant lifecycle

A tenant row existing is not the same as a tenant being usable:

```
discovered  →  claimed  →  configured  →  active
```

- **discovered** — the first person from that organisation appears; a tenant row is created.
  Nothing has been granted.
- **claimed** — an admin has verified ownership through consent.
- **configured** — an admin has connected at least one source.
- **active** — ingestion has run; the employee can answer.

### Admin and member

Two roles. No RBAC.

- **member** — registers themselves, connects their own accounts for action tools.
- **admin** — additionally connects org sources, which is what creates the knowledge base.

Role is **not** derived from the tenant id. A user row carries both, and they answer
different questions: `tenant_id` says which organisation the person belongs to and comes from
the token's `tid` claim; `role` is our own column. Admin consent is what sets it — only a
genuine Entra admin can complete that flow, so completing it promotes the person to admin
here. That is self-verifying, and avoids needing Graph permissions to ask Entra who the
admins are.

This split is not our choice. Connecting an org's Blob container needs an application-level
credential, and Entra requires **admin consent** for application permissions. Delegated
per-user permissions do not need an admin, which is precisely why per-user action tools work
for any member.

The consequence, stated plainly: if a member registers and no admin ever has, that tenant has
an employee with no knowledge of the company, because nobody has given it any. Asking it
about a company policy correctly answers that no documents are connected. The member can
request consent; they cannot grant it.

Once an admin does connect a source, every member sees that corpus — including documents
they did not connect. The knowledge base belongs to the tenant, not to whoever connected it.
Narrowing per person is what `acl_principals` is for, not provenance.

### What registration means in the prototype

Teams installation and real Entra consent are pass I, so onboarding is thin:

- Tenant creation is a seed CLI command, not self-serve signup.
- Users are seeded with a role.
- An admin adds a directory path or Blob container through the admin UI; the credential goes
  to the vault, the config to the table.
- Ingestion is triggered manually.
- A dev-stub login selects which user you are.

Same pattern as elsewhere: the lifecycle states, the roles and the tenant-scoped source
config are real from the first milestone. The self-serve consent flow drops into `claimed`
later without disturbing anything around it.

### A note on ACLs and Blob

Azure Blob is a weak source for demonstrating per-user document permissions — a container is
readable by an identity or it is not, with no meaningful per-file user ACLs short of ADLS
Gen2 POSIX ACLs. Per-document permissions genuinely live in **SharePoint**.

So when ACL enforcement arrives, either ACLs are assigned manually in seed data, or the real
story needs SharePoint as a source.

## Knowledge layer — the deep dive

Document stores only. SQL, CRM, and API access are **action-layer tools**, not knowledge
sources: anything transactional or aggregate ("how many open tickets?") is unanswerable by
vector search at any quality, because the information is in no single passage.

### Sources

In scope: local or mounted directories, Azure Blob Storage. Both exist. The source
abstraction (`list_items` / `open`, change tokens for incremental sync) already generalises
to Drive, SharePoint, and similar — adding one is implementing a protocol, not touching the
pipeline.

Formats: PDF, Markdown, plain text. Narrow on purpose.

### Indexing

In scope, and treated as the substance of the work:

- Metadata extraction — title, dates, document type, section headings. Underrated, and it
  feeds both filtering and citation quality.
- Structure-aware chunking: respect headings rather than splitting blindly on separators;
  contextual chunk headers so a passage knows which document and section it came from.
- Parent/child chunking — index small for precision, keep the enclosing section for context.
- Embedding mechanics: batching, rate limits, retries, dimension discipline.
- Index tuning: HNSW `m`, `ef_construction`, `ef_search` actually move recall.
- Document versioning and deduplication. Two versions of the same policy in one corpus is
  the normal case, not the edge case.
- ACL capture at index time, pruning on source deletion.

Deferred, deliberately: OCR for scanned documents, table and figure extraction from PDFs.
Both are real quality wins and both are month-long rabbit holes.

### Retrieval

Where the depth pays off, and previously mis-scoped as out:

- **Hybrid search** — dense plus lexical, fused (RRF). Embeddings miss exact identifiers,
  product codes, and proper nouns; BM25 does not. The `content_tsv` column exists for this.
- **Reranking** — generally the single largest precision gain available.
- **Pre-filtering** on tenant, ACL, and metadata. Filtering HNSW results *after* the search
  destroys recall: you search the whole index, get ten neighbours, discard nine as other
  tenants'.
- **Query rewriting** — conversational queries are unsearchable as written. "What about the
  second one?" has no useful embedding.
- **Context assembly** — parent expansion, deduplication, diversity so five chunks are not
  all the same page, and a token budget.
- Citation fidelity. Already strong; keep it.

### Agentic retrieval

What makes it *Agentic* RAG rather than RAG, and the thing the demo rests on: the agent
deciding to search again, refining the query between hops, and knowing when to stop. The
recursion limit exists; the judgement does not yet.

## Other layers — thin slices

### Action

A tool is not a function. It is a declaration the dispatcher enforces:

```
Tool:
  name, input schema, description
  connection_type      # which per-user OAuth grant it needs
  side_effect_class    # read | write | irreversible
  approval_required    # resolved from tenant policy, not hardcoded
```

The dispatcher — not the tool — resolves credentials from the vault, checks policy,
enforces approval, and writes the audit record. **The model never sees a credential.**

A few tools only; the exact count is not fixed. What matters is that between them they
cover all three side-effect classes, since each proves a different seam:

| Example | Class | Proves |
|---|---|---|
| `search_documents` | read | corpus read with ACL filtering |
| Read caller's live data (Graph, SQL, CRM) | read | per-user OAuth, delegated identity |
| Send message / create record | write | approval gating, suspend/resume |

Text-to-SQL, CRM reads, and generic API calls all live here when they arrive.

### Memory

Five scopes: working state (checkpointer), conversation memory (keyed by conversation —
shared by many people in a channel), actor memory (per-user), workspace memory (org-level
learned facts), knowledge corpus.

Writes happen through an agent **tool call**, prompted. The agent decides when to remember;
because every write is a tool call, every write lands in the audit log and is inspectable
and correctable — deliberately the opposite of opaque background extraction.

The rule worth proving: **actor memory must not leak into a channel answer others can
read.**

### Scheduling

A `schedules` table, APScheduler with a Postgres jobstore, running inside the worker. The
scheduler's only job is **timing** — it writes a task row and the worker picks it up through
the same path an interactive turn takes, so scheduled and interactive execution cannot
drift apart.

Permissions are **re-resolved at run time**, not snapshotted at creation. If someone leaves
the organisation, their automations stop working.

Run history is in scope. A task that silently failed three weeks ago is worse than no task.

### Isolation

`tenant_id` everywhere, RLS enabled, per-tenant credential scoping, and a test asserting
cross-tenant access fails. Two tenants seeded.

Multi-tenant is the superset: it can be run with one customer in it, but a single-tenant
system cannot become multi-tenant without a migration. Dedicated deployment stays a
packaging decision, not an architectural one.

Out: per-workspace execution sandboxes. Not needed while no model-written code runs.

### Approval

Three layers, in precedence order:

1. **Hard floor** — `side_effect_class: irreversible` always requires approval. No
   configuration can auto-approve it.
2. **Tenant policy** — per action class: auto-approve or require approval. Sets the
   *ceiling* of autonomy.
3. **Agent judgement** — the agent may escalate and ask for approval where policy does not
   require it. It can only ever be more cautious than policy, never less.

The layers decide *whether* a tool call needs approval. *Who* approves is separate, and the
default is the **requester**: the coworker asks the person it is acting for to confirm, in the
conversation, before it acts — the Viktor model. Approval is a confirmation from the user, not
a request to an admin on the user's behalf.

Admins act on the **configuration** side instead: tenant policy decides which action classes
need confirmation at all, and may later route specific classes to a designated approver. A
scheduled run has no requester present, so its approver is the schedule's owner (pass F).

Agreed 2026-10-19. The decision applies to exactly the arguments shown; a changed call is a
new request.

## Evaluation

In scope, because without it every chunking decision is an opinion. The reason it belongs
here rather than in a later phase: chunking changes improve one query class and silently
destroy another, and a scored suite re-run in CI is the only defence.

Three measurements, deliberately separate — if only final answers are scored, a bad answer
is unattributable:

| Layer | Measures | Localises failure to |
|---|---|---|
| Retrieval | Did the right passage come back? | chunking, embedding, filters, top-k |
| Groundedness | Is the answer supported by what was retrieved? | model ignoring its context |
| End-to-end | Is the answer correct? | either of the above, or the prompt |

Datasets: a corpus to index, a retrieval set (questions with known relevant passages), and
a curated golden Q&A set. The middle one is the valuable and commonly skipped one, because
it is what isolates retrieval from generation.

**LLM-as-judge: later.** It applies to groundedness and end-to-end only — retrieval has
ground-truth labels and needs no judge. Starting without it is fine. When it arrives it
needs a fixed rubric, low temperature, and periodic spot-checks against human labels,
because an unvalidated judge produces confident numbers that measure nothing.

Caution on public and synthetic corpora: they have no ACLs, no conflicting document
versions, no internal jargon, no badly-scanned appendix. Excellent for building the harness
and catching regressions. They will flatter the scores, and they are not a substitute for a
real corpus when tuning.

## Admin UI

Jinja2 templates with HTMX, served by the same FastAPI process. No build step, no second
deployment, no CORS.

| Screen | Purpose |
|---|---|
| Workspace setup | Create tenant, invite users |
| Connections | Per-user OAuth connect |
| Tools | The real ones, plus a placeholder for adding more |
| Approvals inbox | Makes seam 2 visible |
| Schedules + run history | Makes seam 3 visible |
| Audit log | What enterprise buyers ask to see |
| Knowledge sources | Source config, reindex trigger |
| Evaluation runs | Retrieval and answer scores over time |
| Chat | Exercise the agent before Teams exists |

The approvals inbox and audit log are the demo. They make "autonomous but governed" legible
— more persuasive than the chat, which looks like every other AI product.

Admin/ops UI, not a product surface. The real conversational surface is Teams.

## Infrastructure decisions

| Decision | Choice | Reason |
|---|---|---|
| Queue | Postgres table, `FOR UPDATE SKIP LOCKED` | No new infrastructure; task row and agent checkpoint commit in one transaction |
| Checkpointer | Postgres | Load-bearing: suspend/resume, scheduling, and autonomy all need durable resumable state |
| Scheduler | APScheduler, Postgres jobstore, in worker | Must not run in the API — two replicas would fire every job twice |
| LLM provider | Switchable, Gemini or OpenAI | Abstraction already exists in `llm.py` |
| Web UI auth | Stubbed dev login behind an identity interface | Entra SSO drops in later; identity read from one place, not scattered across handlers |

## Explicitly out of scope

- **Code execution sandbox.** Viktor needs one because it writes and runs code. With a
  handful of fixed tools we do not. Later: a sandboxed sub-agent behind an ordinary tool
  declaration (`irreversible`, approval required) — so the main agent loop does not change
  when it arrives.
- OCR, table and figure extraction from PDFs.
- Document formats beyond PDF, Markdown, plain text.
- Teams app store packaging and certification.
- Streaming responses.
- Automation *proposals* (the reflection loop) — a demo flourish, not a seam.
- Multi-agent orchestration, self-hosting story.
- Artifact/file outputs. No tool in v1 produces a file.
- Self-serve tenant provisioning. Seeded by CLI.
- LLM-as-judge evaluation.

## Dependency order

Not a plan — build order is decided at development time. This records only what genuinely
depends on what, so an ordering choice is made with the constraints visible.

1. **Knowledge layer** — the deep dive. Indexing and retrieval, with the evaluation harness
   built alongside rather than after, so changes are measurable from the start.
2. **Seams 1 and 4** — identity and isolation. Mostly schema: `tenant_id`, RLS,
   `TurnContext`, employee config, ACL enforcement in retrieval.
3. **Seam 2** — Postgres checkpointer, task queue, worker, approval gating. The structural
   core.
4. **Seam 3** — scheduling. Nearly free once 2 exists.
5. **Admin UI** — the screens plus chat.
6. **Teams adapter** — last, over the top.

The two constraints worth knowing when choosing an order:

- **`tenant_id` should exist before anything is indexed in earnest.** Anything indexed
  without it needs re-indexing. A column nothing reads costs nothing; re-embedding a corpus
  costs real time.
- **Teams is cheapest last.** It is the premise of the product, but debugging an unstable
  agent through a dev tunnel is slow. With `TurnContext` right, the adapter stays thin
  whenever it lands.

## Deferred to build time

- Approval timeout semantics. (Who approves is resolved: the requester — see Approval.)
- Ingestion trigger: queued rather than in-request, reusing the worker.
- **Pass E only** — which provider backs the per-user OAuth action tool. Microsoft Graph is
  the right product integration, but the on-behalf-of exchange from a Teams bot is the
  fiddliest part of the build. Not worth settling until pass E, by which point Azure is
  likely provisioned and Graph is cheap. Nothing before pass E needs per-user credentials at
  all — see [Two kinds of connection](#two-kinds-of-connection).

Resolved: reranker is a cross-encoder — deterministic, no per-query model cost, and an LLM
reranker can replace it if the evaluation numbers justify it.

Also agreed: Teams chat history is **memory, not corpus** — recent messages are passed as
turn context rather than chunked and embedded. It arrives with the Teams adapter in pass I,
where the conversation reference already exists.




## Architecture

❯ How someone shold share or explain about the architecture even for interview or anyone. I know how to tell what it is what it does and what under neath it  
  but between both them articture comes so how we starts it? also help me in way that allow me to explain any arcticture as well

● The reason that middle part is hard: most people describe the diagram (a list of boxes) when they should describe the reasoning (why those boxes and not    
  simpler ones). A box list is unmemorable and leaves the listener nothing to ask about. A chain of decisions is both memorable and interrogable.

  Here's the bridge, then the general method.

  How to start: name the constraint

  The sentence that gets you from what it does into architecture is the one that says why the obvious design fails.

  ▎ "The thing that shapes the whole design is that the coworker often can't answer immediately — it might sit for hours waiting for someone to approve an    
  ▎ email, or wake up at 9am Monday with nobody around. So it can't be a normal request-and-response web app. It's split into something that accepts work and 
  ▎ something that does work, with a queue in between."

  Two sentences, and you've crossed over. The listener now has the fundamental shape, and everything you say next feels inevitable instead of arbitrary.      
  That's the whole trick: architecture explained as forced choices, not as an inventory.

  The five beats

  This works for any system, at any length. You expand or compress each beat.

  ┌───────────────────────────┬──────────────────────────────────────────────────┬────────────────────────────────────────────────────────────┐
  │           Beat            │                   What you say                   │                        Why it works                        │
  ├───────────────────────────┼──────────────────────────────────────────────────┼────────────────────────────────────────────────────────────┤
  │ 1. Purpose                │ What it does, for whom, in one sentence          │ Without it, every component sounds arbitrary               │
  ├───────────────────────────┼──────────────────────────────────────────────────┼────────────────────────────────────────────────────────────┤
  │ 2. The shaping constraint │ The requirement that rules out the simple design │ Makes the rest feel inevitable                             │
  ├───────────────────────────┼──────────────────────────────────────────────────┼────────────────────────────────────────────────────────────┤
  │ 3. One request's journey  │ Follow a single concrete request end to end      │ Narrative is memorable; a static diagram isn't             │
  ├───────────────────────────┼──────────────────────────────────────────────────┼────────────────────────────────────────────────────────────┤
  │ 4. The boundaries         │ What's separated, and what breaks without it     │ Architecture is boundaries — components are implementation │
  ├───────────────────────────┼──────────────────────────────────────────────────┼────────────────────────────────────────────────────────────┤
  │ 5. What you left out      │ Deliberate omissions, with reasons               │ The strongest seniority signal available, and it's free    │
  └───────────────────────────┴──────────────────────────────────────────────────┴────────────────────────────────────────────────────────────┘

  Beat 3 is the one people skip and it's the most valuable. It also solves ordering for you — follow the request and the components arrive in the order they  
  matter, so you never have to say "oh, and there's also a…"

  Beat 5 is what separates a junior from a senior answer. Juniors list everything they built. Seniors say what they chose not to build.

  Worked: your system in about two minutes

  ▎ Purpose. It's an autonomous AI coworker that lives in a company's Microsoft Teams. You @mention it like a colleague and it does real work — searches      
  ▎ internal documents, queries systems, takes actions.
  ▎
  ▎ Constraint. The hard part isn't answering questions, it's that work doesn't finish inside a conversation. It might need approval before sending something,
  ▎ or run on a schedule with nobody there. So the architecture is shaped by one requirement: a unit of work has to outlive the request that created it.      
  ▎
  ▎ One request. Someone @mentions it in Teams. Teams posts to our API, which validates it, works out who's asking and what they're allowed to see, writes a  
  ▎ task, and acknowledges — Teams needs a reply in seconds, so we never try to answer there. A worker picks up the task, runs the agent loop: it searches the
  ▎ document corpus, filtered to that person's permissions, decides whether it needs another search, and when it has an answer it posts back into the
  ▎ channel.
  ▎
  ▎ If it wants to do something sensitive — send an email — it stops. The turn is written to the database, the worker moves on, and an approver gets a card.  
  ▎ When they approve, a different worker picks it back up and continues. That's the same path a scheduled task takes, just triggered by a clock instead of a 
  ▎ person.
  ▎
  ▎ Boundaries. Three that matter. The channel adapter is separated from the agent, so Slack later is an adapter not a rewrite. The dispatcher sits between   
  ▎ the model and every tool — it holds credentials, so the model never sees one. And identity travels with the request all the way down into the search      
  ▎ filter, which is what makes per-user permissions real rather than decorative.
  ▎
  ▎ Left out. No code execution sandbox — it's the biggest capability gap, deliberately deferred, because a handful of fixed tools proves the architecture    
  ▎ without it. Three tools, not three hundred. And one layer goes deep — retrieval — because that's the capability being demonstrated; everything else is a  
  ▎ thin slice.

  That's roughly 300 words and it demonstrates reasoning at every step. Compress to 30 seconds by keeping beats 1, 2, and the shape from 3.

  Altitude control

  Three levels. Pick one and stay there until invited down:

  1. What it does — any audience
  2. How it's shaped — technical peer
  3. How it's built — someone implementing it

  The common failure is dropping two levels mid-sentence: "it's a coworker in Teams that uses SELECT FOR UPDATE SKIP LOCKED". Watch for the signals — "but how
  does X actually happen?" means go down a level; a glazed look means go up.

  The three questions you will always get

  Architecture conversations are Q&A, not a monologue. Prepare these and you're prepared:

  "Why not just do X?" — where X is simpler. Always have the failure mode ready. "We could run the agent inside the HTTP request — that's where we started. It
  breaks the moment something waits on a human, because no request survives hours." If you can't name what the simpler thing was, that's usually a sign of    
  over-engineering.

  "What breaks? How does it scale?" — have one concrete failure and its answer. "The queue is a Postgres table, which caps out around a few hundred tasks a
  second. We're nowhere near, and when we are it's a swap to Service Bus."

  "What would you change?" — "nothing" is the wrong answer. "Retrieval went deep before isolation existed, so anything indexed early needs re-indexing. I'd   
  have put the tenant column in first — it costs nothing when nothing reads it."

  Two habits that do most of the work

  Lead with verbs, not nouns. "The worker runs turns" beats "there is a worker component." Nouns are inert; verbs carry the mechanism, which is what the      
  listener is actually trying to build in their head.

  State limits alongside choices. "Postgres as the queue — cheap to operate, caps out in the hundreds per second, fine for us." Naming the ceiling is what    
  makes the claim credible. Someone who only lists advantages sounds like they've never operated anything.

  The underlying thing, if you remember one sentence: every architecture is a set of answers to constraints, so explain the constraints and the answers       
  explain themselves.
