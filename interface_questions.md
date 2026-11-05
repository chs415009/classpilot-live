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
(confirmed by the team), `dropped`. A `decided` item is not final: any teammate can
reopen it by writing what they need changed under it. Newest items at the bottom.
Details and history stay in `docs/agent/note.md`.

---

## Q-13 Manifest format and versioning
- **Status:** decided · **Area:** manifest · **Affects:** front end (Sai), pipeline (Yaksha) · **Raised:** 2026-11-04
- **Current approach:** The team's existing manifest structure, with only `new` / `changed` fields (IMPLEMENTATION_NOTES section 5): `params`, `slides` keyed by system slide ids `<source>-p<NN>`, `correct_option`, `known_wrong` for every wrong option, remediations of type `tts_explanation` with `text`, `show_slide`, chunk-id `citations`, and a `status` per item. No correct-answer explanation and no `quality` field (the report counts statuses).
- **Why change:** The team structure had no generated content, no status, and human-chosen ids.
- **Suggested direction:** Agree the `new` / `changed` fields. Dropped polls stay in `questions` with `status: "dropped"`; `active_poll` points to another question or is `null`, and the front end reads only `active_poll`. Decide whether the manifest needs a version number.
- **Decision (agent side, 2026-11-04):** The section 5 structure, implemented in `contracts/manifest.py` (fixture `content/manifest.json`). The front end can rely on `active_poll`: it is `null` when a segment has no questions or only dropped ones, otherwise it names a question that is not dropped. No version field for now: a manifest is regenerated per lesson, and a `manifest_version` is added only if the structure changes after the front end reads it.

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

## Q-18 Prep service API and slide image delivery
- **Status:** decided · **Area:** HTTP API · **Affects:** front end (Sai) · **Raised:** 2026-11-04
- **Current approach (draft):** Endpoints in IMPLEMENTATION_NOTES section 3 (lessons, files, process, jobs, manifest, slides by slide id). Slide PNGs and the manifest are served from the prep service's local disk; job state is in memory.
- **Why change:** New service; nothing agreed yet.
- **Suggested direction:** Agree request/response shapes, the upload size limit, and the CORS origin.
- **Decision (agent side, 2026-11-04):** The endpoints in IMPLEMENTATION_NOTES section 3; the agent side fixes the exact shapes in Stage 8 and documents them here. The allowed CORS origin and the upload size limit are settings, so the front end only needs to tell us its origin.

## Q-19 Live endpoints: student question and poll result
- **Status:** decided · **Area:** HTTP API · **Affects:** front end / backend (Sai) · **Raised:** 2026-11-04
- **Current approach (draft):** `POST /questions` (one question → answer or escalate decision) and `POST /polls/result` (poll evidence → explain / reveal), both on the agent service. The poll rule is a plain function; no LLM in the poll path.
- **Why change:** v1 had no HTTP interface.
- **Suggested direction:** Agree paths, payloads, and timeouts. The front end needs a waiting state: v1 measured about 4–8 s for answered questions, and the worst case is roughly the sum of the per-call timeouts (about 30 s). The question payload needs the lesson for the retrieval filter: proposed `lesson_id` in the question (or the agent maps `session_id` to a lesson).
- **Decision (agent side, 2026-11-04):** `POST /questions` and `POST /polls/result` as above. `StudentQuestion.lesson_id` is required, and retrieval always filters on it (mock and Cortex Search `{"@eq": {"LESSON_ID": ...}}`). The agent always answers within the sum of its per-call timeouts (about 30 s); the front end shows a waiting state until then.

## Q-20 Post-class report: trigger and data source
- **Status:** decided · **Area:** HTTP API, report · **Affects:** front end / backend (Sai), pipeline (Yaksha) · **Raised:** 2026-11-04
- **Current approach (draft):** Sai's backend calls `POST /sessions/{id}/report` at session end; `GET /sessions/{id}/report` returns the HTML page; a CLI command does the same. Inputs: the agent's decision log (text), traces, poll evidence, manifest status values. No LLM summary.
- **Why change:** The report reads text that Yaksha's Gold tables do not hold.
- **Suggested direction:** Agree the endpoint and that the report does not read Gold tables.
- **Decision (agent side, 2026-11-04):** As above: the report endpoint and the CLI read the agent's decision log, traces, and manifest statuses, not Gold tables (Stage 10).

## Q-21 Trace records for the star schema
- **Status:** decided · **Area:** trace output · **Affects:** pipeline (Yaksha) · **Raised:** 2026-11-04
- **Current approach (draft):** Trace JSONL with run, node, LLM-call, retrieval, claim, and poll-evidence records (IMPLEMENTATION_NOTES 6.3). Removed: scenario key, assignment key, max reteach, matches-expected count, support score, is-approved, token counts. `BATCH` = one class session; prompt version = compiled DSPy program id or `uncompiled-v1`.
- **Why change:** The trace is the only source of Yaksha's model.
- **Suggested direction:** Agree exact field names and record types; Stage 2 implements them as drafts with a contract test.
- **Decision (agent side, 2026-11-04):** `contracts/trace.py`, described in IMPLEMENTATION_NOTES 6.3 with examples in `.claude/rules/agent.md`. One file `outputs/traces.jsonl` with a `record_type` per line (`run`, `node`, `llm_call`, `retrieval`, `claim`, `poll_evidence`). Common fields: `schema_version` (`v2-draft`), `run_id` (= decision id), `session_id` (= BATCH), `created_at`. Claim `supporting_chunk_id` is `null` instead of `-1` (chunk ids are strings). Nodes that did not run get a `skip` row. `deciding_node` = the first node that blocked or failed. `poll_evidence` has `is_correct` and a nullable `connected_students` per option row. Query and claim text appear only as 16-hex sha256 hashes. `similarity_score` is cosine in Cortex and word overlap in mock runs, and mock runs have `model: "mock"`. A rename request from the pipeline side is cheap: one module and its contract test.
