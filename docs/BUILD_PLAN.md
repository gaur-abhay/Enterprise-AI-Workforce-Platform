# Build Plan

How the prototype in [SCOPE.md](SCOPE.md) gets built. The scope does not change here — only
the order and the thickness of each pass.

## Approach: walking skeleton, then thickening passes

One thin path through **every** layer first, then deepen a layer at a time.

The alternative — finish each layer before starting the next — hides integration problems
until the end and leaves nothing demonstrable for weeks. A walking skeleton surfaces the
joints on day one, and there is always something to show.

So the knowledge layer still gets the depth, just not before the skeleton stands up.

## Invariants

Thin is fine. These are not, because retrofitting each one is expensive in a specific way:

| Invariant | Cost of retrofitting |
|---|---|
| `tenant_id` on every table, RLS on | Re-index the corpus, audit every query |
| `acl_principals` **column** present (filter can wait) | Re-index the corpus |
| `TurnContext` threaded, not a bare `thread_id` | Touch every call site |
| `run_turn(ctx, message)` pure — no HTTP, no framework | Restructure the API and the worker |
| Tools as declarations behind a dispatcher, even with one tool | Rewrite every tool |
| ORM + Alembic from the first migration | Hand-write a baseline migration later |

Everything else is additive and safe to defer: ACL *enforcement*, hybrid search, reranking,
the queue, approvals, memory, scheduling, per-user OAuth, Teams, LLM-as-judge.

The distinction that matters most: **tenant isolation is not ACL.** Isolation is structural
and cannot wait. ACL is one `AND` clause on a column that already exists, and an empty array
already means unrestricted — so it waits safely.

## Milestone 1 — walking skeleton

Thinnest end-to-end path that touches every layer.

**Done when:** two isolated tenants are seeded, a corpus is indexed for each, a question
asked over REST returns a cited answer drawn only from that tenant's documents, a test
proves tenant A cannot read tenant B, and a baseline retrieval score exists.

| Layer | Thin in M1 | Thickens in |
|---|---|---|
| Control | tenant, user, employee; RLS on; seed CLI | B, E |
| Knowledge — ingest | directory source, PDF/MD/TXT, chunk, embed, index, incremental sync | A |
| Knowledge — retrieve | vector search, tenant pre-filter, citations | A, B |
| Action | one tool, `search_documents`, through the dispatcher | D, E |
| Agent | basic loop, `run_turn()` pure | C |
| Evaluation | recall@k over a question set — the baseline number | A, H |
| UI | one chat page | G |
| Memory · Execution · Scheduling · Teams | none | C, D, F, I |

Two notes on what is *in* M1 and might look premature:

**The dispatcher, with one tool.** A single tool could call the database directly. But the
dispatcher is where policy, credentials and audit live, and adding it after three tools
exist means rewriting all three. One tool through the real path costs almost nothing.

Every piece of it exists in M1; none of them are sophisticated. What matters is that
`run_turn → dispatcher → policy → credentials → execute → audit` is a real call chain from
the first commit — adding a link to a chain that already runs is trivial, inserting one into
tools that bypass it is not.

| Piece | Thin in M1 | Thickens to |
|---|---|---|
| Registry | Module-level dict, one entry; declaration *shape* complete | Per-tenant tool grants |
| Validation | Pydantic model from the declared schema | — |
| Policy | One function: `read` → none, `irreversible` → always, `write` → tenant default | Policy table, per-class rules, self-approval |
| Credentials | Resolver returning `None`; M1's tool needs none | Vault lookup, per-user OAuth |
| Audit | One table, one row per call | Diffing, retention, UI view |
| Errors | Catch, audit, return a tool-error the model can recover from | Retries, circuit breaking |

Two pieces have a floor and cannot be thinner:

- **Audit writes rows from M1.** The only component where deferring costs something
  permanent — history cannot be backfilled. An audit log starting at pass G is missing
  exactly the period of fastest iteration. Nothing reads the rows until the UI exists; write
  them anyway.
- **`side_effect_class` on every declaration.** M1's only tool is `read`, so it looks
  pointless. But the hard floor — irreversible always requires approval — is enforced by
  reading that field. A tool added without it does not fail loudly; the rule just silently
  stops applying.

The dispatcher returns `Ok | Error | PendingApproval` from the start. M1 never constructs
the third, but widening the type later means changing a signature the agent loop branches
on.

**A minimal evaluation harness.** M1's retrieval is vector-only — which is exactly the
baseline every later change should be measured against. Scoring it at the end of M1 turns
pass A and B from opinion into measurement. Without the baseline, "hybrid search helped" is
a guess.

## Thickening passes

Independently valuable, reorderable. Dependencies noted.

| Pass | Work | Done when |
|---|---|---|
| **A** · Knowledge depth 1 | Metadata extraction, structure-aware chunking, contextual headers, parent/child | Retrieval score beats the M1 baseline, measurably |
| **B** · Knowledge depth 2 | Hybrid search (dense + `tsvector`, RRF), reranking, query rewriting | Score beats pass A; exact identifiers are findable |
| **C** · Execution plane | Task queue, worker process, Postgres checkpointer; API becomes accept-and-enqueue | A turn survives a worker restart mid-flight |
| **D** · Approvals *(needs C)* | Second tool (write), approval gating, suspend/resume | A turn pauses and a *different* worker resumes it → seam 2 |
| **E** · ACL + per-user OAuth | Turn on `acl_principals` filtering; connection store, secrets vault, live-read tool | Two users, same question, different answers → seam 1 |
| **F** · Scheduling *(needs C)* | Schedules, APScheduler in worker, run history, permission re-resolution | A task fires unattended and posts proactively → seam 3 |
| **G** · Admin UI | The remaining screens: connections, tools, approvals inbox, schedules, audit, sources | The demo is clickable end to end |
| **H** · LLM-as-judge | Groundedness and end-to-end scoring on the held-out set | Answer quality has a number, not an impression |
| **I** · Teams adapter | Bot registration, activity handling, Adaptive Card approvals, proactive messaging | The actual premise works |
| **J** · Memory | The five scopes, writes as a tool, the disclosure rule | Actor memory provably does not leak into a channel reply |

Seam 4 (tenant isolation) is proven in M1, not in a pass — it is an invariant, so it has to
be true from the first migration.

## Datasets

Three Hugging Face datasets, each mapped to one job. All too large to use whole; subsets
only.

| Dataset | Role | Where it lives |
|---|---|---|
| Organisation knowledge corpus | The thing being indexed | `data/` for fast local iteration, and a Blob container to exercise that source path |
| Questions derived from the corpus | Retrieval scoring, tuning | In the repo — small, and versioned alongside the retrieval code it tests |
| ~100 curated Q&A | End-to-end and LLM-as-judge | In the repo, **held out** |

Four things that will quietly ruin the numbers if missed:

**Subset coherently, not randomly.** Take a related slice of the corpus. Random sampling
breaks the question-to-document links, so the question set ends up referencing documents
that were never indexed.

**Filter the question set to the indexed subset.** Any question whose source document is not
in the corpus subset is unanswerable, and scoring it counts a correct system as a failure.
Recall numbers are meaningless without this step.

**Tune on the derived questions, hold out the curated set.** Tuning against the curated set
destroys its only value. It is the set that answers "is this actually good", and it can only
answer that once.

**Size the subset by re-index time, not by realism.** During passes A and B the corpus gets
re-indexed many times — every chunking change forces it. A subset that takes minutes keeps
the loop tight; one that takes an hour will stop the deep dive happening at all.

## Structure

```
src/ai_employee/
  config.py · context.py (TurnContext) · observability.py

  db/
    session.py           engine, session factory, RLS binding
    models/              ORM models, one module per aggregate
    migrations/          alembic

  knowledge/
    sources/ loaders/ chunking.py embeddings.py
    pipeline.py          ingest orchestration
    retrieval.py         hybrid search — Core / raw SQL lives here
    evaluation/          harness, metrics, datasets

  agent/
    graph.py prompts.py memory.py
    runner.py            run_turn() — the pure entrypoint

  tools/
    registry.py dispatcher.py  + one module per tool

  execution/
    queue.py worker.py checkpointer.py approvals.py scheduler.py

  channels/
    teams/               adapter, cards, activity handling

  api/
    main.py · routers/ · schemas/ · templates/ · static/

  cli/                   seed, ingest, eval
```

Directories arrive empty-but-present only where M1 fills them. `execution/`, `channels/` and
the rest appear with their pass.

Two boundaries worth stating: ORM models in `db/models` are never the same classes as the
Pydantic wire models in `api/schemas`, and `channels/teams` is the only place that knows
what a Teams Activity is.

Skipped deliberately: a `repositories/` layer wrapping the ORM. Textbook, but ceremony at
this size. Services use sessions directly; it gets added only if ORM calls start leaking
everywhere.

## Decisions

| Decision | Choice | Why |
|---|---|---|
| ORM | SQLAlchemy, sync | Async buys nothing — the agent blocks on the model, and the worker is already a separate process |
| Retrieval query | SQLAlchemy Core / raw SQL | Fused vector + lexical + array-overlap needs query-plan control; the ORM fights it |
| Migrations | Alembic from migration one | `schema.sql` already carries a comment admitting it needs this |
| RLS | Set in one session factory | `SET LOCAL app.tenant_id` scattered across call sites makes RLS decorative |
| Tree | Build in place, delete old modules as replaced | One tree, one truth; git holds the old version |
| Old `/chat` | Let it break during the restructure | No users, and a shim that gets deleted is wasted work |

## Ported, not assumed

Three pieces from the previous codebase are worth keeping, and get read line by line with
tests around them rather than trusted:

- the source abstraction's change tokens (Azure ETag, local `mtime:size`) for incremental sync
- `observability.py` — the correlation-id contextvar, and the sanitising of caller-supplied
  ids before they reach a log line
- the chunker's undersize-merge rule, so a heading rides with the section it introduces

Everything else is rewritten.