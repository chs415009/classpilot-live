# Agent service: handoff for the data pipeline

For Yaksha. This is the data the agent service (prep, live Q&A, poll rule) hands over
for the star schema and, later, the post-class report. One pull per class session,
plain files; how you stage, load, model, and report is your choice.

Status: works end to end in mock mode. Field names are drafts (`schema_version:
"v2-draft"`) recorded in `interface_questions.md` Q-21 (trace) and Q-22 (export). If a
name or grain does not fit your model, tell Han-Sheng; renames are cheap (one module
and its contract test).

## 1. Get sample data now (offline, no Snowflake)

```bash
git clone <repo> && cd classpilot-live
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python scripts/sample_session.py
# outputs/samples/pipeline/session-sample.zip
```

The sample is a mock class on a synthetic deck: 2 questions (1 answered, 1 escalated)
and 2 polls (1 explain, 1 reveal). Shapes and keys are real; text and numbers are not.

## 2. How to get a real session

After class, any time, as often as you like:

```bash
curl -o session.zip http://<agent-service>/sessions/<session_id>/export   # 404: no decisions
# or, on the machine that runs the service:
python -m classpilot.cli export <session_id>        # -> outputs/exports/<session_id>.zip
```

There is no "session ended" event: the front end creates `session_id` (one per class
session, your `BATCH`), and the export holds whatever the agent decided for it. A
repeated export of a finished session is identical except `exported_at`.

## 3. What is in the zip

| File | What | Grain |
|---|---|---|
| `export.json` | `schema_version`, `session_id`, `exported_at`, `lessons`, counts (`decisions`, `questions`, `polls`, `trace_records`), `files` | one per export |
| `traces.jsonl` | trace records of this session, one JSON object per line, `record_type` says which | see section 4 |
| `decision_log.jsonl` | one entry per decision with its **text** (question, answer, citations, explanation) | one per decision |
| `lessons/<lesson_id>/manifest.json` | the class content and each generated item's `status` | one per lesson |
| `lessons/<lesson_id>/generation_report.json` | prep checks per generated item (attempts, Guardian results), LLM calls, prep program id | one per lesson |

The trace has no free text (question and claim text are 16-hex SHA-256 hashes);
the decision log has the text. Join them on `run_id` = `decision.decision_id`.

## 4. Trace records (`traces.jsonl`)

Every line has: `schema_version`, `run_id` (= decision id), `session_id` (= BATCH),
`created_at` (UTC ISO 8601), `record_type`. Records never carry extra fields. One
decision (a "run") writes one `run` record plus its children.

| `record_type` | Fact | Grain | Fields |
|---|---|---|---|
| `run` | FACT_PIPELINE_RUN | one decision | `path` (`question` \| `poll`), `lesson_id`, `input_ref` (event_id or poll_id), `segment_id`, `misconception_id`, `remediation_id` (poll explain only), `final_action` (`answer` \| `escalate` \| `explain` \| `reveal`), `escalation_reason`, `deciding_node`, `started_at`, `ended_at`, `latency_ms`, `llm_call_count`, `confidence`, `backend` (`mock` \| `cortex`) |
| `node` | FACT_NODE_EXECUTION | one step of a run | `node_seq` (1-based), `node_name`, `status` (`pass` \| `block` \| `fail` \| `skip`), `latency_ms`, `llm_call_count` |
| `llm_call` | FACT_LLM_CALL | one LLM call | `call_id`, `node_name`, `model`, `prompt_version` (compiled program id, e.g. `live-qa-v1`, or `uncompiled-v1`; feeds DIM_PROMPT), `latency_ms`, `retry_count`, `error_count` |
| `retrieval` | FACT_RETRIEVAL | one retrieved chunk | `rank` (1-based), `chunk_id`, `similarity_score`, `cited` (bool), `query_hash` |
| `claim` | FACT_CLAIM_CHECK | one Guardian claim | `claim_seq`, `claim_hash`, `supporting_chunk_id` (null = none), `supported` (bool) |
| `poll_evidence` | FACT_POLL_EVIDENCE | one option of one poll | `poll_id`, `option`, `response_count`, `is_correct`, `connected_students` |

Values worth knowing:
- Question path nodes: `analyst`, `retrieval`, `responder`, `guardian`, `validator`
  (skipped nodes still get a row with `skip`). Poll path: `threshold_check`,
  `decide_poll`, `explanation_lookup`; no LLM.
- `escalation_reason`: `out_of_scope` and `assignment_like` come from the Analyst (the
  first step); `low_confidence`, `unsupported`, `llm_error` come after it.
- `deciding_node`: the first node that blocked or failed, else `validator` (question)
  or `decide_poll` (poll).
- `similarity_score`: cosine from Cortex Search; word overlap in mock runs, where
  `model` is `mock`. Filter `backend = 'mock'` out of real analysis.
- `chunk_id` looks like `<source>-p<NN>-c<N>`; the part before `-c` is the page or slide
  id (`l1-slides-p03`, `l1-pdf-p02`), the part before `-p` the source file.
- Nulls are JSON `null`. Timestamps are UTC with `Z`.

Example (`run`):

```json
{"schema_version": "v2-draft", "run_id": "dec-5e6f7a8b", "session_id": "session-001",
 "created_at": "2026-10-22T18:31:09Z", "record_type": "run", "path": "question",
 "lesson_id": "dbt-basics-01", "input_ref": "evt-123", "segment_id": "seg-01",
 "misconception_id": null, "remediation_id": null, "final_action": "answer",
 "escalation_reason": null, "deciding_node": "validator",
 "started_at": "2026-10-22T18:31:05.120Z", "ended_at": "2026-10-22T18:31:09.480Z",
 "latency_ms": 4360, "llm_call_count": 3, "confidence": 0.84, "backend": "cortex"}
```

## 5. Decision log (`decision_log.jsonl`)

```json
{"schema_version": "v2-draft", "created_at": "...", "lesson_id": "...",
 "decision": {"decision_id": "dec-...", "session_id": "...", "path": "question" | "poll",
              "action": "...", "poll_id": null, "option": null, "misconception_id": null,
              "remediation_id": null, "remediation_text": null, "show_slide": null,
              "correct_option": null, "answer_text": "...", "citations": ["..."],
              "escalation_reason": null, "confidence": 0.84},
 "question": {"session_id": "...", "event_id": "...", "lesson_id": "...",
              "anonymous_learner_id": "...", "objective_id": "...",
              "question_text": "...", "submitted_at": "..."},
 "poll_evidence": null}
```

A question entry has `question` and `poll_evidence: null`; a poll entry the other way
round (`poll_evidence` = the counts the front end sent: `connected_students`,
`answers_received`, `option_counts`, `correct_option`, ...). This is the only place with
question and answer text, escalation reasons with their question, and the explanation
text that was played. `anonymous_learner_id` is a pseudonym from the front end.

## 6. Prep data (`lessons/<lesson_id>/`)

Prep runs are not in the trace. If the model or the report needs content quality:

- `manifest.json`: every generated item has a `status`: `ok`, `ok_after_retry`,
  `fallback`, `dropped`. Items: `slides.<slide_id>` (spoken scripts),
  `segments[].questions.<poll_id>` (polls; `active_poll` is the one used),
  `remediations.<id>` (wrong-option explanations). A wrong option with no explanation
  is a wrong option of a non-dropped poll that is missing from that poll's
  `known_wrong`; if it triggers in class the decision is `reveal`.
- `generation_report.json`: `backend`, `seconds`, `llm_calls`, `poll_count`,
  `prompt_version` (prep program id; missing in runs before 2026-11-06), `items` (one
  per generated item: `item` such as `script <slide_id>`, `poll <poll_id> <segment>`,
  `explanation <poll_id> <option>`; `status`; `attempts` with outcome and Guardian
  result; `detail`; `citations`), and `summary` per item kind.

## 7. What is yours to decide

How to move the zip into Snowflake (e.g. PUT to a stage and COPY INTO Bronze), table
and model names, whether prep data enters the model, dbt tests, and the post-class
report itself (deferred; when it is built, the text it needs is in the decision log).
The agent service never writes into your stages or tables.

## 8. Reference

- Record models: `src/classpilot/contracts/trace.py`; live shapes:
  `src/classpilot/contracts/live.py`; manifest: `src/classpilot/contracts/manifest.py`
- Fact list and agreed removals: `docs/v2/IMPLEMENTATION_NOTES.md` section 6.3
- Decisions and history: `interface_questions.md` Q-15, Q-16, Q-21, Q-22
