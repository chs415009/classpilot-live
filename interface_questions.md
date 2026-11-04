# Interface questions for the team

Things to discuss when the three parts (front end + live state, data pipeline, agent)
agree on the real interfaces. The contracts in `CLAUDE.md` and `docs/v2/IMPLEMENTATION_NOTES.md` are drafts,
not a team agreement yet.

Each item records:
1. **Current approach**: what the agent side does now (v1 items) or proposes (v2 items).
2. **Why change**: the problem or cost with the current approach.
3. **Suggested direction**: a proposal to discuss, not a decision.

Status: `open` (not discussed yet), `agreed` (decision written under the item),
`dropped`. Newest items at the bottom. Details and history stay in `note.md`.

---

## Q-01 Escalation reason when search fails
- **Status:** open · **Area:** decision output · **Affects:** front end, pipeline · **Raised:** 2026-10-21 (Stage 3)
- **Current approach:** If Cortex Search fails (connection or service error), the
  question is escalated with `escalation_reason = "llm_error"`, the closest existing value.
  The trace shows the difference (the responder's LLM call is not counted), but the
  decision alone does not.
- **Why change:** `llm_error` mixes two different failures. Someone reading the summary
  or debugging would look at the LLM when the search service was the problem.
- **Suggested direction:** Either keep `llm_error` and define it as "AI backend error"
  (no change for anyone), or add `retrieval_error`. That would need the front end to
  handle the new value and the pipeline to update accepted values (e.g. dbt
  `accepted_values` tests). Agent side prefers keeping `llm_error` for the demo, plus
  the error detail in the trace (see Q-08).

## Q-02 Protected assignment list: required or optional?
- **Status:** dropped (2026-11-04) · **Area:** content input · **Affects:** professor workflow, agent · **Raised:** 2026-10-21
- **v2 (2026-11-04):** The protected-question check and its list are removed (future work). The Analyst still classifies `assignment_like`.
- **Current approach:** Two layers catch "give me the assignment answer" questions:
  (1) a rule compares the question with `content/protected_questions.json` (the
  assignment prompts) and escalates without an LLM call; (2) the Question Analyst (LLM)
  classifies `assignment_like` without any list. The demo ships 3 sample assignment
  prompts.
- **Why change:** Layer 1 means someone has to supply and keep the assignment list for
  each session. Not every class will have assignments ready, and the team may not want
  to design them.
- **Suggested direction:** Keep the `assignment_like` reason (layer 2 costs nothing
  extra). Make the list optional: the professor pastes existing assignment prompts if
  they want the cheap rule, otherwise leave it empty. The code already works with an
  empty list. Keep the 3 samples in the demo to show the no-LLM path.

## Q-03 Assignment-like questions: escalate or give a hint?
- **Status:** open · **Area:** decision output · **Affects:** front end, professor · **Raised:** 2026-10-20 (Stage 1)
- **Current approach:** Every assignment-like question is escalated to the professor.
- **Why change:** Students get no help at all, and the professor may get many similar
  escalations.
- **Suggested direction:** Optionally reply with a pre-approved pointer (e.g. "review
  chunk-04") instead of an answer. This would need a new action or a hint field in the
  decision, so it is a design change for the front end too.

## Q-04 Poll input: `answers_received` duplicates `option_counts`
- **Status:** open · **Area:** poll input · **Affects:** front end / backend · **Raised:** 2026-10-21
- **Current approach:** Poll evidence sends both `answers_received` and `option_counts`.
  The threshold rule uses `answers_received`.
- **Why change:** `answers_received` should equal the sum of `option_counts`. If the two
  ever disagree (e.g. snapshot timing in Redis), it is unclear which one is right.
- **Suggested direction:** Send only `option_counts` and compute the total in the agent,
  or keep both and define that the agent rejects or logs a mismatch.

## Q-05 Poll input: `connected_students` is not used
- **Status:** open · **Area:** poll input · **Affects:** front end / backend, pipeline · **Raised:** 2026-10-21
- **v2 (2026-11-04):** Still not used by the poll rule, but the post-class report shows attendance, and `FACT_POLL_EVIDENCE` lists connected students as optional (pending Yaksha). Suggested: keep it in poll evidence so the trace can carry it; decide with Yaksha whether the model takes it from the trace or from live-state events.
- **Current approach:** Sent in poll evidence, not used by any rule.
- **Why change:** Fields nobody uses tend to go stale.
- **Suggested direction:** Drop it from the agent input, unless the professor summary
  needs participation rate ("21 of 24 answered"). In that case the pipeline can take it
  straight from the live-state events instead of through the agent.

## Q-06 Question input: `objective_id` is not used
- **Status:** open · **Area:** question input · **Affects:** front end / backend · **Raised:** 2026-10-21
- **v2 (2026-11-04):** In v2 the objective id is the segment id, and the front end knows which segment is playing. Suggested: rename to `segment_id` and pass it to the Analyst as a hint; the run record (`FACT_PIPELINE_RUN`) also wants a segment id.
- **Current approach:** The student question carries an optional `objective_id`, but
  the question path ignores it; the Question Analyst decides the objective itself.
- **Why change:** Either it is dead data, or it is useful context we are throwing away.
- **Suggested direction:** If the front end knows which objective is being taught right
  now, pass it to the analyst as a hint ("current objective: objective-02"). Otherwise
  drop it.

## Q-07 Question input: `anonymous_learner_id` and `submitted_at` are pass-through only
- **Status:** open · **Area:** question input · **Affects:** front end / backend, pipeline · **Raised:** 2026-10-21
- **Current approach:** Both are required in the agent input but only passed along; the
  trace links back to the event with `input_ref = event_id`.
- **Why change:** The agent does not need learner data, and taking less personal data
  in is simpler and safer.
- **Suggested direction:** Keep them in the event the backend sends to the pipeline;
  the agent only needs `session_id`, `event_id`, `question_text` (and maybe Q-06).
  The pipeline joins agent traces to events on `event_id`.

## Q-08 Trace does not keep the reasons behind a decision
- **Status:** resolved by design (2026-11-04), field names open in Q-21 · **Area:** trace output · **Affects:** pipeline, professor summary · **Raised:** 2026-10-21 (Stage 3)
- **v2 (2026-11-04):** The v2 trace carries node, LLM-call, retrieval, and claim records (IMPLEMENTATION_NOTES 6.3), including the error count and each Guardian claim with its support. The drafted answer text goes into the decision log (Q-12).
- **Current approach:** The trace records nodes run, call count, chunk ids, and
  latency. Not stored: the error message, the Guardian's verdict reason, and the
  drafted answer that was rejected.
- **Why change:** The professor summary is meant to be auditable. In a Stage 3 Cortex
  run, the responder once answered with confidence 0.9 and the Guardian passed it. We
  could not look at the answer text afterwards because nothing kept it.
- **Suggested direction:** Add optional trace fields such as `error_detail`,
  `guardian_reason`, and `draft_answer_text`. All are null when unused. Confirm the
  pipeline can load them into Bronze as is.

## Q-09 Poll path has no event id
- **Status:** open · **Area:** poll input, trace output · **Affects:** front end / backend, pipeline · **Raised:** 2026-10-20 (Stage 1)
- **v2 (2026-11-04):** Poll evidence gains `poll_id`, and every decision gets a run id in the trace. Suggested: `input_ref` for a poll = `<session_id>/<poll_id>` (one decision per poll), so no snapshot time is needed. Still open whether the backend also sends its own event id.
- **Current approach:** Poll evidence has no event id, so the trace uses
  `input_ref = "<question_id>@<snapshot_time>"` and `agent_mode = null`.
- **Why change:** The pipeline has to join on a made-up string instead of a real key.
  It is also easy to misread: `question-07@...` is a poll question id, not a student
  question, but it sits in the same `input_ref` column as student `evt-...` ids.
- **Suggested direction:** The backend adds a `snapshot_id` (or `event_id`) to poll
  evidence, and the trace uses it as `input_ref`.

## Q-10 Where LLM calls are processed (data residency)
- **Status:** open · **Area:** Snowflake account setting · **Affects:** whole team, professor · **Raised:** 2026-10-21 (Stage 2)
- **v2 (2026-11-04):** Han-Sheng: cross-region inference is acceptable for now; a move to an account in a region where the models run natively may come later, so the code stays account-portable. Still to confirm with the team before real student data.
- **Current approach:** The account is in <account region> and no LLM runs there, so
  calls use cross-region inference. The account default is
  `CORTEX_ENABLED_CROSS_REGION = ANY_REGION`, so prompts (lesson text and student
  questions) may be processed in any Snowflake region.
- **Why change:** Fine for synthetic demo data. With real student questions, the course
  or school may require a known region.
- **Suggested direction:** Before real student data, decide whether to limit to
  `AWS_US` (one SQL statement by ACCOUNTADMIN) and whether that needs the professor's
  OK.

## Q-11 How long a student waits for a reply
- **Status:** open · **Area:** decision output (timing) · **Affects:** front end / backend · **Raised:** 2026-10-22 (Stage 4)
- **Current approach:** The agent returns one decision when it is done; nothing is
  streamed. Measured on Cortex (mistral-large3, 3-agent mode, now the default; exploratory):
  rule-only escalations (protected question) are instant; analyst escalations ~1-2 s;
  answers ~4.5-7.5 s; an LLM call that hits the 10 s timeout escalates with `llm_error`,
  so the worst case is roughly the sum of the per-call timeouts (about 30 s for
  analyst + responder + Guardian).
- **Why change:** The front end has to show something while the student waits, and needs
  its own timeout that does not fire before the agent's fallback does.
- **Suggested direction:** Front end shows a "checking with approved material" state
  right after submit; the backend waits up to ~35 s, and on its own timeout shows "sent
  to the professor" (same as an `escalate`). Agree on whether the agent should also
  send an early "received" status, or only the final decision. Revisit the numbers after
  the model choice (deferred).

## Q-12 Decisions are not stored; the trace alone misses what was decided
- **Status:** open · **Area:** decision + trace output · **Affects:** pipeline, professor summary, front end / backend · **Raised:** 2026-10-22 (Stage 4)
- **v2 (2026-11-04):** Needed by the post-class report: question and answer text come from the agent's own decision log (option (a), JSONL), because the Gold tables hold only hashes and counts. The trace stays the only source for Yaksha's model (Q-21).
- **Current approach:** Each run makes two records. The **decision** (action,
  `escalation_reason`, `remediation_id`, `answer_text`, `citations`, `confidence`,
  `session_id`) is returned and printed but never written to a file. The **trace** is
  written to `outputs/traces.jsonl` (one line per decision), but it only has `action`
  from the decision. The two share `decision_id`.
- **Why change:** If the pipeline loads only traces into Bronze, the professor summary
  cannot show which session a decision belongs to, why a question was escalated, which
  remediation branch ran, or what answer the student saw. That is the core of the
  "auditable summary".
- **Suggested direction:** Pick one:
  (a) also write decisions as JSONL (e.g. `outputs/decisions.jsonl`); the pipeline loads
  two Bronze tables and joins on `decision_id`. Keeps each contract small and matches the
  two consumers (front end reads decisions, pipeline reads both).
  (b) copy the decision fields into the trace, so one Bronze table has everything; simpler
  to load, but the trace and the decision contract then overlap.
  Agent side leans to (a). Decide together with Q-08 (extra trace fields) and Q-09
  (poll key), since all three set the Bronze schema for agent output.

---

## v2 items (raised 2026-11-04)

Drafts from `docs/v2/IMPLEMENTATION_NOTES.md`. The code still follows v1 until Stage 2.

## Q-13 Manifest format and versioning
- **Status:** open · **Area:** manifest · **Affects:** front end (Sai), pipeline (Yaksha) · **Raised:** 2026-11-04
- **Current approach:** The team's existing manifest structure, with only `new` / `changed` fields (IMPLEMENTATION_NOTES section 5): `params`, `slides` keyed by system slide ids `<source>-p<NN>`, `correct_option`, `known_wrong` for every wrong option, remediations of type `tts_explanation` with `text`, `show_slide`, chunk-id `citations`, and a `status` per item. No correct-answer explanation and no `quality` field (the report counts statuses).
- **Why change:** The team structure had no generated content, no status, and human-chosen ids.
- **Suggested direction:** Agree the `new` / `changed` fields. Dropped polls stay in `questions` with `status: "dropped"`; `active_poll` points to another question or is `null`, and the front end reads only `active_poll`. Decide whether the manifest needs a version number.

## Q-14 Poll path: action values, evidence fields, explain payload
- **Status:** open · **Area:** poll input, decision output · **Affects:** front end / backend (Sai), pipeline · **Raised:** 2026-11-04
- **Current approach (draft):** Actions `explain` / `reveal` replace `reteach` / `continue`. Poll evidence adds `poll_id` and drops `remediations_used`. On `explain`, the decision returns the option, the misconception and remediation ids, the remediation `text`, and `show_slide`; on `reveal`, the correct option.
- **Why change:** v2 has no remediation branches or limits; the front end needs the text and slide to play.
- **Suggested direction:** Agree the field names. Each poll triggers at most once: the backend calls the rule once per poll (an endpoint guard on (`session_id`, `poll_id`) may be added in Stage 8 if trivial).

## Q-15 Removed decision values
- **Status:** open · **Area:** decision output · **Affects:** front end, pipeline (accepted values) · **Raised:** 2026-11-04
- **Current approach (draft):** `remediation_limit` and `no_mapping` escalation reasons and the decision field `remediation_id` are removed. The 5 remaining reasons are `out_of_scope`, `assignment_like`, `low_confidence`, `unsupported`, `llm_error`.
- **Why change:** Path A no longer escalates.
- **Suggested direction:** Update dbt `accepted_values` tests and front-end handling.

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
- **Suggested direction:** Agree paths, payloads, and timeouts (see Q-11 for the wait time). The question payload needs the lesson for the retrieval filter: proposed `lesson_id` in the question (or the agent maps `session_id` to a lesson).

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
