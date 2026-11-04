# CLAUDE.md — ClassPilot Live v2 (prep service + agents)

## Project context

ClassPilot Live runs a full class session when the professor is unavailable. It is a
3-person course project (data engineering + GenAI):

| Part | Owner |
|---|---|
| Front end, live backend (WebSocket, Redis, TTS playback, polls) | Sai |
| Data pipeline (Snowflake star schema, dbt) | Yaksha |
| **Prep service, parse layer, generators, live Q&A and poll endpoints, trace, report: this repo** | Han-Sheng |

The professor does two things: upload materials, and read the post-class report. Nothing
generated is reviewed by a person before class; automatic checks replace review.

Source of truth:
- Behavior: `docs/v2/CLASSPILOT_BEHAVIOR.md`
- Implementation, manifest, trace records, API, decisions log: `docs/v2/IMPLEMENTATION_NOTES.md`
- Stage plan with checks and exit gates: `docs/v2/STAGES.md`
- v1 reuse map and repo decision: `docs/v2/ANALYSIS.md`
- v1 design (history only): `docs/v1/CLAUDE_v1.md`

Where v1 and v2 conflict, v2 wins. Where the v2 docs are unclear, ask; do not guess.

## Architecture (summary)

```
PREP (before class)                       LIVE (in class)                     REPORT
upload -> convert (local) -> stage ->     question -> Analyst -> retrieval     decision log
parse (AI_PARSE_DOCUMENT; vision only     -> Responder -> Guardian ->          + traces + poll
for image pages) -> chunks ->             validator (rule) -> answer/escalate  evidence +
LESSON_CHUNKS_V2 -> search service ->     poll result -> rule (code) ->        manifest status
generate + Guardian check (DSPy) ->       explain (text + show_slide)/reveal   -> HTML report
manifest
```

- LangGraph controls the question flow; DSPy modules are the LLM nodes (Analyst,
  Responder, Guardian; prep generators Segmenter, ScriptWriter, PollPlacer, PollWriter,
  ExplanationWriter). The poll path is a plain function, no LLM.
- Snowflake Cortex provides the LLM, parsing, and Cortex Search. All Snowflake code sits
  behind adapters; everything runs offline in mock mode.
- One FastAPI service: prep endpoints, live endpoints (question, poll result), report
  endpoint. Shapes are `[team]` drafts.

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
- Never run anything that uses Snowflake credits without asking first. Each live stage is
  approved once at its start, based on the estimated LLM calls; inside it, up to 1.5× the
  estimate without asking again. Beyond that, stop and ask.
- Never run SQL that creates, alters, suspends, or drops Snowflake objects without
  showing it first.
- Ask before adding any dependency (expected list: IMPLEMENTATION_NOTES section 10).
- Never put credentials in code, logs, traces, docs, or commits.
- The repo will be public. Account-specific values (account identifier, region, login
  user, key path) live only in `.env`; committed files use placeholders. Service user
  and other object names are configurable defaults. `materials/` and real course content
  are never committed.
- Before every push: `scripts/check_secrets.sh --history` passes and the user reviews
  `git ls-files` and the commits. Release-blocking.
- Keep the code account-portable: account, region, model and object names come from
  `.env` / `config/settings.yaml`. Record account-dependent findings per account in
  `note.md`.
- Items marked **[verify]**: check current official docs, or run a small live probe with
  approval, before relying on them. Record findings in `note.md`. Do not guess Snowflake,
  LiteLLM, or DSPy API names.
- Items marked **[team]**: do not decide alone. Record them in `interface_questions.md`
  and use a clearly marked draft until agreed.
- Keep changes small and focused on the current stage. Every new node, rule, generator,
  parser step, and endpoint has a unit test with mocks.

## Scope

In scope: prep service (upload, parse, chunk, generate, check, manifest), live Q&A and
poll-rule endpoints, trace records and decision log, post-class report.

Out of scope: front end, Redis/WebSocket, TTS, dbt models, deployment, auth, multi-user
handling, the future-work list in BEHAVIOR section 9.

## Data contracts

Drafts until the team agrees (`interface_questions.md` Q-13 to Q-21). Full definitions:
manifest in IMPLEMENTATION_NOTES section 5, trace records in section 6.3, API in
section 3. **The code still implements the v1 contracts until Stage 2.**

Poll evidence (draft: v1 fields plus `poll_id`, without `remediations_used`; see Q-14):
```json
{"session_id": "session-001", "poll_id": "q-01", "objective_id": "seg-01",
 "question_id": "q-01", "snapshot_time": "2026-10-22T18:30:40Z",
 "connected_students": 24, "answers_received": 21,
 "option_counts": {"A": 3, "B": 13, "C": 4, "D": 1}, "correct_option": "A"}
```

Student question (draft: v1 fields; retrieval needs the lesson, so a `lesson_id` is
proposed; see Q-19):
```json
{"session_id": "session-001", "event_id": "evt-123", "lesson_id": "dbt-basics-01",
 "anonymous_learner_id": "learner-017", "objective_id": "seg-01",
 "question_text": "Why do we keep raw data in Bronze if it has errors?",
 "submitted_at": "2026-10-22T18:31:05Z"}
```

Decision (draft): `action` is `explain | reveal | answer | escalate`; `escalation_reason`
is `out_of_scope | assignment_like | low_confidence | unsupported | llm_error`; explain
decisions carry the misconception and remediation ids, the remediation text, and
`show_slide`. Unused fields are `null`.

## Folder layout

```
classpilot-live/
  CLAUDE.md  README.md  note.md  interface_questions.md  pyproject.toml  .env.example
  config/settings.yaml       # thresholds, parameters, model names (no account values)
  docs/v1/  docs/v2/         # v1 archive + results; v2 design and plan
  sql/                       # setup scripts; shown before they run
  scripts/                   # smoke test, probes, check_secrets.sh
  src/classpilot/            # package (v1 modules for now; moves to the v2 layout in
                             #   ANALYSIS 2.6 stage by stage)
  content/ scenarios/ eval/  # v1 sample lesson, scenarios, eval sets (replaced in Stage 2+)
  tests/
  compiled/                  # saved DSPy programs (from Stage 9)
  materials/                 # gitignored: real course slides and references
  outputs/                   # gitignored: traces, eval results, reports
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
| 10 | Post-class report |
| 11 | Integration, rehearsal, handoff |

**Current stage: Stage 1 (in progress).** Stage 0 accepted 2026-11-04. Every stage ends at its exit gate: run the
automated checks, report the results, list what the user must review, and wait for
approval before the next stage. Details are in `docs/v2/STAGES.md`.

## Dev setup

- Python 3.12, `venv` + `pip` (no `uv`).
- Commands (from the repo root):
  - create env: `python3 -m venv .venv && source .venv/bin/activate`
  - install: `pip install -e ".[dev]"` (add `,snowflake` for the Cortex backend)
  - tests: `pytest`
  - lint / format: `ruff check .` and `ruff format --check .` (`ruff format .` to fix)
  - scenarios: `python -m classpilot.cli run-all`
  - eval: `python -m classpilot.cli eval --mode 3`; Guardian-only: `python -m classpilot.cli guardian-eval`
  - secret check: `scripts/check_secrets.sh` (add `--history` before a push)

Standard automated checks for every stage: `pytest` (mock only, no network), `cli run-all`
matches, `ruff check`, `ruff format --check`, `scripts/check_secrets.sh`, and no `.env`,
`outputs/`, `materials/`, keys, or `.venv` in `git ls-files`.

## Working with the user

- Talk with the user in Chinese (Traditional). Every file (docs, code, comments, commit
  messages) is in English.
- Give a short Chinese summary at the start and at the end of every stage.

## Working across sessions

- At the start of a session: read this file, the latest part of `note.md`, and the
  current stage in `docs/v2/STAGES.md`. v1 docs are archived in `docs/v1/`; read them
  only for history or the Stage 4 baseline (`docs/v1/note_v1.md`).
- While working: log changes to the plan or design, deviations from this file, findings
  from docs or probes, and open questions in `note.md` (`- YYYY-MM-DD [type] text`;
  types `change`, `decision`, `finding`, `todo`, `question`, `result`).
- Anything that touches an interface other parts depend on goes into
  `interface_questions.md` (current approach, why change, suggested direction). Do not
  change shared contracts on your own.
- When a stage is accepted: update "Current stage" here and log it in `note.md`.
