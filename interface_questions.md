# Interface questions for the team

Things to discuss when the three parts (front end + live state, data pipeline, agent)
agree on the real interfaces. The contracts in `.claude/rules/agent.md` and
`docs/v2/IMPLEMENTATION_NOTES.md` are drafts, not a team agreement yet. Since Stage 2
the code implements these drafts (`src/classpilot/contracts/`); field names can still
change.

Numbering starts at Q-13: Q-01 to Q-12 were v1 items, archived in
`docs/v1/interface_questions_v1.md` and not carried into v2.

Each item records:
1. **Current approach**: what the agent side does now or proposes.
2. **Why change**: the problem or cost with the current approach.
3. **Suggested direction**: a proposal to discuss, not a decision.

Status: `open` (not discussed yet), `agreed` (decision written under the item),
`dropped`. Newest items at the bottom. Details and history stay in `docs/agent/note.md`.

---

## Q-13 Manifest format and versioning
- **Status:** open · **Area:** manifest · **Affects:** front end (Sai), pipeline (Yaksha) · **Raised:** 2026-11-04
- **Current approach:** The team's existing manifest structure, with only `new` / `changed` fields (IMPLEMENTATION_NOTES section 5): `params`, `slides` keyed by system slide ids `<source>-p<NN>`, `correct_option`, `known_wrong` for every wrong option, remediations of type `tts_explanation` with `text`, `show_slide`, chunk-id `citations`, and a `status` per item. No correct-answer explanation and no `quality` field (the report counts statuses).
- **Why change:** The team structure had no generated content, no status, and human-chosen ids.
- **Suggested direction:** Agree the `new` / `changed` fields. Dropped polls stay in `questions` with `status: "dropped"`; `active_poll` points to another question or is `null`, and the front end reads only `active_poll`. Decide whether the manifest needs a version number.
- **Stage 2 draft (2026-11-04):** Implemented as `contracts/manifest.py` (fixture `content/manifest.json`); the structure is unchanged from section 5. To check with Sai: what the front end can rely on for `active_poll`: it is `null` when a segment has no questions or only dropped ones, otherwise it names a question that is not dropped.

## Q-14 Poll path: action values, evidence fields, explain payload
- **Status:** open · **Area:** poll input, decision output · **Affects:** front end / backend (Sai), pipeline · **Raised:** 2026-11-04
- **Current approach (draft):** Actions `explain` / `reveal` replace `reteach` / `continue`. Poll evidence adds `poll_id` and drops `remediations_used`. On `explain`, the decision returns the option, the misconception and remediation ids, the remediation `text`, and `show_slide`; on `reveal`, the correct option.
- **Why change:** v2 has no remediation branches or limits; the front end needs the text and slide to play.
- **Suggested direction:** Agree the field names. Each poll triggers at most once: the backend calls the rule once per poll (an endpoint guard on (`session_id`, `poll_id`) may be added in Stage 8 if trivial).
- **Stage 2 draft (2026-11-04):** Decision fields: `decision_id`, `session_id`, `path`, `action`, `poll_id`, `option` (the wrong option explained), `misconception_id`, `remediation_id`, `remediation_text`, `show_slide`, `correct_option` (on explain and reveal), plus the question-path fields (`answer_text`, `citations`, `escalation_reason`, `confidence`); unused fields are `null`. The rule reads `min_responses` / `wrong_ratio_threshold` from the manifest `params`. To discuss: (1) the evidence has no `lesson_id`, so the agent cannot find the manifest by itself; the draft function takes the manifest from its caller. Options: add `lesson_id` to the evidence (as in Q-19), or the agent maps `session_id` to a lesson. (2) `poll_id` and `question_id` carry the same value in the draft; keep both or drop one? (3) An unknown or dropped `poll_id`, or a `correct_option` that differs from the manifest, is an input error (planned as 4xx in Stage 8), not a decision.

## Q-15 Removed decision values
- **Status:** open · **Area:** decision output · **Affects:** front end, pipeline (accepted values) · **Raised:** 2026-11-04
- **Current approach (draft):** `remediation_limit` and `no_mapping` escalation reasons and the decision field `remediation_id` are removed. The 5 remaining reasons are `out_of_scope`, `assignment_like`, `low_confidence`, `unsupported`, `llm_error`.
- **Why change:** Path A no longer escalates.
- **Suggested direction:** Update dbt `accepted_values` tests and front-end handling.
- **Stage 2 (2026-11-04):** Implemented: `Action` is `explain | reveal | answer | escalate`, and these 5 reasons are the only ones the code produces.

## Q-16 What escalation means in class, and where escalated questions go
- **Status:** open · **Area:** decision output · **Affects:** front end (Sai), professor · **Raised:** 2026-11-04
- **Current approach (draft):** Escalate = the student sees "saved for the professor"; the question is stored in the agent's decision log and appears, grouped, in the post-class report.
- **Why change:** In v1 escalation meant handing the question to a live professor, who is not there in v2.
- **Suggested direction:** Agree the student-facing message and that the decision log is the store.

## Q-17 Table names for parse output
- **Status:** open · **Area:** Snowflake tables · **Affects:** pipeline (Yaksha) · **Raised:** 2026-11-04
- **Current approach (draft):** The prep service writes stage `@RAW_MATERIALS`, `RAW_FILES`, `PARSED_PAGES`, and `LESSON_CHUNKS_V2` (key `lesson_id` + `chunk_id`; chunks of a file shared across lessons are copied per lesson). Generated content stays in the manifest; prep runs are not written to the data model.
- **Why change:** Names must not clash with Yaksha's Bronze/Silver/Gold models.
- **Suggested direction:** Agree names and schema; Yaksha's dbt does not build these tables.

## Q-18 Prep service API and slide image delivery
- **Status:** open · **Area:** HTTP API · **Affects:** front end (Sai) · **Raised:** 2026-11-04
- **Current approach (draft):** Endpoints in IMPLEMENTATION_NOTES section 3 (lessons, files, process, jobs, manifest, slides by slide id). Slide PNGs and the manifest are served from the prep service's local disk; job state is in memory.
- **Why change:** New service; nothing agreed yet.
- **Suggested direction:** Agree request/response shapes, the upload size limit, and the CORS origin.

## Q-19 Live endpoints: student question and poll result
- **Status:** open · **Area:** HTTP API · **Affects:** front end / backend (Sai) · **Raised:** 2026-11-04
- **Current approach (draft):** `POST /questions` (one question → answer or escalate decision) and `POST /polls/result` (poll evidence → explain / reveal), both on the agent service. The poll rule is a plain function; no LLM in the poll path.
- **Why change:** v1 had no HTTP interface.
- **Suggested direction:** Agree paths, payloads, and timeouts. The front end needs a waiting state: v1 measured about 4–8 s for answered questions, and the worst case is roughly the sum of the per-call timeouts (about 30 s). The question payload needs the lesson for the retrieval filter: proposed `lesson_id` in the question (or the agent maps `session_id` to a lesson).
- **Stage 2 draft (2026-11-04):** `StudentQuestion.lesson_id` is required in the draft, and retrieval always filters on it (mock and Cortex Search `{"@eq": {"LESSON_ID": ...}}`). The same open point applies to poll evidence (Q-14).

## Q-20 Post-class report: trigger and data source
- **Status:** open · **Area:** HTTP API, report · **Affects:** front end / backend (Sai), pipeline (Yaksha) · **Raised:** 2026-11-04
- **Current approach (draft):** Sai's backend calls `POST /sessions/{id}/report` at session end; `GET /sessions/{id}/report` returns the HTML page; a CLI command does the same. Inputs: the agent's decision log (text), traces, poll evidence, manifest status values. No LLM summary.
- **Why change:** The report reads text that Yaksha's Gold tables do not hold.
- **Suggested direction:** Agree the endpoint and that the report does not read Gold tables.

## Q-21 Trace records for the star schema
- **Status:** open · **Area:** trace output · **Affects:** pipeline (Yaksha) · **Raised:** 2026-11-04
- **Current approach (draft):** Trace JSONL with run, node, LLM-call, retrieval, claim, and poll-evidence records (IMPLEMENTATION_NOTES 6.3). Removed: scenario key, assignment key, max reteach, matches-expected count, support score, is-approved, token counts. `BATCH` = one class session; prompt version = compiled DSPy program id or `uncompiled-v1`.
- **Why change:** The trace is the only source of Yaksha's model.
- **Suggested direction:** Agree exact field names and record types; Stage 2 implements them as drafts with a contract test.
- **Stage 2 draft (2026-11-04):** `contracts/trace.py`, described in IMPLEMENTATION_NOTES 6.3 with examples in `.claude/rules/agent.md`. One file `outputs/traces.jsonl` with a `record_type` per line (`run`, `node`, `llm_call`, `retrieval`, `claim`, `poll_evidence`). Common fields: `schema_version` (`v2-draft`), `run_id` (= decision id), `session_id` (= BATCH), `created_at`. Proposals to check with Yaksha: claim `supporting_chunk_id` is `null` instead of `-1` (chunk ids are strings); node status `skip` rows are written for nodes that did not run; `deciding_node` = the first node that blocked or failed; `poll_evidence` adds `is_correct` and keeps `connected_students` per option row (nullable); query and claim text appear only as 16-hex sha256 hashes (the text is in the decision log); `similarity_score` is cosine in Cortex and word overlap in mock runs, and mock runs have `model: "mock"`. Are one file with a type column and these names fine for the Bronze load?
