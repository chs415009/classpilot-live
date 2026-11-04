# Development notes

Log of changes, decisions, and open questions per stage. Newest entries at the bottom
of each stage. Stage plan and checkboxes live in `CLAUDE.md` ("Stages and progress").

Entry format: `- YYYY-MM-DD [type] text` where type is one of
`change` (differs from CLAUDE.md or the plan), `decision`, `finding`, `todo`, `question`.

---

## Stage 1: Mock-mode demo — DONE

- 2026-10-20 [change] Dev setup: Python 3.12 + `venv` + `pip` instead of Python 3.11 + `uv`
  (agreed with the team). CLAUDE.md "Dev setup" updated.
- 2026-10-20 [decision] Dependencies: `langgraph`, `pydantic`, `pyyaml`; dev: `pytest`.
  No Snowflake packages until Stage 3.
- 2026-10-20 [change] Added modules not in the folder layout: `settings.py` (load
  settings.yaml + env overrides), `content.py` (load content/), `text.py` (word-overlap
  similarity), `runner.py` (scenario + eval runner shared by CLI and report).
- 2026-10-20 [change] CLI has extra commands: `run-all` and `report` (besides `run`, `eval`).
- 2026-10-20 [change] More scenarios than the 4 in CLAUDE.md: poll split into reteach /
  below threshold / remediation limit; timeout and low confidence split into 04a / 04b;
  added `05_unsupported_answer` to compare 2-agent vs 3-agent. 05 is expected to show
  MISMATCH in mode 2 (that is the point).
- 2026-10-20 [decision] Skipped the optional LLM note for the professor on the poll path.
  Demo question 1 is answered without it.
- 2026-10-20 [decision] MockLLM scripts one failure mode on purpose: when chunks only
  partly cover a question (coverage 0.3-0.6) the responder adds an unsupported sentence,
  says confidence 0.85 and grounded=true. This is what makes the Guardian comparison
  visible. Mock results show the mechanism, not a real failure rate.
- 2026-10-20 [decision] Thresholds: protected similarity = Jaccard on content words,
  threshold 0.5; responder confidence threshold 0.70; LLM timeout 10 s.
- 2026-10-20 [decision] Escalation reason for malformed LLM output (schema check fails)
  is `llm_error`.
- 2026-10-20 [decision] Poll-path trace uses `agent_mode: null` (no agents run) and
  `input_ref = "<question_id>@<snapshot_time>"` because poll evidence has no event id.
- 2026-10-20 [decision] Trace latency keys: `analyst`, `retrieval`, `responder`,
  `guardian`, `total` (retrieval split out so Stage 4 can measure Cortex Search alone).
- 2026-10-20 [finding] Timeout uses a worker thread; Python cannot kill it, so a slow call
  keeps running in the background after we escalate. Fine for the demo; revisit if Cortex
  calls can be cancelled.
- 2026-10-20 [todo] In 3-agent mode the Guardian still runs when the responder's
  confidence is already below threshold (one wasted call). Could route straight to the
  validator; left as is to keep the flow simple. (Done in Stage 4, 2026-10-22.)
- 2026-10-20 [todo] Cortex adapters are placeholders with a checklist of what to verify
  in the Snowflake docs (`adapters/llm.py`, `adapters/retrieval.py`).
- 2026-10-20 [question] Assignment-like questions are escalated (per CLAUDE.md design).
  Should they instead get a pre-approved hint (e.g. "review chunk-04")? Design change;
  needs team agreement before implementing.
- 2026-10-20 [result] Mock eval (11 questions): 2-agent recall 0.71, 2 unsupported let
  through, 1.55 LLM calls/question; 3-agent recall 1.0, 0 let through, 2.18 calls/question.
  58 tests pass.

## Stage 2: Snowflake setup — DONE (2026-10-21)

- 2026-10-20 [decision] Only the approved lesson chunks go into Snowflake (table + Cortex
  Search service). Poll evidence and student questions stay as input (from Redis in the
  real system); misconception map, remediations, protected questions stay local JSON;
  traces are loaded into Bronze later by the pipeline teammate.
- 2026-10-20 [todo] Check in docs: Cortex LLM availability and models in our US region,
  whether cross-region inference is needed, which role/grant enables Cortex, auth method
  for programmatic access (key pair likely), Cortex Search service creation syntax.
- 2026-10-20 [change] Account is a trial in `<account region>`, not a US
  region as CLAUDE.md planned.
- 2026-10-20 [finding] (docs, checked 2026-10-20) LLM function is `AI_COMPLETE(model,
  prompt, model_parameters, response_format, ...)`; `SNOWFLAKE.CORTEX.COMPLETE` is legacy,
  to be deprecated by end of 2026. `response_format` supports a JSON schema -> useful for
  Stage 3 structured replies.
- 2026-10-20 [finding] No `AI_COMPLETE` model appears to run natively in <account region>, so
  LLM calls need cross-region inference (`CORTEX_ENABLED_CROSS_REGION`, ACCOUNTADMIN only;
  likely already `AWS_US` or `ANY_REGION` by default for new orgs). Region table read from
  a flattened copy, so `00_check_account.sql` confirms it by running real calls.
- 2026-10-20 [finding] Cortex Search and its default embedding model
  (`snowflake-arctic-embed-m-v1.5`) run natively in the account region; the source table
  needs change tracking.
- 2026-10-20 [finding] Trial accounts have AI features disabled until a credit card is
  added (trial continues, credits still used).
- 2026-10-20 [finding] Access: `SNOWFLAKE.CORTEX_USER` database role (+ `USE AI FUNCTIONS`),
  both on PUBLIC by default. `CORTEX_MODELS_ALLOWLIST` is deprecated; do not use.
- 2026-10-20 [decision] Auth: key pair on a `TYPE=SERVICE` user (`CLASSPILOT_AGENT_SVC`).
  Password login is being phased out for programmatic users; PATs need a network policy
  and expire. Private key lives in `<key folder outside the repo>`, never in the repo.
- 2026-10-20 [decision] Object names: role `CLASSPILOT_AGENT_ROLE`, warehouse
  `CLASSPILOT_WH` (XS, auto-suspend 60 s), `CLASSPILOT_DEMO.AGENT`, table `LESSON_CHUNKS`,
  search service `LESSON_SEARCH` (target lag 1 day; content is static).
- 2026-10-20 [change] Added `sql/` (setup scripts 00-03) and `scripts/` (`load_chunks.py`,
  `smoke_test.py`, shared `snowflake_conn.py`). Not in the CLAUDE.md folder layout.
  Chunks are loaded from `content/lesson_chunks.json` so there is one source of truth.
- 2026-10-20 [change] Added `snowflake-connector-python` in Stage 2 (not Stage 3) as an
  optional extra `[snowflake]`, approved by the user. Mock mode and tests do not need it.
  The script loads the private key with `cryptography` and passes `private_key=` so it
  works across connector versions 4.x and 5.x.
- 2026-10-20 [question] Data residency: with cross-region inference, lesson text and
  student questions are processed in US regions. Fine for a synthetic demo; confirm with
  the team / professor before real student data.
- 2026-10-20 [todo] Stage 3: the Python Cortex Search API (`snowflake.core` `Root`) needs a
  Snowpark session; Snowpark may still require connector < 5.0. Check before adding it
  and pin the connector if needed.
- 2026-10-20 [todo] Not verified in docs: whether trial accounts can use or change
  cross-region inference, and whether Cortex Search is covered by the trial AI gate.
  `00_check_account.sql` and `03_search_service.sql` will show this.
- 2026-10-21 [finding] `AI_COMPLETE` needs an active warehouse ("No active warehouse
  selected"). `00_check_account.sql` now creates and uses `CLASSPILOT_WH` right after
  `USE ROLE`, before any query (Snowsight "Run All" stops at the first error, so a later
  `USE WAREHOUSE` may never run). Trial accounts also ship with `SNOWFLAKE_LEARNING_WH`
  (XS), which works too, but the demo uses its own warehouse to match `.env`.
- 2026-10-21 [finding] Usernames with a dot (e.g. `first.last123`) must be double-quoted
  with exact case in `GRANT ... TO USER "..."`; `01_setup_objects.sql` updated.
- 2026-10-21 [result] `00` ran: `AI_COMPLETE('claude-haiku-4-5', ...)` returned text, so
  Cortex LLM works from <account region> via cross-region inference (results for llama3.3-70b
  and mistral-large3 not checked individually; parameter value not yet recorded).
- 2026-10-21 [result] `01`, `02` and `load_chunks.py` done. `smoke_test.py` passed: key-pair
  login as `CLASSPILOT_AGENT_SVC`, region `<ACCOUNT_REGION>`, 5 rows in `LESSON_CHUNKS`.
- 2026-10-21 [finding] Connector 5.0.0 prints a FutureWarning about
  `enable_server_session_keep_alive_auto_detection` on connect. Harmless; revisit in
  Stage 3 when the adapter sets its connection options.
- 2026-10-21 [result] All three test models (`llama3.3-70b`, `mistral-large3`,
  `claude-haiku-4-5`) answer via `AI_COMPLETE` (checked by the user in Snowsight).
- 2026-10-21 [result] `03` created `LESSON_SEARCH`. `smoke_test.py --search` from Python:
  Bronze question -> chunk-01, chunk-02, chunk-03; "what does ref() do in a dbt model" ->
  chunk-04, chunk-05, chunk-02. Top hit correct for both. Stage 2 done criteria met.
- 2026-10-21 [todo] Stage 3: connector is already an optional extra (Stage 2), so the
  "add Snowflake package" item is only about the Search API (`snowflake.core` / Snowpark)
  if we use it; `SEARCH_PREVIEW` is documented as for testing, so check which query API
  the adapter should use.
- 2026-10-21 [finding] `CORTEX_ENABLED_CROSS_REGION = ANY_REGION` (new-org default; we did
  not change it). LLM prompts may be processed in any Snowflake region, not only the US.
  This updates the data-residency question above: still fine for synthetic demo content;
  if the team wants to limit it, `ALTER ACCOUNT SET CORTEX_ENABLED_CROSS_REGION = 'AWS_US'`
  (ACCOUNTADMIN). Team decision, not changed.

## Stage 3: Cortex adapters — DONE (2026-10-21)

Research and live probes came first, then the implementation (see "Implementation" below). Docs read 2026-10-21; "live" =
tested on our account (<account locator>, <account region>) with the connector and key pair. Probes
were one call each, so latencies are rough.

### LLM (`AI_COMPLETE`)
- 2026-10-21 [finding] (live) Model and prompt can be bind variables:
  `SELECT AI_COMPLETE(%s, %s)` works. The connector returns a JSON **string**
  (e.g. `'"ok"'`) -> `json.loads()`.
- 2026-10-21 [finding] (live) Structured output with the schema as a bind variable works:
  `AI_COMPLETE(model => %s, prompt => %s, model_parameters => {'temperature': 0},
  response_format => PARSE_JSON(%s))` returned `{"category": "in_scope", "confidence": 0.95}`
  with mistral-large3. So the schemas can live in Python, no SQL literals needed.
- 2026-10-21 [finding] (live) `return_error_details => TRUE` wraps the result as
  `{"value": {...}, "error": null}`.
- 2026-10-21 [finding] (docs) Every AI_COMPLETE model supports structured output.
  Unsupported schema keywords include number `minimum`/`maximum`, string
  `minLength`/`maxLength`/`format`, and array `minItems`/`maxItems`. So confidence 0-1 and
  "citations non-empty" must be checked in code (the final validator already does this).
  Enums, nesting, and `required` work; set `additionalProperties: false` + full
  `required` anyway (mandatory for OpenAI models, harmless otherwise).
  https://docs.snowflake.com/en/user-guide/snowflake-cortex/complete-structured-outputs
- 2026-10-21 [finding] (docs) On failure AI_COMPLETE returns NULL by default; some cases
  raise instead (e.g. a required field cannot be extracted). Adapter rule: NULL value,
  non-null `error`, or any exception -> `LLMError`.
  https://docs.snowflake.com/en/sql-reference/functions/ai_complete
- 2026-10-21 [finding] (docs) Timeouts: `cursor.execute(sql, params, timeout=N)` aborts the
  query after N s (`ProgrammingError`, errno 604 = canceled). Backstop:
  `ALTER SESSION SET STATEMENT_TIMEOUT_IN_SECONDS`. This lets Cortex calls be cancelled
  server-side, which helps the Stage 1 worker-thread note (a slow call no longer keeps
  running). `network_timeout`/`socket_timeout` are deprecated in connector 5.
  https://docs.snowflake.com/en/developer-guide/python-connector/python-connector-api
- 2026-10-21 [finding] (live) Latency of a trivial prompt: mistral-large3 ~1.2 s,
  llama3.3-70b ~1.6 s, claude-haiku-4-5 ~2.3 s; structured output (mistral-large3) ~2.4 s,
  ~3.9 s with error details.
- 2026-10-21 [finding] (docs) Context / max output: llama3.3-70b 128k / 8k,
  mistral-large3 256k / 32k, claude-haiku-4-5 200k / 64k. None is on the Aug 2026
  legacy/retirement list.
- 2026-10-21 [finding] (docs) Cost: billed in AI Credits per million input + output tokens
  ($2.00/credit with ANY_REGION routing), plus the warehouse while the query runs.
  Per-model rates are in the Credit Consumption Table PDF (not extracted; not verified).
  Actual usage: `SNOWFLAKE.ACCOUNT_USAGE.CORTEX_FUNCTIONS_QUERY_USAGE_HISTORY`.
- 2026-10-21 [finding] (docs) Alternative: Cortex REST API
  (`/api/v2/cortex/v1/chat/completions`, OpenAI-compatible), which the docs recommend for
  latency-sensitive use. It needs a self-signed key-pair JWT (PyJWT, a new dependency).
  Not needed for the demo; option for Stage 4 if SQL latency is too high.
  https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-rest-api
- 2026-10-21 [finding] (docs) Avoid `snowflake-ml-python` (`snowflake.cortex.complete`) and
  Snowpark: both require connector < 5 (PyPI metadata; pip dry-run confirmed the Snowpark
  conflict).

### Search (Cortex Search)
- 2026-10-21 [finding] (live) Results include `@scores` automatically:
  `cosine_similarity`, `text_match`, `reranker_score`. Do not list `@scores` in `columns`
  (error "not indexed"). Bronze question: chunk-01 cos 0.73 / reranker +3.06; chunk-02
  0.60 / -3.64; chunk-03 0.45 / -10.36. SEARCH_PREVIEW ~1.3 s.
- 2026-10-21 [finding] (docs) Score ranges: cosine -1..1; `text_match` and
  `reranker_score` unbounded, depend on the query. Option: map `RetrievedChunk.score` to
  `cosine_similarity` (bounded). Turning the reranker off saves ~100-300 ms.
  https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-search/cortex-search-customize-scoring
- 2026-10-21 [finding] (docs) SEARCH_PREVIEW is "not intended for serving search queries
  in an end-user application", accepts only string literals (no binds; must escape the
  student question into SQL), and is slower than the Python/REST APIs.
  https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-search/query-cortex-search-service
- 2026-10-21 [finding] (docs) Python API: `snowflake-core` ->
  `Root(conn).databases[db].schemas[sch].cortex_search_services[svc].search(query, columns,
  filter, limit)`. `Root` accepts a plain connector connection (no Snowpark).
  (pip dry-run) `snowflake-core` 1.13.2 resolves with connector 5.0.0; runtime not tested.
- 2026-10-21 [finding] (docs) Serving uses separate multi-tenant compute; the warehouse is
  for refresh. Serving is billed per GB-month of indexed data while the service is
  running, even without queries (tiny for 5 chunks). Can be suspended when idle.
  Rate limit 20 queries/s per service.
  https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-search/cortex-search-costs

### Open decisions for Stage 3
- 2026-10-21 [question] Search call path: (a) add `snowflake-core` (new dependency, needs
  approval; check runtime with connector 5 first), or (b) keep SEARCH_PREVIEW via the
  connector (no new dependency, "testing only", query escaped into SQL).
- 2026-10-21 [question] Default model for `settings.yaml` `llm.model`: mistral-large3 was
  fastest in the probe; llama3.3-70b and claude-haiku-4-5 also work. Can compare in Stage 4.
- 2026-10-21 [todo] Retrieval score: decide which `@scores` field fills
  `RetrievedChunk.score` (cosine is the only bounded one).

### Implementation
- 2026-10-21 [decision] User chose option (a): `snowflake-core` for search. Added to the
  `[snowflake]` extra with `snowflake-connector-python>=5`. (live) `snowflake-core` 1.13.2
  works at runtime with connector 5.0.0; `search()` ~150-300 ms vs ~1.3 s for
  SEARCH_PREVIEW.
- 2026-10-21 [decision] Default model `mistral-large3` (`settings.yaml`), per the user.
- 2026-10-21 [decision] `RetrievedChunk.score` = `@scores.cosine_similarity` (bounded).
  Not used in any decision yet.
- 2026-10-21 [change] Moved the connection helper from `scripts/snowflake_conn.py` to
  `src/agents_demo/adapters/snowflake.py` (Cortex code stays in `adapters/`); scripts
  import it. One shared connection per process (`shared_connection()`), closed at exit.
  Sets `enable_server_session_keep_alive_auto_detection=False` (silences the connector
  5 FutureWarning; we never leave async queries running).
- 2026-10-21 [decision] `CortexLLM`: `AI_COMPLETE` with model, prompt, and JSON schema
  bound as `%s`; `temperature 0`, `max_tokens 1024`, `return_error_details => TRUE`.
  NULL / `error` / non-object / exception -> `LLMError`. Query timeout =
  `llm.timeout_seconds` (whole seconds, min 1) so Snowflake cancels slow calls; the
  existing thread timeout in `call_llm` still applies. Schemas (`TASK_SCHEMAS`) mirror the
  pydantic contracts; a test checks they stay in sync.
- 2026-10-21 [finding] (live) Nullable fields work in the schema: both
  `"type": ["string", "null"]` and `anyOf` returned `null` for `objective_id`.
- 2026-10-21 [change] Retrieval errors used to crash the graph (the mock never fails).
  Added `RetrievalError`. The responder catches it and returns an error without calling
  the LLM, so the graph escalates. The trace counts `llm_calls` correctly.
  Escalation reason is `llm_error`, because the contract has no `retrieval_error`.
  [question] Add `retrieval_error` to the decision contract? That is a contract change,
  so confirm with the team in Stage 5.
- 2026-10-21 [result] 72 tests pass. All of them use mocks or fakes.
- 2026-10-21 [result] Done criterion met: scenarios 02-05 with `BACKEND=cortex` in mode 2 and 3
  all produce valid decisions + traces (`backend: cortex`). One run each, exploratory:
  - 02 in scope: answer, cites chunk-01, conf 1.0. Total 4.1 s (mode 2) / 3.9 s (mode 3).
    Per call ~1.0-2.1 s, retrieval ~0.25 s.
  - 03a out of scope: escalate (analyst), ~2 s. 03b assignment: escalate by rule, 0 calls.
  - 04a timeout (0.5 s override): escalate `llm_error` at ~0.5 s, no hang.
  - 04b DIFF: expected `low_confidence`, got `out_of_scope`. The analyst says "snapshots
    for SCD" is not in the lesson objectives. Still escalated, but for a different
    reason; defensible, since the objectives don't mention snapshots.
  - 05 DIFF: the real responder is more honest than the mock. Twice it said "the chunks
    do not cover Kafka" with conf 0.2-0.3, which escalates. In one mode-3 run, however,
    it answered with conf 0.9 citing chunk-01, and the Guardian passed it. This is
    non-deterministic even at temperature 0. The answer text of that run was not
    captured (it is not in the trace).
- 2026-10-21 [todo] Stage 4: the scenario `expected` values and the eval labels were written
  for the mock. Decide whether 04b/05 expectations stay as they are (mock-only) or get
  backend-specific expectations. Also look at the 05 mode-3 "answer" case: repeat it
  several times and record answer_text.
- 2026-10-21 [change] Added `interface_questions.md`. Contracts in CLAUDE.md are drafts;
  the team agrees on real interfaces after each part's demo. Items Q-01 to Q-10 cover
  the open questions so far (incl. the Stage 1 hint question and the Stage 3
  `retrieval_error` question). CLAUDE.md now says to keep the file updated.
- 2026-10-21 [decision] Q-01: keep `llm_error` for search failures for now (user).
- 2026-10-21 [todo] Stage 4: retrieval has no timeout (the mock never needed one). Cortex
  Search took ~0.25 s, but add a bound if it ever hangs.

## Stage 4: Real-model eval and tuning

- 2026-10-21 [change] `cli eval` output names now include the backend
  (`outputs/eval_<backend>_mode<N>.json`, `eval_traces_<backend>_mode<N>.jsonl`), so mock
  and Cortex results do not overwrite each other. `report` still uses the old names
  (to be updated with the report wording item).
- 2026-10-21 [change] Eval rows have a `details` field with the raw analyst / responder /
  guardian outputs and LLM errors (`run_question(..., details=)`). This is eval output only;
  the trace contract is unchanged (Q-08 is still open).
- 2026-10-21 [result] First Cortex eval (mistral-large3, one run per mode, prompts and
  thresholds unchanged from Stage 3). Exploratory:
  - Both modes: 11/11 correct action, escalation recall 1.0, 0 unsupported answers let
    through, 0 false escalations. LLM calls per question 1.45 (mode 2) / 2.18 (mode 3).
  - Latency per node (median, min-max): analyst 1.0-1.2 s (0.8-2.1), retrieval 0.16-0.19 s
    (0.12-0.36), responder 1.5-1.7 s (1.2-2.7), guardian 1.2 s (0.9-1.7).
  - Total per question, median: 2.3 s (mode 2) / 4.2 s (mode 3), over all questions.
    Answered questions only: 3.6 s (max 4.2) / 4.6 s (max 6.2). The Guardian adds ~1.2 s.
- 2026-10-21 [finding] The real responder does not fill gaps the way the mock does. For
  tq-09/10/11 it says "the chunks do not cover X" with confidence 0.1-0.3, so the
  confidence threshold escalates them. The Guardian passes these "not covered" answers
  (correctly: they are supported), so in this run it caught nothing. The eval set
  cannot show the Guardian's value with the real model yet.
- 2026-10-21 [finding] All actions match, but 4 escalation reasons differ from the
  mock-based labels: tq-10/11 `low_confidence` (label `unsupported`); tq-09 `out_of_scope`
  in mode 2 (analyst: snapshots are not in the objectives) but `unsupported` in mode 3
  (analyst said in_scope, responder cited nothing). So the analyst is not stable on
  tq-09 between runs, even at temperature 0. The summary only scores the action.
- 2026-10-22 [finding] Kafka question (scenario 05 input) 5x in mode 3 on Cortex: all
  escalated (conf 0.2-0.3), the Stage 3 conf-0.9 answer did not come back. But the old
  Guardian passed all 5, including two with no citations at all and one that added
  "including streaming sources" (not in chunk-01). The Guardian was too lenient.
- 2026-10-22 [change] Added `eval/guardian_cases.json` (12 hand-written question / answer /
  cited-chunk cases: 4 should pass, 8 should fail; gc-06 is a real Cortex answer) and
  `cli guardian-eval`, which sends them straight to the Guardian. This measures the
  Guardian's catch rate without waiting for the responder to make a mistake.
- 2026-10-22 [result] Baseline (old Guardian, Cortex): caught 3/8, 0 false fails. Missed
  even gc-05 (an invented Spark sentence), plus "true but not in the chunks" (gc-07/08),
  the real answer gc-06, and the A1-Q4 giveaway gc-12. Saved as
  `outputs/guardian_eval_cortex_baseline.json`.
- 2026-10-22 [decision] User: no risk-based Guardian gating (option B); never skip a case
  that should be checked. Make the Guardian stricter instead.
- 2026-10-22 [change] Stricter Guardian. The prompt asks for every claim plus the cited
  chunk that states it (null if none), with explicit rules: only cited chunks count,
  "true in general" is not supported, a chunk that only names a term does not support an
  explanation of it. New output fields `claims` and `reveals_graded_work`
  (`GuardianOutput` and `TASK_SCHEMAS`). The pass/fail call moved into code:
  `rules.check_guardian` fails if the verdict is fail, graded work is revealed, the claim
  list is empty, or any claim's chunk is null or not cited. So an LLM "pass" next to an
  unsupported claim still fails. Old-schema output -> `llm_error`.
- 2026-10-22 [change] Option A (user approved): `rules.check_response` (citations exist and
  were retrieved, `grounded`, confidence >= threshold) runs before the Guardian. If it
  already escalates, the graph goes straight to the validator. Closes the Stage 1 todo.
  Two side effects: mode 3 now also escalates on `grounded=false` (before, only mode 2
  did), and a low-confidence answer in mode 3 now gets `low_confidence` instead of
  `unsupported`. Allowed values are unchanged.
- 2026-10-22 [result] New Guardian, Cortex, 3 runs of guardian-eval: caught 8/8, 8/8, 7/8.
  0 false fails in all three. The 7/8 run was not a miss: gc-06 timed out at 10 s ->
  error, which escalates in the graph (fail-closed). The code rule never had to overrule
  an LLM "pass" (the LLM was consistent with its own claim list), but it stays as a
  backstop. Full eval: both modes still 11/11, 0 false escalations. Mode 3 LLM calls
  24 -> 20 (1.82 per question; tq-09/10/11 skip the Guardian).
- 2026-10-22 [finding] The claim list makes the Guardian slower: avg 1.3 s -> 2.1-2.6 s
  per call in guardian-eval; in the eval, 1.5-1.8 s for three answers, but 5.2 s for
  tq-04. One timeout (10 s) in ~40 Guardian calls. Answered questions in mode 3 now take
  4.4-7.6 s in total.
- 2026-10-22 [todo] Decide on `llm.timeout_seconds` for the Guardian (keep 10 s and
  accept rare fail-closed escalations, or raise it); shared setting, so ask first.
- 2026-10-22 [change] Report simplified (user): `cli report` now runs every scenario live
  (poll scenarios once, question scenarios in mode 2 and 3) and shows one table, mode 2
  next to mode 3. Eval sections, findings cards and example JSON were removed; eval stays
  in `cli eval` / `cli guardian-eval` JSON files. Colors: green = as expected, yellow =
  right action but a different reason (mock-written expectations), red = wrong action.
  The CLI prints each result while it runs. Cortex run: ~26 s, no red; 04b (both modes)
  and 05 (mode 3) yellow.
- 2026-10-22 [question] CLAUDE.md's Stage 4 done criterion ("the report answers all four
  demo questions") no longer fits the simplified report. The answers to the four questions
  are in this file. Update the criterion, or put them in the README?
  -> [decision] User: drop that criterion. New criterion: Cortex eval + Guardian results in
  this file, and the report shows live mode 2 / 3 scenario results. Met.
- 2026-10-22 [decision] Default agent mode is now 3 (user: do not miss anything that should
  be caught). Changed in `settings.yaml`, the `Settings` code default, the `cli eval`
  default, `.env.example`, and CLAUDE.md. `run-all` without `--mode` now passes all 9
  scenarios on mock (05 used to show MISMATCH under the mode-2 default).
- 2026-10-22 [finding] Poll scenarios (01/01b/01c) run once in the report: Path A is
  rules only, `agent_mode` only changes Path B. The report now says so in that row.
- 2026-10-22 [change] Added Q-11 to `interface_questions.md` (how long a student waits;
  the front end needs a waiting state and a timeout longer than the agent's fallback).
- 2026-10-22 [finding] Decisions are never written to a file; only traces are, and traces
  carry just `action` from the decision (no session, reason, remediation, answer). Added
  Q-12 (store decisions as their own JSONL vs. merge into the trace). Also noted in Q-09
  that `input_ref = question-07@...` (poll) is easy to confuse with student `evt-...` ids.
- 2026-10-22 [todo] Advanced features, deferred by the user (not in scope now):
  (1) spread-out wrong answers: no single wrong option reaches 60% (e.g. B 40% / C 40%), so
  the poll rule says `continue` even when most of the class is wrong; (2) many students
  typing similar questions: each is handled alone, nothing notices a shared confusion.
  Both are design changes; any future handling must still use pre-approved branches or
  escalate, never an LLM-written reteach.
- 2026-10-22 [change] Added `ARCHITECTURE.html` in the project root (user request): system
  context, Path A and Path B flow diagrams, Snowflake objects, outputs, repo map, open
  items. Static HTML with inline SVG; update it when the flow or contracts change.
- 2026-10-22 [change] Added `DEMO_OVERVIEW.html` (user request): one simple diagram to show
  before the live demo. Front end + backend drawn as one "mock input" box (scenarios JSON),
  then the two LangGraph paths, outcomes, and the three LLM nodes' link to Cortex.
  `ARCHITECTURE.html` stays as the fuller version.
- 2026-10-22 [result] Stage 4 done. Deferred to a later quality pass: model choice /
  per-node models, `confidence_threshold` and protected-similarity tuning, Guardian
  timeout, the 6 "tempting" end-to-end questions, mock-written eval labels.
- 2026-10-22 [todo] The 6 "tempting" questions for `test_questions.json` (end-to-end with the real
  responder) are not added yet. guardian_cases covers the Guardian alone.

## Stage 5: Team handoff
