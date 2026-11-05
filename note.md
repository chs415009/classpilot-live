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
