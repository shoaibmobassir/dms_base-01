# Durable Run Runtime: design doc

Status: proposal, **Rev 2.2** · Scope: Assistant (`app/chat`) · Builds on: `ASSISTANT_ARCHITECTURE.md`

This document replaces the request-bound agent loop with a **durable, resumable, observable Run**. It covers schema, state machine, worker/lease/fencing, write-ahead tool calls, recovery-by-fold, idempotency, cancellation with side effects, event protocol, notes/evidence, plan/task, tool metadata, migration phases and the test matrix. Part II (§22) adds the legal research subsystem. Appendix A logs what changed in each revision and why.

---

## 1. Problem

Today a turn is one HTTP request: `send_message` → SSE generator → `run_chat_agent`. Consequences:

| Limitation | Cause |
|---|---|
| Hard 180 s / 10-round ceiling | Work is bound to the request process |
| Browser disconnect = awkward Stop path | SSE generator *is* the executor |
| Worker crash = lost turn | No persisted execution state |
| `ask_inputs` ends the turn; answer = new message | No resume protocol |
| Old tool output is stubbed by `fit_context` and findings are lost | No durable semantic state |
| Retrieval seeded from the raw user string | Seed happens in the router before the agent has context |
| `session_doc_cache` inconsistent across workers | Per-process LRU |

## 2. Goals and non-goals

**Goals**

1. A turn is a **Run** owned by a worker, not by a browser connection.
2. Crash, disconnect, timeout and human waits are all **resumable** from persisted state.
3. Mutating tool calls are **never duplicated** by recovery, and an unverifiable effect surfaces as an explicit `unknown`.
4. The UI consumes an **append-only event log** with replay (`Last-Event-ID`).
5. Interactive and background work share **one runtime**.
6. Zero change to prompts, retrieval, grounding, DocIndex or tool semantics in phase 1.

**Non-goals (v1)**

Separate planner/executor/evaluator models, a task-classifier LLM call, Matter Graph, Evidence Graph, Monitors, client Portal, sub-agent orchestration, manual pause/resume, multiple concurrent runs per session (designed for, not built), an owned legal corpus or citator (Part II integrates licensed ones).

## 3. Principles

1. **The worker never knows whether a browser is connected.**
2. **Every state write is fenced** by the lease epoch, so a zombie worker cannot corrupt state.
3. **Write-ahead the model's decision** (assistant message + tool calls) before executing anything.
4. **State is a fold over write-ahead records.** Checkpoints are snapshots of that fold, never a second source of truth.
5. **Effects are idempotent at the target**, not just "keyed". Fencing protects the database, not the outside world.
6. **Notes may only cite evidence the system created** from a located source span.
7. **ACL is re-evaluated on every claim, every document read and every evidence read.** Nothing is cached across a pause.
8. **The event log is the source of truth.** Pub/sub only wakes readers; a missed wake-up costs latency, never correctness.
9. **One place owns state transitions.** Worker, sweeper and API all go through the same transition module.
10. **Events are the UI contract.** Reuse existing SSE event types; add new ones.

---

## 4. Concepts

| Concept | Meaning |
|---|---|
| **Run** | One execution of the agent for one user message (or continuation) |
| **Turn / round** | One LLM call inside a run plus its tool calls, indexed by `round` |
| **Event** | Immutable, sequenced record of something the UI can render |
| **Checkpoint** | Snapshot of *derived* state after a completed round (no messages) |
| **Tool call** | A persisted, individually tracked invocation with a stable `call_id` |
| **Span handle** | Deterministic reference to a source passage returned by a tool: `(call_id, index)` |
| **Evidence** | System-created, ACL-guarded pointer to a verified quote in a source |
| **Note** | Compact finding/decision/hypothesis the agent writes; factual notes must cite evidence |
| **Task** | Goal/scope/deliverable/expected duration the model declares in `update_plan` |
| **Session context** | Small cross-run state: matter lock, active docs, resolved entities, constraints |
| **Lane** | `interactive` (priority, tight budget) or `background` (long budget) |
| **`lease_epoch`** | Fencing token, bumped on every claim and every release/requeue |
| **`attempt`** | Crash-recovery counter, bumped **only** when an expired run is requeued |

---

## 5. State machine and the transition module

```mermaid
stateDiagram-v2
  [*] --> QUEUED
  QUEUED --> RUNNING: worker claims (lease)
  RUNNING --> QUEUED: lease expired, attempt < max
  RUNNING --> WAITING_INPUT: ask_inputs
  RUNNING --> WAITING_APPROVAL: gated tool call(s)
  RUNNING --> COMPLETED: final answer persisted
  RUNNING --> FAILED: fatal error / attempts exhausted
  RUNNING --> CANCELLED: cancel_requested observed
  WAITING_INPUT --> QUEUED: answer received
  WAITING_APPROVAL --> QUEUED: all decisions received
  WAITING_INPUT --> FAILED: wait TTL expired
  WAITING_APPROVAL --> FAILED: wait TTL expired
  QUEUED --> CANCELLED: user Stop
  WAITING_INPUT --> CANCELLED: user Stop
  WAITING_APPROVAL --> CANCELLED: user Stop
  COMPLETED --> [*]
  FAILED --> [*]
  CANCELLED --> [*]
```

Promotion from interactive to background is **not** a state: it is an in-place lane change by the lease holder (§12).

Transition table (authoritative):

| From | To | Trigger | Side effects |
|---|---|---|---|
| QUEUED | RUNNING | worker claim | `lease_owner` set, `lease_epoch += 1`; `run_resumed` event (with `reason`: `crash_recovery` \| `input` \| `approval`) unless it is the first claim |
| RUNNING | QUEUED | sweeper: lease expired and `attempt < max_attempts` | lease cleared, `lease_epoch += 1`, **`attempt += 1`**, `run_status` event |
| RUNNING | FAILED | fatal error, or lease expired and `attempt >= max_attempts` | `error` event, partial answer projected |
| RUNNING | WAITING_INPUT | `ask_inputs` | `input_requested`, `pending` set, `wait_expires_at`, lease released, `lease_epoch += 1` |
| RUNNING | WAITING_APPROVAL | one or more gated calls in the round | `approval_requested` (all gated calls), lease released, `lease_epoch += 1` |
| WAITING_INPUT | QUEUED | input endpoint | `input_provided`, answer stored as the `ask_inputs` call's result, `pending` cleared |
| WAITING_APPROVAL | QUEUED | last outstanding decision received | `approval_decided` events, decisions stored on the calls |
| WAITING_* | FAILED | `wait_expires_at` passed | `error` (reason `wait_expired`), partial projected |
| any non-terminal | CANCELLED | Stop | `stopped`, partial projected (see §14 for in-flight effects) |
| RUNNING | COMPLETED | grounding done | `grounding`, `text_final`, `citation_data`, projection, `[DONE]` |

Rules:

- Waiting for input or approval **never consumes `attempt`**. Only crash recovery does.
- Any transition out of RUNNING bumps `lease_epoch`, which invalidates the previous holder.
- A rejected approval is not a failure: the rejection becomes the tool result and the model adapts.

**Transition module (single authority).** Worker, sweeper and API endpoints call one function; nothing else writes `runs.status`:

```python
def transition(run_id, *, fence=None, from_states, to_state, patch=None,
               events=(), reason=None, project=False):
    with tx():
        row = select_for_update(run_id)
        assert row.status in from_states
        if fence: assert (row.lease_owner, row.lease_epoch) == fence   # worker-initiated
        apply(row, patch, to_state)
        if row.status == "RUNNING" and to_state != "RUNNING":
            row.lease_epoch += 1; row.lease_owner = None
        seqs = allocate_seq(row, len(events))                          # same txn
        insert_events(run_id, seqs, events)
        if to_state in TERMINAL or project:
            project_to_chat_message(row)                               # idempotent, keyed by run_id
```

The sweeper is just a loop that finds expired rows `FOR UPDATE SKIP LOCKED` and calls `transition`. There is no `REQUEUEING` state: a single transaction makes the change atomic.

---

## 6. Schema

```sql
-- ─────────── runs ───────────
CREATE TABLE runs (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id       uuid NOT NULL REFERENCES chat_sessions(id),
  user_message_id  uuid NOT NULL REFERENCES chat_messages(id),
  message_id       uuid NOT NULL REFERENCES chat_messages(id),   -- reserved assistant row
  member_id        uuid NOT NULL,
  matter_id        uuid,
  parent_run_id    uuid REFERENCES runs(id),                     -- continuation of an earlier run
  status           text NOT NULL CHECK (status IN
    ('QUEUED','RUNNING','WAITING_INPUT','WAITING_APPROVAL',
     'COMPLETED','FAILED','CANCELLED')),
  lane             text NOT NULL DEFAULT 'interactive' CHECK (lane IN ('interactive','background')),
  mode             text NOT NULL DEFAULT 'reason',               -- reason|research|review|cite
  input            jsonb NOT NULL,        -- snapshot, see §7.1
  budget           jsonb NOT NULL,        -- {max_rounds,max_tokens,max_cost,deadline_at}
  usage            jsonb NOT NULL DEFAULT '{}',
  plan             jsonb,                 -- latest update_plan steps
  task             jsonb,                 -- declared via update_plan, see §10.3
  pending          jsonb,                 -- ask_inputs form or approval requests
  wait_expires_at  timestamptz,
  cancel_requested boolean NOT NULL DEFAULT false,
  lease_owner      text,
  lease_expires_at timestamptz,
  lease_epoch      bigint NOT NULL DEFAULT 0,   -- fencing token
  attempt          int NOT NULL DEFAULT 1,      -- recovery attempt, bumped only by crash recovery
  max_attempts     int NOT NULL DEFAULT 3,
  fold_version     int NOT NULL DEFAULT 1,      -- fold_round() version this run was created with; recovery uses the same one
  last_seq         bigint NOT NULL DEFAULT 0,   -- event sequence allocator
  error            jsonb,
  created_at       timestamptz NOT NULL DEFAULT now(),
  started_at       timestamptz,
  finished_at      timestamptz,
  updated_at       timestamptz NOT NULL DEFAULT now()
);

-- v1: one active run per session. To allow background runs alongside one
-- interactive run later, add `AND lane = 'interactive'` to the predicate (see §20).
CREATE UNIQUE INDEX runs_one_active_per_session ON runs(session_id)
  WHERE status IN ('QUEUED','RUNNING','WAITING_INPUT','WAITING_APPROVAL');
CREATE INDEX runs_claim ON runs(lane, created_at) WHERE status = 'QUEUED';
CREATE INDEX runs_lease ON runs(lease_expires_at) WHERE status = 'RUNNING';
CREATE INDEX runs_wait  ON runs(wait_expires_at)
  WHERE status IN ('WAITING_INPUT','WAITING_APPROVAL');

-- ─────────── event log ───────────
CREATE TABLE run_events (
  run_id     uuid NOT NULL REFERENCES runs(id),
  seq        bigint NOT NULL,
  type       text NOT NULL,
  payload    jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (run_id, seq)
);

-- ─────────── write-ahead model turns ───────────
CREATE TABLE run_turns (
  run_id            uuid NOT NULL REFERENCES runs(id),
  round             int  NOT NULL,
  kind              text NOT NULL DEFAULT 'turn' CHECK (kind IN ('turn','wrap_up')),
  assistant_message jsonb NOT NULL,   -- text + tool_calls with fixed call_ids
  usage             jsonb,
  attempt           int NOT NULL,
  created_at        timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (run_id, round)
);

-- ─────────── tool calls ───────────
CREATE TABLE run_tool_calls (
  id              uuid PRIMARY KEY,                  -- call_id, assigned when the turn is persisted
  run_id          uuid NOT NULL REFERENCES runs(id),
  round           int  NOT NULL,
  idx             int  NOT NULL,
  name            text NOT NULL,
  args            jsonb NOT NULL,
  args_hash       text NOT NULL,                     -- sha256 of canonical args; approvals bind to this
  risk            text NOT NULL,                     -- read|draft|mutate|external_send|control
  status          text NOT NULL CHECK (status IN
    ('planned','awaiting_approval','approved','rejected',
     'started','succeeded','failed','unknown','cancelled')),
  idempotency_key text NOT NULL,                     -- f(run_id, call_id)
  approved_by     uuid,
  approved_at     timestamptz,
  decision_reason text,
  result          jsonb,                             -- small results inline (includes spans, new aliases)
  result_ref      text,                              -- object-store key for large results
  effect_ref      text,                              -- artifact / version / export id for verification
  error           jsonb,
  attempt         int,
  started_at      timestamptz,
  finished_at     timestamptz,
  UNIQUE (run_id, round, idx)
);

-- ─────────── checkpoints (derived state only) ───────────
CREATE TABLE run_checkpoints (
  run_id     uuid NOT NULL REFERENCES runs(id),
  round      int  NOT NULL,
  state      jsonb NOT NULL,   -- see §9
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (run_id, round)
);

-- ─────────── evidence & notes ───────────
CREATE TABLE evidence (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id          uuid NOT NULL REFERENCES runs(id),
  type            text NOT NULL CHECK (type IN ('document','authority','email','record')),
  source_id       text NOT NULL,          -- document_id / authority id / email id
  source_version  text,                   -- document version or content hash
  locator         jsonb NOT NULL,         -- {page, section, start_char, end_char}
  quote           text,                   -- copied from SOURCE text at located offsets; NULL once purged
  quote_hash      text NOT NULL,
  tool_call_id    uuid REFERENCES run_tool_calls(id),
  purged_at       timestamptz,
  created_at      timestamptz NOT NULL DEFAULT now(),
  UNIQUE (run_id, source_id, source_version, quote_hash)
);

CREATE TABLE run_notes (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id       uuid NOT NULL REFERENCES runs(id),
  round        int  NOT NULL,
  kind         text NOT NULL CHECK (kind IN ('finding','decision','hypothesis','open_question')),
  text         text NOT NULL,
  evidence_ids uuid[] NOT NULL DEFAULT '{}',
  tool_call_id uuid REFERENCES run_tool_calls(id),   -- the update_notes call that wrote it
  idx          int NOT NULL DEFAULT 0,
  created_at   timestamptz NOT NULL DEFAULT now(),
  CHECK (kind NOT IN ('finding','decision') OR cardinality(evidence_ids) >= 1),
  UNIQUE (tool_call_id, idx)             -- replay-safe: re-running update_notes cannot duplicate
);

-- ─────────── session context (cross-run) ───────────
CREATE TABLE session_context (
  session_id         uuid PRIMARY KEY REFERENCES chat_sessions(id),
  matter_id          uuid,
  resolved_entities  jsonb NOT NULL DEFAULT '{}',   -- {"that agreement": doc_id, ...}
  active_documents   jsonb NOT NULL DEFAULT '[]',   -- superset of today's working_set
  constraints        jsonb NOT NULL DEFAULT '[]',   -- [{id, text, superseded_by}]
  version            int NOT NULL DEFAULT 0,
  updated_by_run     uuid,
  updated_at         timestamptz NOT NULL DEFAULT now()
);
```

Notes on the schema:

- **`lease_epoch` vs `attempt`.** The earlier draft used one counter for both. Because it was bumped on every claim, a run that legitimately waited for input or approval three times would have exhausted `max_attempts = 3` and failed. They are now separate: `lease_epoch` fences, `attempt` counts crash recoveries only.
- **Tool call status lifecycle:** `planned` → (`awaiting_approval` → `approved` | `rejected`) → `started` → `succeeded` | `failed` | `unknown`. `cancelled` is for calls that never started or were aborted. `approved` means *authorized but not yet started*. It is a real, observable state because a run may sit in QUEUED between approval and execution.
- `run_notes` cannot be `finding`/`decision` without evidence, enforced in the database.
- `evidence` rows are created **only** by system code, and `quote` is copied from the **source text** at the located offsets, never from the model's string.
- `session_context` replaces a per-run context table and subsumes today's `working_set` event.

---

## 7. Run lifecycle

### 7.1 Creation (API process)

`POST /api/chat/sessions/{id}/messages` (same path and SSE contract as today):

1. Rate limit, ownership check, persist user message (as today).
2. Reserve the assistant row (as today).
3. Run the retrieval seed (`_search`) and build the initial DocIndex **now**, then snapshot into `runs.input`:

```jsonc
{
  "user_text": "...",
  "attachments": [...],
  "history_message_ids": [...],          // window already selected
  "matter_scope": {"id": "...", "code": "MTR-…", "title": "…"},
  "seed_hits": [...],                    // passages/docs with scores
  "doc_index": {"doc-0": {"document_id": "...", "version": "...", "title": "..."}},
  "session_context_version": 7,
  "mode": "reason"
}
```

4. Insert the `runs` row as `QUEUED`. The partial unique index gives a clean `409` (with the active `run_id`) if the session already has an active run.
5. Open an SSE tail of the new run and return it.

Snapshotting makes resumed and retried runs deterministic. Retrieval is **not** re-seeded on resume.

### 7.2 Claim (worker)

```sql
UPDATE runs SET
  status = 'RUNNING',
  lease_owner = $worker,
  lease_expires_at = now() + interval '30 seconds',
  lease_epoch = lease_epoch + 1,
  started_at = COALESCE(started_at, now()),
  updated_at = now()
WHERE id = (
  SELECT id FROM runs
  WHERE status = 'QUEUED'
  ORDER BY (lane = 'interactive') DESC, created_at
  FOR UPDATE SKIP LOCKED
  LIMIT 1
)
RETURNING *;
```

The worker's fence is `(lease_owner, lease_epoch)` as returned. Identity is re-resolved on every claim (§15). Lease expiry always uses **database time** (`now()`), never worker clocks.

**Sweeper** (every ~10 s, inside the transition module):

```python
for run in select_expired_running(limit=50, skip_locked=True):
    if run.attempt < run.max_attempts:
        transition(run.id, from_states=["RUNNING"], to_state="QUEUED",
                   patch={"attempt": run.attempt + 1},
                   events=[run_status("requeued", reason="lease_expired")])
    else:
        transition(run.id, from_states=["RUNNING"], to_state="FAILED",
                   patch={"error": {"code": "attempts_exhausted"}},
                   events=[error("attempts_exhausted")], project=True)
for run in select_expired_waits(limit=50, skip_locked=True):
    transition(run.id, from_states=["WAITING_INPUT","WAITING_APPROVAL"], to_state="FAILED",
               patch={"error": {"code": "wait_expired"}}, events=[error("wait_expired")], project=True)
```

The `lease_epoch` bump inside `transition` guarantees a stalled original holder can no longer write.

### 7.3 Fencing

Every worker write carries `(run_id, lease_owner, lease_epoch)`:

```sql
-- heartbeat
UPDATE runs SET lease_expires_at = now() + interval '30 seconds'
WHERE id = $1 AND lease_owner = $2 AND lease_epoch = $3 AND status = 'RUNNING';

-- allocate sequence numbers atomically with the fence check
UPDATE runs SET last_seq = last_seq + $n, updated_at = now()
WHERE id = $1 AND lease_owner = $2 AND lease_epoch = $3 AND status = 'RUNNING'
RETURNING last_seq;
```

Zero rows means the lease is lost. The worker must **stop immediately**: abort the in-flight LLM stream, signal tool cancellation, write nothing more. Events, turns, tool-call rows, checkpoints, evidence and notes are all inserted inside the same transaction as the fence update.

Additional rules:

- **Heartbeat runs on an independent thread/task.** Tool timeouts (up to 170 s for batch review) far exceed the 30 s lease, so a blocked tool must never starve the heartbeat. Two missed heartbeats set a `lease_lost` flag that the loop and all tool wait loops observe.
- **Fencing protects the database, not the outside world.** A zombie mid-effect can still complete an external effect. That is covered by target idempotency (§8.4). What fencing does guarantee: the `started` mark is a fenced write, so a zombie can never *begin* a new effect after losing the lease.
- **Single-writer ordering.** Only the lease holder (or the transition module for a released run) appends events, so `seq` commits in order and readers never see a later `seq` before an earlier one.

### 7.4 Worker loop

```python
def work(run, fence):
    state, pending_turn = recover(run, fence)          # §8.2, may need no LLM call
    rnd = state.next_round
    while True:
        fence.check()
        if pending_turn is None:
            if cancel_requested(run):            return finish(CANCELLED)
            if over_budget(run, state):
                if can_promote(run, state):      promote(run, fence)          # §12
                else:                            state.wrap_up = True
            turn = llm(view_for_llm(state),                                   # eviction is a VIEW
                       tools=None if state.wrap_up else visible_tools(run))
            persist_turn(run, fence, rnd, turn)                               # WRITE-AHEAD
        else:
            turn, pending_turn = pending_turn, None                           # recovered, LLM NOT called

        if not turn.tool_calls:
            break                                                             # final-answer candidate

        outcome = execute_calls(run, fence, rnd)                              # §8.3
        if outcome.waiting:
            return release_and_wait(run, fence, outcome)

        state = fold_round(state, rnd)                                        # pure fold
        checkpoint(run, fence, rnd, state)
        rnd += 1

    final = ground(state, turn)                                               # idempotent, no external effects
    commit_completion(run, fence, final)                                      # one transition() txn
```

`execute_calls` preserves current semantics: parallel only when every pending call is `parallel_safe`, UI events in model order, per-tool timeouts, paused tool names.

---

## 8. Write-ahead turns, recovery and idempotency

### 8.1 Write-ahead

If a worker dies mid-round and resume simply re-calls the LLM, the model may emit **different** tool calls, so idempotency keys no longer line up. So:

```
llm response ─► persist run_turns + run_tool_calls(status=planned, call_ids fixed)
            ─► execute ─► persist results (with their events) ─► checkpoint
```

Text deltas stream live during generation, tagged `{round, attempt}`. A turn is only authoritative once `run_turns` has it.

### 8.2 State is a fold; the recovery algorithm

`state = fold(run_turns, run_tool_calls, run_notes, plan)` is a **pure function** of persisted records. Messages are never checkpointed. Tool outputs are referenced (`result` / `result_ref`), and `fit_context` eviction is a **view** computed per LLM call, never baked into stored state. Tool results record the DocIndex aliases they allocated, so alias allocation is replayable.

```python
def recover(run, fence):
    cp = latest_checkpoint(run)                       # may be None
    state = cp.state if cp else initial_state(run.input, session_context)
    start = cp.round + 1 if cp else 0

    for turn in persisted_turns(run, from_round=start):          # ascending
        calls = tool_calls(run, turn.round)

        if not calls:                                  # persisted turn with no tool calls
            return state, turn                         # terminal candidate: ground it, DO NOT call LLM

        todo = []
        for call in calls:                             # by idx
            if call.status in TERMINAL_CALL_STATES:    # succeeded|failed|rejected|cancelled|unknown
                continue                               # result already persisted
            if call.status == "awaiting_approval":
                return park_waiting_approval(run, fence)            # worker died before transitioning
            if call.status in ("planned", "approved"):
                todo.append(call)
            if call.status == "started":
                todo.append(resolve_started(call))     # §8.4: rerun | adopt effect | mark unknown
        if todo:
            outcome = execute_calls(run, fence, turn.round, only=todo)
            if outcome.waiting:
                return park(outcome)

        state = fold_round(state, turn.round)          # rebuild state_after_round WITHOUT the model
        checkpoint(run, fence, turn.round, state)
    return state, None                                 # next step: ask the model for the next turn
```

This closes three crash windows that an "execute the non-terminal calls" rule alone misses:

| Crash point | Recovery |
|---|---|
| Turn persisted, all tools terminal, **no checkpoint** | Fold the persisted results into state, checkpoint, continue. No LLM call |
| Turn persisted with **zero tool calls** (final candidate) | Ground the persisted text. No LLM call. Grounding is idempotent: it only produces events and `commit_completion` |
| Crash mid-generation, no turn persisted | Re-call the LLM. Clients discard unfinished `text_delta`s from earlier attempts on `run_resumed` |

A wrap-up turn is stored like any other turn with `kind = 'wrap_up'`.

### 8.3 Tool call execution

```python
def execute_calls(run, fence, rnd, only=None):
    calls = only or planned_calls(run, rnd)
    gated = [c for c in calls if policy.needs_approval(c)]
    free  = [c for c in calls if c not in gated]

    for call in free:                                  # ungated calls run first (independent by construction)
        fence.check()
        mark(call, "started")                          # FENCED write, committed before any effect
        result = execute_tool(call, idempotency_key=call.idempotency_key, cancel=token)
        persist_result(call, result)                   # status + result + its UI events, one txn

    if gated:                                          # one request for ALL gated calls in the round
        for c in gated: mark(c, "awaiting_approval")
        return Outcome(waiting="approval", calls=gated)
    return Outcome(waiting=None)
```

- **Approval binds to `args_hash`.** The request shows the exact args and hash. The approval endpoint requires the client to echo `args_hash`. At execution time the worker recomputes the hash, **re-runs policy**, and re-checks that referenced sources (e.g. document version) have not changed. A mismatch invalidates the approval and re-requests it (`approval_stale` event).
- **`tool_started` is emitted once per call**, in the same transaction as `mark(started)`. Recovery of a `started` call emits `tool_retry {call_id, attempt}` instead, so the UI timeline never shows duplicate steps.
- Result events (`doc_read`, `review_table`, `edit_proposals`, ...) are emitted **with `persist_result`**, not while the tool runs. A tool that crashes before persisting emits nothing, and the rerun emits exactly once.
- `update_notes` and `update_plan` are ordinary calls. Notes are keyed `(tool_call_id, idx)`, so replay cannot duplicate them.

### 8.4 Recovery of a call found in `started`

A crash can happen after the effect but before the result row. Each tool declares a **recovery strategy**:

| Strategy | Used by | Behavior |
|---|---|---|
| `rerun` | `read_document`, `get_outline`, `find_in_document`, `fetch_documents`, `search_firm_records`, `resolve_matter`, `get_matter_profile`, `find_people`, `ask_firm`, `review_documents`, `edit_document`, `propose_edits`, `update_plan`, `update_notes` | Safe to execute again |
| `verify` | `generate_docx`, `generate_excel`, edit export, future `create_task` | Look up `effect_ref` by deterministic key. If the effect exists, adopt it as the result. Otherwise rerun |
| `manual` | future `send_email`, external mutations | Mark `unknown`. Return the model a tool result "outcome unknown, confirm with the user" and surface a confirm prompt |

Effects must be idempotent at the target:

| Tool | Mechanism |
|---|---|
| `generate_docx` / `generate_excel` | Object key derived from `(run_id, call_id)` plus unique constraint on the artifact row |
| Edit export / new document version | Unique `(message_id, export_hash)` on the version row |
| `edit_document`, `propose_edits` | Produce proposals only (no mutation) |
| External send (future) | Provider idempotency key, or outbox table with unique `(run_id, call_id)` |

### 8.5 Fixed rules

- A run resumes from the **latest checkpoint + fold of later persisted records**.
- Test invariant: `fold(all records) == checkpoint.state + fold(later records)` at every round.
- **The LLM is never called again merely because a checkpoint is missing.** It is called only when the latest persisted turn is fully folded and no final candidate exists.
- **A recovery attempt creates no new logical turn or tool call.** `(run_id, round, call_id)` are identical across `attempt` and `lease_epoch` changes; `attempt` on a turn or call row only records which recovery attempt wrote it.
- **Fold versioning.** `fold_round()` is versioned (`runs.fold_version`, mirrored in each checkpoint). A run recovers with the fold version it was created with, so changing fold logic later never silently reconstructs old runs differently. A new version applies only to new runs, and any change to fold code requires a replay test against stored runs of the previous version.
- Doc text is **not** persisted in run state. It is rehydrated through the normal ACL-checked read path (`session_doc_cache`, moved to Redis keyed by member + version).
- DocIndex aliases are **append-only**. `doc-N` is never renumbered, so earlier citations stay valid.

---

## 9. Checkpoint format (derived state only)

```jsonc
{
  "round": 4,
  "attempt": 2,
  "fold_version": 1,
  "doc_index": {"doc-0": {...}, "doc-1": {...}},   // append-only
  "revoked_aliases": [],
  "plan": { "steps": [ ... ] },
  "task": { ... },
  "notes_cursor": "uuid",              // last run_notes.id included in the notes block
  "usage": {"rounds": 4, "tokens": 81234, "cost_usd": 0.42},
  "matter_scope": {...},
  "session_context_version": 7
}
```

- **No messages.** They are rebuilt from `run_turns` + `run_tool_calls`, so checkpoints stay small and there is exactly one source of truth.
- Keep the **last 3** checkpoints per run. Delete 7 days after the run finishes.
- Tool results above ~32 KB go to the object store; `result_ref` holds the key.
- The always-in-context **notes block** is rebuilt from `run_notes` on every LLM call, so eviction of old tool output never destroys findings.

---

## 10. Notes, evidence, plan/task, session context

### 10.1 Span handles and evidence

The model needs a *handle* to cite, and the system must avoid creating a row for every passage it reads. So:

1. Tools that return source passages (`read_document`, `find_in_document`, `fetch_documents`, `search_firm_records`, `ask_firm`, `review_documents` cells) annotate each returned passage with a **span handle** `(call_id, index)`, resolved from that call's persisted `result.spans[index]` (doc, version, offsets, page/section). No table; deterministic; replay-safe.
2. `update_notes` accepts evidence as `span_handle | evidence_id | {doc, quote}`. On write the system:
   - resolves the span (or locates `{doc, quote}` via `locate_quote`),
   - re-checks **ACL** and that the **source version** still matches,
   - copies the quote from the **source text** at the located offsets (never the model's string),
   - **upserts** the `evidence` row (idempotent via the unique key) and attaches the `evidence_id`.
3. Unknown handles, unlocatable quotes, inaccessible sources → the note is rejected with a tool error.

Evidence is therefore created **when first used**, not eagerly for every read passage. The final-answer grounding path upserts evidence for located quotes too, so notes and citations share provenance.

### 10.2 `update_notes`

```jsonc
{ "notes": [
  {"kind": "finding", "text": "SPA §8.2 permits termination after 30 June 2027", "evidence": ["c7f2a1.3"]},
  {"kind": "hypothesis", "text": "Side letter may override §8.2"},
  {"kind": "open_question", "text": "Which SPA version governs?"}
]}
```

- `finding`/`decision` require evidence (DB check plus validator).
- `hypothesis`/`open_question` are labeled ungrounded in the prompt block and may not appear as facts in the final answer.
- **Grounding integration:** `ground_answer` receives notes plus evidence as additional sources. A claim resting on a hypothesis is flagged or removed.
- Notes whose evidence the member can no longer access are omitted from the notes block (§15).

### 10.3 `update_plan` and the declared task

```jsonc
{ "task": {
    "type": "batch_review",              // lookup | analysis | batch_review | research | drafting | other
    "goal": "Compare 300 NDAs against the firm playbook",
    "scope": "matter MTR-123, all NDAs",
    "deliverable": "review_table",
    "success_criteria": ["every document evaluated", "deviations cited"],
    "expected_duration": "long"          // short | medium | long
  },
  "steps": [
    {"id": "s1", "title": "Find termination provisions", "status": "completed"},
    {"id": "s2", "title": "Compare with side letter", "status": "running"},
    {"id": "s3", "title": "Draft summary", "status": "pending"}
  ]
}
```

- Stored on `runs.plan` and `runs.task`, emitted as `plan_updated`. Statuses: `pending | running | completed | blocked`.
- **No classifier call.** The model declares the task in its first `update_plan`, at no extra latency. The declaration drives promotion eligibility (§12), tool visibility hints, completion review in evals, and the UI header.
- Lawyer edits to the plan arrive as a message/input event and are injected as a constraint.

### 10.4 Session context and conflicts

`session_context` is loaded at run start and updated on completion. Runs write **deltas**, not whole documents:

```jsonc
{ "add_active_documents": [...],
  "set_entities": {"the disclosure letter": "doc-uuid"},
  "add_constraints": [{"id": "c9", "text": "use v3 of the SPA"}],
  "supersede_constraints": [{"id": "c4", "by": "c9"}] }
```

```sql
UPDATE session_context SET ..., version = version + 1
WHERE session_id = $1 AND version = $expected;     -- 0 rows → re-read, re-apply delta
```

Merge rules on conflict: `active_documents` union; `resolved_entities` per-key last writer with timestamp; `constraints` **append-only with explicit supersession**, so "use v3" is never silently overwritten by "use v2". Two conflicting supersessions of the same constraint surface a `context_conflict` event. With one active run per session this is rare in v1, but the rules are fixed now so concurrent runs can be enabled later safely.

---

## 11. Tool metadata and policy

Replace bare schemas with a registry entry per tool:

```yaml
name: generate_docx
schema: {...}
risk: mutate            # read | draft | mutate | external_send | control
timeout_s: 60
parallel_safe: false
requires_approval: false
recovery: verify        # rerun | verify | manual
idempotency: deterministic_object_key
visible_when: [matter_pinned: any]
```

Policy (one check in the dispatcher):

| Risk | Default |
|---|---|
| `read`, `draft` | Auto |
| `mutate` | Auto if reversible and idempotent, else approval |
| `external_send` | Always approval |
| `control` | Handled by the runtime (`ask_inputs`, `update_plan`, `update_notes`) |

Applying a redline to a stored document version, sending email, changing matter metadata and any external mutation are approval-gated. Nothing is autonomous-delete.

Tools that send data outside the firm carry `egress: external` in their metadata. The runtime applies the outbound query policy and audit from §22.11 before dispatch. Legal research tools are defined in §22.5.

Initial classification:

| Tool | Risk | Recovery |
|---|---|---|
| `search_firm_records`, `read_document`, `get_outline`, `fetch_documents`, `find_in_document`, `resolve_matter`, `get_matter_profile`, `find_people`, `ask_firm`, `list_workflows`, `read_workflow` | read | rerun |
| `review_documents` | read (cached) | rerun |
| `edit_document`, `propose_edits` | draft | rerun |
| `generate_docx`, `generate_excel` | mutate (creates artifact) | verify |
| edit export (API) | mutate | verify |
| `ask_inputs`, `update_plan`, `update_notes` | control | rerun / n.a. |

---

## 12. Budgets, lanes and promotion

| | interactive | background |
|---|---|---|
| Priority | high (claimed first) | normal |
| `max_rounds` | 10 | 40 |
| Deadline | 180 s | 30 min (configurable) |
| Wrap-up | 60 s | 120 s |
| `max_cost` | per-member cap | per-run cap |

**Promotion** happens in place: the lease holder swaps `lane` and `budget` in one fenced transaction and keeps running. It is **not automatic** for every slow turn. It requires:

```text
can_promote =
      run.task.expected_duration in ("medium", "long")
  AND run.task.type != "lookup"
  AND progress in the last N rounds (new evidence, notes, or a plan step advanced)
  AND member is under the background concurrency/cost quota
```

- On promotion emit `run_status {state: "RUNNING", lane: "background", reason: "interactive_budget_exhausted"}` and notify on completion.
- If not eligible, the run wraps up with its partial result and the UI offers "continue in the background", which creates a new run with `parent_run_id` and loads the parent's plan and notes.
- A simple lookup such as "what is the termination date?" is never turned into a 30-minute job.

**Fairness.** Reserve at least one worker slot for the interactive lane, and cap background runs per member, so a large review cannot starve interactive users.

Token and cost accounting is written to `runs.usage` and emitted as `budget_update`. Hard caps always force a wrap-up answer with partial results, never a silent stop.

---

## 13. Events and SSE

### 13.1 Event types

| Keep (unchanged contract) | Add |
|---|---|
| `session_id`, `reasoning`, `text_delta`, `text_final`, `tool_started`, `tool_finished`, `doc_read`, `doc_find`, `search_results`, `firm_answer`, `matter_resolution`, `matter_profile`, `people_results`, `review_table`, `edit_proposals`, `doc_created`, `ask_inputs`, `citation_data`, `grounding`, `chat_title`, `error`, `stopped`, `working_set` | `run_status` (state, lane, reason), `run_resumed` (attempt, reason), `tool_retry`, `plan_updated`, `note_added` (with evidence ids), `input_requested`, `input_provided`, `approval_requested`, `approval_decided`, `approval_stale`, `budget_update`, `context_conflict` |

- `text_delta` carries `{round, attempt}`. On `run_resumed`, clients drop unfinished deltas from earlier attempts.
- `ask_inputs` stays as the UI event; `input_requested` carries the same form plus `run_id`.
- Research events (`authority_results`, `authority_read`, `authority_status`, `citation_check`, `research_coverage`) are defined in §22.13.
- `stopped` payload: `{partial_text, completed_effects: [{tool_call_id, tool, effect_ref, status}], cancelled_calls: [call_id]}` (§14).

### 13.2 Transport

- `GET /api/runs/{id}/events?after={seq}` (SSE). Also honors `Last-Event-ID`.
- Each frame: `id: {seq}`, `data: {json}`. Keepalive comment every 15 s. `[DONE]` after the terminal `run_status`.
- **Invariant: the event log, not pub/sub, is authoritative.** Fan-out via Redis pub/sub (or `LISTEN/NOTIFY`) is only a wake-up hint. Tailers always query `seq > last_seen` from the table, and **poll every 1 s as fallback**. This also makes the run-creation race safe: if the worker finishes before the client's SSE connects, the client simply replays from the log.
- Clients dedupe by `seq`; reconnect replays the gap.
- **Text deltas (v1):** stored durably but coalesced (~100 ms / ~200 chars). With `grounding_enabled` (default) the final answer is not delta-streamed, only interim narration between tool rounds, so volume is modest. A retention job prunes `text_delta` rows 7 days after completion.
- **Later optimization (not v1):** keep deltas ephemeral on pub/sub and persist a `partial_text` snapshot on the run every ~2 s for reconnect and for the partial answer saved on Stop or crash. Structural events and `text_final` stay durable either way.

### 13.3 Compatibility and API

`POST /api/chat/sessions/{id}/messages` still returns an SSE stream, now a tail of the created run. **The SPA works unchanged in phase 1.** New endpoints:

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/chat/sessions/{id}/active-run` | Reattach after refresh. Returns a **list** of active runs (length ≤ 1 in v1) |
| `GET` | `/api/runs/{id}` | Status, plan, task, pending |
| `GET` | `/api/runs/{id}/events` | SSE tail with replay |
| `POST` | `/api/runs/{id}/cancel` | Stop |
| `POST` | `/api/runs/{id}/input` | Answer `ask_inputs` |
| `POST` | `/api/runs/{id}/approvals/{call_id}` | `{decision: approve\|reject, args_hash, reason?}` |

### 13.4 Projection to chat messages

`chat_messages` becomes a **read model**. At any terminal state (COMPLETED / FAILED / CANCELLED) the transition module writes the assistant row in the same transaction: content (from `text_final`, else the accumulated partial), `events` (tool/edit/review), `citations`, `model`. Projection is idempotent (keyed by `run_id`) and is performed by whichever actor causes the terminal transition (worker, sweeper or API). History, export and "Continue in the Assistant" paths are unchanged.

---

## 14. Cancel, waits, resume

**Cancel.** `POST /runs/{id}/cancel` sets `cancel_requested`. If QUEUED/WAITING_*, transition directly to CANCELLED and project. If RUNNING, the worker checks the flag between LLM chunks, before each tool call and inside tool wait loops.

**Cancellation and side effects.** Not every call can be interrupted safely:

| Call state at cancel | Behavior |
|---|---|
| `planned`, `awaiting_approval`, `approved` (not started) | Marked `cancelled`, never executed |
| `started`, risk `read` or `draft` | Aborted via cancellation token, marked `cancelled`, result discarded |
| `started`, risk `mutate` or `external_send` | **Not interrupted.** Allowed to reach a terminal state (`succeeded` / `failed` / `unknown`), bounded by its timeout, then the run cancels |

The `stopped` event and the projected message list mutating effects that completed ("Completed before stopping: generated `Diligence.xlsx`"), so the lawyer is never unaware of something that happened. An approval POST against a CANCELLED run returns `409`.

**Input.** The `ask_inputs` call stays open. `POST /runs/{id}/input` writes `input_provided`, stores the answers **as that call's result**, clears `pending` and re-queues the same run. The model sees a normal tool result. There is no synthetic user message. This does not consume `attempt`.

**Approval.** Gated calls in a round are requested together. Decisions are recorded per call as they arrive; the run re-queues when all are decided. Approve → execute the stored call (after the `args_hash` re-check). Reject → tool result `{"rejected": true, "reason": ...}` and the model adapts.

**Wait TTL.** `wait_expires_at` defaults to 24 h for input and 72 h for approval (configurable), then FAILED (`wait_expired`).

---

## 15. Security and ACL

- Identity is re-resolved on **every claim**. An inactive member or changed role fails the run (`access_revoked`).
- Every document read re-checks ACL (as today). Resume rehydrates text through this path.
- **Evidence is ACL-guarded itself.** All reads go through one data-access function `get_evidence(evidence_id, member)` that joins the source's current ACL (matter visibility, ethical walls). No code path selects `evidence.quote` directly, and a test enforces that.
- **Notes inherit evidence ACL.** A note whose evidence is inaccessible is hidden in every view, shown as "[source no longer accessible]", and excluded from the notes block on resume. Its claims are also excluded from grounding sources.
- If access to a document is lost while paused, the read returns "no longer accessible" and the alias goes to `revoked_aliases`.
- **Deletion and retention.** `evidence.quote` is a copy of client-confidential text. It is encrypted at rest like documents and follows the source's retention. On document or matter deletion (absent a legal hold) quotes are purged (`quote = NULL`, `purged_at` set) and dependent notes are demoted.
- Spotlight fences apply to everything rebuilt on resume, including text returned by external research providers. External research egress is policy-controlled and audited (§22.11).
- Audit: keep `chat.prompt` / `chat.answer`, and add `run.created`, `run.resumed`, `run.approval`, `run.cancelled`, `run.failed`, `evidence.denied` with document ids.

---

## 16. Observability

| Signal | Why |
|---|---|
| Trace per run: spans per LLM call and tool call, with tokens, cost, latency, model | Replay "why did it conclude this" |
| `queue_wait_ms`, `time_to_first_event_ms`, `run_duration_ms` | Latency SLOs |
| `rounds`, `tool_calls`, `tokens`, `cost` | Budget tuning |
| `lease_lost_total`, `resumes_total{reason}`, `attempts_exhausted_total` | Reliability |
| `stuck_runs` (RUNNING, lease expired > 2x TTL) | Alarm |
| `approval_wait_ms`, `input_wait_ms`, `wait_expired_total`, `approval_stale_total` | Product health |
| `cancelled_with_effects_total`, `unknown_outcomes_total` | Side-effect safety |
| `promotions_total`, `promotion_denied_total{reason}` | Lane policy |
| `notes_without_evidence_rejected_total`, `ungrounded_claims_removed_total`, `evidence_acl_denied_total` | Quality and security |

Targets: first visible event < 3 s; simple lookups < 15 s; resume after a worker crash < 45 s (lease TTL + sweeper interval).

---

## 17. Configuration

| Setting | Default |
|---|---|
| `run_lease_seconds` | 30 |
| `run_heartbeat_seconds` | 10 |
| `run_sweeper_seconds` | 10 |
| `run_max_attempts` | 3 |
| `run_input_wait_hours` | 24 |
| `run_approval_wait_hours` | 72 |
| `run_interactive_max_rounds` / `_deadline_seconds` | 10 / 180 |
| `run_background_max_rounds` / `_deadline_seconds` | 40 / 1800 |
| `run_promotion_progress_rounds` | 3 |
| `run_background_per_member_max` | 3 |
| `run_interactive_reserved_workers` | 1 |
| `run_checkpoint_keep` | 3 |
| `run_delta_coalesce_ms` | 100 |
| `run_event_delta_retention_days` | 7 |
| `run_worker_concurrency` | per process, tuned to LLM concurrency |

---

## 18. Migration plan

Each phase ships independently behind a flag with an exit gate.

| Phase | Deliverable | Exit gate |
|---|---|---|
| **1. Run + event log** | `runs`, `run_events`; worker wraps the **unchanged** `run_chat_agent`; SSE becomes a tail; lease, heartbeat, `lease_epoch` fencing; transition module (incl. sweeper); `active-run` reattach; message projection | Existing chat e2e passes unchanged; tests 1, 4, 13, 14, 21 pass |
| **2. Durability** | `run_turns` write-ahead, `run_tool_calls`, fold-based recovery, checkpoints, cancel (incl. side-effect rules), budgets | Tests 2, 3, 5, 18, 19, 20 pass with fault injection |
| **3. Waits** | WAITING_INPUT / WAITING_APPROVAL, args-hash binding, resume, idempotent mutating tools, `verify` recovery | Tests 6–10, 22, 23, 33 pass; no duplicate artifacts in chaos test |
| **4. Notes + Evidence** | `update_notes`, span handles, evidence with ACL-guarded reads, `session_context` deltas, grounding sees notes | Tests 11, 16, 17, 24, 27 pass; long-run finding-retention eval passes |
| **5. Plan/task + registry** | `update_plan` with task, tool metadata, central policy, promotion eligibility | Policy tests; tests 15, 25, 26 pass |

**Legal research track.** Phases R0–R5 are in §22.15. R0 (provider choice and licensing) can start now; R1 onward depends on Run phases 2, 4 and 5.

**Parallel workstream: retrieval regression suite** (no retrieval change until a baseline exists).

| Case | Measures |
|---|---|
| Simple matter-scoped lookup | Recall@5/10, MRR, nDCG@10 |
| Follow-up reference ("also the disclosure letter") | Same, conditioned on history |
| Multi-document | Recall across required docs |
| Multi-hop | Hit on each hop |
| Document-role query | Right doc type ranked |
| Long-context | Correct section selected |
| No-answer | Abstains, no false grounding |
| **ACL-negative** | **Zero hits** for an unauthorized member |

Then compare: current retrieval vs + context resolution vs + query decomposition. Adopt only what moves the numbers. A stronger embedding model than MiniLM 384-d is a separate, independently measurable experiment.

**Phase 1, smallest useful slice:**

1. Worker process imports `run_chat_agent` and iterates its event generator.
2. Each yielded event is appended via the fenced sequence allocator.
3. The router's SSE endpoint tails `run_events`.
4. Terminal projection reuses the existing `finally` persistence code.

No prompt, tool, retrieval, grounding or DocIndex change.

---

## 19. Test matrix

Fault injection: `RUN_FAULT=after_llm_turn|before_tool_effect|after_tool_effect|before_checkpoint|mid_stream|mid_grounding`, plus `kill -9` of the worker and `SIGSTOP`/`SIGCONT` to simulate a stalled worker.

| # | Scenario | Expected | Blocker |
|---|---|---|---|
| 1 | Browser drops mid-run | Run continues; reconnect replays from `Last-Event-ID`, no duplicate UI events | |
| 2 | Worker killed during LLM call (no turn persisted) | Lease expires, resume re-calls the LLM; clients drop earlier-attempt deltas | **Yes** |
| 3 | Worker killed after tool effect, before result row | `verify` adopts the existing artifact; no duplicate docx/export | **Yes** |
| 4 | Stalled worker resumes after lease was taken | All its writes rejected (0 rows); it exits without emitting events; `started` mark refused | **Yes** |
| 5 | Stop during a read tool | CANCELLED; tool aborted; partial answer saved; `stopped` event | |
| 6 | `ask_inputs`, then answer | Same run resumes; answers become the tool result; no new agent execution | |
| 7 | Approval rejected | Model receives rejection, proceeds differently | |
| 8 | Approval granted, worker crashes during execution | Recovery per tool strategy; single effect | |
| 9 | Attempts exhausted | FAILED, clear user-facing error, partial answer projected | |
| 10 | Wait TTL expires | FAILED (`wait_expired`), projected | |
| 11 | Member's access revoked while paused | Resumed reads denied; alias revoked; grounding excludes it | **Yes** |
| 12 | Second message to a session with an active run | `409` with `run_id` | |
| 13 | Two workers claim simultaneously | Exactly one wins (`SKIP LOCKED`) | |
| 14 | Redis pub/sub down | SSE still delivers via polling within ~1 s | |
| 15 | Interactive budget exhausted mid-task | Eligible runs promote and finish; ineligible runs wrap up with a "continue in background" offer | |
| 16 | Note with `finding` and no evidence | Rejected with tool error | |
| 17 | Note references evidence from another run or an unlocatable quote | Rejected | |
| 18 | Long run (30+ tool calls) | Finding #3 still available after eviction; final answer cites it | |
| 19 | Token/cost cap hit | Wrap-up answer with partial results, not a silent stop | |
| 20 | Crash after all tools terminal, **before checkpoint** | Fold rebuilds state, checkpoint written, **no LLM call** for that round | **Yes** |
| 21 | Existing chat e2e suite | Green at every phase | **Yes** |
| 22 | Run that waits for input/approval four times | Completes; `attempt` still 1 (waits never burn attempts) | **Yes** |
| 23 | Approval POST with wrong `args_hash`, or source version changed after approval | Rejected or `approval_stale`; nothing executes | **Yes** |
| 24 | Persisted no-tool-call turn, crash before grounding completes | Recovery grounds the persisted text; no LLM call | **Yes** |
| 25 | Sweeper requeue racing a late zombie write | Zombie write fails on `lease_epoch`; one consistent event order | **Yes** |
| 26 | Cancel while a `mutate` tool is `started` | Tool finishes and is recorded; run then CANCELLED; `stopped` lists the effect | **Yes** |
| 27 | Source access revoked after a note was written | Note hidden, excluded from notes block and grounding; `evidence_acl_denied` counted | **Yes** |
| 28 | Re-run `update_notes` on replay | No duplicate notes (`(tool_call_id, idx)`) | |
| 29 | `tool_started` for a recovered `started` call | UI shows one step plus `tool_retry`, not two steps | |
| 30 | Concurrent `session_context` deltas | Version conflict, re-apply, constraints never silently overwritten | |
| 31 | Heartbeat during a 170 s tool | Lease kept alive; no spurious requeue | |
| 32 | `fold(all) == checkpoint + fold(rest)` at every round | Always true | |
| 33 | Approval granted, call marked `approved`, worker crashes **before execution starts** | New worker executes the same `call_id` with the same `args_hash` exactly once | **Yes** |
| 34 | Fold logic changed after a run was created | Recovery uses the run's `fold_version`; result identical to pre-change reconstruction | |

Release blockers are rows 2, 3, 4, 11, 20–27, 33. Research tests R1–R3, R6, R7 and R8 (§22.16) are blockers for enabling external research. The core property to prove: **kill the worker at every point between LLM decision, tool effect and persistence, and show the run either resumes exactly once or surfaces an explicit `unknown` state.**

---

## 20. Risks and open questions

| Risk / question | Mitigation or decision needed |
|---|---|
| Postgres event volume from deltas | Coalesce, prune; ephemeral deltas plus `partial_text` snapshots if needed (§13.2) |
| Fold cost for long runs | Rows are few (≤ 40 rounds); checkpoints bound it; results loaded lazily |
| Worker concurrency vs LLM rate limits | Global semaphore per provider; interactive reserved slot |
| `manual` recovery UX | Needs a design for "outcome unknown" confirm prompts |
| Concurrent runs per session | v1 keeps the single-active index. To allow one interactive plus N background runs, restrict the index predicate to `lane = 'interactive'`. Context merge rules (§10.4) and list-returning `active-run` are already in place |
| Draft streaming before grounding | Only ever as a labeled `draft_delta`, per-firm opt-in, later |
| Wait TTL values | Product decision per firm |
| Promotion thresholds | Tune from trajectory data (progress window, quotas) |
| Cross-run reuse of notes/evidence (matter-level memory) | Out of scope; needs ACL and retention design; evaluate after v1 data |
| Worker deployment | Same codebase, separate process type (`worker`) |

## 21. Deliverables checklist

- [ ] Alembic migrations for §6 (incl. `lease_epoch`, `args_hash`, notes uniqueness)
- [ ] Transition module incl. sweeper (single authority for `runs.status`)
- [ ] Fenced write helpers (`append_events`, `persist_turn`, `persist_result`, `checkpoint`)
- [ ] Pure, versioned `fold_round` (`fold_version`) + `recover()` + fold-consistency and cross-version replay tests
- [ ] Worker entrypoint, independent heartbeat
- [ ] SSE tail endpoint + reattach endpoint
- [ ] Idempotent projection writer
- [ ] Tool registry with metadata, recovery strategies and approval binding
- [ ] Span handles in document/retrieval tool results
- [ ] `get_evidence` ACL-guarded accessor and purge job
- [ ] Session-context delta merge
- [ ] Fault-injection harness and §19 suite
- [ ] Retrieval regression suite with ACL-negative cases
- [ ] Dashboards/alerts for §16
- [ ] `LegalResearchProvider` interface, first adapter, license-flag enforcement (§22.4)
- [ ] Research tools, span handles for authorities, `egress` metadata and outbound query builder (§22.5, §22.11)
- [ ] Deterministic `CitationFormatter` and authority ranker config, lawyer-reviewed (§22.6, §22.8)
- [ ] Verify-before-rely pipeline and cite-check mode (§22.9)
- [ ] Research gold set, adversarial cases and provider bake-off (§22.14)

---

## 22. Legal research subsystem

Part II of this spec. It plugs into the Run runtime (§5–§16) and reuses its tool registry (§11), evidence model (§10), ACL rules (§15) and grounding. It does not change the durable-run design.

### 22.1 Assessment and market reference

| | Score | Why |
|---|---|---|
| Legal research as built today | **~1.5 / 10** | Firm-internal records only. "Research" mode researches the firm's own documents: no external law, no authority ranking, no status/treatment checks, no jurisdiction handling |
| Foundations that transfer | **~6 / 10** | Claim grounding with a separate verifier, quote-located citations, typed evidence (`authority` already in §6), durable runs, tool registry, prompt-injection fences, ACL discipline |
| Target after R1–R4 (licensed provider) | **~7 / 10** | Comparable to Harvey's model: licensed primary law and citator signals inside your agent, with your stricter verification |
| Legora-class | Not reachable by architecture alone | Needs an owned or deeply licensed corpus, an ontology of authority relationships and an in-house citator. That is a data business |

A 5/10 rating blends the first two rows. The capability is near zero today, but the parts that make research trustworthy (grounding, located quotes, provenance) are already stronger than most.

Market reference (public information as of Oct 2026; both vendors ship fast, so re-verify before relying on it):

| Capability | Harvey | Legora | This design |
|---|---|---|---|
| Content | LexisNexis alliance (announced June 2025): US primary law and Shepard's Citations inside Harvey | Building its own US primary-law corpus (case law with pincites, updated every 24 h; statutes and regulations; agency guidance) plus partnerships in other jurisdictions | Provider interface, licensed content (§22.3, §22.4) |
| Good-law / treatment | Shepard's via Lexis | AI-native citator on an "ontology of law" (announced Sept 2026) | Provider citator signals, plus an explicit "not verified" state (§22.9) |
| Authority handling | Through Lexis | Ranks sources by authority, jurisdiction-aware | Deterministic ranker and binding labels (§22.6) |
| Verification | Citation-validated answers | Verifies each finding against primary law and checks the source still holds | Verify-before-rely pipeline (§22.9) |
| Execution | Plan Mode for complex tasks | Plans research and investigates several angles in parallel | `update_plan`, parallel reads, background lane (§22.7) |
| Citation granularity | Not documented | One third-party review reports source-level, not character-level | Pincite plus character offsets (an existing advantage) |
| Cite-check while drafting | Via Lexis tooling | Not documented | Cite-check mode (R4) |

### 22.2 Principles

1. **Buy the law, build the trust layer.** Content and citator come from providers behind one interface. You build orchestration, verification, ranking rules, formatting, evals and UI.
2. **Authority is a typed object**, distinct from document evidence. It has a jurisdiction, court level, date, version and status, and is never treated as a firm document.
3. **Verify before rely.** No authority reaches the final answer unless it was resolved from a provider by identifier, its quote and pincite were located in retrieved text, and its status was checked. Model memory and search snippets never count.
4. **Jurisdiction and time are explicit on every query.** Ambiguity is resolved by asking (`WAITING_INPUT`), not guessing.
5. **Status honesty.** "Unknown" is never rendered as "good law".
6. **Format citations from metadata**, never from model text.
7. **Outbound queries are a confidentiality risk.** External research egress is policy-controlled and audited (§22.11).
8. **Provider text is untrusted input.** It goes through the same spotlight fences as document text.

### 22.3 Buy vs build

| Buy / integrate | Build |
|---|---|
| Case law full text with pagination and pincites | `LegalResearchProvider` interface and adapters |
| Statutes, regulations, rules, agency guidance | Authority ranker and jurisdiction resolver (lawyer-reviewed config) |
| Citator / treatment signals | Verify-before-rely pipeline and proposition-support checks |
| Citation graph, if the provider has one | Deterministic citation formatter |
| | Research skill, cite-check mode, research evals, UI cards |

Do **not** build a corpus or a citator in v1.

### 22.4 Provider interface

```python
class LegalResearchProvider(Protocol):
    def capabilities(self) -> Capabilities: ...          # jurisdictions, kinds, citator?, pincites?, update lag, license flags
    def search(self, q: str, *, jurisdictions, kinds, courts=None,
               date_range=None, limit=20) -> list[AuthorityHit]: ...
    def resolve_citation(self, citation: str, *, jurisdiction_hint=None) -> list[AuthorityRef]: ...
    def get_authority(self, authority_id: str, *, as_of: date | None = None) -> Authority: ...
    def get_citing(self, authority_id: str, *, treatment=None, limit=50) -> list[CitingRef]: ...
    def get_status(self, authority_id: str, *, as_of: date | None = None) -> AuthorityStatus: ...
```

Normalized `Authority` object (every provider maps into this):

```jsonc
{
  "authority_id": "prov:<provider>:<native id>",
  "provider": "...", "provider_version": "...",
  "kind": "case | statute | regulation | rule | agency_guidance | treaty | secondary",
  "jurisdiction": {"country": "..", "level": "federal | state | regional | supranational", "region": ".."},
  "court": {"name": "..", "level": "supreme | appellate | trial | tribunal"},
  "citation": {"primary": "..", "parallel": [".."]},
  "title": "..", "decision_date": "..", "effective_date": "..", "as_of": "..",
  "structure": [{"locator": {"page": 18, "para": 23, "section": "8.2"},
                 "role": "majority | concurrence | dissent | statute_text | headnote | unknown",
                 "text": ".."}],
  "status": {"signal": "good_law | caution | negative | superseded | repealed | amended | unknown",
             "signals": [{"type": "..", "by": "authority_id", "as_of": ".."}],
             "source": "provider | derived | none", "checked_at": ".."},
  "retrieved_at": "..", "text_hash": "..",
  "license": {"llm_use": true, "cache_ttl_s": 86400, "store_text": false, "display": "full | excerpt"}
}
```

Rules:

- `capabilities()` gates features: no citator means R2 status checks return `unknown` with `source: none`.
- The `license` block is enforced by the runtime (cache TTL, storage, display, LLM use), not by convention.
- Publisher editorial content (headnotes, summaries) is marked `role: headnote` and is never quoted as the authority's own words.

### 22.5 Tools (added to the registry, §11)

All are `risk: read`, `recovery: rerun`, with the new metadata field `egress: external` (§22.11).

| Tool | Behavior | Parallel-safe |
|---|---|---|
| `search_authority` | Jurisdiction- and kind-scoped search; returns hits with span handles and authority metadata | yes |
| `read_authority` | Outline-first read of an authority (same budget and cursor model as `read_document`); returns span handles | yes |
| `find_in_authority` | In-authority search with true hit counts and page/para context | yes |
| `resolve_citation` | Citation string → candidate `authority_id`s. Used for cite-checking and for the model's own recalled cites | yes |
| `get_citing_authorities` | Forward citations with treatment filter (contrary, distinguishing, following) | yes |
| `check_authority_status` | Status as of a date, with the signals behind it | yes |
| `verify_citations` | Batch cite-check of a block of text or a draft (§22.9) | no (background job) |

All tool results carry span handles that feed `update_notes` and evidence creation exactly as in §10.1, with `evidence.type = 'authority'`.

### 22.6 Jurisdiction resolution and authority ranking

**Jurisdiction resolver.** Inputs: matter profile (governing law, forum, parties' locations), `session_context` constraints, user text. Output: a ranked set of jurisdictions with confidence.

- Low confidence or several plausible jurisdictions → `ask_inputs` (durable wait), then persist the answer as a session constraint (`governing_law`, `forum`) so follow-ups inherit it.
- Every search call must carry an explicit jurisdiction and date. The registry rejects calls without them.

**Authority ranker (deterministic, not LLM).** Score each authority for a given forum:

```text
weight = f(binding_status, court_level, same_jurisdiction, recency, treatment, relevance)
binding_status ∈ {binding, persuasive, unknown}   -- relative to the forum
```

- Court hierarchy and binding rules live in a per-jurisdiction config (YAML) **authored and reviewed by lawyers**, versioned and covered by tests. The runtime never asks the model to decide what is binding.
- Ranking output labels each authority (binding / persuasive / unknown) and the final answer must show that label.
- Negative treatment caps the weight and forces disclosure regardless of relevance.

### 22.7 How the research agent performs

Research is a skill (`skills/legal_research.md`, §10 skills model) running in a normal durable Run:

1. **Frame**: list the legal issues, jurisdiction(s), as-of date and forum. Declare `task.type = "research"` in `update_plan` so eligible runs can be promoted to the background lane (§12).
2. **Search in parallel**: issue × source × jurisdiction, as parallel-safe `search_authority` calls. Coverage is tracked in notes.
3. **Triage**: rank with the deterministic ranker; discard non-binding or irrelevant hits.
4. **Read primary text** of the top candidates (`read_authority`), never just snippets.
5. **Check status** of every authority that may be cited; fetch citing authorities to find contrary or distinguishing cases.
6. **Synthesize** per issue, with `finding` notes that cite authority evidence.
7. **Verify** (§22.9), then ground and deliver.

Completion criteria:

- Each issue has at least one controlling authority, or an explicit "none found" stated as a result.
- A **research log** is delivered with the answer: providers and jurisdictions searched, queries (redacted), as-of date, counts, authorities excluded and why.
- Negative results are reported, never papered over.

Budgets: parallel searches inside one round; multi-issue research defaults to the background lane. Sub-agents stay out of v1.

### 22.8 Authority evidence, citations and formatting

- `evidence.type = 'authority'`, `source_id = authority_id`, `source_version = text_hash`, locator `{page, para, section, start_char, end_char}`. The `quote` is copied from the retrieved authority text at the located offsets.
- Authority-specific data is kept in `run_authorities` (§22.12).
- **Deterministic citation formatting.** A per-jurisdiction `CitationFormatter` renders citations from `Authority` metadata (style configurable per firm). The model emits structured citation references (`authority_id` + locator), never free-text reporter citations.
- **Proposition grounding.** Each legal proposition in the answer maps to `(authority_id, pincite, quote)`. The verifier model checks that the quote actually supports the proposition and classifies it: `holding | analogous | dicta | unclear`. Passage `role` (dissent, headnote) prevents citing a dissent or editorial summary as the holding.
- Existing grounding and `<CITATIONS>` parsing stay; authority sources are added as source records alongside document passages.

### 22.9 Verify-before-rely pipeline

Runs before `text_final` for any answer that cites authority, and standalone as cite-check mode. All six checks must pass or the citation is removed or flagged:

| # | Check | Failure handling |
|---|---|---|
| 1 | **Existence**: authority resolved from a provider by id or `resolve_citation`, not from model text | Remove the citation; list under "could not verify" |
| 2 | **Quote and pincite** located in retrieved text | Remove the quote; keep the authority only if the proposition is otherwise supported |
| 3 | **Status** checked as of the research date | Negative treatment disclosed in the answer; `superseded`/`repealed` cannot be cited as current law; `unknown` labeled "status not verified" |
| 4 | **Proposition support** (verifier ≠ generator) | Downgrade to "analogous/dicta" or remove |
| 5 | **Binding label** relative to the forum (§22.6) | Label shown; wrong-jurisdiction authority moved to persuasive or removed |
| 6 | **Currency**: statute version as of the relevant date, amendments noted | Flag with the amendment |

Hard rule: a final answer cannot contain an authority citation that failed check 1 or 2.

**Cite-check mode.** For a lawyer's draft (selection or uploaded document): extract citations → run `verify_citations` as a background job → produce a table (citation, resolved authority, quote found, status, support, issues). This mirrors drafting-time citation validation now appearing in the market.

### 22.10 Internal and external synthesis

- Firm work product (prior memos, opinions, precedents via `ask_firm` and `search_firm_records`) is **never** presented as authority. It is labeled `internal` with its age, and any authority it relies on is re-verified (§22.9) before reuse.
- The answer separates: external authority, firm precedent and client documents. Each claim shows which kind supports it.

### 22.11 Confidentiality and egress

External search can leak matter facts. Controls:

- **Outbound query builder.** Abstract the legal issue; strip party names, amounts and unique identifiers using a deny-list built from the matter profile. A query that still contains deny-listed entities is blocked or must be rewritten.
- **Per-matter and per-firm switches** to disable external research (client outside-counsel guidelines, ethical walls).
- **Audit.** Every outbound call logs `research.query` with provider, redacted query, filters and counts.
- **Provider terms.** Zero-retention / no-training commitments and LLM-use rights are checked at onboarding (R0) and enforced through `license` flags. If `store_text` is false, authority text is cached only within `cache_ttl` and evidence quotes follow the purge rules in §15.
- **Entitlements.** Which providers and jurisdictions a member may query comes from licensing, not from document ACL. Authorities themselves are public law, but the access path is still checked per member.
- Provider text is fenced as untrusted input (prompt-injection defense).

### 22.12 Data model

```sql
CREATE TABLE research_providers (
  id           text PRIMARY KEY,
  kind         text NOT NULL,
  capabilities jsonb NOT NULL,
  license      jsonb NOT NULL,
  enabled      boolean NOT NULL DEFAULT true
);

CREATE TABLE run_authorities (
  run_id           uuid NOT NULL REFERENCES runs(id),
  authority_id     text NOT NULL,
  provider         text NOT NULL,
  kind             text NOT NULL,
  citation         jsonb NOT NULL,
  jurisdiction     jsonb NOT NULL,
  court            jsonb,
  decision_date    date,
  as_of            date,
  text_hash        text,
  provider_version text,
  status           jsonb,                 -- signal, signals, source, checked_at
  binding_for_forum text,                 -- binding | persuasive | unknown
  retrieved_at     timestamptz NOT NULL,
  PRIMARY KEY (run_id, authority_id)
);

CREATE TABLE research_queries (           -- audit and eval
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id       uuid NOT NULL REFERENCES runs(id),
  tool_call_id uuid REFERENCES run_tool_calls(id),
  provider     text NOT NULL,
  redacted_q   text NOT NULL,
  filters      jsonb,
  result_count int,
  latency_ms   int,
  created_at   timestamptz NOT NULL DEFAULT now()
);
```

Caching (Redis, TTL per license, not durable): authority text keyed by `(authority_id, text_hash)`, status by `(authority_id, as_of)` with a short TTL so treatment changes are noticed.

### 22.13 Events and UI

New events: `authority_results`, `authority_read`, `authority_status`, `citation_check` (per-citation verdicts), `research_coverage`.

UI: an authority card with court, date, binding label and status badge; a treatment timeline; open-in-viewer at the pincite (extends `CitationDocumentPanel`); per-citation states **Verified / Verified with caution / Negative treatment / Not verified**; and the research log as an expandable section.

### 22.14 Research evals

Gold set: lawyer-authored questions with expected controlling authorities per jurisdiction (start with 100–200, partner-reviewed).

| Metric | Gate |
|---|---|
| Hallucinated / non-existent citation rate in **final** answers | **0** |
| Status checked for every cited authority | 100% |
| Quote and pincite accuracy | ≥ 99% located |
| Controlling-authority recall@k | tracked, regression-gated |
| Proposition-support accuracy (human-labeled) | tracked, regression-gated |
| Binding-label accuracy | tracked |
| Issue coverage and completeness | tracked |

Adversarial cases: planted fake citations, overruled-case bait, wrong-jurisdiction bait, outdated-statute bait, no-answer questions, prompt injection inside authority text. Also trajectory evals (plan coverage, redundant searches, stop criteria) and a **provider bake-off** on the gold set before licensing. Use a stronger verifier than the cost-optimized one for proposition support and compare them on the gold set. Lawyer feedback ("wrong authority", "irrelevant") feeds the gold set.

### 22.15 Research phases

Needs Run Phases 2 (durability), 4 (evidence) and 5 (registry) from §18. R0 can start immediately.

| Phase | Deliverable | Exit gate |
|---|---|---|
| **R0: Decide and license** | Choose target jurisdictions; provider bake-off; licensing (LLM use, caching, display, retention, pricing); seed gold set | Signed terms or written answers; bake-off results |
| **R1: Interface + first provider** | `LegalResearchProvider`, one adapter, `search_authority`, `read_authority`, `resolve_citation`, authority evidence, pincite verification, `CitationFormatter`, events | Hallucinated-citation rate 0 on the gold set; answers show only verified citations |
| **R2: Status + verification** | `check_authority_status`, `get_citing_authorities`, verify-before-rely pipeline, badges. No citator from the provider → ship the honest "not verified" state | 100% of cited authorities status-checked; negative-treatment baits caught |
| **R3: Jurisdiction + ranking + skill** | Jurisdiction resolver, ranker config and binding labels, `legal_research` skill, research log, background research runs | Binding-label and coverage evals pass |
| **R4: Cite-check mode** | `verify_citations` batch job, draft cite-check table, hook for Word later | Cite-check accuracy on planted errors |
| **R5: Scale** | Second provider or jurisdiction, cache tuning, optional narrow own corpus (official court or gazette sources, only where terms allow), evaluate an ontology only after usage data | Provider parity on the gold set |

### 22.16 Research tests (added to §19)

| # | Scenario | Expected |
|---|---|---|
| R1 | Model cites a case it "remembers" that the provider cannot resolve | Citation removed and listed under "could not verify" |
| R2 | Model quotes text not present in the retrieved authority | Quote rejected; proposition re-checked or dropped |
| R3 | Cited case has negative treatment | Treatment disclosed; not cited as good law |
| R4 | Status check unavailable (provider down or no citator) | "Status not verified" shown; run completes |
| R5 | Wrong-jurisdiction authority ranks high by relevance | Labeled persuasive or excluded for the forum |
| R6 | Ambiguous jurisdiction | `ask_inputs` wait; answer persisted as a session constraint; later runs inherit it |
| R7 | Query contains a party name from the matter | Blocked or rewritten; audit shows the redacted query |
| R8 | Authority text contains injected instructions | Ignored (spotlight fences); no behavior change |
| R9 | Worker crash mid-research | Resume from folded state; no duplicate provider calls beyond idempotent searches; research log consistent |
| R10 | License forbids storing text | Text only in TTL cache; evidence quote purged per policy |
| R11 | Cite-check of a draft with planted wrong pincites and a repealed statute | Each flagged correctly |
| R12 | Dissent or headnote quoted as the holding | Flagged by passage `role` |

### 22.17 Risks and open questions

| Risk / question | Decision needed |
|---|---|
| **Target jurisdiction(s) and buyer.** Provider options, citator availability and hierarchy rules all depend on it | Decide in R0 |
| **Providers without a citator API.** Some markets have no Shepard's-equivalent available programmatically | Ship honest "not verified" status; evaluate a derived signal (for example, citing-reference treatment) only as a labeled heuristic, never as "good law" |
| **Licensing:** LLM-use rights, caching and display limits, redistribution, retention | Legal and commercial, before R1 |
| **Provider vendor claims.** Coverage and accuracy statements in public comparisons are often vendor-authored | Verify with your own gold set and a sample of official court copies |
| **Publisher summaries or AI-generated headnotes** must not be treated as authority | Enforced via `role: headnote` (§22.4) |
| **Verifier model quality** on legal support judgments | Compare a stronger verifier on the gold set (§22.14) |
| **Latency:** verification adds calls | Run verification in parallel; show progress events; background lane for large research |
| **Conditional example, if India is a target:** public comparisons list Indian Kanoon (API), SCC Online, Manupatra (no public API reported), and several newer API vendors, with uneven citator and citation-graph support | All claims above come from vendor-authored pages. Validate coverage, terms and court-copy provenance in the R0 bake-off before choosing |

---

## Appendix A: Change log (external review triage)

| Review point | Disposition | What changed |
|---|---|---|
| Recovery of a persisted turn with terminal tools and no checkpoint | **Accepted, generalized** | Recovery is now a pure fold over write-ahead records (§8.2), which also covers the zero-tool-call terminal turn. Checkpoints no longer hold messages |
| Separate `attempt` and `lease_epoch` | **Accepted; real bug found** | The single counter meant any run that waited three times would exhaust `max_attempts`. Waits no longer consume attempts |
| Sweeper is a second transition authority | **Accepted, modified** | Single transition module with atomic epoch bump; the proposed extra `REQUEUEING` state was rejected as unnecessary (§5) |
| Keep `text_delta` ephemeral | **Partly accepted** | Volume is modest with grounding on (final answer is not delta-streamed). Durable-coalesced stays for v1; ephemeral plus `partial_text` snapshots is documented as a later optimization (§13.2) |
| Event log is the source of truth (SSE race) | **Accepted** | Promoted to an explicit invariant (§3, §13.2) |
| `session_context` conflict semantics | **Accepted** | Delta-based merge rules and versioned updates (§10.4) |
| Create evidence when tools return spans | **Accepted, modified** | Eager rows for every read passage would bloat the table. Tools return span handles; evidence is materialized on first use (§10.1). This also fixes a gap in the earlier draft: the model had no handle to cite |
| ACL on evidence itself | **Accepted, extended** | ACL-guarded accessor, note hiding, and purge/retention for the stored quote copy (§15) |
| Split approval vs execution status | **Declined as a split** | `approved` already differs from `started`. Added what was actually missing: args-hash binding, re-check at execution, approval batching (§8.3, §14) |
| Explicit promotion state and eligibility | **Accepted, modified** | Promotion is an in-place lane change (no `PROMOTING` state) with explicit eligibility rules (§12) |
| Run intent / task classification | **Accepted, lightweight** | The model declares the task in `update_plan`. No classifier call or new service (§10.3) |
| Don't hard-wire one active run per session | **Accepted** | Index predicate documented as relaxable; `active-run` returns a list; merge rules ready (§13.3, §20) |
| Define cancellation semantics for external side effects (listed but not specified in the review) | **Specified** | Per-state cancel behavior and `stopped` reporting (§14) |
| *Found in this pass:* zombie can still complete an external effect | **Added** | Fencing covers DB only; `started` mark is fenced; effects rely on target idempotency (§7.3) |
| *Found in this pass:* heartbeat starved by long tools | **Added** | Independent heartbeat, two-miss rule (§7.3) |
| *Found in this pass:* `update_notes` not replay-safe; duplicate `tool_started` on recovery | **Added** | `(tool_call_id, idx)` uniqueness; `tool_retry` event; result events emitted with persisted result (§6, §8.3) |
| *Found in this pass:* lane starvation | **Added** | Reserved interactive worker slot and per-member background cap (§12) |
| *Rev 2.1, second external review:* add fold versioning, approval-then-crash test, explicit invariants | **Accepted** | `fold_version` on runs and checkpoints; tests 33 and 34; invariants "LLM never re-called because a checkpoint is missing" and "recovery creates no new logical turn or call" (§8.5); explicit `stopped` payload (§13.1) |
| *Rev 2.1 review claim:* Rev 2 still uses one `attempt` counter, keeps messages in checkpoints, lacks mutation-cancel rules | **Not applicable** | Checked against the file: `lease_epoch` (§6, §7.3), message-free checkpoints (§9) and cancel semantics (§14) are present. The review appears to have read an earlier copy |
| *Rev 2.1 review suggestion:* bump `attempt` on every claim alongside `lease_epoch` | **Declined** | That reintroduces the bug Rev 2 fixed: a run waiting for input or approval several times would exhaust `max_attempts`. `attempt` increments only on crash recovery |
| *Rev 2.2:* legal research scored against Harvey and Legora (external review: 5/10) | **Re-scored and designed** | Capability today ~1.5/10, foundations ~6/10, target ~7/10 with a licensed provider. New Part II (§22): provider interface, typed authorities, jurisdiction resolver and deterministic ranker, research skill, verify-before-rely pipeline, cite-check mode, egress controls, research evals and phases R0–R5 |
| *Rev 2.2 review point:* "don't build the data yourself" | **Accepted** | Buy vs build table (§22.3); no corpus or citator in v1 |