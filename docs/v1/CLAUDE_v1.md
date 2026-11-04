# CLAUDE.md — ClassPilot Live: Agent Demo

## Project context

ClassPilot Live is a 3-person course project (data engineering + GenAI). It runs one
faculty-approved class session when the professor is unavailable: students join on their
phones, answer polls, and ask questions. If many students pick the same wrong answer, the
system switches to a pre-approved re-teaching branch. Afterwards the professor gets an
auditable summary.

The system has three parts, each owned by one person:
- Front end + live state (WebSocket, Redis) — teammate
- Data pipeline (Snowflake Bronze/Silver/Gold, dbt, Airflow) — teammate
- **Agent / RAG / LangGraph — this folder**

## Goal of this demo

Show how the agent part works and interacts with the other parts, using mock JSON input.
This is a learning demo to share with the team, not production code.

It should answer these questions with real runs:
1. Does the poll-trigger path need an LLM at all, or is a lookup enough?
2. How should student typed questions flow (answer vs. escalate to professor)?
3. Is a separate Guardian agent worth it (2-agent vs. 3-agent mode)?
4. How long does a Cortex call (retrieval + answer) take?

### Not in scope
- No front end, no Redis, no WebSocket, no real-time streaming
- No dbt / Airflow / Bronze-Silver-Gold work (other teammate)
- No deployment, auth, or multi-user handling

## Architecture

LangGraph controls the flow. Snowflake Cortex provides the LLM and retrieval
(Cortex Search over approved lesson content). Both sit behind adapters so the demo can
run fully offline in mock mode.

### Path A: poll trigger (no LLM needed for the decision)

```
evidence JSON -> threshold check (rule) -> misconception map lookup (rule)
              -> remediation limit check (rule) -> decision + trace
```
- Trigger rule: at least `min_responses` answers AND the top wrong option share
  >= `wrong_ratio_threshold` (defaults: 5 and 0.60).
- Each wrong option maps to a misconception, and each misconception maps to one
  pre-approved remediation branch.
- At most `max_remediations_per_objective` (default 1). If exceeded, or no mapping
  exists, escalate.
- Optional: an LLM may write a one-sentence note for the professor. It never chooses
  the branch.

### Path B: student typed question

2-agent mode (toggle `AGENT_MODE=2`):
```
question JSON -> protected-question check (rule)
              -> Question Analyst (LLM) -> Grounded Responder (LLM, uses Cortex Search)
              -> final validator (rule) -> answer | escalate + trace
```

3-agent mode (default since Stage 4):
```
... -> Grounded Responder (LLM) -> Guardian (LLM) -> final validator (rule) -> ...
```

Node responsibilities:
- **Protected-question check (rule):** similarity against the protected assignment list;
  above threshold -> escalate immediately, no LLM call.
- **Question Analyst (LLM):** classify as `in_scope`, `out_of_scope`, or
  `assignment_like`; link to a learning objective if possible.
- **Grounded Responder (LLM):** retrieve approved chunks, answer only from them, cite
  chunk ids, return a confidence. In 2-agent mode it also self-checks grounding.
- **Guardian (LLM, 3-agent mode only):** sees only the question, the answer, and the
  cited chunks. Checks whether the answer is supported and does not reveal assignment
  answers. Lists each claim with the cited chunk that supports it (or null), plus
  pass/fail with a reason; a rule (`check_guardian`) makes the call from that list.
  Skipped when the responder's answer will be escalated anyway (low confidence,
  missing citations, or self-check failed).
- **Final validator (rule):** the only node that makes the final decision. Checks schema,
  that citations exist in the retrieved set, confidence threshold, and Guardian result.

### Hard rules for the design
- Thresholds and final decisions are always code, never the LLM.
- The agent never queries Snowflake event tables for live data. Live evidence is passed
  in as input (in the real system it comes from Redis via the backend).
- Snowflake is used only for LLM calls and Cortex Search over static, pre-approved content.
- Any LLM timeout or error -> escalate to professor (fallback), never hang.
- Every decision writes one trace record (this is what the data pipeline will load into
  Bronze later).

## Data contracts

Field names follow the team README so they line up with the other parts.
These are the agent demo's **draft** contracts. The team agrees on the real interfaces
after each part's demo; items to discuss are tracked in `interface_questions.md`.

### Poll evidence (input to Path A)
```json
{
  "session_id": "session-001",
  "objective_id": "objective-02",
  "question_id": "question-07",
  "snapshot_time": "2026-10-22T18:30:40Z",
  "connected_students": 24,
  "answers_received": 21,
  "option_counts": {"A": 3, "B": 13, "C": 4, "D": 1},
  "correct_option": "A",
  "remediations_used": {"objective-02": 0}
}
```

### Student question (input to Path B)
```json
{
  "session_id": "session-001",
  "event_id": "evt-123",
  "anonymous_learner_id": "learner-017",
  "objective_id": "objective-02",
  "question_text": "Why do we keep raw data in Bronze if it has errors?",
  "submitted_at": "2026-10-22T18:31:05Z"
}
```

### Decision (output of both paths)
```json
{
  "decision_id": "dec-001",
  "session_id": "session-001",
  "path": "poll | question",
  "action": "continue | reteach | answer | escalate",
  "remediation_id": "R-03",
  "answer_text": null,
  "citations": ["chunk-04"],
  "escalation_reason": "out_of_scope | assignment_like | low_confidence | unsupported | llm_error | no_mapping | remediation_limit",
  "confidence": 0.82
}
```
Unused fields are `null`.

### Trace (one per decision, JSONL)
```json
{
  "decision_id": "dec-001",
  "input_ref": "evt-123",
  "agent_mode": 2,
  "nodes_run": ["protected_check", "analyst", "responder", "validator"],
  "llm_calls": 2,
  "retrieved_chunk_ids": ["chunk-02", "chunk-04"],
  "latency_ms": {"analyst": 900, "responder": 2100, "total": 3100},
  "backend": "mock | cortex",
  "action": "answer",
  "created_at": "2026-10-22T18:31:08Z"
}
```

## Folder layout

```
agents_demo/
  CLAUDE.md
  note.md                   # per-stage dev log: changes, decisions, open questions
  interface_questions.md    # interface/contract items to discuss with the team
  ARCHITECTURE.html         # diagrams: components, Path A, Path B, Snowflake, repo map
  DEMO_OVERVIEW.html        # one-diagram intro to show before the live demo
  README.md
  pyproject.toml
  .env.example              # never commit .env
  config/
    settings.yaml           # thresholds, agent mode, model name, timeouts
  content/                  # small sample lesson (topic: dbt + Medallion architecture)
    lesson_chunks.json      # 3-5 approved text chunks with ids
    poll_questions.json     # poll question, options, correct option
    misconception_map.json  # wrong option -> misconception -> remediation branch
    remediations.json       # pre-approved re-teaching branches
    protected_questions.json
  scenarios/                # mock input JSON for each demo scenario
  eval/
    test_questions.json     # ~10 labeled questions (expected action)
  src/agents_demo/
    contracts.py            # pydantic models for the contracts above
    rules.py                # thresholds, lookup, protected check, final validator
    graph.py                # LangGraph definition (2/3-agent mode)
    nodes/                  # analyst.py, responder.py, guardian.py
    adapters/
      llm.py                # LLMClient interface + MockLLM + CortexLLM
      retrieval.py          # Retriever interface + MockRetriever + CortexSearchRetriever
    trace.py                # write JSONL traces
    cli.py                  # run scenarios / eval
    report.py               # build HTML results page
  tests/
  outputs/                  # traces + HTML report (gitignored)
```

## Demo scenarios

1. Poll trigger: 62% picked the same wrong option -> reteach with mapped branch.
2. In-scope question -> answer with citations.
3. Out-of-scope or assignment-like question -> escalate.
4. LLM timeout / low confidence -> fallback escalate.

## Evaluation

Run `eval/test_questions.json` in both 2-agent and 3-agent mode and compare:
- escalation recall (questions that should escalate and did)
- unsupported answers let through
- LLM calls and latency per question

`eval/guardian_cases.json` checks the Guardian alone (hand-written answers; catch rate and
false fails). Eval results go to `outputs/eval_*.json` / `guardian_eval_*.json`; the HTML
report shows a live run of the scenarios in both modes. Label all results as exploratory
(small, synthetic set).

## Snowflake Cortex notes

- Account: not set up yet (will apply with school email, US region). Until then,
  develop everything in mock mode.
- Use the official Snowflake Python packages to connect. Credentials come from `.env`.
- Before writing Cortex code, check the current Snowflake docs for the exact LLM
  function name, available models in our region, and Cortex Search setup. Do not guess
  API names.
- Keep Cortex-specific code inside `adapters/` only.

## Dev setup

- Python 3.12, `venv` + `pip` for dependencies (agreed with the team; no `uv`)
- Dependencies: `langgraph`, `pydantic`, `pyyaml`; dev: `pytest`.
  Snowflake packages are added later, once Cortex access exists.
- `pytest` for tests; tests always use mock adapters and never call Snowflake
- Commands (run from the project root):
  - create env: `python3 -m venv .venv && source .venv/bin/activate`
  - install: `pip install -e ".[dev]"`
  - run a scenario: `python -m agents_demo.cli run scenarios/<file>.json`
  - run eval: `python -m agents_demo.cli eval --mode 3`
  - run Guardian-only eval: `python -m agents_demo.cli guardian-eval`
  - tests: `pytest`

## Rules for Claude Code

- Keep changes small and focused on the task asked. Do not add features outside this file's scope.
- Ask before adding a new dependency.
- Never put credentials in code, logs, traces, or commits.
- Code and comments in English. Keep names plain and readable.
- Every new node or rule needs a unit test with mock adapters.
- Do not let the LLM make threshold or final decisions; if a change would do that, stop and ask.
- When unsure about a Snowflake API, say so and point to what needs checking instead of guessing.

## Stages and progress

**Current stage: Stage 5 (not started).** Details, changes, and open questions for each
stage are logged in `note.md`.

### Stage 1: Mock-mode demo — DONE (2026-10-20)
- [x] Sample lesson content, misconception map, remediations, protected questions
- [x] Contracts + rules (poll threshold, lookup, limit, protected check, final validator)
- [x] LangGraph flows: poll path, question path with 2-agent / 3-agent toggle
- [x] Mock adapters (LLM + retrieval), timeout -> escalate fallback
- [x] Scenarios (9 files), eval set (11 questions), HTML report, JSONL traces
- [x] Unit tests (58, all mock)
- Done when: all scenarios and eval run offline and tests pass. Met.

### Stage 2: Snowflake setup — DONE (2026-10-21)
- [x] Account (school email; ended up <account region>, see note.md); confirm Cortex LLM availability and models in region
- [x] Role, XS warehouse (auto-suspend), database + schema for the demo
- [x] Decide auth method (check docs; key pair likely) and fill `.env`
- [x] Load approved lesson chunks into a table (only static, approved content)
- [x] Create a Cortex Search service over that table
- [x] Connection smoke test script (reads `.env`, runs one trivial query)
- Done when: smoke test passes and a manual Cortex Search query returns our chunks.

### Stage 3: Cortex adapters — DONE (2026-10-21)
- [x] Check docs for exact LLM / Search Python APIs before coding; record findings in `note.md`
- [x] Add Snowflake package(s) as a dependency (ask first)
- [x] `CortexLLM`: send prompt, parse JSON reply, map timeouts/errors to `LLMError`
- [x] `CortexSearchRetriever`: query the service, return chunk ids, text, score
- [x] Tests still use mocks; add an opt-in manual check for the real backend
- Done when: scenarios 02-05 run with `BACKEND=cortex` and produce valid decisions + traces.

### Stage 4: Real-model eval and tuning — DONE (2026-10-22)
- [x] Run eval in mode 2 and 3 with `BACKEND=cortex`; record latency (answers demo question 4)
- [x] Tune prompts and thresholds; log every change (Guardian prompt + rule made stricter;
      Guardian skipped when escalation is certain; other tuning deferred, see below)
- [x] Add cases where the real model behaves differently from the mock
      (`eval/guardian_cases.json`; end-to-end "tempting" questions deferred, see below)
- [x] Report: live run of all scenarios, mode 2 next to mode 3 (simplified, per the user)
- Done when: Cortex eval and Guardian results are recorded in `note.md`, and the report
  shows live mode 2 / mode 3 scenario results. Met. (The original criterion, "the report
  answers all four demo questions", was dropped by the user; the answers are in `note.md`.)
- Deferred to a later quality pass (not blocking Stage 5): model choice / per-node models,
  `confidence_threshold` and protected-similarity tuning, Guardian timeout, the 6 "tempting"
  end-to-end eval questions, eval labels written for the mock.

### Stage 5: Team handoff
- [ ] Go through `interface_questions.md` with the team; record each outcome there
- [ ] Confirm decision + trace contracts with the front end / backend and pipeline teammates
- [ ] Confirm trace JSONL can be loaded into Bronze as is
- [ ] Walkthrough: README + report + a live run of the scenarios
- Done when: teammates have run the demo and signed off on the contracts.

## Working across sessions

- At the start of a session: read this section and `note.md` to see where we are.
- While working: add entries to `note.md` for anything that changed the plan or the design,
  any deviation from this file, findings from the Snowflake docs, and open questions.
- Whenever something touches an interface other parts depend on (input/output fields,
  allowed values, trace content, shared settings or team-level decisions), add or update
  an item in `interface_questions.md`. Format: current approach, why change, suggested
  direction. Do not change the shared contracts on your own; record the item instead.
- When a task or stage is finished: tick it here, update "Current stage", and log it in `note.md`.
