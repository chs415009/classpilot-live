# Interface questions for the team

Interfaces between the three parts (front end + live state, data pipeline, agent):
only what another part reads or sends. The agent side moves first, so it decides the
items it can settle, implements them (`src/classpilot/contracts/`), and records the
decision here with status `decided`. Teammates review these and reopen any item they
need changed; agent-internal formats are not listed here.

Numbering starts at Q-13: Q-01 to Q-12 were v1 items, archived in
`docs/v1/interface_questions_v1.md` and not carried into v2.

Each item records:
1. **Current approach**: what the agent side does now or proposes.
2. **Why change**: the problem or cost with the current approach.
3. **Suggested direction**: the proposal that led to the decision.

Status: `open` (needs input from another part), `decided` (decided by the agent side
and implemented or planned for a named stage; written under the item), `agreed`
(confirmed by the team), `deferred` (not built for now; decided later), `dropped`. A `decided` item is not final: any teammate can
reopen it by writing what they need changed under it. Newest items at the bottom.
Details and history stay in `docs/agent/note.md`.

---

## Q-13 Manifest format and versioning
- **Status:** decided · **Area:** manifest · **Affects:** front end (Sai), pipeline (Yaksha) · **Raised:** 2026-11-04
- **Current approach:** The team's existing manifest structure, with only `new` / `changed` fields (IMPLEMENTATION_NOTES section 5): `params`, `slides` keyed by system slide ids `<source>-p<NN>`, `correct_option`, `known_wrong` for every wrong option, remediations of type `tts_explanation` with `text`, `show_slide`, chunk-id `citations`, and a `status` per item. No correct-answer explanation and no `quality` field (the report counts statuses).
- **Why change:** The team structure had no generated content, no status, and human-chosen ids.
- **Suggested direction:** Agree the `new` / `changed` fields. Dropped polls stay in `questions` with `status: "dropped"`; `active_poll` points to another question or is `null`, and the front end reads only `active_poll`. Decide whether the manifest needs a version number.
- **Decision (agent side, 2026-11-04):** The section 5 structure, implemented in `contracts/manifest.py` (fixture `content/manifest.json`). The front end can rely on `active_poll`: it is `null` when a segment has no questions or only dropped ones, otherwise it names a question that is not dropped. No version field for now: a manifest is regenerated per lesson, and a `manifest_version` is added only if the structure changes after the front end reads it.
- **Update (agent side, 2026-11-05, Stage 6):** Generated manifests (`prep run` / `prep generate`) follow this. **The front end reads only `active_poll`**: a poll that failed its checks stays in `questions` with `status: "dropped"`, so the report can count it, but it may have empty `text` / `options` and always has `known_wrong: {}`; never show it. At most one question per segment and at most `poll_count` active polls. Slide `image_ref` is `slides/<slide_id>.png`, served by the prep service (Q-18, Stage 8). Example: `tests/fixtures/deck/manifest_mock.json` (mock content).
- **Update (agent side, 2026-11-06, Stage 9):** `known_wrong` may now leave out a wrong option whose explanation failed its checks before class (it can even be `{}` for a poll in use); before, such a failure dropped the whole poll, and in Stage 7 every poll was dropped. Nothing changes for the front end: it still sends poll evidence and plays what the decision returns; when the most chosen wrong option has no explanation, the decision is `reveal` (no `remediation_text` or `show_slide`).

## Q-14 Poll path: action values, evidence fields, explain payload
- **Status:** decided · **Area:** poll input, decision output · **Affects:** front end / backend (Sai), pipeline · **Raised:** 2026-11-04
- **Current approach (draft):** Actions `explain` / `reveal` replace `reteach` / `continue`. Poll evidence adds `poll_id` and drops `remediations_used`. On `explain`, the decision returns the option, the misconception and remediation ids, the remediation `text`, and `show_slide`; on `reveal`, the correct option.
- **Why change:** v2 has no remediation branches or limits; the front end needs the text and slide to play.
- **Suggested direction:** Agree the field names. Each poll triggers at most once: the backend calls the rule once per poll (an endpoint guard on (`session_id`, `poll_id`) may be added in Stage 8 if trivial).
- **Decision (agent side, 2026-11-04):** Poll evidence carries `lesson_id` (as the question does, Q-19), and the agent loads that lesson's manifest; the rule uses the manifest `params`. The agent keys on `poll_id`; `question_id` stays because the team README has it, and the agent ignores it. Decision fields: `decision_id`, `session_id`, `path`, `action`, `poll_id`, `option` (the wrong option explained), `misconception_id`, `remediation_id`, `remediation_text`, `show_slide`, `correct_option` (on explain and reveal), plus the question-path fields; unused fields are `null`. Evidence that does not fit the manifest is a request error, not a decision: 404 for an unknown or dropped `poll_id`, 422 for another lesson or a different `correct_option` (Stage 8). The Stage 8 endpoint returns the stored decision again for a repeated (`session_id`, `poll_id`), so a poll never triggers twice.

## Q-15 Removed decision values
- **Status:** decided · **Area:** decision output · **Affects:** front end, pipeline (accepted values) · **Raised:** 2026-11-04
- **Current approach (draft):** `remediation_limit` and `no_mapping` escalation reasons and the decision field `remediation_id` are removed. The 5 remaining reasons are `out_of_scope`, `assignment_like`, `low_confidence`, `unsupported`, `llm_error`.
- **Why change:** Path A no longer escalates.
- **Suggested direction:** Update dbt `accepted_values` tests and front-end handling.
- **Decision (agent side, 2026-11-04):** Implemented: `Action` is `explain | reveal | answer | escalate`, and these 5 reasons are the only ones the code produces. The dbt `accepted_values` tests should use these values.

## Q-16 What escalation means in class, and where escalated questions go
- **Status:** decided · **Area:** decision output · **Affects:** front end (Sai), professor · **Raised:** 2026-11-04
- **Current approach (draft):** Escalate = the student sees "saved for the professor"; the question is stored in the agent's decision log and appears, grouped, in the post-class report.
- **Why change:** In v1 escalation meant handing the question to a live professor, who is not there in v2.
- **Suggested direction:** Agree the student-facing message and that the decision log is the store.
- **Decision (agent side, 2026-11-04):** Escalated questions are stored in the agent's decision log and listed, grouped by `escalation_reason`, in the post-class report. Suggested student message (the front end owns the wording): "Good question. It is saved for your professor and will be answered after class."

## Q-17 Table names for parse output
- **Status:** decided · **Area:** Snowflake tables · **Affects:** pipeline (Yaksha) · **Raised:** 2026-11-04
- **Current approach (draft):** The prep service writes stage `@RAW_MATERIALS`, `RAW_FILES`, `PARSED_PAGES`, and `LESSON_CHUNKS_V2` (key `lesson_id` + `chunk_id`; chunks of a file shared across lessons are copied per lesson). Generated content stays in the manifest; prep runs are not written to the data model.
- **Why change:** Names must not clash with Yaksha's Bronze/Silver/Gold models.
- **Suggested direction:** Agree names and schema; Yaksha's dbt does not build these tables.
- **Decision (agent side, 2026-11-04):** The names above. The prep service creates and writes them (SQL shown before it runs, Stage 5); the pipeline's dbt does not build or write them.
- **Update (agent side, 2026-11-05, Stage 5):** Created by `sql/04_parse_objects.sql`, columns there. `RAW_FILES` key (`LESSON_ID`, `FILE_ID`); `PARSED_PAGES` key (`FILE_ID`, `PAGE_INDEX`, 1-based), lesson-independent; `LESSON_CHUNKS_V2` key (`LESSON_ID`, `CHUNK_ID`), text column `CHUNK_TEXT`, `ORIGIN` `text_layer | llm_description`. Search service `LESSON_SEARCH_V2` (`sql/05`) filters on `LESSON_ID`. Names are configurable (`config/settings.yaml` `objects`).

## Q-18 Prep service API and slide image delivery
- **Status:** decided · **Area:** HTTP API · **Affects:** front end (Sai) · **Raised:** 2026-11-04
- **Current approach (draft):** Endpoints in IMPLEMENTATION_NOTES section 3 (lessons, files, process, jobs, manifest, slides by slide id). Slide PNGs and the manifest are served from the prep service's local disk; job state is in memory.
- **Why change:** New service; nothing agreed yet.
- **Suggested direction:** Agree request/response shapes, the upload size limit, and the CORS origin.
- **Decision (agent side, 2026-11-04):** The endpoints in IMPLEMENTATION_NOTES section 3; the agent side fixes the exact shapes in Stage 8 and documents them here. The allowed CORS origin and the upload size limit are settings, so the front end only needs to tell us its origin.
- **Update (agent side, 2026-11-05, Stage 8): implemented** in `src/classpilot/service/` (models in `service/schemas.py`; run with `uvicorn classpilot.service.app:create_app --factory`). Errors are `{"detail": "<message>"}`.
  - `POST /lessons` body `{"lesson_id"?: "info6205-l1", "title"?: "..."}` (id: lowercase letters, digits, `-`; generated as `lesson-<8 hex>` if left out) → 201 `Lesson` `{lesson_id, title, created_at, files: [LessonFile], has_manifest, last_job_id}`; 409 if the id exists.
  - `GET /lessons/{id}` → `Lesson`; 404.
  - `POST /lessons/{id}/files` multipart: `kind` = `slides` (pptx, pdf) or `reference` (pdf, docx), `file` → 201 `LessonFile` `{file_id (SHA-256), name, kind, format, size_bytes, reused}`. `reused: true` means these bytes were uploaded or parsed before (no parse cost). 415 for a wrong extension or content, 413 over `service.max_upload_mb` (100), 404 for no lesson; nothing is stored on an error. The same name or bytes again replaces the entry.
  - `POST /lessons/{id}/process` body `{"poll_count"?: 0-20}` (default 5) → 202 `{job_id, lesson_id, status: "queued"}`; 409 without slides or while a job of the lesson runs.
  - `GET /jobs/{job_id}` → `{job_id, lesson_id, status: queued|running|done|failed, step, steps: [...], progress: {done, total, detail}, poll_count, failures: [{item, status: fallback|dropped, detail, problems}], error, created_at, started_at, ended_at, llm_calls}`. Steps in order: `queued, converting, uploading, parsing, chunking, generating, checking, assembling, done` (or `failed` with `error`). `progress` counts files, then pages while parsing (e.g. 12/40), then generated items. Poll it every 1-2 s. Jobs live in memory (lost on restart).
  - `GET /lessons/{id}/manifest` → the manifest (Q-13); 404 until a job is done. A failed job keeps the previous manifest.
  - `GET /lessons/{id}/slides/{slide_id}` (`.png` optional) → `image/png`; 404. `image_ref` in the manifest is `slides/<slide_id>.png`, so the URL is `/lessons/{id}/` + `image_ref`.
  - CORS origins: `service.cors_origins` in `config/settings.yaml` (now `http://localhost:3000`, `http://localhost:5173`). **Sai: tell us the real origin.**
- **Update (agent side, 2026-11-06, Stage 11): one zip for class.** The interface stays small so the front end can be built freely: everything a class needs is the manifest plus the slide PNGs, and the prep service holds no live state. `GET /lessons/{id}/bundle` → `application/zip` with `manifest.json` and `slides/<slide_id>.png` (the manifest's `image_ref` paths); 404 without the lesson or its manifest. Fetch it once after the job is `done` and store it however the front end likes (Redis, disk, CDN); `GET /manifest` and `GET /slides/...` stay for single files. What the front end reads: `slides` (order, `image_ref`, `script` for TTS) and each segment's `active_poll` (text, options, `correct_option`). Explanations are not read from the manifest: the poll decision returns them (Q-19). **Sai: tell us if you need anything else in the bundle.**

## Q-19 Live endpoints: student question and poll result
- **Status:** decided · **Area:** HTTP API · **Affects:** front end / backend (Sai) · **Raised:** 2026-11-04
- **Current approach (draft):** `POST /questions` (one question → answer or escalate decision) and `POST /polls/result` (poll evidence → explain / reveal), both on the agent service. The poll rule is a plain function; no LLM in the poll path.
- **Why change:** v1 had no HTTP interface.
- **Suggested direction:** Agree paths, payloads, and timeouts. The front end needs a waiting state: v1 measured about 4–8 s for answered questions, and the worst case is roughly the sum of the per-call timeouts (about 30 s). The question payload needs the lesson for the retrieval filter: proposed `lesson_id` in the question (or the agent maps `session_id` to a lesson).
- **Decision (agent side, 2026-11-04):** `POST /questions` and `POST /polls/result` as above. `StudentQuestion.lesson_id` is required, and retrieval always filters on it (mock and Cortex Search `{"@eq": {"LESSON_ID": ...}}`). The agent always answers within the sum of its per-call timeouts (about 30 s); the front end shows a waiting state until then.
- **Update (agent side, 2026-11-05, Stage 8): implemented.** Both take and return the contracts in `.claude/rules/agent.md` (examples there) and `contracts/live.py`.
  - `POST /questions` body `StudentQuestion` → 200 `Decision` with `action` `answer` or `escalate`. An LLM timeout or error is a 200 `escalate` with `escalation_reason: "llm_error"`, never a 5xx. 404 if the lesson has no manifest; 422 for a malformed body.
  - `POST /polls/result` body `PollEvidence` → 200 `Decision` with `action` `explain` (`option`, `misconception_id`, `remediation_id`, `remediation_text` for TTS, `show_slide` to display, `correct_option`) or `reveal` (`correct_option`). 404 for an unknown lesson or poll, or a dropped one; 422 when `correct_option` differs from the manifest. The same (`session_id`, `poll_id`) again returns the first decision unchanged and is not traced twice (kept in memory).
  - Every decision appends its trace records to `<service.data_dir>/traces.jsonl` and one line to `decision_log.jsonl` (Q-21).
- **Update (agent side, 2026-11-06, Stage 11): stateless calls, repeats are safe.** The agent service never reads or writes the front end's Redis or WebSocket; queueing, routing the answer to the student, and the class pace (pausing for an explanation, then revealing the answer and resuming) are the front end's choice. Each call is one request and one decision. `POST /questions` now also guards repeats: the same (`session_id`, `event_id`) returns the first decision without new LLM calls or a second trace, and a repeat sent while the first is still running waits for it. Both guards (questions and polls) are rebuilt from `decision_log.jsonl` on start, so they survive a restart. `event_id` is the identity of a question: give each new question a new id. Timeouts: the agent answers within about 30 s (sum of the per-call timeouts; L1 runs: 1-15 s); set the client timeout to about 35 s and keep the student's waiting state until then. One `session_id` = one class session (the pipeline's BATCH); the front end creates it.

## Q-20 Post-class report: trigger and data source
- **Status:** deferred · **Area:** HTTP API, report · **Affects:** front end / backend (Sai), pipeline (Yaksha) · **Raised:** 2026-11-04
- **Current approach (draft):** Sai's backend calls `POST /sessions/{id}/report` at session end; `GET /sessions/{id}/report` returns the HTML page; a CLI command does the same. Inputs: the agent's decision log (text), traces, poll evidence, manifest status values. No LLM summary.
- **Why change:** The report reads text that Yaksha's Gold tables do not hold.
- **Suggested direction:** Agree the endpoint and that the report does not read Gold tables.
- **Decision (agent side, 2026-11-04):** As above: the report endpoint and the CLI read the agent's decision log, traces, and manifest statuses, not Gold tables (Stage 10).
- **Update (agent side, 2026-11-06): deferred** (user decision). The post-class report is not built for now, and no report endpoint exists. Who builds it, and from which tables (likely the pipeline's Gold tables, after all prep and live data is collected), is decided later; the decision above no longer stands. The agent side keeps its data complete: trace records (Q-21), the decision log with question and answer text (`decision_log.jsonl`, one entry per decision), and the manifest statuses (Q-13). Nothing changes for the front end or the pipeline now.

## Q-21 Trace records for the star schema
- **Status:** decided · **Area:** trace output · **Affects:** pipeline (Yaksha) · **Raised:** 2026-11-04
- **Current approach (draft):** Trace JSONL with run, node, LLM-call, retrieval, claim, and poll-evidence records (IMPLEMENTATION_NOTES 6.3). Removed: scenario key, assignment key, max reteach, matches-expected count, support score, is-approved, token counts. `BATCH` = one class session; prompt version = compiled DSPy program id or `uncompiled-v1`.
- **Why change:** The trace is the only source of Yaksha's model.
- **Suggested direction:** Agree exact field names and record types; Stage 2 implements them as drafts with a contract test.
- **Decision (agent side, 2026-11-04):** `contracts/trace.py`, described in IMPLEMENTATION_NOTES 6.3 with examples in `.claude/rules/agent.md`. One file `outputs/traces.jsonl` with a `record_type` per line (`run`, `node`, `llm_call`, `retrieval`, `claim`, `poll_evidence`). Common fields: `schema_version` (`v2-draft`), `run_id` (= decision id), `session_id` (= BATCH), `created_at`. Claim `supporting_chunk_id` is `null` instead of `-1` (chunk ids are strings). Nodes that did not run get a `skip` row. `deciding_node` = the first node that blocked or failed. The run record also has `llm_call_count` (added in Stage 3). `poll_evidence` has `is_correct` and a nullable `connected_students` per option row. Query and claim text appear only as 16-hex sha256 hashes. `similarity_score` is cosine in Cortex and word overlap in mock runs, and mock runs have `model: "mock"`. A rename request from the pipeline side is cheap: one module and its contract test.

## Q-22 Session data for the post-class report
- **Status:** decided · **Area:** HTTP API, data handoff · **Affects:** pipeline (Yaksha) · **Raised:** 2026-11-06
- **Current approach:** The post-class report is deferred (Q-20) and will most likely be built from the pipeline's tables. The agent side only hands over its data: the trace records (Q-21) are the source of the star schema; the decision log holds the text the Gold tables do not (question, answer, citations, escalation reason, explanation text); the manifest holds each generated item's `status` and the generation report the prep checks.
- **Why change:** Before, the only way to get the data was to read the service's local JSONL files, which mix every session.
- **Suggested direction:** One pull per session after class, plain files, and the pipeline chooses how to load them.
- **Decision (agent side, 2026-11-06, Stage 11):** `GET /sessions/{session_id}/export` → `application/zip` (404 if the session has no decision); the CLI `export <session_id>` writes the same zip. Contents: `export.json` (`schema_version`, `session_id`, `exported_at`, `lessons`, counts of decisions, questions, polls, trace records, and the file list), `traces.jsonl` (this session's trace records, Q-21), `decision_log.jsonl` (one `DecisionLogEntry` per decision: the decision plus the question or the poll evidence, `contracts/trace.py`), and `lessons/<lesson_id>/manifest.json` and `generation_report.json` for each lesson the session used. Reason: JSONL loads straight into a stage and Bronze tables; one zip per session matches `BATCH`; pulling any time after class needs no end-of-session call, and repeating it is harmless. The agent side does not write into the pipeline's tables or stages. **Yaksha: tell us how you will load it (e.g. PUT to a stage and COPY INTO), and whether you need the prep data (manifest statuses, generation report) in the model.**
