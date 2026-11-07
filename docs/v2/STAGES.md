# ClassPilot Live v2: Stage plan

Status: approved with changes 2026-11-04; this version includes those changes. Based
on IMPLEMENTATION_NOTES.md (updated 2026-11-04) and `ANALYSIS.md`. Question numbers
such as Q7 point to `ANALYSIS.md` section 3 (answers are in the IMPLEMENTATION_NOTES
decisions log); `Q-nn` are items in `interface_questions.md`.

## Order and why

| Choice | Why |
|---|---|
| Live probes are their own stage (1), right after repo setup. | Route A or B, the vision model, and parse availability decide how stages 3, 5, and 6 are built. Cheap to answer first. |
| Path A/B on v2 contracts and the trace v2 structure come early (Stage 2). | Mostly deleting v1 code. Gives Sai and Yaksha draft contracts, the team manifest model, and trace records early. |
| The DSPy port of the live agents (3) comes before the generators. | It is checked against the known Stage 4 baseline on the v1 lesson, which proves the DSPy and Cortex path before any new content exists. |
| The parse layer is split into local (4) and Snowflake (5). | Local conversion runs without credits and is easy to test. Snowflake parse needs SQL review and live runs. |
| Generators are split into mock (6) and one live deck run (7). | Content review needs a live run, but the retry and fallback logic does not. |
| The service API (8) comes after the pipeline runs from the CLI. | The endpoints are thin wrappers. Their shapes are a `[team]` item anyway. |
| Agent quality (12) runs while Stage 11 waits for the team; the Stage 11 rehearsal comes after it. | Stage 11's first task (interfaces, handoff) is done; integration and rehearsal need Sai and Yaksha. The rehearsal should run the improved programs, and quality work changes no field the teammates read. |
| Further optimization (13) is optional and never blocks Stage 11. | Stage 12 met its gate; Stage 13 only runs when the user starts it (for example while waiting on the team, or after the rehearsal). |

No dates: the plan aims for completeness, not a deadline. You decide when each stage
runs.

## Rules that apply to every stage

- Tests use mocks only and never call Snowflake. `force_mock_backend` stays in
  `conftest.py`.
- Thresholds and final decisions are code, never the LLM.
- Live Snowflake use: each live stage is approved once, at its start, based on its
  estimated LLM calls. Inside the stage I may run up to **1.5× the estimate** without
  asking again. Beyond that I stop and ask.
- SQL that creates, alters, suspends, or drops objects is shown before it runs.
- Dependencies are added only after you approve them.
- No credentials in code, logs, traces, docs, or commits.
- The repo will be public. Account-specific values (account identifier, region, login
  user, key path) live only in `.env`. Committed docs, SQL, and config use
  placeholders. `materials/` and real course content are never committed.
- Code is account-portable: account, region, model and object names come from `.env`
  or `config/settings.yaml`. Account-dependent findings go into docs/agent/note.md per account.
- `[verify]` items are checked in current docs or with an approved probe before code
  relies on them. Findings go to docs/agent/note.md.
- `[team]` items: the agent side decides what it can settle and records it in
  interface_questions.md as `decided` (teammates can reopen it); only items that need
  another part's input stay `open`.
- Cost estimates are rough until Stage 1 replaces them with real readings.

**Standard automated checks** ("standard checks" in each stage below):
- `pytest` passes with mock adapters only, and no test opens a network connection.
- `cli run-all` matches every scenario's expectation in mock mode.
- `ruff check` and `ruff format --check` pass.
- `scripts/check_secrets.sh` passes on the tree and on the new commits
  (`git log -p <since last push>`).
- `git ls-files` contains no `.env`, `outputs/`, `materials/`, keys, or `.venv`.

**Before every push** (release-blocking, since the repo will be public): the secret
check passes, and you review the `git ls-files` list and the commits being pushed.

---

## Stage 0: Repository setup and v2 docs
Goal: A new private repo `classpilot-live` holds the cleaned v1 code as package
`classpilot`, tests and ruff pass, account-specific values are out of committed
files, and the v2 docs are in place. Behavior does not change.
Depends on: approval of this plan (Q1–Q4 answered).
Tasks:
- Create the folder `classpilot-live` and run `git init`. Write `.gitignore` per
  ANALYSIS 2.3.
- Copy the kept files (ANALYSIS 2.6) and rename the package `agents_demo` → `classpilot`
  (imports, `pyproject.toml`, CLI module path). Keep the v1 data the tests still need
  for now.
- Add `ruff` as a dev dependency with its config in `pyproject.toml`. Format and fix
  the carried code in its own commit (no logic changes).
- Move account-specific values out of committed files:
  - account locator, region names, login user, and key path in `docs/agent/note.md`, the v1
    archive, `docs/v2/`, `README.md`, `.env.example`, `config/settings.yaml` comments,
    and `sql/` → placeholders
  - SQL object names become variables set at the top of each script, so the scripts
    can be rerun on a new account (deferred to Stage 5: the docs do not confirm
    `IDENTIFIER($var)` for every statement used; see docs/agent/note.md 2026-11-04)
- Archive v1: `docs/v1/CLAUDE_v1.md`, `ARCHITECTURE_v1.html`, `DEMO_OVERVIEW_v1.html`,
  and `docs/v1/results/` (Stage 4 Cortex eval JSONs, mode 2 and mode 3).
- `docs/agent/note.md`: copy (redacted) and add a dated v2 `change` entry.
- `interface_questions.md`: add the items in IMPLEMENTATION_NOTES section 12. Archive
  the v1 items (Q-01 to Q-12) in `docs/v1/`; they are not carried into v2.
- New `CLAUDE.md`: goal, architecture, hard rules (the project rules, the replacement
  for the v1 Snowflake rule, account portability, public-repo rules), scope, folder
  layout, the stage list from this file, and dev setup (including ruff).
- `scripts/check_secrets.sh`: grep for private key headers, `snowflakecomputing.com`,
  account locator patterns, region strings, `/Users/` and key paths, email addresses,
  and a tracked `.env`.
- Short README for v2 (setup, mock run, where the docs are).
- Local commits only. Push to a private GitHub repo after your review.
Out of scope for this stage:
- Any behavior change, any dependency other than `ruff`, Snowflake use.
Automated checks:
- Standard checks. 85 tests pass under the new package name.
- `check_secrets.sh` finds nothing in the tree or the history, and flags a planted test
  string such as a fake `BEGIN PRIVATE KEY` or a region name (run once, not committed).
Human review:
- The `ruff` dependency.
- Repo visibility (private for now) and the full `git ls-files` list before the push.
- New `CLAUDE.md`, the docs/agent/note.md entry, and the interface_questions changes.
- The placeholder replacements (is anything account-specific left?).
Live Snowflake usage: none
Done when: the new repo has a green v1 under `classpilot`, ruff passes, the secret
check passes on tree and history, the v2 docs are in place, and you have approved the
push.
Exit gate: stop, report results of the automated checks, list what I need to review,
and wait for my approval before starting the next stage.

## Stage 1: Live probes for `[verify]` items
Goal: Settle the facts the design depends on (DSPy ↔ Cortex route, vision model and the
image-page idea, document parsing, search filter, cost per call) with small scripts,
before code is built on them.
Depends on: Stage 0; approval to add `dspy` (and `PyJWT` if Route A needs it; and
`pymupdf` early if the vision probe needs a text layer).
Tasks:
- Docs check (no credits). Record each finding with a link and date in docs/agent/note.md:
  - current `dspy.LM` and `dspy.BaseLM` API
  - the LiteLLM `snowflake/` provider and its auth (JWT / PAT)
  - Cortex REST models reachable from the current account
  - `AI_PARSE_DOCUMENT` region support, and whether it extracts PPTX notes
  - vision models (including claude-haiku-4-5), and `response_format` with image
    prompts
  - Cortex Search filter syntax and target lag
  - `dspy.Refine`
  - DSPy's test LM (`DummyLM` or its current name)
- Cost calibration: read what the v1 Stage 3/4 runs actually cost from
  `CORTEX_AI_FUNCTIONS_USAGE_HISTORY` and `WAREHOUSE_METERING_HISTORY`.
- Probe Route A: `dspy.LM("snowflake/<model>")`, one Analyst-style structured call.
- Probe Route B: a minimal custom `dspy.BaseLM` over the existing `AI_COMPLETE`
  adapter, same call.
- For the chosen route, force a timeout and a malformed reply and check that both map
  to `LLMError`.
- Vision probe on 3 slides from one deck (one text-only, one diagram, one mixed):
  `AI_COMPLETE` plus image plus `response_format`, on 2 candidate models. For each
  slide, record whether vision added information beyond the text layer. This tests the
  image-page heuristic idea before Stage 4 builds it.
- Parse probe: `AI_PARSE_DOCUMENT` (LAYOUT, page_split) on one reference PDF of a few
  pages.
- Probe SQL: a probe stage with a directory table (shown first).
- Record the decisions: route, the cheapest passing model per role (live Q&A,
  generation, vision).
- Write account-dependent findings (models, cross-region setting, costs) under a
  per-account heading in docs/agent/note.md.
Out of scope for this stage:
- Product code. Probes live in `scripts/probes/` and are not imported by `src/`.
- Compiling, generation, and chunking.
Automated checks:
- Standard checks. No test imports `scripts/probes/`.
- Probe output goes to `outputs/` (gitignored), not to the repo.
- The probe scripts read account and model names from `.env` / settings (no literals).
Human review:
- The `dspy` dependency (plus `PyJWT` / `pymupdf` if needed).
- The probe stage SQL before it runs.
- Vision output for the 3 slides against the real slides, and the image-page findings.
- Cost readings (v1 calibration plus this stage), the route, the models, and the
  per-call cost figures that replace the estimates in this file.
Live Snowflake usage: about 15–25 LLM calls (2 routes × a few calls, 3 slides × 2
models, error probes), 1 parse call on a few pages, 2 ACCOUNT_USAGE queries, and a few
minutes of XS warehouse. Expected under $3 (rough). Approval limit: 1.5× = about 38
calls.
Done when: every `[verify]` item in IMPLEMENTATION_NOTES 4.2, 4.3, 7.2, 7.4, and 9 has a
finding in docs/agent/note.md (or "still open" with a reason), the route and models are chosen,
and a cost per call is known.
Exit gate: stop, report results of the automated checks, list what I need to review,
and wait for my approval before starting the next stage.

## Stage 2: Live paths, manifest, and trace on v2 contracts (mock)
Goal: Path A gives `explain` (with remediation text and `show_slide`) or `reveal` from a
team-structure manifest. Path B runs in 3-agent mode only, without the protected check,
with retrieval as its own node and a `lesson_id`. Trace v2 records and the decision log
exist. Draft contracts are ready to show the team.
Depends on: Stage 0. Contracts are marked DRAFT until the team agrees.
Tasks:
- `contracts`:
  - `Action` gets `explain` / `reveal`.
  - Reasons are reduced to the 5 in BEHAVIOR 5.3.
  - `remediation_id` in the decision is replaced by the poll's
    misconception / remediation ids.
  - `PollEvidence` gets `poll_id` and loses `remediations_used`.
- `Manifest` model following the team structure (IMPLEMENTATION_NOTES section 5) and a
  fixture manifest that uses it. Validation rules:
  - every wrong option is in `known_wrong`
  - each misconception has exactly one remediation
  - `show_slide` and all segment slides are real slide ids
  - a segment without a poll has `active_poll: null` and `questions: {}`
  - `active_poll` never points to a question with `status: "dropped"`
- Path A as a plain function: `check_poll_threshold` (unchanged) → `decide_poll` →
  `known_wrong[option]` → misconception → remediation → returns `text` + `show_slide`;
  otherwise `reveal` with the correct option. No correct-answer explanation.
- Path B: remove `protected_check`, split out a `retrieval` node, mode 3 only (remove
  `AGENT_MODE` and the mode-2 path), `lesson_id` filter in the mock retriever.
- **Trace v2 structure** (IMPLEMENTATION_NOTES 6.3), as draft field names:
  - run, node, LLM call, retrieval, claim, and poll-evidence records
  - `prompt_version` = `uncompiled-v1` until Stage 9
  - none of the removed fields (scenario key, assignment key, max reteach,
    matches-expected, support score, is-approved, token counts)
- Decision log (draft): every decision with its text (question, answer, sources,
  escalation reason, explain text), as JSONL.
- Delete the misconception map file, remediations file, protected questions, the
  mode-2 code, and their tests.
- Update the scenarios (ANALYSIS 1.3). Add scenarios for explain with `show_slide`,
  reveal, and the `lesson_id` filter.
- Record all contract changes in interface_questions.md.
Out of scope for this stage:
- The HTTP endpoints (only the functions they will call), DSPy (nodes keep their v1
  prompts behind the same interface), parsing, and the prep service.
- Real values for model, cosine, and claims in the trace (Stage 3; mock values here).
- Enforcing "at most one trigger per poll" across repeated calls. The backend calls the
  rule once per poll; recorded as a `[team]` point.
Automated checks:
- Standard checks.
- Every new or changed rule has a unit test: `decide_poll` explain/reveal, the
  `known_wrong` → remediation lookup, each manifest validation rule, the `lesson_id`
  filter.
- Contract test: a fixture run of each path produces one valid record of each trace
  type that applies (poll: run, node, poll evidence; question: run, node, LLM call,
  retrieval, claim), and no removed field appears.
- The JSON examples in `.claude/rules/agent.md` (and the manifest example in
  IMPLEMENTATION_NOTES section 5) validate against their pydantic models (poll
  evidence, question, decision, trace records, manifest).
- The schema-sync test (`TASK_SCHEMAS` ↔ pydantic) still passes.
- grep finds no `reteach`, `no_mapping`, `remediation_limit`, `protected`, or
  `agent_mode` left in `src/`.
Human review:
- Every contract change (diff plus interface_questions entries), the manifest model and
  fixture, the trace record shapes, and the decision log shape.
Live Snowflake usage: none
Done when: all v2 live scenarios run offline and match, v1-only code and data are gone,
trace v2 and decision-log records are written for every run, and the draft contracts
are recorded.
Exit gate: stop, report results of the automated checks, list what I need to review,
and wait for my approval before starting the next stage.

## Stage 3: Live agents as DSPy modules
Goal: Analyst, Responder, and Guardian become uncompiled DSPy modules carrying the v1
instructions. They run on mock and on Cortex, fill the trace records with real values,
and match the Stage 4 baseline on the v1 lesson.
Depends on: Stages 1 and 2 (route, models, contracts, trace structure).
Tasks:
- LM adapter for the chosen route. Timeouts and errors become `LLMError`, and malformed
  output becomes `llm_error`.
- Signatures for the three agents. The instructions come from the v1 prompts, including
  the strict Guardian rules. The typed outputs are `AnalystOutput`, `ResponderOutput`,
  and `GuardianOutput`.
- Mock implementations behind the same interface (port the `MockLLM` logic), so graph
  tests do not depend on DSPy internals.
- `rules.check_guardian` and the validator stay unchanged.
- Fill the trace records with real values:
  - LLM call: model, prompt version, latency, retry and error counts
  - retrieval: rank, chunk id, cosine score, cited or not, query hash
  - claims: sequence, hash, supporting chunk id or null (decided in Stage 2), supported or not
- After the live runs, suspend the v1 search service (SQL shown first).
Out of scope for this stage:
- Compiling, the expanded eval, and the generators.
Automated checks:
- Standard checks.
- Sync test: each signature's output fields match its pydantic model.
- DSPy parsing tests with the DSPy test LM (no network): a good reply parses, and a
  malformed reply gives `llm_error`.
- Every module has unit tests for success, timeout, and error.
- Trace consistency: a mock Path B run produces node, LLM-call, retrieval, and claim
  records, and the counts agree:
  - the run's LLM call count equals the number of LLM-call records
  - each node's call count equals its LLM-call records
  - retrieval records equal the retrieved chunks, and the cited flags match the
    citations
  - claim records equal the Guardian's claims
Human review:
- Signatures and the full instruction text inside them.
- The parity comparison against the Stage 4 baseline in `docs/v1/note_v1.md`:
  - eval: 11/11 actions, recall 1.0, 0 let through, 1.82 calls per question,
    answered questions 4.4–7.6 s
  - guardian-eval: 8/8 caught, 0 false fails
- A sample of real trace records from one Cortex run.
- The cost reading and the suspend SQL.
Live Snowflake usage: `eval` on the v1 lesson (11 questions, ~20 calls) plus
`guardian-eval` ×2 (24 calls), about 45 LLM calls plus search. Expected under $3
(rough; Stage 1 rate). Approval limit: about 68 calls.
Done when: Cortex eval and guardian-eval are no worse than the baseline on action
accuracy, let-through, and catch rate, or each difference is explained and you accept
it. Trace records from the Cortex run are complete.
Exit gate: stop, report results of the automated checks, list what I need to review,
and wait for my approval before starting the next stage.

## Stage 4: Parse layer, local conversion
Goal: A PPTX or PDF deck and PDF/DOCX references become per-page text, notes, PNGs, and
an image-page flag on the local machine, with file hashes, system slide ids, and a
slide/page alignment check.
Depends on: Stage 0 (and Stage 1's image-page findings); approval of `python-pptx` and
`pypdfium2` (not PyMuPDF: AGPL-3.0, repo is MIT); LibreOffice in Docker (no host install,
user decision 2026-11-05).
Tasks:
- `prep/convert.py`:
  - PPTX: python-pptx text and notes, LibreOffice → PDF, pypdfium2 → PNG.
  - PDF slides: pypdfium2 text layer and PNG.
  - Remove `pymupdf` from the dependencies (Stage 1 probes only).
  - References: PDF pages get a PNG and an image-page flag. DOCX is passed through.
- Slide ids `<source>-p<NN>`.
- Alignment check: the PPTX slide count must equal the PDF page count, and per-page text
  must roughly match. A mismatch is an error.
- PNG size limit (under 3.75 MB, downscale if needed).
- Image-page heuristic for slides and references (image count, drawing area). Output
  is `image`, `text`, or `unsure`; `unsure` goes to vision.
- SHA-256 per file as `file_id`.
- A small synthetic fixture deck (about 6 slides, made by me, with notes, one diagram
  slide, one image-only slide, and one slide with code), committed with its converted
  PDF so tests do not need LibreOffice.
- CLI: `prep convert <files>` writes to `outputs/`.
Out of scope for this stage:
- Snowflake, chunking, and generation.
Automated checks:
- Standard checks.
- Unit tests for each converter step on the fixture deck:
  - text, notes, PNG count, and the size limit
  - slide ids
  - the image-page flag on each fixture slide
  - an alignment error on a deliberately mismatched pair
  - the same hash for the same file
- A LibreOffice test that is skipped (and reported as skipped) when the LibreOffice
  Docker image is not available.
Human review:
- New dependencies and the LibreOffice Docker image.
- Conversion output for one real deck from `materials/`: page count, notes, PNG
  quality, and the image-page flags (do they match what you see?).
Live Snowflake usage: none
Done when: `prep convert` handles the fixture deck and one real deck (PPTX and PDF)
with correct alignment and plausible image-page flags.
Exit gate: stop, report results of the automated checks, list what I need to review,
and wait for my approval before starting the next stage.

## Stage 5: Parse layer in Snowflake, chunks, and search
Goal: Files go to a stage. References are parsed with `AI_PARSE_DOCUMENT`. Image pages
of slides and references get a vision `AI_COMPLETE` description. The results become
stable chunks in `LESSON_CHUNKS_V2` with a `lesson_id`-filtered search service.
Depends on: Stages 1 and 4; draft table names (`[team]`, Yaksha).
Tasks:
- SQL (parameterized object names, shown before running). Object names are filled in
  client-side by `scripts/run_sql.py` from `.env` and settings (user decision
  2026-11-05; replaces the planned `IDENTIFIER($var)` probe):
  - stage `@RAW_MATERIALS` with a directory table
  - `RAW_FILES`, `PARSED_PAGES`
  - `LESSON_CHUNKS_V2` with change tracking
  - the v2 search service with a `lesson_id` attribute
  - grants

  The v1 table and service stay untouched (suspended) for the baseline.
- Adapters: stage `PUT`, `AI_PARSE_DOCUMENT`, and vision `AI_COMPLETE`, each with a mock
  that returns canned output for the fixture deck.
- Vision runs only for pages flagged `image` or `unsure`. Text-only pages use their
  text layer and notes.
- Vision prompt: describe only what is visible. Output schema `slide_text`,
  `diagram_description`, `key_concepts`.
- `prep/chunking.py` (pure code):
  - Chunks keep `source_id`, `page_index`, and `origin`.
  - Ids are `<source>-p<NN>-c<n>`.
  - The same input always gives the same ids.
- Hash reuse: a known file hash is never parsed again, also across lessons. A reused
  file's chunks are copied for the new lesson; key = (`lesson_id`, `chunk_id`).
- Loader into `LESSON_CHUNKS_V2`. The retriever gets the new columns and the filter.
- CLI: `prep parse` (mock by default; `BACKEND=cortex` after approval).
Out of scope for this stage:
- Generation, the API, and the eval.
Automated checks:
- Standard checks.
- Chunking tests:
  - same input → same ids
  - every chunk has `source_id`, `page_index`, and `origin`
  - empty pages are handled
  - chunk ids start with their slide id
- Vision routing test: only `image` / `unsure` pages reach the vision adapter (mock).
- Hash-reuse test: a second parse of the same file (also for another lesson) makes no
  parse or vision call, and the chunks exist once per lesson with the same chunk ids.
- Schema-sync test between the vision `response_format` and its pydantic model.
- The mock end-to-end parse of the fixture deck produces the expected chunks.
- No test executes SQL.
Human review:
- All SQL before it runs.
- Vision output for about 5 image slides of the real deck, checked against the slides.
- A sample of 10 chunks.
- Cost reading.
Live Snowflake usage: one real deck (~30–40 slides; vision only for image/unsure pages,
roughly 10–20) plus one reference (~20–50 pages of `AI_PARSE_DOCUMENT`, with vision for
roughly 5–15 image pages). About 15–35 vision calls plus 1–2 parse calls and search
service creation. Expected $1–5 plus warehouse (rough). Approval limit: about 53 vision
calls.
Done when: the v2 search service returns the right lesson's chunks for 3 hand-written
queries with the `lesson_id` filter, and re-parsing the fixture (mock) gives the same
chunk ids with no new parse calls.
Exit gate: stop, report results of the automated checks, list what I need to review,
and wait for my approval before starting the next stage.

## Stage 6: Generators and the prep-time Guardian (mock)
Goal: Segments, scripts, poll placement, polls with misconceptions, and explanations
(remediations with `show_slide`) are generated as DSPy modules. Each item is checked by
the Guardian, retried once with feedback, then given a fixed fallback. A team-structure
manifest is assembled. Everything runs on mock.
Depends on: Stages 2, 3, and 5 (manifest model, Guardian module, chunk format).
Tasks:
- Signatures, all citing chunk ids and all accepting a `feedback` input:
  - `Segmenter`: segments, one objective each; the objective id is the segment id.
  - `ScriptWriter`
  - `PollPlacer`: up to `poll_count`, at most one per segment, after the last slide
    allowed.
  - `PollWriter`: question, 4 options, correct option, one misconception per wrong
    option.
  - `ExplanationWriter`: one remediation per misconception (TTS text, citations, and a
    `show_slide` picked from the slides of the cited chunks).
- No correct-answer explanation.
- Prep Guardian per item type (IMPLEMENTATION_NOTES 7.4): it sees only cited chunks.
  - scripts: transitions are not claims
  - polls: the question and the correct option are supported, and each wrong option is
    shown wrong
  - explanations: every claim is supported
- Prep rules (code):
  - structure checks:
    - 4 options
    - `correct_option` in options
    - every wrong option in `known_wrong`
    - every misconception has a remediation
    - `show_slide` is a real slide id
    - at most one poll per segment
    - at most `poll_count` polls
    - no Markdown or backticks in scripts
  - retry at most `prep_max_retries`
  - fallbacks:
    - script: slide text cleaned for TTS → vision description → fixed "look at the
      slide" sentence
    - poll: if the poll or any of its explanations fails, drop the whole poll and try
      the next segment end
  - status values `ok`, `ok_after_retry`, `fallback`, `dropped`; dropped polls stay in
    `questions` and `active_poll` points to another question or is `null`
- The TTS cleanup function is used for both script lint and the fallback text.
- The retry loop is code, not left to the LLM.
- Generation cache: a change of `poll_count` (or another generation parameter)
  regenerates from the stored parse without re-parsing.
- Manifest builder plus validation (Stage 2 model). CLI: `prep generate` on parsed
  fixture output.
- Record in interface_questions.md that dropped polls stay with `status: "dropped"`
  and the front end reads only `active_poll` (`[team]`, Sai).
Out of scope for this stage:
- Live runs, the API, and compiling.
Automated checks:
- Standard checks.
- Unit tests for every generator, prep rule, and the TTS cleanup (code and symbols are
  spelled out or removed).
- Retry-path tests:
  - pass the first time → `ok`
  - fail then pass → `ok_after_retry`, and the feedback reaches the retry
  - script fails twice → each fallback level in turn
  - one explanation fails twice → the whole poll is dropped and the next segment end
    is tried
  - never more than `prep_max_retries` retries
  - an LLM timeout → the same safe path
- Fewer usable segments than `poll_count` → fewer polls and a valid manifest.
- A `poll_count` change makes no parse call.
- The manifest validates against its model.
- The prep pipeline runs end to end (convert → parse → chunk → generate → check →
  manifest) on the fixture deck in mock mode.
Human review:
- All five signatures and their instruction text.
- The prep Guardian instructions per item type.
- The fixture manifest.
- The fixed fallback sentence.
Live Snowflake usage: none
Done when: `prep run --backend mock` turns the fixture deck into a valid team-structure
manifest, and each status value and fallback level shows up in at least one test.
Exit gate: stop, report results of the automated checks, list what I need to review,
and wait for my approval before starting the next stage.

## Stage 7: Live prep run on one deck
Goal: Run the full prep pipeline on Cortex for one real deck, measure retries,
fallbacks, cost, and time, and judge the content.
Depends on: Stage 6; your approval at the start of the stage.
Tasks:
- One full run on the deck parsed in Stage 5. Parse is reused by hash, so it adds no
  parse cost.
- Record per item type: retries, fallbacks, drops, latency, and calls.
- Small instruction fixes if the review asks for them. Each one is logged, followed by
  at most one more run.
Out of scope for this stage:
- Compiling, the API, and new item types.
Automated checks:
- Standard checks.
- The manifest validates.
- Every item has a status.
- Every citation resolves to a chunk id in `LESSON_CHUNKS_V2`.
- Every `show_slide` is a slide of a cited chunk.
- Scripts pass the TTS lint rule.
- No segment's `active_poll` points to a dropped question.
Human review:
- About 10 scripts, all polls with their misconceptions and explanations, each
  `show_slide`, and the placement.
- 3–5 Guardian decisions, including any fails, with their reasons.
- Cost reading.
Live Snowflake usage: for a 40-slide deck with 5 polls, roughly:
- 1 segment call
- 40 script calls
- 1 placement call
- 5 poll calls
- 15 explanation calls (3 wrong options × 5)
- about 60 Guardian calls
- retries

That is about 120–160 LLM calls per run, at most 2 runs (about 320). Expected $3–10 per
run (rough; Stage 1 rates). Approval limit: about 480 calls.
Done when: the run finishes with a valid manifest and you have read the sample and
accepted the quality (or listed the fixes).
Exit gate: stop, report results of the automated checks, list what I need to review,
and wait for my approval before starting the next stage.

## Stage 8: Service API (prep and live endpoints)
Goal: A FastAPI service wraps the prep pipeline (create lesson, upload, background
processing, job progress, manifest, slide images) and the two live paths (Q&A endpoint,
poll-rule endpoint). Everything runs on mock.
Depends on: Stages 2, 3, and 6; approval of `fastapi`, `uvicorn`, `python-multipart`,
and `httpx` (test); draft endpoint shapes (`[team]`, Sai).
Tasks:
- Prep endpoints per IMPLEMENTATION_NOTES 3:
  - type and size checks before any other work
  - SHA-256 reuse across lessons
  - job steps and progress, e.g. "parsing 12/40"
  - per-item failures in the job status
  - in-memory job store
  - slide images and the manifest on local disk
  - CORS for the front-end origin
- Live endpoints:
  - `POST /questions` → Path B decision. Writes the trace and decision log.
  - `POST /polls/result` → Path A decision, with `show_slide` and the text on
    `explain`. Writes the trace and decision log. If trivial, a (`session_id`,
    `poll_id`) guard returns the first decision on a repeat call; otherwise skipped.
- Credentials come only from the service `.env`. Responses and logs never contain them.
- Record all request/response shapes in interface_questions.md.
Out of scope for this stage:
- The report endpoint (the post-class report is deferred; see Stage 10).
- Auth and multi-user handling, deployment.
Automated checks:
- Standard checks.
- `TestClient` tests on mock for every endpoint:
  - happy path
  - wrong type or too large → 4xx before any processing
  - the same file twice (also to another lesson) → reused
  - job steps in order
  - a failing step → `failed` with a message
  - a missing lesson or slide → 404
  - a Q&A LLM timeout → an escalate response, not a hang or a 500
  - poll explain/reveal responses match the manifest
  - every live call writes its trace records and a decision-log line
- grep of the test logs and responses finds no credential variable values.
Human review:
- New dependencies and all endpoint shapes (interface_questions entries).
- A local run with `uvicorn` on mock: upload the fixture deck, watch the progress, then
  send one question and one poll result.
Live Snowflake usage: none
Done when: the fixture deck goes from upload to manifest through the API in mock mode,
and both live endpoints return valid decisions with trace and log records.
Exit gate: stop, report results of the automated checks, list what I need to review,
and wait for my approval before starting the next stage.

## Stage 9: Eval expansion, DSPy compile, baseline comparison
Goal: Build a labeled eval set of 40–60 questions on the v2 lesson plus 30–40 Guardian
cases you label, compile the three live modules with small `BootstrapFewShot` runs, and
compare them with the uncompiled baseline.
Depends on: Stages 3 and 5.
Tasks:
- Expand `eval/` to 40–60 questions with a train/dev split. Include the 6 "tempting"
  questions deferred in Stage 4.
- Draft 30–40 Guardian cases (live answers plus prep items: scripts, polls,
  explanations) for you to label. They are used as a metric only after labeling.
- Metrics per IMPLEMENTATION_NOTES 7.3, written to `outputs/`.
- Baseline (b): the uncompiled (v1-instruction) modules on the dev set. Baseline (a),
  the v1-lesson parity check, was done in Stage 3.
- Compile Analyst and Guardian first (about 10 examples, `max_bootstrapped_demos=2`, DSPy
  cache on), then the Responder.
- Save programs to `compiled/*.json` with an id. Load them at runtime behind a setting.
  The id is written as `prompt_version` in the LLM-call records.
- Measure latency after compiling.
- Prep fixes carried from Stage 7 (docs/agent/note.md, Stage 7):
  - ExplanationWriter: the ScriptWriter rule (reword chunk content, use only the
    chunks' examples, nothing of its own, no claims about later lessons).
  - One rule for "this option is wrong" in PollGuardian and ExplanationGuardian (a
    poll passed because a complete list in a chunk excludes an option; its explanation
    then failed for saying exactly that).
  - Guardian false passes on prep items: Stage 7 passed a script with claims the
    chunks lack (`l1-slides-p06`) and failed the same claims on the next slide. Label
    prep cases from the Stage 7 runs (`outputs/prep/info6205-l1*/generation_report.json`)
    among the Guardian cases, measure, then decide between instruction changes,
    compiling, or another model for the prep Guardian.
  - Malformed replies (2 in Stage 7: an empty PollWriter reply, an unparsable claims
    list): measure their rate; keep the safe path.
  - Then one live prep run on the Stage 7 deck to confirm (about 80-100 calls).
  - Cases built from `materials/` are real course content: keep them in a gitignored
    file unless the content may go public.
Out of scope for this stage:
- Joint compile and MIPRO (Stage 11, only if there is time).
- Compiling the generators (only if time is left here; ask first).
Automated checks:
- Standard checks.
- Loading a compiled program is tested with a tiny committed fixture JSON (no network),
  and its id appears as `prompt_version` in the trace.
- The eval split has no overlap between train and dev.
- The metrics files exist and list the Stage 4 baseline and the uncompiled v2 baseline
  next to the compiled numbers.
Human review:
- Labeling the Guardian cases, the eval labels, and the train/dev split.
- The few-shot demos the compile picked: no assignment-like answer, no dev item, and no
  real course content that should not go public, since `compiled/` is committed.
- The comparison table.
- Cost reading after each compile.
- Your decision on whether the compiled programs become the default.
Live Snowflake usage: the largest stage. Roughly:
- baseline dev run: about 25 questions × about 2.5 calls ≈ 60 calls
- each module compile: about 50–150 calls
- compiled dev run: about 60 calls
- Guardian eval: about 2 × 40 calls

- prep confirmation run (Stage 7 fixes): about 80–100 calls

That is about 430–720 LLM calls in total. Expected $10–40 plus warehouse (rough).
Approval limit: 1.5× the estimate confirmed at the stage start (about 1,080 at the
upper estimate).
Done when: the comparison table is in docs/agent/note.md (escalation recall, let-through, Guardian
catch rate and false fails, calls and latency per question), labeled exploratory, and
you have decided on the compiled programs.
Exit gate: stop, report results of the automated checks, list what I need to review,
and wait for my approval before starting the next stage.

## Stage 10: Dev report (prep output and live test questions)
Goal: One command is the demo entry: prep a lesson from a local folder, run that
lesson's fixed test questions through the live question path, and write a static HTML
dev report. The report shows whether prep produced the scripts, polls, and wrong-option
explanations it should, and whether the live path handled each test question as
expected. It is also the tool for comparing runs while we keep improving prompts and
rules. The professor's post-class report is deferred (BEHAVIOR 7, user decision
2026-11-06); the agent side only keeps its trace, decision log, and manifest complete.
Depends on: Stages 6, 8, and 9.
Tasks:
- Lesson folders (gitignored, under `materials/`): `materials/lessons/<lesson_id>/` with
  `slides/` (pptx, pdf), `refs/` (pdf, docx), `test_questions.json`, and an optional
  `lesson.yaml` (title, poll count). L1 moves to `materials/lessons/l1/`.
- Test questions: fixed per lesson, written by hand from the lesson's materials (the
  user and Claude), not generated by code; a new lesson gets its own file. 4 categories
  × 3 questions: `direct`, `reworded` (rewording or a direct inference), `partial` (the
  materials cover only part; escalate when a full answer needs facts the materials never
  state), `out_of_scope` (not about the lesson's teaching content, course logistics
  included). Each question has
  `question_id`, `category`, `question_text`, `expected_action`, `accepted_reasons`
  (the escalation reasons that count as a match; non-empty on escalate), `sources` (the
  chunk ids an answer should cite; may be empty), and `why`. No `objective_id`: segment
  ids change with each prep run. Code checks the format only. The committed fixture deck gets a small synthetic question file.
- CLI `dev <lesson_id> [--backend mock|cortex] [--skip-prep]` and `dev --list`. Steps:
  read the folder → `prep run` (or reuse the last manifest with `--skip-prep`) → each
  test question through the question graph → report. Output in
  `outputs/dev/<lesson_id>/<run_id>/` (`report.html`, `results.json`, slide images) and
  `outputs/dev/index.html`, which lists every run with its summary numbers.
- Report: computed by code from the prep outputs and the question results (no LLM),
  v1 theming, large blocks collapsed (`<details>`):
  - Overview: files, backend, model, prep and live program ids, LLM calls, time, item
    status counts (`ok`, `ok_after_retry`, `fallback`, `dropped`), wrong options
    without an explanation, test questions matching expected / to check, latency avg
    and max.
  - Scripts: one row per slide (thumbnail, status, first sentence); expanded: the full
    script, the fallback reason, the Guardian attempts.
  - Polls: text, options, correct option; per wrong option its explanation and
    `show_slide` thumbnail (expanded), or marked as having no explanation; dropped polls
    with their reason.
  - Live questions: one row per question (category, expected, actual, match),
    mismatches first; expanded: the answer, the cited chunk texts, the Analyst output,
    the retrieved chunks with scores, the Guardian claims and rescued claims, node
    statuses and latency.
Out of scope for this stage:
- The post-class report and its endpoint (deferred). Generated test questions. Poll
  simulation (the poll path is code only; unit tests cover it). A service endpoint for
  the dev report.
Automated checks:
- Standard checks.
- Test-question format check: a valid file passes; an unknown category or action, or a
  escalate without `accepted_reasons`, fails.
- `dev` on `tests/fixtures/deck` (mock) writes a report. One test per section:
  - status counts equal the manifest statuses
  - every wrong option shows its explanation or is marked as having none
  - every test question appears with expected and actual; mismatches come first
- Building the report makes no LLM call (asserted with an LLM that fails when called).
- `dev --list` on a temporary folder.
Human review:
- The L1 `test_questions.json` (before any live run).
- The report from the fixture deck (mock) and from L1.
Live Snowflake usage: optional, after approval. L1 with `--backend cortex`: prep about
125 calls (parse reused by hash) + 12 questions × about 2.5 calls ≈ 30, so about 155;
with `--skip-prep` about 30. Approval limit: about 235 calls.
Done when: `dev` builds a complete report for the fixture deck (mock) and for L1, and
the section tests pass.
Exit gate: stop, report results of the automated checks, list what I need to review,
and wait for my approval before starting the next stage.

## Stage 11: Integration, rehearsal, handoff
Goal: The system runs with Sai's front end and backend and Yaksha's pipeline on the
agreed contracts. A full class is rehearsed, and the contracts are signed off.
Depends on: Stages 0–10; team agreement on the `[team]` items.
Tasks:
- First (user, 2026-11-06), before tuning: small stateless interfaces for the other
  parts. Lesson bundle `GET /lessons/{id}/bundle` (Q-18), repeat guard on `POST
  /questions` by (`session_id`, `event_id`), guards rebuilt from the decision log on
  start (Q-19), session export `GET /sessions/{id}/export` and CLI `export` (Q-22).
  TestClient tests for each. Done 2026-11-06.
- Switch the draft contracts to the agreed versions (interface_questions → `agreed`).
- Integration fixes on my side only.
- Confirm with Yaksha that the trace JSONL loads into the star schema as it is (every
  fact in IMPLEMENTATION_NOTES 6.3 can be built).
- Rehearsal: one lesson end to end. Upload → manifest, slides with TTS, polls (one that
  triggers an explanation), about 20 student questions, then the dev report of that
  lesson (the post-class report is deferred).
- README walkthrough. Redraw `ARCHITECTURE.html` and `DEMO_OVERVIEW.html` for v2.
- Optional, if time and budget allow: joint compile of the Q&A program (ask first).
- Public release check: secret check on the full history, a `git ls-files` review, and
  no real course content in `compiled/`, `eval/`, or `tests/fixtures/`.
Out of scope for this stage:
- New features, deployment, auth.
Automated checks:
- Standard checks.
- Contract tests updated to the agreed versions.
- All scenarios and the prep fixture run offline.
Human review:
- Contract sign-off with the team.
- The rehearsal run.
- Final cost reading against the $400 budget.
- What gets pushed, and the switch to public.
Live Snowflake usage: one rehearsal. Prep of one deck is about 120–160 calls, or 0 if
reused by hash. Plus about 20 questions × about 3 calls ≈ 60 calls. Expected $5–15
(rough). Approval limit: about 330 calls.
Done when: teammates have run the demo and signed off on the contracts, and the public
release check passes.
Exit gate: stop, report results of the automated checks, list what I need to review,
and wait for my approval.

## Stage 12: Agent quality (live Q&A, prep generation, DSPy, more lessons)
Goal: Fewer false escalations and fewer dropped prep items, with no unsupported answer
let through, measured on lessons the tuning never saw. Live Q&A: the Analyst stops
judging scope from objective titles alone, the live Guardian passes direct inferences
(BEHAVIOR 5.3: rewording and direct inferences pass; facts the materials never state
escalate), and the Guardian no longer times out. Prep: no script fallback that reads
slide boilerplate, more wrong options explained. Three new lessons (L2, L3, L4)
give a held-out check.
Depends on: Stage 10 (dev report as the evaluation tool). Runs before the rest of
Stage 11 (see "Order and why").
Constraints:
- No assignment concept (user, 2026-11-06): the system has no assignments, so the
  `assignment_like` category and escalation reason, the Guardian's graded-work check,
  and the assignment questions in the eval sets are removed. This is the one interface
  change of the stage (Q-15, Q-19, handoff docs; the user approved it).
- Interfaces stay as handed over otherwise: no field change in Q-13, Q-19, Q-21, Q-22 (decision,
  question, trace, export, manifest). If a fix needs one, stop and ask the user first.
  Changes inside the agent (signatures, prompts, rules, settings, node order) are fine;
  each one that a teammate could notice (for example node order in the trace) is
  listed at the exit gate.
- Thresholds and final decisions stay in code. A change that would let an LLM output
  decide by itself (for example a claim kind that code trusts without a check) is
  proposed to the user first.
- The question path still answers within about 30 s (Q-19).
Data roles (against overfitting):
- Train (compile only): the synthetic sets in `eval/` (committed).
- Dev (tuning; may steer changes): L1 `materials/eval/questions_dev.json` (27 after the
  assignment questions were removed; 31 in Stage 9),
  L1 `test_questions.json` (12), the labeled Guardian cases (v1, live dev, prep dev).
- Held-out (not used for tuning): L2, L3, L4 `test_questions.json`, written by the user
  and Claude from the materials before any change in this stage is measured on them.
  Run once at the end with both the Stage 10 programs and the new ones (the old
  program on the same unseen questions is the baseline, so a difference comes from the
  program, not from the lessons' difficulty). A held-out
  question that fails is reported, not tuned for; if the user decides to fix it, the
  lesson becomes dev and the result says so.
- Every result says which sets steered it. Single runs are labeled exploratory.
Tasks (in order; each step measures before the next change):
1. Diagnosis without LLM calls: re-score the stored Stage 9 and Stage 10 replies (live
   dev, L1 test, prep generation reports) by failure cause (Analyst scope, Guardian on
   an inference, timeout, Responder addition, explanation of an option the chunks do
   not cover, writer analogy). Cost reading: queries 1 and 3 of
   `sql/probes/cost_reading.sql` (no LLM call; user approves first).
2. Live Guardian timeout. The Guardian gets its own timeout
   (`question.guardian_timeout_seconds`, about 15 s) capped by a per-question deadline
   (`question.deadline_seconds`, 30 s: the Guardian gets at most what is left), so the
   Q-19 promise holds. The Responder is asked for a short answer (2-4 sentences), which
   also shortens the Guardian's claim list. Measure Guardian latency (avg, max) on the
   dev set.
3. Live Guardian on direct inferences. First the instructions: align the live Guardian
   prompt with the user's bar (rewording and direct inferences pass: a conclusion that
   follows directly from stated facts names the chunk of those facts; facts the chunks
   never state still get null). Measure on every labeled live Guardian case (v1 8,
   live dev 13, synthetic): catch rate must not drop. Only if that is not enough, and
   after the user agrees: a claim kind (`stated | inference`) whose premises code
   checks (each premise supported, no content words beyond the premises and the
   question, no extra negation). The trace claim record keeps its fields.
4. Analyst scope. Retrieval runs before the Analyst, and the Analyst sees the top
   retrieved chunks (short) next to the objectives. Instructions: in scope = about the
   lesson's subject matter as the materials cover it; out of scope = logistics, other
   courses, personal requests, or a topic the lesson does not touch. A question the
   lesson touches only partly is in scope (the Responder and Guardian then escalate
   it as unsupported or low_confidence). The node records keep their fields; the
   retrieval node now runs before the Analyst and also for blocked questions.
5. Recompile the live Q&A program (`live-qa-v2`) on the synthetic train set after the
   signature changes; include the Guardian if steps 3 and 4 leave it weaker than its
   labeled cases need. Optimizer choice after a [verify] of the current DSPy API:
   `BootstrapFewShot` as before, random search over candidate demo sets with a
   synthetic validation split, and optionally a stronger teacher model to bootstrap
   demos for the mistral-large3 student. Dev run on L1 (27 + 12).
5b. DSPy experiment on the live Guardian (user, 2026-11-06: before Part B; its result
   decides how the prep modules are compiled). Question: does a searching optimizer
   beat hand-written prompts plus first-passing demos (`live-qa-v3`)?
   - Data: train = synthetic Guardian cases (`eval/guardian_cases_train.json`, 46, user
     labels; committed); val = labeled L1 live dev cases (13, gitignored) + v1 cases
     (12, fixture lesson). Only train items can become demos or reach GEPA's
     reflection, so `compiled/` holds no course content (checked by a test: no `l1-`
     chunk id or dev text in the saved instructions and demos).
   - Metric: the code verdict (`check_guardian`) equals the label; GEPA also gets the
     case note as text feedback. Selection gate as in the exit metrics (v1 at least
     6/8, live dev 1/1), then fewest false fails.
   - Optimizers ([verify] done on the installed DSPy 3.4.1): `BootstrapFewShotWithRandomSearch`
     (about 4 candidate demo sets scored on val) and `GEPA` (instructions rewritten
     from feedback, `max_metric_calls` caps the budget; reflection LM chosen by the
     user). Baselines: `uncompiled-v3` and `live-qa-v3`, each run twice on val, since
     single runs move by about 2 cases.
   - The winner, if any, runs L1 dev end to end once; its instructions are reviewed
     by the user before it can become the default.
6. Prep: script fallback. Code only: the slide-text fallback also drops boilerplate
   (ISBN, copyright and publisher lines, "materials are edited by"); a title slide
   falls back to its title and lecturer line. Title slides keep the one-or-two-sentence
   rule.
6b. Prep Guardians with random search (user, 2026-11-06, after the task 5b result):
   labeled synthetic prep cases (`eval/guardian_cases_prep_train.json`, scripts, polls,
   explanations; user labels) as train, the 21 labeled L1 prep cases (gitignored) as
   val, one `BootstrapFewShotWithRandomSearch` per Guardian kind
   (`optimize-guardian --kind script|poll|explanation`), re-checked twice before use.
7. Prep: wrong-option explanations. The Stage 9 drops are mostly the writer describing
   the wrong option's own topic (recursion, graphs), which the chunks never state, or
   an analogy not tied to a cited idea. ExplanationWriter instructions: say why the
   option is wrong from what the chunks state (the correct concept's definition, or a
   closed list that leaves the option out); say nothing about the wrong option's own
   topic beyond the chunks; at most one analogy, tied to a cited idea. PollWriter
   instructions: prefer wrong options the chunks mention or exclude. Recompile the prep
   writers (`prep-writers-v6`; the ExplanationWriter had 0 demos). Measure the prep
   Guardian's consistency (the 21 prep dev cases, 3 runs) and report it; any change to
   how verdicts are combined is a user decision.
8. One full L1 run (prep + 12 questions) with the new programs, then the dev set.
9. New lessons L2, L3, L4 under `materials/lessons/l<n>/` (materials from the user;
   test questions written with the user, 4 categories × 3, before step 10). Parse and
   prep each with the new programs.
10. Held-out run: L2, L3, L4 test questions with the new programs and a baseline. Done
    first against the Stage 10 code with `live-qa-v1b`, then (user, 2026-11-07, for the
    demo) against the same code without compiled programs, prep and questions per
    lesson (results in docs/agent/note.md).
11. Comparison table in docs/agent/note.md; README updated (new settings, commands);
    IMPLEMENTATION_NOTES section 13 for decisions.
Out of scope for this stage:
- Field changes to any handed-over interface (ask first). Joint compile and MIPRO-style
  instruction search unless the user approves them with a call estimate. Changing the
  generation or vision model without a measurement on the labeled cases. The
  post-class report.
Automated checks:
- Standard checks.
- Unit tests (mock) for each new rule and setting: the Guardian deadline (a slow
  Guardian escalates as `llm_error` within the deadline), the boilerplate fallback, the
  Analyst inputs (chunks passed), and any inference check (premises supported,
  no new content words, negation).
- Contract tests for Q-19, Q-21, Q-22 unchanged and passing (no field change).
- Loading compiled programs (`live-qa-v5`, `prep-v6` at the end) is tested with fixtures,
  and the ids appear as `prompt_version`.
- No real course content in `compiled/` (train is synthetic).
- `cli dev` on the fixture deck (mock) still writes a complete report.
Human review:
- The diagnosis (task 1) before any change.
- New prompts and rules (diffs) and the labeled-case results after each.
- L2, L3, L4 test questions (written together, before the held-out run).
- The compiled demos (no dev or held-out item).
- The L1 dev report and the held-out reports; the comparison table.
- Cost reading and the decision on which programs become the default.
Exit metrics (exploratory; the gate is the user's review, not these numbers):
- Hard: 0 unsupported answers let through and every out_of_scope question still
  escalated as out_of_scope on dev and held-out; Guardian catch rate on the labeled
  fail cases at least v1 6/8 and live dev 1/1 (user, 2026-11-06: was "not lower than
  Stage 9's 8/8"; gc-07 and gc-12, true content beyond the chunks, pass under the looser
  bar of this stage, and no code check separates them).
- Targets: L1 dev + test action correct above Stage 9/10 (28/31, i.e. 24/27 without the 4
  assignment questions, which Stage 9 all escalated correctly; 7/12); no Guardian
  timeout; latency avg about 5 s, max under 20 s; L1 prep 0 boilerplate fallbacks and
  more than 8 of 15 wrong options explained; held-out action match reported per
  category for both programs.
Live Snowflake usage (approved in two parts, each at its start):
- Part A, live Q&A on L1 (tasks 1-5): Guardian case runs about 3 × 25 = 75; Analyst
  runs on dev + test about 3 × 43 = 130; compile about 20-40; two dev runs (27 + 12
  questions) about 2 × 110 = 220. About 450-470 calls.
- Part B also includes task 6b: per Guardian kind, baselines about 2 x 21, random search
  about 150, re-checks about 60; about 600 for the three kinds. The user said the budget
  is ample (2026-11-06): plans are sized for reliable comparisons (repeats) rather than
  the fewest calls; Part B limit raised to about 2,200.
- Part B, prep and new lessons (tasks 6-10): prep Guardian consistency about 65; prep
  compile about 30-60; L1 full run about 155; L2, L3, L4 parse (AI_PARSE_DOCUMENT plus
  vision on image pages) and prep about 3 × 130 = 390; held-out runs about
  3 lessons × 12 × 2.5 × 2 programs = 180. About 820-850 calls.
- Part A2, DSPy experiment (task 5b): baselines about 50; random search about 180;
  GEPA about 240 (200 Guardian calls + about 40 reflection calls); winner on val twice
  and L1 dev once about 115. About 585 calls; approval limit about 900.
- Total about 1,300 calls, roughly 2.5-3.5 credits at the Stage 9 rate (warehouse time
  is the largest item). Approval limit: 1.5× each part (about 700 for A, about 1,275
  for B). Beyond that, stop and ask. Part A approved by the user 2026-11-06.
Done when: the comparison table (Stage 9/10 programs vs Stage 12 programs, on L1 dev
and on the held-out lessons) is in docs/agent/note.md, the user has decided which
programs become the default, and the standard checks pass.
Exit gate: stop, report results of the automated checks, list what I need to review,
and wait for my approval before the Stage 11 integration and rehearsal.

## Stage 13 (optional): Further optimization
Status: optional; runs only when the user starts it. It never blocks Stage 11, and a
Stage 11 rehearsal in progress keeps the programs it started with.
Goal: Close the gaps Stage 12 left, with comparisons that hold up across repeated
runs: more wrong options explained (Stage 12: 40/57 with DSPy), fewer script fallbacks
(4/67, 3 of them in L4), the same or better question results, and still no unsupported
answer let through.
Depends on: Stage 12 (programs `live-qa-v5`, `prep-v6`; the `optimize-guardian` command;
the L1-L4 comparison runs in `outputs/dev/` as the starting point).
Constraints:
- Same as Stage 12: no field change in Q-13, Q-19, Q-21, Q-22 without asking; thresholds
  and final decisions stay in code; the question path answers within about 30 s.
- A new program becomes the default only by the user's decision, after it beats the
  current one on repeated runs (not a single run).
Data roles (against overfitting):
- Train stays synthetic and committed (`eval/`), so `compiled/` holds no course content.
- Val/dev: L1 as in Stage 12. Labeled cases drafted from L2-L4 runs
  (`scripts/draft_*_guardian_cases.py`, labels by the user) may join val; any lesson used
  this way becomes dev, and results say so.
- Held-out: at least one new lesson (L5, materials from the user) whose test questions
  are written before any Stage 13 change is measured on it. Without a new lesson, results
  on L2-L4 are labeled "dev" once those lessons have steered a change.
Candidate tasks (the user picks which to run at the start; each measures before the next):
1. Diagnosis without LLM calls: re-score the stored Stage 12 runs (L1-L4, with and
   without DSPy) by failure cause: dropped explanations (writer adds the wrong option's
   own topic, Guardian false fail, poll text), script fallbacks (which slides, why),
   question misses per category.
2. Repeat baseline: the current programs on L2-L4 (and L5) two more times, so each
   comparison has a spread instead of a single run.
3. Prep writers with random search: `BootstrapFewShotWithRandomSearch` for ScriptWriter,
   PollWriter, and ExplanationWriter (Stage 12 compiled them with first-passing demos
   only), scored by the prep Guardian plus code checks on synthetic val slides.
4. Poll Guardian: random search gave no gain in Stage 12; first more labeled poll cases
   (synthetic train, user labels), then a rerun.
4b. Labels drafted by a stronger model (for example claude-sonnet-4-5), to grow the
   labeled Guardian sets faster. The labels are data, not decisions: the Guardian bar
   stays the user's, and code still makes every verdict. First measure agreement with
   the existing user labels (live and prep cases, train and val); use drafted labels
   only if agreement is high enough for the user, and the user reviews every
   disagreement and a sample of the rest. Drafted labels are marked as such in the case
   files, and results say which sets used them.
5. Teacher bootstrapping: demos generated by a stronger model (for example
   claude-sonnet-4-5) for the mistral-large3 student, if a [verify] of the current DSPy
   API confirms the teacher setting.
6. Instruction search (MIPROv2 or GEPA) on one module at a time, with a call cap set at
   the start; GEPA's reflection sees train items only.
7. Optional model comparison for generation (the measured alternatives from Stage 9/12)
   on the labeled cases, before any switch.
8. Final comparison: the chosen programs vs `live-qa-v5` / `prep-v6`, prep and questions
   per lesson, repeated runs; table in docs/agent/note.md, README updated.
Out of scope: field changes to handed-over interfaces; letting an LLM output decide
without a code check; the post-class report.
Automated checks:
- Standard checks.
- Unit tests (mock) for every new metric, optimizer option, and setting.
- No real course content in `compiled/` (existing leak test covers new programs).
- Loading each new program is tested with fixtures; its id appears as `prompt_version`.
Human review:
- The diagnosis and the chosen task list before any change.
- New labeled cases (user labels), new prompts and rules (diffs), compiled demos.
- The comparison table and the decision on defaults.
Exit metrics (the gate is the user's review):
- Hard: 0 unsupported answers let through on dev and held-out; Guardian catch rate on
  labeled fail cases not lower than Stage 12 (v1 at least 6/8, live dev 1/1).
- Targets: wrong options explained above 40/57 and script fallbacks below 4/67 on L1-L4
  (averaged over repeats), question results not lower than 44/48.
Live Snowflake usage: estimated per chosen task at the start and approved by the user
before it runs (rough sizes: one full lesson run with prep and 12 questions about
150-200 calls; one random search on one module about 150-250; a repeat baseline of
L2-L4 about 3 x 180 per repeat). Approval limit 1.5x the approved estimate.
Done when: the chosen tasks are done, the comparison is in docs/agent/note.md, the user
has decided the defaults, and the standard checks pass.
Exit gate: stop, report results of the automated checks, list what I need to review,
and wait for my approval.
