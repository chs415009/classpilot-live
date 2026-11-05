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
`pypdfium2` (not PyMuPDF: AGPL-3.0, repo is MIT); LibreOffice installed.
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
- A LibreOffice test that is skipped (and reported as skipped) when `soffice` is not
  installed.
Human review:
- New dependencies and the LibreOffice install.
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
- SQL (parameterized object names, shown before running). First check with a small
  probe which statements accept `IDENTIFIER($var)` (deferred from Stage 0):
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
- The report endpoint (built in Stage 10, where the report exists).
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

That is about 350–620 LLM calls in total. Expected $10–40 plus warehouse (rough).
Approval limit: 1.5× the estimate confirmed at the stage start (about 930 at the upper
estimate).
Done when: the comparison table is in docs/agent/note.md (escalation recall, let-through, Guardian
catch rate and false fails, calls and latency per question), labeled exploratory, and
you have decided on the compiled programs.
Exit gate: stop, report results of the automated checks, list what I need to review,
and wait for my approval before starting the next stage.

## Stage 10: Post-class report
Goal: Build the professor's HTML report from one session's decision log, traces, poll
evidence, and the manifest's per-item status values. The report is triggered by an endpoint and a CLI
command. Numbers and lists are computed by code; there is no LLM summary.
Depends on: Stages 2, 6, and 8.
Tasks:
- A synthetic session fixture with a manifest, poll evidence, decision log, and traces.
  It includes explain and reveal polls, answers, every escalation reason, an LLM error,
  a script fallback, and a dropped poll.
- Report sections per BEHAVIOR 7:
  - attendance
  - poll results and triggered explanations (with `show_slide`)
  - Q&A with sources
  - escalated questions, grouped
  - content quality
  - system notes
- Question and answer text comes from the decision log, not the Gold tables. Reuse the
  v1 report theming.
- `POST /sessions/{id}/report` and `GET /sessions/{id}/report` (draft, `[team]`, Sai),
  plus CLI `report <session>`.
Out of scope for this stage:
- Any LLM-written text. Reading from Yaksha's tables.
Automated checks:
- Standard checks.
- One test per section on the fixture:
  - counts equal the fixture data
  - every answer lists its sources
  - every escalation reason appears
  - retries, fallbacks, and drops are counted from the manifest status values
- The report code makes no LLM call (the mock LLM is never called; asserted).
- `TestClient` tests for both report endpoints (happy path, unknown session → 404).
Human review:
- Read the report built from the fixture session.
- The report endpoint shapes (interface_questions entry).
Live Snowflake usage: none
Done when: the endpoint and the CLI build a complete report from the fixture session,
and all section tests pass.
Exit gate: stop, report results of the automated checks, list what I need to review,
and wait for my approval before starting the next stage.

## Stage 11: Integration, rehearsal, handoff
Goal: The system runs with Sai's front end and backend and Yaksha's pipeline on the
agreed contracts. A full class is rehearsed, and the contracts are signed off.
Depends on: Stages 0–10; team agreement on the `[team]` items.
Tasks:
- Switch the draft contracts to the agreed versions (interface_questions → `agreed`).
- Integration fixes on my side only.
- Confirm with Yaksha that the trace JSONL loads into the star schema as it is (every
  fact in IMPLEMENTATION_NOTES 6.3 can be built).
- Rehearsal: one lesson end to end. Upload → manifest, slides with TTS, polls (one that
  triggers an explanation), about 20 student questions, then the report.
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
