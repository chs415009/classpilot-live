# Development notes (v2)

Log of changes, decisions, findings, and open questions per stage. Newest entries at the
bottom of each stage. Stage plan: `docs/v2/STAGES.md`. The v1 log (Stages 1-4, including
the Stage 4 baseline numbers) is archived in `docs/v1/note_v1.md`.

Entry format: `- YYYY-MM-DD [type] text` where type is one of `change` (differs from
CLAUDE.md or the plan), `decision`, `finding`, `todo`, `question`, `result`.

---

Design: `docs/v2/CLASSPILOT_BEHAVIOR.md` (behavior), `docs/v2/IMPLEMENTATION_NOTES.md`
(implementation, decisions log in section 13), `docs/v2/ANALYSIS.md` (v1 reuse map, repo
decision), `docs/v2/STAGES.md` (stage plan). v1 rules and contracts: `docs/v1/CLAUDE_v1.md`.

## Stage 0: Repository setup and v2 docs

- 2026-11-04 [change] Direction change to v2: the professor only uploads materials and
  reads the post-class report. The system generates per-slide scripts, polls,
  misconceptions, and explanations before class and checks them automatically (Guardian,
  one retry with feedback, fallback). No pre-approved branches, no professor review, no
  protected-question check, no 2-agent mode. New parts: prep service, parse layer,
  generators, live endpoints, trace records for the team star schema, post-class report.
- 2026-11-04 [decision] New repo `classpilot-live`, package `classpilot`, seeded with the
  cleaned v1 code (ANALYSIS.md section 2). The old `agents_demo/` folder was never a git
  repository, so there was no history to carry or scan. It stays as the local v1
  reference.
- 2026-11-04 [decision] The repo will become public. Account locator, region, and key
  path replaced with placeholders before the first commit. Service user and other object
  names stay as configurable defaults. `scripts/check_secrets.sh` (grep-based) is
  release-blocking before every push.
- 2026-11-04 [change] `ruff` adopted (dev): rules E, F, I, B, UP; line length 100. The
  prompt files (`nodes/*.py`) and `report.py` ignore E501 so the v1 prompt text stays
  byte-identical to the Stage 4 baseline (checked) until DSPy replaces it. `zip(...,
  strict=True)` added in `scripts/smoke_test.py` (B905).
- 2026-11-04 [finding] (docs, checked 2026-11-04) `IDENTIFIER($var)` with a session
  variable is documented by example only for `USE SCHEMA`, `CREATE TABLE`, `INSERT`,
  `SELECT`, `DROP TABLE`; the docs say "in some cases" and do not list `CREATE WAREHOUSE`,
  `USE ROLE`, `GRANT`, `CREATE USER`, or `CREATE CORTEX SEARCH SERVICE`.
  https://docs.snowflake.com/en/sql-reference/identifier-literal ,
  https://docs.snowflake.com/en/sql-reference/session-variables
- 2026-11-04 [change] Because of that finding, the Stage 0 task "SQL object names become
  variables" is deferred: the v1 SQL keeps its object names as defaults (with
  `IF NOT EXISTS`, still rerunnable on a new account). Stage 5 rewrites the SQL and checks
  variable support with a small probe (with approval) before relying on it.
- 2026-11-04 [question] Git author email of the commits is a personal address, which is
  public once pushed. Use a GitHub noreply address for this repo? The `--history` mode of
  the secret check fails until this is decided.
  -> [decision] User: keep the personal git email (public by choice). The history check
  allows the address from `git config user.email` (not written into the repo) plus
  noreply addresses.
- 2026-11-04 [change] User: all v1 docs are archived and v1 interface items are ignored.
  The v1 dev log moved to `docs/v1/note_v1.md` and v1 items Q-01 to Q-12 to
  `docs/v1/interface_questions_v1.md`. `interface_questions.md` keeps only v2 items
  (Q-13 to Q-21; numbering continues so archived references stay unique). References to
  v1 items in CLAUDE.md and the v2 docs were removed.
- 2026-11-04 [change] User: no date-driven planning; the user decides when stages run.
  Removed the trial-expiry check from Stage 0 and the trial-date dependency of Stages 1
  and 9.
- 2026-11-04 [result] Stage 0 accepted by the user. Checks: pytest 85 passed (also with
  network connections blocked), `run-all` 9/9 OK, ruff check + format clean,
  `check_secrets.sh --history` clean, no forbidden files tracked.
- 2026-11-04 [decision] User: the repo is public from the start (teammates need to read
  it). Created and pushed https://github.com/chs415009/classpilot-live after the
  secret check passed.

## Stage 1: Live probes for `[verify]` items

- 2026-11-04 [decision] User started Stage 1. Approval covers the `dspy` dependency and
  the stage estimate (about 15-25 LLM calls, limit about 38). `PyJWT` / early `pymupdf`
  only if needed, asked separately. Probe SQL is shown before it runs.


### Docs check: Cortex Search (docs read 2026-11-04; quotes via summarized fetch)
- 2026-11-04 [finding] Filters work only on ATTRIBUTES columns ("Attribute columns must be
  included in the source query"). Operators `@eq`, `@contains`, `@gte`, `@lte`,
  `@primarykey`, combined with `@and` / `@or` / `@not`. Lesson filter:
  `{"@eq": {"LESSON_ID": "<id>"}}`. snowflake-core:
  `svc.search(query, columns, filter=..., limit=...)` (needs snowflake-core >= 0.8.0; we
  have 1.13.2).
  https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-search/query-cortex-search-service
- 2026-11-04 [finding] `TARGET_LAG = '<num> {seconds|minutes|hours|days}'` is a soft
  target; no minimum is stated. A manual `ALTER CORTEX SEARCH SERVICE <name> REFRESH`
  exists, so prep can refresh right after loading chunks instead of relying on a short
  lag. Default refresh is incremental (needs change tracking + time travel).
  https://docs.snowflake.com/en/sql-reference/sql/create-cortex-search ,
  https://docs.snowflake.com/en/sql-reference/sql/alter-cortex-search
- 2026-11-04 [finding] `ALTER CORTEX SEARCH SERVICE <name> {SUSPEND|RESUME}
  [INDEXING|SERVING]` (both layers if neither is given). Suspended serving is not billed;
  suspended indexing runs no refreshes. Storage billing while suspended: not stated.
- 2026-11-04 [finding] Optional `PRIMARY KEY (<cols>)`: "a set of columns that uniquely
  identify each row"; TEXT columns only; duplicates are ignored in the index. So
  (`LESSON_ID`, `CHUNK_ID`) fits the per-lesson chunk copies (decided 2026-11-04), and a
  primary key enables an optimized refresh path.
  https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-search/cortex-search-overview
- 2026-11-04 [finding] Cost: serving per GB-month of indexed data while available;
  embeddings only for inserted or changed rows (incremental mode); warehouse only when a
  refresh finds changes; storage flat per TB. Credit rates not read.

### Docs check: LiteLLM Snowflake provider and Cortex REST (docs read 2026-11-04)
- 2026-11-04 [finding] LiteLLM: `model="snowflake/<model>"`, token from `SNOWFLAKE_JWT`,
  account from `SNOWFLAKE_ACCOUNT_ID` (or `api_key` / `account_id` params). PAT with a
  `pat/` prefix is the recommended auth; key-pair JWT also works, but the caller must
  generate it (max 1 hour validity, so it must be refreshed). `response_format` is **not
  supported** (raises `UnsupportedParamsError` unless `drop_params`).
  https://docs.litellm.ai/docs/providers/snowflake
- 2026-11-04 [finding] Cortex REST: OpenAI-compatible `/api/v2/cortex/v1/chat/completions`
  (all models), `/api/v2/cortex/v1/messages` (Claude). Bearer token = key-pair JWT, OAuth,
  or PAT. JWT: `iss = ACCOUNT.USER.SHA256:<fingerprint>`, `sub = ACCOUNT.USER`, uppercase,
  at most 1 hour. Default role needs `SNOWFLAKE.CORTEX_USER` or `CORTEX_REST_API_USER`.
  Billed in AI credits per million tokens ($2.00/credit global routing). Warehouse use:
  not stated. 503 = inference timed out; no timeout value stated.
  https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-rest-api ,
  https://docs.snowflake.com/en/developer-guide/sql-api/authenticating
- 2026-11-04 [finding] REST `response_format` (JSON schema) works for OpenAI models and
  (json_schema type) Claude models; it is **ignored** for other models (Mistral, Llama).
  Images: OpenAI and Claude models only (`claude-sonnet-4-5`+, `openai-gpt-4.1`+).
- 2026-11-04 [finding] PAT on a `TYPE=SERVICE` user only works if the user is under a
  network policy (or an authentication policy sets `NETWORK_POLICY_EVALUATION =
  NOT_ENFORCED`). Default PAT lifetime 15 days.
  https://docs.snowflake.com/en/user-guide/programmatic-access-tokens
- 2026-11-04 [finding] Not stated: whether cross-region inference applies to REST the same
  way as to `AI_COMPLETE`, and which models our account reaches over REST. The probe checks
  `GET /api/v2/cortex/models` (per account).
- 2026-11-04 [question] Route comparison for the probe. Route A (LiteLLM → REST) loses
  `response_format` (DSPy then parses plain text) and needs a self-made, refreshed JWT
  (`PyJWT`, or `cryptography`, which is already installed) or a PAT plus a network policy
  (account-level SQL). Route B (custom `dspy.BaseLM` over `AI_COMPLETE`) keeps the
  structured output and key-pair auth verified in v1 Stage 3, but needs the warehouse.

### Docs check: DSPy (source and docs at tag 3.4.1, read 2026-11-04)
dspy.ai pages returned only redirect stubs, so the docs were read from the repo at the
tag that matches the PyPI release. `main` is already ahead (3.5 changes); do not copy
patterns from `main`.
- 2026-11-04 [finding] Latest `dspy` is 3.4.1 (2026-10-12), Python `>=3.10,<3.16`. It
  pulls `openai`, `litellm` (on Python < 3.15), `pydantic>=2.11`, `diskcache`,
  `json-repair`, `tenacity`, `gepa[dspy]==0.1.4`, and others.
  https://pypi.org/pypi/dspy/3.4.1/json
- 2026-11-04 [finding] Custom LMs by subclassing `dspy.BaseLM.forward()` are **deprecated
  in 3.4 and scheduled for removal in 3.5**. The current way is a custom engine:
  `class E: def complete(self, request: dspy.lm15.Request) -> dspy.lm15.Response`, passed
  as `dspy.LM("<name>", engine=E(), ...)`. Connection settings go to the engine's
  constructor (`dspy.LM(engine=..., api_key=...)` raises `ValueError`). Failures must be
  raised as `dspy.lm15` errors, not returned. Saving a program with an engine needs
  `dump_state` / `load_state` and `program.load(..., allow_unsafe_lm_state=True)`.
  docs/docs/tutorials/custom_lm_engines/index.md, dspy/clients/base_lm.py
- 2026-11-04 [finding] `dspy.LM` caches by default (`cache=True`; global
  `dspy.configure_cache(...)`) and retries by default (`num_retries=3`, exponential backoff
  up to 60 s). For our "timeout → escalate, never hang" rule, set `num_retries=0` for live
  Q&A. Errors: `dspy.LMError` and subclasses.
- 2026-11-04 [finding] ChatAdapter is the default; on `dspy.AdapterParseError` it makes one
  more call with JSONAdapter unless `use_json_adapter_fallback=False`. JSONAdapter is
  recommended only when the model supports `response_format`. Output fields can be
  `Literal[...]` or pydantic models (their JSON schema goes into the instructions).
- 2026-11-04 [finding] Tests without network: `dspy.utils.DummyLM(answers, ...)` (list or
  dict mode; never caches). `dspy.Refine(module, N, reward_fn, threshold, fail_count)`
  generates its own feedback with an extra LM call (hint field); the caller cannot pass
  the Guardian's feedback directly, so the prep retry loop stays our own code (as
  planned). Save/load: `program.save("x.json")` / `program.load("x.json")`;
  `BootstrapFewShot(metric, max_bootstrapped_demos=4, max_labeled_demos=16, ...)`, metric
  `(example, pred, trace=None)`. `dspy.Snowflake` / `SnowflakeRM` no longer exist.
- 2026-11-04 [decision] (proposed, for review) Route B is a custom engine (not
  `BaseLM.forward`). Pin `dspy>=3.4.1,<3.5` so the engine API we test is the one we run.
  Live Q&A uses `num_retries=0` and `cache=False`; eval and compile keep the cache on.

### Docs check: AI_PARSE_DOCUMENT, stages, vision, cost views (docs read 2026-11-04)
- 2026-11-04 [finding] `AI_PARSE_DOCUMENT(TO_FILE(...), {'mode': 'OCR'|'LAYOUT'|'AGENTIC'
  (preview), 'page_split': true, 'page_filter': [...], 'extract_images': true}
  [, return_error_details])`. Accepts PDF, PPTX, DOCX, images, HTML, TXT; max 100 MB and
  2,000 pages. With `page_split`: `pages[]` with `content`, zero-based `index`,
  `dimensions`. Billed per page (PPTX page counting: not stated). PPTX speaker notes: not
  stated (the probe checks it). Not native in our region; "available through cross-region
  inference to accounts in all regions". Legacy `PARSE_DOCUMENT` deprecated by end of 2026.
  https://docs.snowflake.com/en/sql-reference/functions/ai_parse_document
- 2026-11-04 [finding] Stage: `CREATE STAGE <s> DIRECTORY = (ENABLE = TRUE) ENCRYPTION =
  (TYPE = 'SNOWFLAKE_SSE')`. AI_COMPLETE with images needs server-side encryption
  ("client-side encrypted stages are not supported"); the default `SNOWFLAKE_FULL` cannot
  be changed after creation, so SSE must be set at create time. Internal-stage directory
  tables need `ALTER STAGE <s> REFRESH` after `PUT`.
  https://docs.snowflake.com/en/sql-reference/sql/create-stage ,
  https://docs.snowflake.com/en/user-guide/data-load-dirtables-manage
- 2026-11-04 [finding] Vision: `AI_COMPLETE(model, predicate, TO_FILE(...)
  [, model_parameters])` or `AI_COMPLETE(model, PROMPT('... {0}', TO_FILE(...)))`.
  claude-haiku-4-5 is listed as image-capable (cross-region only). Claude: max 3.75 MB and
  8000x8000 per image. **Structured output (`response_format`) cannot be combined with an
  image prompt**: the vision step must ask for JSON in the text and parse/validate it in
  code (malformed → retry/fallback, like any LLM error).
  https://docs.snowflake.com/en/sql-reference/functions/ai_complete-single-file ,
  https://docs.snowflake.com/en/sql-reference/functions/ai_complete-prompt-object
- 2026-11-04 [finding] Our region is not native for AI_COMPLETE or AI_PARSE_DOCUMENT; only
  AI_EMBED / AI_EXTRACT are listed for it ("extended regions"). Cross-region covers parse;
  whether image input has extra cross-region limits is not stated. (per account)
  https://docs.snowflake.com/en/user-guide/snowflake-cortex/aisql-regional-availability
- 2026-11-04 [finding] Cost views: `CORTEX_FUNCTIONS_QUERY_USAGE_HISTORY` is **no longer
  updated** (data ends 2025-11-21). Use `SNOWFLAKE.ACCOUNT_USAGE.CORTEX_AI_FUNCTIONS_USAGE_HISTORY`
  (FUNCTION_NAME, MODEL_NAME, QUERY_ID, WAREHOUSE_ID, METRICS with tokens/pages, CREDITS
  excluding warehouse; latency about 5 min). `WAREHOUSE_METERING_HISTORY` lags up to 3 h.
  https://docs.snowflake.com/en/sql-reference/account-usage/cortex_ai_functions_usage_history
- 2026-11-04 [change] Plan docs updated to name `CORTEX_AI_FUNCTIONS_USAGE_HISTORY`
  instead of the old view.
- 2026-11-04 [result] User reviewed and approved `sql/probes/stage1_probe_setup.sql` and
  ran Part 1 in Snowsight as ACCOUNTADMIN: `GRANT CREATE STAGE ON SCHEMA
  CLASSPILOT_DEMO.AGENT TO ROLE CLASSPILOT_AGENT_ROLE`, checked with `SHOW GRANTS`.
  Part 2 (`PROBE_STAGE`) not run yet.

### Cost calibration from v1 (account: current trial; read by the user 2026-11-04)
- 2026-11-04 [result] `CORTEX_AI_FUNCTIONS_USAGE_HISTORY` since 2026-10-20: 330 queries
  (AI_COMPLETE 329, AI_EMBED 1), **0.0456 AI credits** in total. mistral-large3 on the
  Stage 3/4 days: 195 queries 0.0284, 65 queries 0.0104 → about **0.00015 AI credits per
  call** (about $0.0003 at $2/credit). claude-haiku-4-5 and llama3.3-70b probes were in
  the same range per call.
- 2026-11-04 [result] `WAREHOUSE_METERING_HISTORY`: `CLASSPILOT_WH` **0.855 credits** in
  total, 0.849 of it on 2026-10-20..24 (active work), then 0.0002-0.002 per day with no
  work (most likely the v1 `LESSON_SEARCH` refresh checks; to confirm). Cloud services
  0.008.
- 2026-11-04 [finding] The warehouse costs about 19× the AI credits. Per-call LLM cost is
  negligible at our volumes; what matters is how long the warehouse stays up (XS = 1
  credit/hour, auto-suspend 60 s). The plan's dollar estimates (e.g. "under $3" for 25
  calls) are far too high for the AI part; a stage's real cost is mostly warehouse
  minutes. Route A (REST) may avoid the warehouse entirely (probe). Cortex Search serving
  cost is not in these two views.

### Live probes (2026-11-04, current trial account; outputs in outputs/probes/, gitignored)
- 2026-11-04 [result] Offline engine probe: with `num_retries=0` and
  `ChatAdapter(use_json_adapter_fallback=False)`, DSPy makes exactly one engine call.
  Malformed output, a bad `Literal` value, or non-JSON → `dspy.AdapterParseError`. Engine
  errors surface as `dspy.utils.exceptions.LMTimeoutError` (from `lm15.TimeoutError`),
  `LMServerError` (from `lm15.ServerError`), `LMUnexpectedError` (any other exception).
  All of these map to our `LLMError` → `llm_error`. JSONAdapter does not pass a
  `response_format` to a custom engine (the JSON schema goes into the prompt text).
- 2026-11-04 [result] Route B (custom engine over `AI_COMPLETE`, mistral-large3): the
  Analyst signature parses with both ChatAdapter (1.33 s) and JSONAdapter (1.07 s), with
  the right category and objective. Prompt about 1.7k characters.
- 2026-11-04 [finding] With ChatAdapter, an `objective_id: str | None` field came back as
  the string `"None"`, not null. The Stage 3 signatures must normalize this (or use a
  sentinel) before the validator sees it.
- 2026-11-04 [finding] **The connector's `cursor.execute(..., timeout=N)` did not cancel a
  running `AI_COMPLETE`**: with `timeout=1` the call returned after 15.9 s. So in v1 the
  thread timeout escalated on time, but the query kept running (and billing). v1 note
  2026-10-21 ("cancels slow calls server-side") was wrong in practice.
- 2026-11-04 [finding] `ALTER SESSION SET STATEMENT_TIMEOUT_IN_SECONDS = 2` **does** cancel
  it server-side: error 000630 after 2.37 s. The Stage 3 adapter uses the session
  statement timeout (whole seconds), plus the thread timeout as a backstop.
- 2026-11-04 [result] Route A (Cortex REST, key-pair JWT signed with `cryptography`, no
  PyJWT): authentication is accepted (403, not 401), but every REST endpoint returns
  `003001 "This account is not allowed to access this endpoint. Please contact Snowflake
  support."`, both through LiteLLM and direct. (per account: likely a trial restriction)
  `GET /api/v2/cortex/models` returned 400 "request entity required". Not retried.
- 2026-11-04 [decision] (proposed, for review) **Route B** for all LLM calls on this
  account: a DSPy custom engine over `AI_COMPLETE` via the existing connector. Keep the
  JWT helper idea for a future account where REST is enabled.
- 2026-11-04 [result] Created `PROBE_STAGE` (approved SQL, SSE, directory table), `PUT`
  both materials with `AUTO_COMPRESS=FALSE`, `ALTER STAGE ... REFRESH`, then
  `AI_PARSE_DOCUMENT` LAYOUT + page_split: reference PDF 3 pages in 5.4 s; slide PDF in
  4.8 s. Output keys `metadata`, `pages[]` (`index`, `content`, `dimensions`).
- 2026-11-04 [finding] `AI_PARSE_DOCUMENT` reports **13 pages** for `L1_slide.pdf`, while
  the macOS `file` command said 8. To confirm with PyMuPDF; the Stage 4 alignment check
  must count pages with the same library used for rendering.
- 2026-11-04 [finding] LAYOUT output marks embedded images as `![img-N.jpeg](img-N.jpeg)`
  in the page Markdown. That is a cheap image-page signal from the parse output itself
  (pages 0, 1, 5, 12 of the slides have it). Vector diagrams without embedded images
  would not show up this way, so it complements, not replaces, the PyMuPDF heuristic.
- 2026-11-04 [finding] PPTX speaker notes could not be tested: the materials are PDF.
- 2026-11-04 [result] LLM calls so far in Stage 1: 5 `AI_COMPLETE` (3 Route B, 2 timeout
  probes) + 2 `AI_PARSE_DOCUMENT` (16 pages) + 4 rejected REST requests. Limit about 38.
- 2026-11-04 [decision] User approved adding `pymupdf` in Stage 1 (needed to render the PDF
  slides and read their text layer). Installed PyMuPDF 2.1. User confirmed by hand that
  `L1_slide.pdf` has 13 pages (PyMuPDF agrees; the macOS `file` command was wrong).
- 2026-11-04 [question] PyMuPDF is licensed **AGPL-3.0** (or Artifex commercial). The
  repo is public and the prep service would run it on a server. Which license should the
  repo use, and is AGPL acceptable for the course project (alternative: `pypdfium2`,
  Apache/BSD)? To decide before Stage 4 builds on it.
- 2026-11-04 [result] Page signals (PyMuPDF, 13 slides): embedded image area fraction is
  0.32-0.50 on the four image slides (0, 1, 5, 12) and 0.03 on a slide with only a small
  logo (2); 0 elsewhere. Same four slides as the `![img-N]` markers in the parse output.
  Drawing area is about 1.8 on every slide (template background), so drawings are only
  useful after subtracting what every page of the deck shares. Draft heuristic for
  Stage 4: image if image area >= 0.10; unsure if 0.02-0.10 or non-template drawings
  cover a large area; text otherwise. PNG at 144 dpi: 1584x1224, 13-660 KB (well under
  3.75 MB).
- 2026-11-04 [result] Vision probe, single-file `AI_COMPLETE` with the text layer in the
  prompt, slides 7 (text only), 5 (image), 12 (image + text):
  - `claude-haiku-4-5`: 3.1-3.6 s per slide. Valid JSON with all three keys, but always
    wrapped in a ```json fence (strip in code). Descriptions match the slides (checked
    against the slide content); empty `diagram_description` on the text-only slide.
  - `llama4-maverick`: error 100351 "has been in legacy state, please use other models".
    (per account)
  - `openai-gpt-5-nano`: empty reply at `max_tokens` 800 (reasoning model; tokens used
    up). With 4000 it returned valid JSON without a fence, but took 18.9 s.
- 2026-11-04 [decision] (proposed, for review) Vision model: `claude-haiku-4-5` (fast,
  reliable JSON). `openai-gpt-5-nano` only if the cost reading shows a large price
  difference. Text model for live Q&A stays `mistral-large3` (v1 baseline; fastest in
  v1). Vision is used only for image pages, so it is a small share of prep calls.
- 2026-11-04 [result] Stage 1 live usage so far: 15 `AI_COMPLETE` (3 Route B, 2 timeout,
  10 vision incl. 3 rejected as legacy) + 2 `AI_PARSE_DOCUMENT` (16 pages). Limit about 38.
