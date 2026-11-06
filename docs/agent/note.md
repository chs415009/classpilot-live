# Development notes — agent part (v2)

Only what someone needs later: changes to the plan or design, significant findings
(things that change how we build or what it costs), user decisions, and open questions
that block work. Routine task completion is not logged; commits and the plan cover it.
Stage plan: `docs/v2/STAGES.md`. Decisions log: `docs/v2/IMPLEMENTATION_NOTES.md`
section 13. v1 log (incl. the Stage 4 baseline numbers): `docs/v1/note_v1.md`.
The detailed Stage 0-1 log was condensed on 2026-11-04; the full version is in git
history (commit 8412b8e).

Entry format: `- YYYY-MM-DD [type] text`, type one of `change`, `decision`, `finding`,
`question`, `result`. Keep entries to 1-3 lines; link the source for findings.

---

## Stage 0: Repository setup — accepted 2026-11-04

- 2026-11-04 [change] v2 direction: the professor only uploads materials and reads the
  post-class report; scripts, polls, misconceptions, and explanations are generated
  before class and checked automatically. No pre-approved branches, protected check, or
  2-agent mode. Design: `docs/v2/`.
- 2026-11-04 [decision] New public repo `classpilot-live` (package `classpilot`), seeded
  with the cleaned v1 code. Account locator, region, login user, and key path are
  placeholders in committed files; `scripts/check_secrets.sh --history` blocks every
  push. The owner's git email is allowed on commits by choice. License MIT.
- 2026-11-04 [change] All v1 docs archived in `docs/v1/`; v1 interface items ignored
  (v2 items start at Q-13). No date-driven planning.
- 2026-11-04 [change] Team repo layout: shared rules in `CLAUDE.md`, agent-part rules in
  `.claude/rules/agent.md` (path-scoped), personal preferences in `CLAUDE.local.md`
  (gitignored). Teammates work on their own branches and merge into `main` by pull
  request. https://code.claude.com/docs/en/memory
- 2026-11-04 [finding] Snowflake docs do not confirm `IDENTIFIER($var)` for `CREATE
  WAREHOUSE`, `GRANT`, `CREATE USER`, or `CREATE CORTEX SEARCH SERVICE`, so SQL object
  names stay literal defaults; Stage 5 probes variable support before relying on it.

## Stage 1: Live probes — accepted 2026-11-04

Account-dependent results are for the current trial account.

**LLM connection**
- 2026-11-04 [decision] **Route B** for all LLM calls: a DSPy 3.4 custom engine
  (`complete(Request) -> Response`) over `AI_COMPLETE`. `BaseLM.forward()` is deprecated
  in 3.4 and removed in 3.5, so `dspy>=3.4.1,<3.5` is pinned.
- 2026-11-04 [finding] Route A is blocked on this account: Cortex REST (direct and via
  LiteLLM) answers 003001 "This account is not allowed to access this endpoint"; JWT auth
  itself was accepted. LiteLLM's Snowflake provider would not support `response_format`
  anyway. https://docs.litellm.ai/docs/providers/snowflake
- 2026-11-04 [finding] **The connector's `cursor.execute(..., timeout=N)` does not cancel
  `AI_COMPLETE`** (timeout 1 s, returned after 15.9 s), so v1's "server-side cancel" was
  wrong. `ALTER SESSION SET STATEMENT_TIMEOUT_IN_SECONDS` does cancel it (000630 after
  2.4 s). Stage 3 uses the session timeout plus the thread timeout as a backstop.
- 2026-11-04 [finding] DSPy defaults conflict with "never hang": `dspy.LM` retries 3 times
  with backoff and caches by default. Live Q&A sets `num_retries=0`, `cache=False`, and
  `ChatAdapter(use_json_adapter_fallback=False)`; then one engine call per prediction.
  Parse failures raise `dspy.AdapterParseError`; engine errors become `LMTimeoutError` /
  `LMServerError` / `LMUnexpectedError`. All map to `llm_error`.
- 2026-11-04 [finding] With ChatAdapter, a `str | None` output field came back as the
  string `"None"`. Stage 3 signatures must normalize it.
- 2026-11-04 [finding] `dspy.Refine` writes its own feedback (extra LM call); it cannot
  take the Guardian's feedback, so the prep retry loop stays our own code.
  `dspy.utils.DummyLM` covers offline tests.

**Parse and vision**
- 2026-11-04 [finding] Structured output (`response_format`) cannot be combined with an
  image prompt. Vision asks for JSON in the text and code parses it; `claude-haiku-4-5`
  always wraps it in a ```json fence.
  https://docs.snowflake.com/en/sql-reference/functions/ai_complete-single-file
- 2026-11-04 [decision] Vision model `claude-haiku-4-5` (3.1-3.6 s, reliable JSON);
  live Q&A model `mistral-large3`. `llama4-maverick` is legacy (error 100351);
  `openai-gpt-5-nano` needs about 4000 tokens and takes 19 s.
- 2026-11-04 [finding] Stages for `AI_COMPLETE` images must use `ENCRYPTION = (TYPE =
  'SNOWFLAKE_SSE')` (cannot be changed later); `PUT` needs `AUTO_COMPRESS=FALSE`;
  internal-stage directory tables need `ALTER STAGE ... REFRESH`.
- 2026-11-04 [finding] Image pages: embedded-image area >= 0.10 of the page identified
  the image slides (same pages as the `![img-N]` markers in `AI_PARSE_DOCUMENT` LAYOUT
  output). Template drawings cover every slide, so drawings count only after subtracting
  what all pages share. Page counts must come from the rendering library (the macOS
  `file` command reported 8 pages for a 13-page PDF).
- 2026-11-04 [decision] PyMuPDF is AGPL-3.0; the repo is MIT, so Stage 4 uses pypdfium2.
  PyMuPDF stays only for the Stage 1 probe scripts.
- 2026-11-04 [question] PPTX speaker notes via `AI_PARSE_DOCUMENT` are untested (the
  materials were PDF). Check in Stage 4 with a PPTX.

**Search**
- 2026-11-04 [finding] Lesson filter `{"@eq": {"LESSON_ID": "<id>"}}` on an ATTRIBUTES
  column; manual `ALTER CORTEX SEARCH SERVICE <name> REFRESH` exists, so prep refreshes
  right after loading chunks; `PRIMARY KEY (LESSON_ID, CHUNK_ID)` (TEXT) is allowed;
  suspended serving is not billed.
  https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-search/query-cortex-search-service

**Cost** (`CORTEX_AI_FUNCTIONS_USAGE_HISTORY`; the old `CORTEX_FUNCTIONS_QUERY_USAGE_HISTORY`
is no longer updated)
- 2026-11-04 [finding] AI credits per unit: mistral-large3 Analyst call 0.0002;
  claude-haiku-4-5 vision 0.0017 per slide; `AI_PARSE_DOCUMENT` LAYOUT 0.0037 per page
  (the most expensive unit). All of v1 used 0.046 AI credits but 0.86 warehouse credits.
- 2026-11-04 [finding] **Warehouse minutes, not LLM calls, drive the cost.** Slides use
  the free local text layer plus vision for image pages only; parse is for references
  only. The $400 trial budget is not a constraint at this scale.
- 2026-11-04 [result] Stage 1 used 15 `AI_COMPLETE` + 2 `AI_PARSE_DOCUMENT` (16 pages).
  Probe stage dropped; v1 `LESSON_SEARCH` suspended (Stage 3 asks before `RESUME`).
  Probe scripts: `scripts/probes/`, SQL: `sql/probes/`.

## Stage 2: Live paths, manifest, and trace on v2 contracts (mock) — accepted 2026-11-04

- 2026-11-04 [decision] Modules move to the ANALYSIS 2.6 layout as they change
  (`contracts/`, `rules/`, `live/`). Fixture lessons and manifest stay in `content/`
  (the CLI and the Stage 3 parity check read them); objective ids are now segment ids.
- 2026-11-04 [decision] Path A takes the manifest from its caller, since poll evidence has
  no lesson id (Q-14), and uses the manifest `params` for the threshold.
- 2026-11-04 [finding] The v1 `LESSON_SEARCH` already has `LESSON_ID` as an attribute
  (`sql/03_search_service.sql`), so Cortex Search always filters by lesson and the
  Stage 3 parity check still works. The planned `filter_by_lesson` switch was dropped.
- 2026-11-04 [decision] Trace v2: one JSONL file with `record_type`; claim support is
  `null` instead of `-1`; question and claim text only as hashes (text in the decision
  log). Draft, Q-21.
- 2026-11-04 [decision] interface_questions.md holds only what another part reads or
  sends (manifest, API shapes, decision/trace records, table names). Agent-internal
  formats (decision log, prep-only validation) are recorded in IMPLEMENTATION_NOTES.
- 2026-11-04 [decision] The fixture manifest cites v1 chunk ids (`chunk-01`), not
  `<slide>-c<N>`, so the Stage 3 parity check can use the v1 search index.
- 2026-11-04 [change] The agent side decides the interface items it can settle and
  records them as `decided` (teammates can reopen them); it no longer waits for team
  agreement. Q-13 to Q-21 decided; poll evidence now carries `lesson_id`.
- 2026-11-04 [result] Both live paths run on the v2 contracts in mock mode (12 scenarios,
  126 tests); v1-only code and data removed; trace v2 and the decision log are written
  for every run. No Snowflake use.

## Stage 3: Live agents as DSPy modules — accepted 2026-11-05

- 2026-11-05 [finding] DSPy's stock ChatAdapter puts the signature instructions last,
  after the field lists and format template. With the v1 Guardian text, live
  guardian-eval (mistral-large3) caught 5/8 and 6/8 (missed gc-07, gc-10, gc-12).
  `RulesFirstChatAdapter` leads with the instructions, as the v1 prompt did: 8/8, then
  7/8 (gc-07 missed once). Instruction wording is unchanged from v1.
- 2026-11-05 [finding] LLM timeouts at 10 s: 3 in 33 live calls (Guardian twice,
  Responder once), against about 1 in 40 in v1. All fail closed (`llm_error`). Calls
  usually take 1.2-4.4 s.
- 2026-11-05 [result] Parity on the v1 lesson (Cortex, uncompiled): eval 10/11 actions
  (tq-03 = Guardian timeout), recall 1.0, 0 let through, 0 wrong answers, 1.91 calls per
  question (v1 1.82; tq-07 now goes through the Analyst), answered 4.1-6.5 s.
  guardian-eval with the final prompt 8/8 and 7/8 (+1 timeout), 0 false fails. Reason
  labels differ on tq-09/10/11 (labels were written for the mock in v1). 72 LLM calls
  (approval 68 + 12 extra approved).
- 2026-11-05 [finding] `LESSON_SEARCH` answered "already resumed" at the start of the
  live run: `CORTEX_SEARCH_DAILY_USAGE_HISTORY` has a SERVING row every day from
  2026-10-20 to 2026-11-04, so it was never suspended (the Stage 1 teardown did not take
  effect). Cost rounds to 0.0000 credits per day for 5 chunks; `CLASSPILOT_WH` shows
  0.0002-0.002 credits per day for the daily refresh. Suspended after the run and
  checked with `scripts/search_service.py status`.
- 2026-11-05 [result] Stage 3 cost: mistral-large3 0.026 AI credits for the day (73 billed
  calls incl. Stage 1's; the 3 timed-out calls do not appear). Guardian about 0.0004 per
  call, Analyst 0.0002. Snowsight queries ran on `SNOWFLAKE_LEARNING_WH` (0.12 credits on
  11-04), not on our warehouse. `sql/probes/stage3_cost_reading.sql`.
- 2026-11-05 [decision] User: keep `llm.timeout_seconds` at 10 s for now (revisit after
  compiling in Stage 9). gc-07 stays as is: a useful edge case for Stage 9, no prompt
  change now.

## Stage 4: Parse layer, local conversion — accepted 2026-11-05

- 2026-11-05 [decision] User: nothing installed on the host. LibreOffice runs in Docker
  (`scripts/libreoffice/`, LibreOffice 25.2 on Debian 13); the LibreOffice tests skip
  when the image is missing. Fixture deck generated by script (user agreed).
- 2026-11-05 [finding] The real PPTX (`L1_slides.pptx`, generated outside PowerPoint)
  writes `[Content_Types].xml` and `.rels` with prefixed namespaces (`<ns0:Types>`);
  LibreOffice cannot load it ("source file could not be loaded"), python-pptx can.
  A python-pptx re-save fixes it, so convert retries once that way.
- 2026-11-05 [finding] LibreOffice ignores fonts embedded in a PPTX; the fallback font
  broke words ("Dictionar / y"). The image now carries Open Sans and the metric-compatible
  Office fonts. LibreOffice also exports shapes with shadows as bitmaps, so shadowed
  diagram slides are flagged through image area, not drawing area.
- 2026-11-05 [finding] Real materials: the PPTX has no speaker notes (0 of 14); text
  callout boxes in the reference PDF make 2 of its 3 pages `unsure` (sent to vision,
  about 0.0017 credits each). Kept: unsure errs toward vision by design.
- 2026-11-05 [result] `prep convert` handles the fixture deck and the real deck (14
  slides, aligned, 3 image slides) and reference (3 pages); 204 tests. No Snowflake use.

## Stage 5: Parse layer in Snowflake, chunks, and search — accepted 2026-11-05

- 2026-11-05 [decision] User: SQL object names are rendered client-side
  (`scripts/run_sql.py`), no `IDENTIFIER($var)` probe. The v1 service is only a
  development aid and is not re-checked.
- 2026-11-05 [finding] Docs: `AI_PARSE_DOCUMENT` supports page_split for PDF, PPTX, DOCX;
  `index` is 0-based; 100 MB and 2,000 pages per file. Cortex Search recommends at most
  512 tokens per chunk (default embedding model truncates beyond that); `PRIMARY KEY`
  columns must be TEXT. https://docs.snowflake.com/en/sql-reference/functions/ai_parse_document
  https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-search/cortex-search-overview
- 2026-11-05 [finding] Live (current account): 1 `AI_PARSE_DOCUMENT` (3 pages) and 7 vision
  calls, none failed; the real deck plus reference took about 61 s. Creating
  `LESSON_SEARCH_V2` over 57 rows took 7 s.
- 2026-11-05 [finding] The 2 reference pages flagged `unsure` (text callout boxes) got
  "No diagrams ... only text" descriptions, and those chunks ranked first for an ADT
  query. Vision on text-only pages wastes calls and adds noise chunks.
- 2026-11-05 [result] Real deck + reference parsed into 25 chunks; a second lesson with
  the same files made 0 calls with the same ids; `lesson_id` filter returned only the
  queried lesson's chunks (4 queries). Service suspended. 245 tests.
- 2026-11-05 [decision] User: keep the cautious routing; vision now reports `has_visuals`
  (no description chunk when false) and key concepts are not chunked. The Stage 5 live
  rows were chunked before this change (no `has_visuals`, key concepts in chunks); the
  next `prep parse` of those lessons re-chunks them with 0 LLM calls.
- 2026-11-05 [result] Stage 5 cost (ACCOUNT_USAGE): vision 7 calls 0.0150 AI credits
  (0.0021 each, with the page text in the prompt), AI_PARSE_DOCUMENT 3 pages 0.0110,
  embedding 0.0002, serving 0.0000, `CLASSPILOT_WH` 0.0715. Total about 0.098 credits;
  warehouse time is again the largest item. `sql/probes/stage5_cost_reading.sql`.

- 2026-11-05 [decision] User: re-chunk the Stage 5 live lessons in Stage 7 (first real
  v2 use), not now.

## Stage 6: Generators and the prep-time Guardian (mock) — accepted 2026-11-05

- 2026-11-05 [decision] User agreed: one prep Guardian signature per item type (live
  Guardian unchanged); Segmenter fallback = fixed 3-slide groups; dropped polls keep
  their text but no misconceptions (validator relaxed, Q-13); a dropped poll moves to
  the next segment in the PollPlacer's ranking; fallback sentence "Please look at the
  slide on screen."
- 2026-11-05 [change] Segmenter and PollPlacer cite no chunk ids (STAGES asked all
  signatures to): they return structure only and no Guardian checks them.
- 2026-11-05 [result] `prep run --backend mock` turns the fixture deck into a valid
  manifest (38 mock calls: 3 segments, 6 scripts, 3 polls, 9 explanations); every
  status, every script fallback level, and the poll drop path are covered by tests
  (391 tests). No Snowflake use. Stage 7 estimate for a 14-slide deck: about 70 calls
  if everything passes, up to about 140 with every retry.
- 2026-11-05 [change] User: README is updated in every stage (features, setup and
  deployment steps, commands run again).

## Stage 7: Live prep run on one deck — accepted 2026-11-05

- 2026-11-05 [decision] User: generation model `mistral-large3` (prep.model null), up to
  200 LLM calls (limit 300), at most 2 runs, poll_count 5. Leftover data (v1 table and
  service, the `fixture-lesson` rows) stays until all stages are done, then is cleaned.
- 2026-11-05 [finding] Account inventory (`sql/probes/stage7_account_inventory.sql`,
  run with the service role via `scripts/probes/readonly_sql.py`): only the expected
  objects; both search services suspended; the service user has one RSA key, no
  password or PAT; no network policies or tasks. A teammate's user also holds
  CLASSPILOT_AGENT_ROLE (owner of our tables).
- 2026-11-05 [finding] Re-chunk kept 25 chunks; key concepts are gone, but the stored
  "No diagrams ... only text" description of `l1-pdf-p02` stays (stored rows predate
  `has_visuals`, which defaults to true); removing it needs a new vision call.
- 2026-11-05 [result] Run 1 (mistral-large3): 76 calls, 224 s; 9 segments; scripts ok 3,
  ok_after_retry 2, fallback 9; all 7 polls dropped. `prep check` passed.
- 2026-11-05 [finding] Run 1 causes: (1) the poll Guardian wrote wrong options as
  "A: <text>" (they are shown to it that way), so the rule never matched a key: 5 of 7
  drops were this bug; (2) PollWriter gave a misconception for the correct option and
  asked NOT questions; placement listed logistics segments as backups; (3) ScriptWriter
  added examples and analogies the slides lack (sparse bullet slides), which the
  Guardian rightly failed, and the Guardian counted "this slide shows ..." as claims;
  (4) fallback text kept bullet-only lines, page numbers, the footer, and URLs, and the
  lint failed plain double quotes.
- 2026-11-05 [change] Fixes before run 2, user approved. Code: (A) the rule reads the
  option key from the start of the Guardian's text; (B) plain double quotes are no
  TTS issue; (C) the slide-text fallback drops bullet-only lines, page numbers, URLs,
  and lines on most slides (footer); (H) script retrieval queries objective + slide
  text and adds reference chunks until 2 are present (`prep.script_reference_chunks`).
  Instructions: (D) ScriptWriter may reword chunk content and use examples the chunks
  contain, no examples of its own; (E) ScriptGuardian: sentences that only say what the
  slide shows are not claims; (F) PollWriter: no misconception for the correct option,
  no NOT/EXCEPT questions, no logistics; (G) PollPlacer leaves out logistics segments.
- 2026-11-05 [decision] User: generated examples and explanations of the writer's own
  stay out (only content the chunks contain), for quality and a small scope; an
  `illustration` item type is a possible Stage 9 topic if scripts stay too dry.
- 2026-11-05 [result] Run 2 (after fixes A-H): 82 calls, 284 s (158 in both runs, of
  200 approved); 7 segments; scripts ok 3, ok_after_retry 6, fallback 5; 4 of 5 polls
  passed their own checks, but each had an explanation fail twice, so all 5 were
  dropped and no active poll remains. `prep check` passed; search service suspended.
- 2026-11-05 [finding] Run 2 causes: ExplanationWriter adds content of its own (fix D
  was applied to the ScriptWriter only); PollGuardian accepts "not in the complete list"
  as showing an option wrong, ExplanationGuardian rejects the same statement; the
  script Guardian passed invented claims on one slide (p06) and failed the same claims
  on the next (p07), so mistral-large3 as prep Guardian is not consistent; 2 malformed
  replies (safe path). Scripts now use the reading's own examples (car analogy).
- 2026-11-05 [decision] User: close Stage 7 without a third run; the fixes go to Stage 9
  (STAGES.md, Stage 9 tasks), where labeled prep Guardian cases decide between
  instruction changes, compiling, or another model.
- 2026-11-05 [result] Stage 7 cost (ACCOUNT_USAGE, `sql/probes/stage7_cost_reading.sql`):
  `CLASSPILOT_WH` 0.1757 (20:00 UTC hour: inventory, re-chunk, run 1) + 0.1339 (21:00
  hour: run 2, checks) = 0.31 credits, about 4x Stage 5, since AI_COMPLETE keeps the
  warehouse up for the whole run (4-5 min each); search embedding 0.0003, serving
  0.0000. AI credits: run 2 alone 82 AI_COMPLETE (mistral-large3) = 0.0532 credits,
  about 0.00065 per call (prep prompts carry several chunks; live calls were
  0.0002-0.0004). Run 1 was cut off by the query bound (see the next entry); at the
  same rate about 0.05, so Stage 7 AI cost is about 0.10 credits against 0.31 for the
  warehouse.
- 2026-11-05 [finding] `CORTEX_AI_FUNCTIONS_USAGE_HISTORY.START_TIME` behaves as an
  hourly bucket: a bound inside the hour drops that hour's calls. Cost queries bound
  by whole hours (`sql/probes/stage7_cost_reading.sql` fixed).

## Stage 8: Service API (prep and live endpoints) — accepted 2026-11-05

- 2026-11-05 [decision] User approved `fastapi`, `uvicorn`, `python-multipart` (and
  `httpx` for tests). Agent side: lessons on disk under `outputs/service`, jobs and the
  poll guard in memory; upload limit 100 MB; CORS origins are a setting (Sai to confirm).
- 2026-11-05 [change] `parse_lesson` now works in phases over all files, so job steps
  never go back, and refreshes the stage once per run instead of once per new file.
- 2026-11-05 [result] Service on mock: 29 TestClient tests (uploads, reuse, steps,
  failures, 404s, Q&A timeout -> escalate, poll explain/reveal/repeat, no credential
  values in responses, traces, or logs); 448 tests in all. Local uvicorn run: fixture
  PPTX (LibreOffice in Docker) to manifest in about 1 s, one question (answer), one
  poll result (explain with the manifest's text and slide). No Snowflake use.

## Stage 9: Eval expansion, DSPy compile, baseline comparison — accepted 2026-11-06

- 2026-11-05 [decision] User: train on a synthetic lesson written from L1's topics in
  own words (`eval/questions_train.json`, committed), dev on the real L1 lesson
  (`materials/eval/`, gitignored), so compiled demos can be committed. Compiled files
  hold the demos' full inputs (chunk text, question, answer), which rules out real
  content in train.
- 2026-11-05 [decision] User: one "option is wrong" rule for PollGuardian and
  ExplanationGuardian: a closed, complete list in a chunk that leaves the option out
  counts; a list of examples does not.
- 2026-11-05 [decision] User: prep Guardian false passes are handled in order: quotes per
  claim checked by code against the chunk, then another model (`claude-haiku-4-5`) on
  the same labeled cases, then (asking first) compiling.
- 2026-11-05 [change] Generation reports kept no draft text or generator citations, so
  failed Stage 7 drafts are rebuilt from the claims their Guardian listed
  (`reconstructed`), and cited chunks = the item's own chunks plus the chunks the
  Guardian named.
- 2026-11-05 [finding] DSPy 3.4 `Predict.dump_state()` fails on a custom engine LM;
  saving works on a copy without the LM, so `compiled/` never stores model settings.
- 2026-11-06 [finding] Uncompiled dev baseline (L1, 31 questions, 62 calls): action
  correct 25/31, escalation recall 1.0, 0 unsupported let through, 6 false escalations:
  Guardian caught Responder additions (dv-06/07/09), Analyst judged scope from objective
  titles only (dv-10 inheritance, dv-15 car analogy), 1 malformed Analyst reply (dv-03).
- 2026-11-06 [finding] v1 Guardian cases, uncompiled, 2 runs: identical, 7/8 caught,
  0 false fails, 0 errors; gc-07 missed both times.
- 2026-11-06 [decision] User labeling standard for prep cases: differences in wording or
  in describing the slide are not claims (pass); new knowledge, own examples, or wrong
  facts fail. True content found only in uncited chunks still fails (a citation
  problem for the generator, not a looser Guardian). Round 1: 25 cases labeled.
- 2026-11-06 [finding] Uncompiled prep Guardians on the 21 labeled prep cases: 8/9
  caught (missed pc-02, the writer's own "family tree"), 5 false fails: slide-describing
  sentences counted as claims (pc-01, pc-09), closed lists not used (pc-14, pc-15; D2
  rule not yet in the prompt), "that option is inheritance" (pc-18). Synthetic live:
  2/2 caught, 2 false fails (gs-01 "chunks do not cover", gs-03 recommendation).
- 2026-11-06 [change] Prep fixes: per-claim (and per wrong option) quotes checked by
  code; quote parts split at ' | ' and '...' may come from any cited chunk (the
  Guardian joins list lines and sometimes names the wrong cited chunk). Shared
  closed-list rule in PollGuardian and ExplanationGuardian; slide-describing sentences
  are not claims; ExplanationWriter gets the ScriptWriter rule plus "nothing about later
  lessons". Generation reports keep each attempt's draft.
- 2026-11-06 [finding] Quotes are real text but do not catch a quote that does not mean
  the claim (pc-02 "family tree" quoted "similar to a Graph or Tree"). After the fixes
  (mistral-large3, dev cases): 8/9 caught, false fails 5 -> 4 (pc-01, pc-09, pc-15
  outline not taken as closed, pc-17 linking sentence without quote). Prompt changes
  were checked on these dev cases, so the number is optimistic.
- 2026-11-06 [finding] `claude-haiku-4-5` as prep Guardian on the same cases: 4/9
  caught, 6 false fails. Worse on both; prep Guardian stays on mistral-large3.
- 2026-11-06 [result] Prep confirmation run on L1 after the fixes (76 calls): scripts
  ok 8 / fallback 6 (Stage 7: 9 / 5); polls pass the Guardian more often (4 of 5 on a
  first or second attempt, Stage 7: 2 of 5), but every poll is still dropped because
  an explanation fails. The stored drafts show the writers still add their own
  content (menu analogy, bank account, "car class inherits from vehicle"); the
  Guardians caught those correctly. 3 malformed replies: 2 empty `[[ `, 1 fenced JSON.
- 2026-11-06 [change] Malformed replies: the adapter drops ``` fence lines before
  parsing (live and prep); prep asks the same call again once on an unparseable reply
  (`prep.malformed_retries`), never on a timeout. Live keeps the safe path (escalate).
- 2026-11-06 [decision] User: keep a poll when one of its explanations fails (that option
  reveals only), and compile the prep writers; bar for generated content is "does not
  mislead", not perfect grounding.
- 2026-11-06 [finding] Compiling: a Guardian-passed v1 demo held the writer's own
  analogy ("like putting a fence around"), so demos need the own-comparison check too
  (v2). The ExplanationWriter got 0 demos: in 6 tries it added analogies 3 times
  (recipe, shopping bag, coffee line) and the Guardian wrongly failed 2.
- 2026-11-06 [result] L1 prep with prep-writers-v2 + own-comparison check + safety net
  (91 calls): script fallbacks 3 (before 6), 4 polls live (before 0), 6 of 12 wrong
  options explained, the rest reveal only. Spot check: no misleading explanation; R-06
  calls overloading "polymorphism" (narrower than the lesson's definition) and q-05
  uses Abstraction as a wrong option (wrong only within the lesson's closed list).
- 2026-11-06 [decision] User: allow content-free transition/motivation sentences, and the
  writer's own examples, analogies, and rewordings when each fits an idea the chunks
  state (materials do not have an example for every idea); new facts stay forbidden.
  Reverses the Stage 7 "no writer-made examples" rule. pc-02 relabeled pass.
- 2026-11-06 [change] Prep Guardian claims carry `kind` (fact / example / framing); code
  allows up to `prep.max_framing_claims` (2) framing claims without a chunk and checks
  an example's quote against the idea it illustrates. The own-comparison check is
  removed. Dev cases: 8/8 caught, 3 false fails, poll options agree 16/18.
- 2026-11-06 [result] L1 prep with prep-writers-v4 (own examples allowed, 98 calls):
  script fallbacks 6 (v2 run: 3), 4 polls live, 3 of 12 wrong options explained (v2
  run: 6). Cause: mistral-large3 as prep Guardian is inconsistent on the new claim
  kinds (a chunk's own "blueprint" analogy judged untied; facts marked framing), and
  longer scripts give it more to judge. Single runs vary a lot.
- 2026-11-06 [finding] `claude-sonnet-4-5` as prep Guardian on the 21 dev cases (new
  rules): 6/8 caught (missed pc-07 wrong course title, pc-08 wrong topic order), 4 false
  fails. Not better than mistral-large3 (8/8, 3); the prep Guardian stays on it.
- 2026-11-06 [finding] Of 42 claims the prep Guardian called unsupported in two L1 runs,
  7 (17%) were in a cited chunk (Guardian miss), 5 (12%) only in an uncited given chunk,
  30 (71%) nowhere, mostly elaboration on title/outline slides. Cortex Search is not
  involved: the Guardian gets chunk texts directly.
- 2026-11-06 [decision] User: prep.max_retries 1 -> 2; the Guardian sees every chunk the
  writer was given (cited first); code passes a claim the Guardian could not tie when
  >= 0.8 of its content words are in one given chunk with no extra negation
  (`prep.rescue_coverage`); title/outline slides get one or two sentences. Budget cap
  raised to about 800 calls. pc-03 and pc-10 relabeled pass with the stating chunks.
- 2026-11-06 [result] L1 prep with prep-writers-v5 and the changes above (125 calls,
  413 s): 1 script fallback (title slide p03), all 5 polls live, 8 of 15 wrong options
  explained. Spot check: nothing misleading; minor: p04 calls the lecture outline "the
  course outline", one recipe analogy is muddled, q-04's wrong options are too easy.
  Stage 9 calls so far about 676 (cap raised to about 800).
- 2026-11-06 [decision] User: live answers follow the same bar (rewording and direct
  inferences pass; nothing made up or beyond the syllabus). The live Guardian now sees
  every retrieved chunk (cited first) and `rules.check_guardian` has the word rescue
  (`question.guardian_rescue_coverage` 0.8). Live Guardian prompt unchanged.
- 2026-11-06 [finding] The baseline live Guardian blocked dv-06/07/09 for the same three
  causes as prep: an inference (dv-06), a missed rewording plus an uncited retrieved
  chunk (dv-07), and a claim word for word in a cited chunk (dv-09). Retrieval had
  every needed chunk in all three. Round 2: 13 live dev cases labeled (12 pass, 1 fail).
- 2026-11-06 [result] live-qa-v1 (Analyst 3 demos, Responder 2, synthetic; 8 calls) on
  the L1 dev set with the new live Guardian rule: action correct 25 -> 28 of 31, false
  escalations 6 -> 3, recall 1.0, 0 unsupported let through. Fixed dv-03/06/07/15;
  still dv-09 (Guardian) and dv-10 (Analyst: "inheritance" out of scope); new dv-12
  (Responder added setter validation, not in L1: correct block). Latency avg 4.1 ->
  4.8 s, max 13.4 s, 2 of 31 over 10 s (longer prompts, 3 chunks to the Guardian).
  Compile and the rule change cannot be separated without another dev run; the new rule
  on the stored baseline replies changes nothing.
- 2026-11-06 [finding] Rule hole found by the v1 regression run: gc-09 passed because
  code rescued a true claim and overruled the "fail" verdict, while the Guardian had
  tied the invented claim to a chunk and named it in its reason. Fix (live and prep):
  a fail verdict stands unless its reason names only rescued claims. Re-scored stored
  replies: v1 8/8 caught, no other result changes. Live dev cases: 1/1 caught, 2 of 12
  false fails (baseline 3, different cases).
- 2026-11-06 [result] Stage 9 comparison (exploratory: single runs; the dev cases also
  steered the rule changes; full table `scripts/stage9_comparison.py`):

  | Live Q&A | actions | recall | let through | false esc. | calls/q | latency avg / max |
  |---|---|---|---|---|---|---|
  | Stage 4 baseline (v1 lesson, 11 q) | 11/11 | 1.0 | 0 | 0 | 1.82 | 4.4-7.6 s answered |
  | uncompiled v2 (L1 dev, 31 q) | 25/31 | 1.0 | 0 | 6 | 2.0 | 4.1 / 9.9 s |
  | live-qa-v1 + new Guardian rule (dev) | 28/31 | 1.0 | 0 | 3 | 2.1 | 4.8 / 13.4 s |

  Guardian cases: v1 7/8 -> 8/8 caught, 0 false fails; prep dev (mistral-large3) 8/8,
  3 false fails; live dev 1/1, 2 false fails. Malformed replies: dev 1/62 -> 0/65;
  L1 prep runs 2-3 per run -> 0. L1 prep: polls live 0 -> 5 of 5, script fallbacks
  5 -> 1. Stage 9 used about 780 LLM calls (estimate 480, cap raised to about 800).
- 2026-11-06 [decision] User accepted Stage 9. Open: whether compiled programs become
  the default; the Stage 9 cost reading (`sql/probes/stage9_cost_reading.sql`).
- 2026-11-06 [decision] User: compiled programs are the default (`live-qa-v1`,
  `prep-writers-v5` in `config/settings.yaml`); tests use code defaults (uncompiled).
