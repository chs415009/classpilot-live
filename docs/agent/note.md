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

## Stage 2: Live paths, manifest, and trace on v2 contracts (mock)

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
