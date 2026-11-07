---
paths:
  - "src/classpilot/**"
  - "tests/**"
  - "config/**"
  - "sql/**"
  - "scripts/**"
  - "content/**"
  - "scenarios/**"
  - "eval/**"
  - "compiled/**"
  - "docs/agent/**"
  - "docs/v1/**"
  - "docs/v2/**"
  - "pyproject.toml"
---

# Agent part rules — prep service, parse layer, live agents, trace, report

Owner: Han-Sheng. These rules load when Claude works on the agent part's files (paths
above). Read this whole file before starting agent-part work. The shared rules in the
root `CLAUDE.md` always apply as well.

## Project context
ClassPilot Live runs a full class session when the professor is unavailable. It is a
3-person course project (data engineering + GenAI):

| Part | Owner |
|---|---|
| Front end, live backend (WebSocket, Redis, TTS playback, polls) | Sai |
| Data pipeline (Snowflake star schema, dbt) | Yaksha |
| **Prep service, parse layer, generators, live Q&A and poll endpoints, trace, dev report (this file)** | Han-Sheng |

The professor does two things: upload materials, and read the post-class report
(deferred: BEHAVIOR 7). Nothing generated is reviewed by a person before class;
automatic checks replace review.

Source of truth:
- Behavior: `docs/v2/CLASSPILOT_BEHAVIOR.md`
- Implementation, manifest, trace records, API, decisions log: `docs/v2/IMPLEMENTATION_NOTES.md`
- Stage plan with checks and exit gates: `docs/v2/STAGES.md`
- v1 reuse map and repo decision: `docs/v2/ANALYSIS.md`
- v1 design (history only): `docs/v1/CLAUDE_v1.md`

Where v1 and v2 conflict, v2 wins. Where the v2 docs are unclear, ask; do not guess.

## Architecture (summary)

```
PREP (before class)                       LIVE (in class)                     REPORT (deferred)
upload -> convert (local) -> stage ->     question -> retrieval -> Analyst     decision log
parse (AI_PARSE_DOCUMENT; vision only     -> Responder -> Guardian ->          + traces + poll
for image pages) -> chunks ->             validator (rule) -> answer/escalate  evidence +
LESSON_CHUNKS_V2 -> search service ->     poll result -> rule (code) ->        manifest status
generate + Guardian check (DSPy) ->       explain (text + show_slide)/reveal   -> HTML report
manifest

DEV REPORT (Stage 10): lesson folder -> prep run + fixed test questions -> HTML
```

- LangGraph controls the question flow; DSPy modules are the LLM nodes (Analyst,
  Responder, Guardian; prep generators Segmenter, ScriptWriter, PollPlacer, PollWriter,
  ExplanationWriter). The poll path is a plain function, no LLM.
- Snowflake Cortex provides the LLM, parsing, and Cortex Search. All Snowflake code sits
  behind adapters; everything runs offline in mock mode.
- One FastAPI service: prep endpoints and live endpoints (question, poll result).
  Shapes are decided by the agent side and recorded in `interface_questions.md`.
- Dev report (Stage 10): `cli dev <lesson_id>` preps a lesson folder, runs its fixed
  test questions, and writes static HTML. The post-class report is deferred.

## Hard rules

- Thresholds and final decisions are always code, never the LLM. If a change would let
  the LLM decide, stop and ask.
- Any LLM timeout or error leads to a safe outcome: fallback before class, escalate in
  class. Never hang.
- Prep may write its own stage and tables (`RAW_FILES`, `PARSED_PAGES`,
  `LESSON_CHUNKS_V2`). The live path never reads event tables; live evidence is passed in.
- Every live decision writes trace records (run, node, LLM call, retrieval, claim, poll
  evidence) and a decision-log line with its text.
- Tests always use mocks and never call Snowflake.
- Snowflake credits: each live stage is approved once at its start, based on the
  estimated LLM calls; inside it, up to 1.5× the estimate without asking again. Beyond
  that, stop and ask. (Expected dependencies: IMPLEMENTATION_NOTES section 10.)
- The shared rules in the root `CLAUDE.md` (public repo, secrets, Snowflake approval,
  dependencies, push checks) apply here too.
- Keep the code account-portable: account, region, model and object names come from
  `.env` / `config/settings.yaml`. Record account-dependent findings per account in
  `docs/agent/note.md`.
- Items marked **[verify]**: check current official docs, or run a small live probe with
  approval, before relying on them. Record findings in `docs/agent/note.md`. Do not guess Snowflake,
  LiteLLM, or DSPy API names.
- Items marked **[team]** (interfaces another part reads or sends): if the agent side
  can settle it, decide it, implement it, and record it in `interface_questions.md`
  with status `decided` and the reason; teammates can reopen it. Leave it `open` only
  when it needs a value or choice that only another part has.
- Keep changes small and focused on the current stage. Every new node, rule, generator,
  parser step, and endpoint has a unit test with mocks.

## Scope

In scope: prep service (upload, parse, chunk, generate, check, manifest), live Q&A and
poll-rule endpoints, trace records and decision log, the dev report (Stage 10). The
post-class report is deferred (owner and source decided later).

Out of scope for the agent part (other parts own them): front end, Redis/WebSocket, TTS, dbt
models. Out of scope for everyone for now: deployment, auth, multi-user
handling, the future-work list in BEHAVIOR section 9.

## Data contracts

Decided by the agent side, open to change requests (`interface_questions.md` Q-13 to Q-22). Code: live shapes
in `src/classpilot/contracts/live.py`, manifest in `contracts/manifest.py`, trace and
decision log in `contracts/trace.py`. Full definitions: manifest in IMPLEMENTATION_NOTES
section 5, trace records in section 6.3, API in section 3. A test validates every JSON
block below against its model, so keep them current.

Poll evidence (v1 fields plus `lesson_id` and `poll_id`, without `remediations_used`; Q-14):
```json
{"session_id": "session-001", "lesson_id": "dbt-basics-01", "poll_id": "q-01",
 "objective_id": "seg-02",
 "question_id": "q-01", "snapshot_time": "2026-10-22T18:30:40Z",
 "connected_students": 24, "answers_received": 21,
 "option_counts": {"A": 3, "B": 13, "C": 4, "D": 1}, "correct_option": "A"}
```

Student question (v1 fields plus `lesson_id` for the retrieval filter; Q-19):
```json
{"session_id": "session-001", "event_id": "evt-123", "lesson_id": "dbt-basics-01",
 "anonymous_learner_id": "learner-017", "objective_id": "seg-01",
 "question_text": "Why do we keep raw data in Bronze if it has errors?",
 "submitted_at": "2026-10-22T18:31:05Z"}
```

Decision: `action` is `explain | reveal | answer | escalate`; `escalation_reason` is
`out_of_scope | low_confidence | unsupported | llm_error`. Explain
carries the option, the misconception and remediation ids, the remediation text, and
`show_slide`; explain and reveal carry `correct_option`. Unused fields are `null`.
```json
{"decision_id": "dec-1a2b3c4d", "session_id": "session-001", "path": "poll",
 "action": "explain", "poll_id": "q-01", "option": "B", "misconception_id": "M-01",
 "remediation_id": "R-01", "remediation_text": "Bronze keeps raw data exactly as it arrived.",
 "show_slide": "deck1-p03", "correct_option": "A", "answer_text": null, "citations": null,
 "escalation_reason": null, "confidence": null}
```
```json
{"decision_id": "dec-5e6f7a8b", "session_id": "session-001", "path": "question",
 "action": "answer", "poll_id": null, "option": null, "misconception_id": null,
 "remediation_id": null, "remediation_text": null, "show_slide": null,
 "correct_option": null, "answer_text": "We keep raw data unchanged so we can replay it.",
 "citations": ["deck1-p03-c1"], "escalation_reason": null, "confidence": 0.84}
```

Trace records (one JSONL line each; `record_type` is `run | node | llm_call | retrieval |
claim | poll_evidence`; Q-21). Two examples:
```json
{"schema_version": "v2-draft", "run_id": "dec-5e6f7a8b", "session_id": "session-001",
 "created_at": "2026-10-22T18:31:09Z", "record_type": "run", "path": "question",
 "lesson_id": "dbt-basics-01", "input_ref": "evt-123", "segment_id": "seg-01",
 "misconception_id": null, "remediation_id": null, "final_action": "answer",
 "escalation_reason": null, "deciding_node": "validator",
 "started_at": "2026-10-22T18:31:05.120Z", "ended_at": "2026-10-22T18:31:09.480Z",
 "latency_ms": 4360, "llm_call_count": 3, "confidence": 0.84, "backend": "cortex"}
```
```json
{"schema_version": "v2-draft", "run_id": "dec-5e6f7a8b", "session_id": "session-001",
 "created_at": "2026-10-22T18:31:09Z", "record_type": "node", "node_seq": 4,
 "node_name": "guardian", "status": "pass", "latency_ms": 1210, "llm_call_count": 1}
```

The decision log (`outputs/decision_log.jsonl`) has one entry per decision: the
decision plus the question or the poll evidence it answered.

## Folder layout

```
classpilot-live/
  CLAUDE.md  README.md  interface_questions.md  LICENSE  pyproject.toml  .env.example
  .claude/rules/agent.md     # this file
  docs/agent/note.md         # dev log of the agent part
  config/settings.yaml       # thresholds, parameters, model names (no account values)
  docs/v1/  docs/v2/         # v1 archive + results; v2 design and plan
  sql/                       # setup scripts; shown before they run
  scripts/                   # smoke test, search service, SQL runner, check_secrets.sh
  src/classpilot/            # package; contracts/, rules/, live/ are in the ANALYSIS 2.6
                             #   layout, the rest moves there stage by stage
  content/ scenarios/ eval/  # fixture lessons + manifest (v1 lesson), scenarios, eval sets
  tests/
  compiled/                  # saved DSPy programs (live-qa-v5, prep-v6)
  materials/                 # gitignored: real course content; lessons/<id>/ holds
                             #   slides/, refs/, test_questions.json (Stage 10)
  outputs/                   # gitignored: traces, eval results, dev reports
```

## Stages

| Stage | Name |
|---|---|
| 0 | Repository setup and v2 docs |
| 1 | Live probes for `[verify]` items |
| 2 | Live paths, manifest, and trace on v2 contracts (mock) |
| 3 | Live agents as DSPy modules |
| 4 | Parse layer, local conversion |
| 5 | Parse layer in Snowflake, chunks, and search |
| 6 | Generators and the prep-time Guardian (mock) |
| 7 | Live prep run on one deck |
| 8 | Service API (prep and live endpoints) |
| 9 | Eval expansion, DSPy compile, baseline comparison |
| 10 | Dev report (prep output and live test questions) |
| 11 | Integration, rehearsal, handoff |
| 12 | Agent quality (live Q&A, prep, DSPy, more lessons) |

**Current stage: Stage 12 (at its exit gate; the rest of Stage 11 follows it).** Stages 0-2 accepted 2026-11-04, Stages 3-8 on 2026-11-05, Stages 9-10 on 2026-11-06. Every stage ends at its exit gate: run the
automated checks, report the results, list what the user must review, and wait for
approval before the next stage. Details are in `docs/v2/STAGES.md`.

## Dev setup

- Python 3.12, `venv` + `pip` (no `uv`).
- Commands (from the repo root):
  - create env: `python3 -m venv .venv && source .venv/bin/activate`
  - install: `pip install -e ".[dev]"` (add `,snowflake` for the Cortex backend)
  - LibreOffice (PPTX → PDF, Docker only, nothing on the host): `scripts/libreoffice/build.sh`
  - local conversion: `python -m classpilot.cli prep convert <slides> --ref <reference>`
  - parse a lesson: `python -m classpilot.cli prep parse --lesson <id> <slides> --ref <ref>`
    (mock; `BACKEND=cortex` after approval); `prep search --lesson <id> "<query>"`
  - generate a lesson: `python -m classpilot.cli prep generate --lesson <id> [--poll-count N]`
    (from the stored parse); whole pipeline: `prep run --backend mock --lesson <id> <slides>`;
    checks + review sheet: `prep check --lesson <id>`
  - service: `uvicorn classpilot.service.app:create_app --factory --port 8000` (docs at `/docs`)
  - SQL templates: `python scripts/run_sql.py sql/<file>.sql` (prints; `--execute` runs)
  - tests: `pytest`
  - lint / format: `ruff check .` and `ruff format --check .` (`ruff format .` to fix)
  - scenarios: `python -m classpilot.cli run-all`
  - DSPy experiments: `python -m classpilot.cli optimize-guardian --method eval|rs|gepa --kind live|script|poll|explanation`
  - eval: `python -m classpilot.cli eval`; Guardian-only: `python -m classpilot.cli guardian-eval`
  - secret check: `scripts/check_secrets.sh` (add `--history` before a push)

Standard automated checks for every stage: `pytest` (mock only, no network), `cli run-all`
matches, `ruff check`, `ruff format --check`, `scripts/check_secrets.sh`, and no `.env`,
`outputs/`, `materials/`, keys, or `.venv` in `git ls-files`.

## Working across sessions

- At the start of a session: read this file, the latest part of `docs/agent/note.md`, and the
  current stage in `docs/v2/STAGES.md`. v1 docs are archived in `docs/v1/`; read them
  only for history or the Stage 4 baseline (`docs/v1/note_v1.md`).
- `docs/agent/note.md` records only what someone needs later: changes to the plan or
  design, deviations from these rules, significant findings (things that change how we
  build or what it costs), user decisions, and open questions that block work. Do not
  log routine task completion, step-by-step results, or anything the commits and plan
  already show. Entries are 1-3 lines (`- YYYY-MM-DD [type] text`; types `change`,
  `decision`, `finding`, `question`, `result`); one short `result` entry per stage.
- Anything that touches an interface other parts depend on goes into
  `interface_questions.md` (current approach, why change, suggested direction). Do not
  change shared contracts on your own.
- When a stage is accepted: update "Current stage" here and log it in `docs/agent/note.md`.
