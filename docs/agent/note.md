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
- 2026-11-06 [result] Stage 9 cost (ACCOUNT_USAGE, `sql/probes/stage9_cost_reading.sql`,
  read 2026-11-06): `CLASSPILOT_WH` 0.1026 + 0.4603 + 0.5132 + 0.1524 (04:00-07:00 UTC
  hours) = 1.23 credits, about 4x Stage 7 for about 780 calls. The AI-function and
  Cortex Search queries returned no rows yet (ACCOUNT_USAGE lag); at the Stage 7 rate
  (0.00065 per prep call) AI cost would be about 0.5 credits, rough, since the Sonnet and
  Haiku Guardian runs cost more per call. Warehouse time is still the largest item.

## Stage 10: Dev report (prep output and live test questions) — accepted 2026-11-06

- 2026-11-06 [decision] User: the post-class report is deferred (owner and source
  tables, likely Gold, decided later); the agent side keeps trace, decision log, and
  manifest statuses complete. Stage 10 is a dev report instead: `cli dev <lesson>` preps
  a lesson folder (`materials/lessons/<id>/`) and runs its fixed, hand-written test
  questions (4 categories × 3); static HTML, large blocks collapsed; no generated
  questions, no poll simulation, no endpoint. Q-20 marked deferred.
- 2026-11-06 [decision] User: test questions are fixed and hand-written per lesson
  (`materials/lessons/<id>/test_questions.json`); no assignment category (4 × 3 = 12 for
  L1); `partial` escalates when a full answer needs facts the materials never state
  (tq-09 "cycles"); course logistics count as out of scope.
- 2026-11-06 [finding] Prep tables keep every file ever added to a lesson (no removal),
  so a lesson folder that loses a file still generates from it. `cli dev` warns and the
  report shows a banner; no table delete was added.
- 2026-11-06 [change] `generation_report.json` now records the prep program id
  (`prompt_version`). Live Content for a prepped lesson is built by
  `content.lesson_content` (shared by the service and `cli dev`).
- 2026-11-06 [result] L1 dev report on Cortex (`dev info6205-l1 --skip-prep`, Stage 9
  prep, live-qa-v1, mistral-large3; 24 LLM calls, 59 s): 7/12 as expected, 0 answered
  that should escalate. To check: tq-02 polymorphism and tq-08 time complexity (Analyst
  too strict: out_of_scope from the objective titles, as dv-10; tq-08 should pass the
  Analyst and escalate unsupported or low_confidence), tq-04/tq-06 (live Guardian blocks
  a direct inference; the word rescue does not cover conclusions), tq-05 (Guardian
  timeout at 10 s). Open for later tuning; labels unchanged.
- 2026-11-06 [decision] User: out_of_scope (and assignment_like) come only from the
  Analyst; once it passes a question, an escalation is unsupported, low_confidence, or
  llm_error. The `partial` category tests exactly that path.
- 2026-11-06 [decision] User accepted Stage 10. Later: a full L1 run (prep + questions,
  about 155 calls) once things are stable.

## Stage 11: Integration, rehearsal, handoff

- 2026-11-06 [decision] User: interfaces to Sai and Yaksha stay small and stateless so
  they keep freedom; the agent never reads Redis. Added the lesson bundle (Q-18), the
  question repeat guard with guards rebuilt from the decision log (Q-19), and the
  session export zip plus `cli export` (new Q-22). Open for them: Sai's origin and
  bundle needs; Yaksha's loading method and whether prep data goes into the model.


## Stage 12: Agent quality (live Q&A, prep generation, DSPy, more lessons)

- 2026-11-06 [decision] User: Stage 12 runs before the Stage 11 integration and rehearsal;
  handed-over interface fields (Q-13, Q-19, Q-21, Q-22) do not change. Held-out lessons
  L2-L4 (`materials/lessons/l2..l4`), run at the end with live-qa-v1 and the new
  program. Part A (live Q&A, about 470 calls) approved.
- 2026-11-06 [decision] User: retrieval runs before the Analyst, and the Analyst sees the
  retrieved chunks. Before, it saw only the segment objective titles, and readings never
  reached it (tq-02 polymorphism is defined only in the reading). Internal change; node
  order in the trace changes, fields do not.
- 2026-11-06 [finding] The service user cannot read `SNOWFLAKE.ACCOUNT_USAGE` (no
  ACCOUNTADMIN, 003013; own role 002003): cost readings run in Snowsight by the user.
- 2026-11-06 [finding] Diagnosis of stored replies (0 calls). Live, live-qa-v1 dev + L1
  test: scope from titles 5 (dv-10, dv-24, dv-25, tq-02, tq-08; dv-24/25/tq-08 should
  reach the Responder and escalate there); Guardian on an inference or summary 3 (dv-09,
  tq-04, tq-06); Responder addition 1 (dv-12, correct block); timeout 1 (tq-05, the
  longest answer, 699 chars; other Guardian calls 1.4-7.2 s). Prep, L1 v5 run: of 21
  failed explanation attempts, 15 describe the wrong option's own topic (laundry pile,
  recursion, graphs, tree branches), 4 add an untied analogy, 2 state an inference.
- 2026-11-06 [finding] Prep false fail caused by code: the Guardian splits a sentence
  into supported claims, then lists the whole sentence again as an untied "example"
  with a pass verdict; the word rescue misses it at 11/14 = 0.79 (p01; p07 similar).
- 2026-11-06 [decision] User: the system has no assignments; the concept is removed
  everywhere, interface included (`assignment_like` reason gone from Q-15/Q-19 and the
  handoff docs: 4 reasons). Analyst: in_scope / out_of_scope; Guardian: no
  `reveals_graded_work`. Removed: scenario 03b, train tr-13..15, gs-04, v1 eval tq-07/08,
  L1 dev dv-20..23 (dev set 31 -> 27; Stage 9 numbers were on 31). `live-qa-v1` is
  replaced by `live-qa-v1b` (quiz-question Analyst demo dropped, instructions updated,
  no recompile); it is the default and the held-out baseline.
- 2026-11-06 [result] Stage 9 cost, complete (user ran `sql/probes/stage9_cost_reading.sql`
  in Snowsight): AI_COMPLETE mistral-large3 729 calls 0.5193 credits (0.00071 per call),
  claude-sonnet-4-5 21 calls 0.1534, claude-haiku-4-5 21 calls 0.0483; warehouse 1.23;
  Cortex Search serving 0.0000 for the day. About 1.95 credits for about 780 calls; the
  warehouse is about 63%.
- 2026-11-06 [change] Tasks 2-4 (mock): retrieval runs before the Analyst, which sees
  the retrieved chunks; new Analyst, Responder (2-4 sentences), and Guardian prompts
  (direct conclusions pass; each claim once); Guardian timeout 15 s on its own Cortex
  connection, capped by a 30 s per-question deadline. Live uncompiled prompt version is
  now `uncompiled-v2`.
- 2026-11-06 [finding] DSPy `Signature.load_state` maps saved field labels by position, so
  a program compiled before the Analyst gained `chunks` would mislabel its fields;
  `apply_program` now refuses a field-count mismatch. `live-qa-v1b` therefore runs only
  on the pre-Stage-12 graph; `llm.compiled_program` is null until `live-qa-v2`.
- 2026-11-06 [finding] `shared_connection()` is cached, so every Cortex LM in a process
  shared one session and the last LM built set the statement timeout for all of them
  (in the service: live 10 s and prep 60 s). The first Stage 12 dev run hit it (dv-08:
  Guardian cut at 10 s). Fix: `llm_connection(seconds)`, one session per timeout.
- 2026-11-06 [result] Part A run 1 (uncompiled-v2, 121 calls): L1 dev 25/27 actions
  (Stage 9 live-qa-v1: 24/27), recall 1.0, 0 let through; L1 test 10/12 (Stage 10:
  7/12; fixed tq-02, tq-04, tq-05, tq-08; tq-03 and tq-06 now blocked for Responder
  additions: "organizational charts", "e.g., add, remove"). Analyst: dv-10, dv-25, tq-02,
  tq-08 now in scope; dv-24 Big-O still out_of_scope. Guardian cases: v1 6/8 caught
  (Stage 9: 8/8; missed gc-07 "names a term only" and gc-12, the old graded-work case),
  0 false fails; live dev 1/1, 3 false fails (lc-03, lc-05 inferences; lc-11 a claim the
  Guardian made up about an image, not in the answer); synthetic 1/1, 1 false fail.
  Latency avg 4.8 s, max 13.2 s (the 10 s bug). Guardian-eval outputs overwrote the
  Stage 9 files (names lack the prompt version); Stage 9 eval files kept in `outputs/stage9/`.
- 2026-11-06 [decision] User: live answers follow the prep bar for examples too: a short
  example or comparison that illustrates an idea a chunk states passes (no new fact).
  Responder and Guardian prompts say so; the Guardian prompt also gives a non-lesson
  example for "a chunk that only names a term" (gc-07).
- 2026-11-06 [finding] Rejected rule: ignoring a null Guardian claim whose words are
  mostly not in the answer. On the 56 stored null claims it would drop gc-11's real
  unsupported claim (the Guardian restates a SQL answer in words), a let-through risk.
- 2026-11-06 [result] Guardian cases with the example and names-only prompt
  (`uncompiled-v3`, 28 calls): v1 6/8 (gc-07, gc-12 still missed), 0 false fails; live
  dev 1/1, 2 false fails (lc-01, lc-02; run 1 had lc-03, lc-05, lc-11); synthetic 1/1,
  gs-01 false fail. Prompt changes alone do not converge (mistral-large3 varies per run),
  so the Guardian gets compiled. Part A so far about 150 calls.
- 2026-11-06 [decision] User: gc-12 stays fail; reason relabeled to "needs facts the
  chunks do not state" (the graded-work reason is gone). Guardian compile on labeled
  synthetic cases instead of an inference claim kind (the code check would not pass the
  real inference cases, and trusting the label would let the LLM decide).
- 2026-11-06 [change] `compile --side live --task guardian` (metric: `check_guardian`
  verdict = label, cases fail/pass alternating) and 13 new synthetic Guardian cases
  gs-05..gs-17 (proposed labels, for the user to confirm). Eval and guardian-eval
  output names now carry the prompt version.
- 2026-11-06 [result] live-qa-v2 (compiled on synthetic sets: Analyst 3 demos, Responder 2,
  Guardian 2, both fail cases gs-02/gs-12; gs-03 reworded first, its question was word
  for word dev dv-31): v1 Guardian cases 7/8 (gc-07 caught, gc-12 missed), 0 false fails;
  live dev 1/1, 2 false fails; L1 test 12/12; L1 dev 24/27, recall 1.0, 0 let through,
  latency avg 4.5 s, max 10.3 s, no timeout. Dev misses: dv-01 malformed Guardian reply
  ("[["), dv-08 and dv-10 Responder additions blocked ("efficient", "add or override");
  dv-24 Big-O and dv-25 overloading judged out_of_scope (both escalate either way).
  Single runs move by about 2 questions. Part A so far about 285 calls.
- 2026-11-06 [change] Live: a malformed reply is asked again once (`question.malformed_retries`)
  while at least `question.min_retry_seconds` (5) of the deadline is left; never after a
  timeout. The trace row's `retry_count` counts it (Q-21 field, now non-zero).
- 2026-11-06 [result] live-qa-v3 (Analyst demos tr-09, tr-17 uncovered course topic, tr-12;
  Guardian 3 demos fail/pass/fail): L1 dev 26/27 actions, 25/27 with the reason group
  (dv-24 Big-O still out_of_scope; dv-10 Responder addition blocked), 0 let through;
  L1 test 11/12 (tq-06 Guardian false fail); v1 Guardian cases 6/8 (gc-07, gc-12 missed),
  live dev 1/1, 2 false fails; latency avg 4.7 s, max 13.1 s; no timeout. Part A so far
  about 420 calls.
- 2026-11-06 [finding] Across Stage 12 runs the v1 catch rate is 6-7/8 (Stage 9: 8/8 with
  the strict "directly states" prompt): gc-07 (explains tests a chunk only names) and
  gc-12 (applies listed tests to an unstated key) pass under the looser bar. A code
  check on the word coverage of tied claims does not separate them (gc-07 claims 0.62-0.67;
  71 of 384 pass-case claims are below 0.6). 0 unsupported answers let through on L1 dev
  and test in all Stage 12 runs.
- 2026-11-06 [decision] User (option A): the Guardian gate becomes "v1 cases at least 6/8,
  0 let through on dev and held-out"; gc-07 and gc-12 are the accepted cost of the looser
  bar. No Guardian ensemble or model change. Part A closed at about 420 calls;
  `live-qa-v3` is the working program (the default decision stays at the exit gate).
- 2026-11-06 [change] Part B code (mock): slide-text fallback drops ISBN, copyright,
  publisher, and "materials are edited by" lines (L1 p03 now reads the university,
  title, lecturer, college); PollWriter prefers wrong options the chunks rule out;
  ExplanationWriter must not describe the chosen option's own topic beyond the chunks,
  at most one own example. Prep uncompiled prompt version `uncompiled-v2`.
- 2026-11-06 [finding] Rescuing untied explanation claims with the poll's own text would
  pass 2 of 80 stored claims (one a negated option statement): not added.
- 2026-11-06 [decision] User: run a DSPy experiment on the live Guardian before Part B
  (STAGES task 5b): random search and GEPA against `uncompiled-v3` and `live-qa-v3`.
  So far DSPy gave structure and first-passing demos; the Stage 12 gains came from
  hand changes, and compiled vs uncompiled is within run-to-run noise.
- 2026-11-06 [finding] [verify] Installed DSPy 3.4.1 has `BootstrapFewShotWithRandomSearch`
  (`num_candidate_programs`, `valset`), `MIPROv2` (`auto` light/medium/heavy), and
  `GEPA` (experimental; feedback metric `(gold, pred, trace, pred_name, pred_trace)`,
  `max_metric_calls`, `reflection_lm`); the `gepa` package (0.1.4) is already installed
  as a dspy dependency, so nothing new is added.
- 2026-11-06 [result] DSPy experiment (task 5b, about 556 calls): val = v1 cases 12 + L1 live
  dev 13. Correct of 25 per run: uncompiled-v3 21, 22; live-qa-v3 21, 22 (v1 6/8 each);
  random search `live-qa-v4-rs` 24 at selection, then 24, 23 (v1 8/8 in all three runs,
  gc-07 and gc-12 caught); GEPA `live-qa-v4-gepa` 24 at selection, then 22, 22 (v1 7/8).
  v4-rs on L1 dev end to end: 27/27 actions, 0 let through, latency avg 4.5 s, max 11.3 s.
  Random search picked the unshuffled candidate with 3 demos (gs-02 fail, gs-03 pass,
  gs-05 pass); shuffled candidates had 1-2 demos and scored 84-92%. GEPA (claude-sonnet-4-5,
  5 reflection calls) only strengthened the names-only rule. The val cases chose the
  winner, so the val numbers are optimistic; held-out L2-L4 is the real check.
- 2026-11-06 [decision] User: `live-qa-v4-rs` is the working live program (default decided at
  the exit gate); `live-qa-v4-gepa` deleted; prep Guardians get the same random-search
  method in Part B (task 6b, 32 synthetic prep cases for the user to label). User: the
  credit budget is ample; size experiments for reliable results. Part B approved, limit
  about 2,200 calls.
- 2026-11-06 [finding] Prep Guardian baselines (uncompiled, L1 prep dev cases, 3 runs, 63
  calls): script 5-7/10 (pc-07 caught 1 of 3 runs, pc-08 never; false fails pc-02, pc-09,
  once pc-01); poll 6/6 every run; explanation 4/5 every run (pc-19 missed). pc-08 (an
  outline script with other slides' topics in the wrong order) passes because the
  Guardian sees every chunk the writer was given (Stage 9), so each claim is tied; added
  synthetic pair ps-15 (fail) / ps-16 (pass). Stage 9's 8/8 was measured before that change.
- 2026-11-06 [result] L2-L4 parsed on Cortex (3 AI_PARSE_DOCUMENT calls for the readings,
  33 vision pages): chunks l2 27, l3 28, l4 35. Slides 18/18/17 pages. Part B so far
  about 100 calls.
- 2026-11-06 [change] Held-out test questions drafted for L2, L3, L4
  (`materials/lessons/l<n>/test_questions.json`, 4 categories x 3) from the parsed
  chunks; waiting for the user's review. Not used for tuning.
- 2026-11-06 [decision] User labeled the 34 synthetic prep cases as proposed (pp-01 pass:
  "no order" shows set and bag wrong for a FIFO question; ps-15 fail for a reversed
  outline order, ps-16 pass) and approved the L2-L4 test questions as drafted.
- 2026-11-06 [result] Prep Guardians with random search (task 6b; val = L1 prep dev cases,
  3 runs each after selection): script 5/6/7 -> 6/8/8 of 10 (fewer false fails; pc-07 and
  pc-08 still mostly missed), explanation 4/4/4 -> 4/5/5 of 5 (pc-19 caught 2 of 3), poll
  6/6/6 -> 5/6/6 (no gain; poll Guardian stays uncompiled). Selection scores (9/10, 5/5)
  were optimistic, as expected with val sets of 5-10.
- 2026-11-06 [change] ScriptWriter: title and outline slides name their items in the
  slide's own order and words, keep each name (a lecture title is not the course name),
  and add no topics from other slides (pc-07/pc-08 come from the writer). `prep-v6` =
  writers compiled with BootstrapFewShot (script 2 demos, explanation 2) + the random-search
  script and explanation Guardians.
- 2026-11-06 [change] L1 renamed `l1` (parse reused by hash; chunk ids unchanged; the dev
  set still searches `info6205-l1`, same chunks). Search refresh while the service is
  suspended still indexes: L2-L4 were searchable after resume.
- 2026-11-06 [result] L1 full run with prep-v6 (97 calls, 313 s; Stage 9: 125 calls, 413 s):
  scripts 14/14, 0 fallback (title slide p03 reads course, instructor, textbook; outline
  p04/p05 keep the slide's two topics); 4 polls live, 1 dropped (wrong options not shown
  wrong); 12 of 12 wrong options explained (Stage 9: 8 of 15).
- 2026-11-06 [change] Responder self-check counted its own tied example as ungrounded
  (tq-02 escalated with grounded=false); it now counts a short example of a stated idea
  as supported. `live-qa-v5` = live-qa-v4-rs with the Responder recompiled; live
  uncompiled prompt version `uncompiled-v4`.
- 2026-11-06 [result] live-qa-v5: L1 test 12/12, L1 dev 26/27 (dv-10: Responder added
  "override", correctly blocked), 0 let through, latency avg 4.5 s, max 9.7 s. Part B so
  far about 570 calls.
- 2026-11-07 [result] Held-out L2-L4 (prep-v6 + live-qa-v5 vs Stage 10 code at 0ff4101 +
  live-qa-v1b on the same manifests; 2 runs each, 36 questions per run): v5 32 and 31,
  baseline 30 and 31. Let through: v5 1 (L2 tq-09 run 2: "java -ea MyClass" for the
  command line, tied by the Guardian to the Eclipse -ea chunk), baseline 0. Reason group
  wrong (out_of_scope for a partial): v5 L2 tq-09 once, L4 tq-07 twice; baseline L2 tq-08
  twice, L4 tq-07 twice. False escalations: v5 5 (L3 tq-02 x2, L4 tq-05 x2, L2 tq-04),
  baseline 7 (L4 tq-02, tq-05 x2, tq-06 x2, L3 tq-01, L4 tq-03 llm_error).
- 2026-11-07 [result] Held-out prep with prep-v6: scripts fallback L2 5/18, L3 0/18, L4 3/17;
  polls live 5/5/5; wrong options explained L2 11/15, L3 11/15, L4 7/15 (L1: 12/12).
  Causes seen: L2 title script failed the TTS lint on "(Jones)"; four L2 quote checks
  failed where the reading has HTML entities and LaTeX (`$x &gt; 0$`); L4 explanations
  about diagram facts the vision text does not state. Not fixed: held-out findings wait
  for the user's decision. Part B so far about 1,300 calls.
- 2026-11-07 [decision] User: accept the L2 tq-09 let through (option a: a correct `-ea`
  answer beyond the materials, same kind as gc-07); fix the two code bugs found on L2
  (L2 prep results after the fix are no longer held-out); demo baseline = the same code
  without compiled programs (B: `uncompiled-v4` live, `uncompiled-v2` prep), to show what
  DSPy adds.
- 2026-11-07 [change] Code fixes from L2: quotes and word checks decode HTML entities
  (`&gt;`) before matching; generated scripts and explanations lose round and square
  brackets (no words change) instead of failing the TTS lint. L2 after the fixes: script
  fallbacks 5 -> 1.
- 2026-11-07 [result] DSPy vs no DSPy, same Stage 12 code, one full run per lesson (prep +
  12 questions; ~2,080 Part B calls in all):

  | Lesson | Questions (DSPy / none) | Let through | Script fallbacks | Wrong options explained |
  |---|---|---|---|---|
  | L1 (dev) | 12 / 8 | 0 / 1 | 0 / 2 of 14 | 12/12 / 7/12 |
  | L2 | 11 / 11 | 0 / 0 | 1 / 1 of 18 | 10/15 / 10/15 |
  | L3 | 11 / 11 | 0 / 0 | 0 / 8 of 18 | 11/15 / 5/15 |
  | L4 | 10 / 9 | 0 / 0 | 3 / 3 of 17 | 7/15 / 6/15 |
  | Total | 44 / 39 of 48 | 0 / 1 | 4 / 14 of 67 | 40/57 / 28/57 |

  Single runs (about +-2 questions per lesson between runs); L1 steered the tuning. The
  v5 let through on L2 tq-09 happened in a second questions-only run. Latency avg
  4.1-4.6 s both.
- 2026-11-07 [change] Cleanup before the push: removed `scripts/probes/` (Stage 1), the
  per-stage SQL probes (one `sql/probes/cost_reading.sql` remains),
  `scripts/stage9_comparison.py`, and compiled programs other than `live-qa-v5` and
  `prep-v6`. Local `outputs/` keeps the 8 comparison runs (`dev/l1-l4`, prep `l<n>` and
  `l<n>.uncompiled`), parses and conversions of L1-L4, the v5 dev-set eval, and the
  Guardian baselines in `optimize/`.
- 2026-11-07 [change] Retired the v1 Snowflake path: removed `sql/02`, `sql/03`,
  `scripts/load_chunks.py`, and `question.search_service`. The `content/` fixture lesson
  reads its chunks locally also with `BACKEND=cortex`; `smoke_test.py` and
  `search_service.py` use `objects` (V2). The Snowflake objects are not dropped yet.
