# ClassPilot Live v2 — Implementation Notes (Han-Sheng)

Status: personal working notes, written 2026-11-04, updated 2026-11-04 after the
analysis review (`ANALYSIS.md`, answers in section 13). Companion to
`CLASSPILOT_BEHAVIOR.md`.
Covers my part: prep service, parse layer, content generation, DSPy agents, live Q&A
and poll endpoints, trace records, post-class report. Items marked **[verify]** must be
checked in current docs or by a live test before coding. Items marked **[team]** need
agreement with Sai / Yaksha. The stage plan is in `STAGES.md`.

---

## 1. Change summary vs v1 (Stages 1–4)

### Kept
- LangGraph as the flow controller for Path B; rules make all final decisions.
- Path B structure: Analyst → retrieval → Responder → Guardian → validator (3 agents fixed).
- `check_response` before the Guardian; Guardian skipped when escalation is certain.
- Strict Guardian: claim list + `rules.check_guardian`.
- Cortex adapters, key-pair auth on a service user, a Cortex Search service.
- Mock adapters for development and all tests.
- Trace JSONL per live decision (now several record types, section 6.3).

### Changed
- Path A: no hand-written misconception map or remediation branches. Rule →
  `known_wrong[option]` → misconception → remediation, all generated at prep time and
  stored in the manifest (section 5). TTS reads the remediation text while the front
  end shows its `show_slide`. Path A is a plain function, not a LangGraph graph.
- LLM nodes rewritten as DSPy modules (signatures replace hand-written prompts).
- Knowledge chunks now come from the parse layer instead of hand-written
  `content/lesson_chunks.json`.
- Escalation in class now means "saved for the professor's report".
- The trace now carries run, node, LLM-call, retrieval, claim and poll-evidence records
  for Yaksha's star schema (section 6.3).

### Removed
- Protected-question check and `protected_questions.json` (future work).
  The Analyst still classifies `assignment_like`.
- `misconception_map.json`, `remediations.json` as hand-written files;
  `remediation_limit` / `no_mapping` escalation reasons (Path A no longer escalates).
- 2-agent mode and the `AGENT_MODE` toggle. v1 mode-2 numbers stay in `docs/v1/note_v1.md`
  and `docs/v1/results/`.
- Explanation for the correct answer (only the correct option is revealed).

### New
- Prep service (FastAPI): upload + preprocessing in one flow, async jobs.
- Live endpoints on the same service: student question (Q&A) and poll result (rule).
- Parse layer (local conversion + Snowflake AI functions).
- Generators: segments, scripts, poll placement, polls with misconceptions,
  explanations (remediations).
- Prep-time Guardian check with one feedback retry.
- Decision log with text and the post-class report endpoint.

---

## 2. Component map

```
Front end (Sai) ──HTTP──> Prep service (FastAPI, mine)
                             ├─ convert (LibreOffice, PyMuPDF, python-pptx)   [local]
                             ├─ PUT to stage                                  [Snowflake]
                             ├─ parse (AI_PARSE_DOCUMENT; AI_COMPLETE+image
                             │         for image pages only)                  [Snowflake]
                             ├─ chunk -> LESSON_CHUNKS_V2 -> search service   [Snowflake]
                             ├─ generate + Guardian check (DSPy)              [Cortex LLM]
                             └─ manifest + slide images (local disk) -> GET /manifest

Live backend (Sai) ──HTTP──> same service (mine)
                             ├─ question     -> Q&A agent (LangGraph + DSPy) -> Cortex LLM + Search
                             ├─ poll result  -> poll rule (plain function, no LLM)
                             └─ session end  -> post-class report (HTML)

Trace JSONL ──> Yaksha's dbt star schema (facts + dimensions)
Decision log (text) + traces + poll evidence + manifest ──> report (mine)
```

### 2.1 Account portability and public repo
- The repo will be public. Account-specific values (account identifier, region, login
  user, key path) live only in `.env`. Docs, SQL, and committed config use placeholders.
  The service user and other object names are configurable defaults and may appear in
  docs.
  `materials/` and real course content are never committed. The secret check and a
  `git ls-files` review block every push.
- The code is account-portable: account, region, model names, and object names come
  from `.env` / `config/settings.yaml`. SQL setup scripts are parameterized and can be
  rerun on a new account. Account-dependent findings (available models, cross-region
  setting, costs) are recorded per account in `note.md`.

---

## 3. Prep service API

Separate service from Sai's live backend. Upload and preprocessing run as one flow from
the front end's view (upload, then call process immediately). The same service also
serves the live and report endpoints.

| Endpoint | Purpose |
|---|---|
| `POST /lessons` | Create lesson, return `lesson_id` |
| `POST /lessons/{id}/files` | Upload slides (PPTX/PDF) and references (PDF/DOCX) |
| `POST /lessons/{id}/process` | Start preprocessing, return `job_id` immediately |
| `GET /jobs/{job_id}` | Status: step, progress (e.g. 12/40), per-item failures |
| `GET /lessons/{id}/manifest` | Final manifest |
| `GET /lessons/{id}/slides/{slide_id}` | Slide image (PNG) for playback |
| `POST /questions` (draft) | Live: one student question → decision (answer / escalate) |
| `POST /polls/result` (draft) | Live: poll evidence → `explain` (option, remediation text, `show_slide`) or `reveal` |
| `POST /sessions/{id}/report` (draft) | Build the post-class report at session end |
| `GET /sessions/{id}/report` (draft) | The report as an HTML page |

Job steps: `queued → converting → uploading → parsing → chunking → generating →
checking → assembling → done | failed`.

Implementation notes:
- Run the pipeline in a background task. Job state is an in-memory dict; it does not
  need to survive a restart for the demo.
- Slide images and the manifest are stored on the service's local disk.
- File hash (SHA-256) per upload; same hash → reuse earlier parse results, across
  lessons. A known hash is never re-parsed (this keeps chunk ids stable). If a
  generation parameter changes (e.g. `poll_count`), regenerate from the stored parse.
- Validate type (pptx, pdf, docx) and size limit before anything else.
- Credentials only in the service's `.env`; the front end never sees them.
- CORS for the front-end origin.
- **[team]** Confirm the exact request/response shapes and endpoint names with Sai
  (prep, live, report).

---

## 4. Parse layer

### 4.1 Local step (Snowflake cannot render slides)

| Input | Steps |
|---|---|
| PPTX | python-pptx → per-slide text + speaker notes; LibreOffice (headless) → PDF; PyMuPDF → PNG per page |
| PDF slides | PyMuPDF → per-page text layer + PNG per page (no notes) |
| PDF / DOCX references | Upload as is |

- LibreOffice must be installed on the machine running the prep service.
- Slide PNGs serve two uses: vision-LLM input (image pages only) and front-end playback.
- Image-page check (image count, drawing area) decides which pages go to the vision
  LLM, for slides and references alike. When the check is unsure, the page goes to
  vision.
- Keep PNGs under 3.75 MB (Claude models' image limit on Cortex).
- PPTX slide index and PDF page index must line up; check after conversion.
- Slide ids are system-generated: `<source>-p<NN>` (e.g. `deck1-p02`).

### 4.2 Snowflake step

- `PUT` files to an internal stage (Bronze). Stage needs a directory table for
  `TO_FILE`.
- **References:** `AI_PARSE_DOCUMENT(TO_FILE(...), {'mode': 'LAYOUT', 'page_split': TRUE})`
  → per-page Markdown. Only image pages go to the vision LLM.
  (`PARSE_DOCUMENT` is legacy, deprecated by end of 2026 — use `AI_PARSE_DOCUMENT`.)
- **Slides:** text-only slides use their text layer (and notes) directly. Image slides
  use `AI_COMPLETE(model, PROMPT('... {0} ...', TO_FILE(...)), response_format)` with
  the slide image plus its text layer (and notes) in the prompt. Output schema:
  `slide_text`, `diagram_description`, `key_concepts`.
- Prompt rule for vision: describe only what is visible on the slide; no outside
  knowledge.

**[verify]** (record results per account)
- Which vision models are available from the current account via cross-region
  (docs list claude-3-5/3-7-sonnet, claude-4-opus, llama4-maverick/scout,
  openai-gpt-4.1, pixtral-large; mistral-large3 is not a vision model; check
  claude-haiku-4-5).
- `AI_PARSE_DOCUMENT` availability in our region and whether it extracts PPTX notes.
- Whether `response_format` works together with the image prompt object.

### 4.3 Chunking

- Chunk from Silver per-page text. Keep `source_id`, `page_index`, and `origin`
  (`text_layer` | `llm_description`) on every chunk.
- Stable chunk ids: `<source>-p<NN>-c<n>` (e.g. `deck1-p02-c1`), so the page part
  matches the slide id. Re-parsing never happens for a known file hash, so ids stay
  stable (old traces and citations still resolve).
- Load into `LESSON_CHUNKS_V2` (change tracking on) → the v2 search service refreshes.
  Add `lesson_id` as a filter column so one service serves many lessons.
  **[verify]** filter syntax and target lag for faster refresh after upload.
- The v1 `LESSON_CHUNKS` / `LESSON_SEARCH` stay for the baseline comparison and are
  suspended when not in use.
- With hash reuse across lessons, a file's chunks are copied per lesson. Key =
  (`lesson_id`, `chunk_id`). The data is small, and the Cortex Search `lesson_id` filter
  stays simple.

### 4.4 Tables written by the prep service (draft) **[team: names, so they do not clash with Yaksha's model]**

| Layer | Table | Key columns |
|---|---|---|
| Bronze | stage `@RAW_MATERIALS` + `RAW_FILES` | `file_id`, `lesson_id`, `kind` (slides/reference), `format`, `sha256`, `uploaded_at` |
| Silver | `PARSED_PAGES` | `file_id`, `page_index`, `text_layer`, `notes`, `llm_description`, `parse_method` |
| Gold | `LESSON_CHUNKS_V2` | `chunk_id`, `lesson_id`, `source_id`, `page_index`, `origin`, `text` |

- My code writes these. Prep may write its own stage and tables; the live path never
  reads event tables.
- Generated content (slides, segments, polls, misconceptions, remediations) lives in
  the manifest, not in Snowflake tables. Prep runs are not written to the analytics
  data model.
- Yaksha's dbt builds the analytics model (facts and dimensions) from my trace JSONL
  (section 6.3).

---

## 5. Content generation (prep time)

Order:
1. **Segments + objectives** from slide content (one call over the whole deck summary).
   One objective per segment; the objective id is the segment id.
2. **Scripts**, one per slide, with segment context. TTS-friendly: spell out
   code/symbols in words, no Markdown.
3. **Poll placement**: choose up to `poll_count` (default 5) segment ends, at most one
   poll per segment. Fewer polls are accepted; a poll after the last slide is allowed.
4. **Polls**: question, 4 options, correct option, grounded in chunks; for every wrong
   option, the misconception it shows.
5. **Explanations** (remediations): one per misconception, i.e. one per wrong option:
   TTS text, `show_slide` (picked from the slides of the cited chunks), and citations.
   No explanation for the correct answer.

Each output goes through the Guardian (section 7.4). Generation uses retrieval over the
lesson's chunks so citations exist for checking.

### Manifest: the team's structure **[team]**

The manifest uses the team's existing structure. Every existing field name is kept.
Fields marked `new` are added; `changed` means same field, new meaning.

```json
{
  "lesson_id": "dbt-basics-01",
  "params": {"poll_answer_seconds": 60, "min_responses": 5,
             "wrong_ratio_threshold": 0.60},                       // new
  "slides": {                                                      // new
    "deck1-p01": {"order": 1, "image_ref": "slides/deck1-p01.png",
                  "script": "...", "status": "ok"}
  },
  "segments": [{
    "segment_id": "seg-01",
    "objective": "Understand what dbt does in the modern data stack",
    "slides": ["deck1-p01", "deck1-p02"],                          // changed: system ids
    "questions": {
      "q-01": {
        "text": "In an ELT pipeline, what is dbt responsible for?",
        "options": {"A": "...", "B": "...", "C": "...", "D": "..."},
        "correct_option": "B",                                     // new
        "known_wrong": {"A": "M1", "C": "M2", "D": "M3"},          // changed: every wrong option
        "segment": "seg-01",
        "status": "ok"                                             // new
      }
    },
    "active_poll": "q-01"
  }],
  "misconceptions": {
    "M1": {"label": "...", "description": "...", "remediation": "R-01"}
  },
  "remediations": {
    "R-01": {
      "type": "tts_explanation",                                   // changed
      "title": "...",
      "text": "...",                                               // new
      "show_slide": "deck1-p02",                                   // new
      "content_ref": null,                                         // changed
      "citations": ["deck1-p02-c1"],                               // changed: chunk ids
      "status": "ok_after_retry"                                   // new
    }
  }
}
```

Rules:
- Slide ids are system-generated (`<source>-p<NN>`).
- `known_wrong` covers every wrong option. Each wrong option maps to exactly one
  misconception, and each misconception to exactly one remediation.
- `citations` hold chunk ids (they include the page).
- A segment without a poll has `active_poll: null` and `questions: {}`.
- There is no correct-answer explanation.
- `status` values: `ok`, `ok_after_retry`, `fallback`, `dropped`.
- No `quality` summary field is added. The report counts the per-item `status` values.
- A dropped poll stays in `questions` with `status: "dropped"`. `active_poll` points to
  another question of that segment or is `null`. **[team]** (Sai: the front end reads
  only `active_poll`.)

---

## 6. Live paths

### 6.1 Path A (poll) — rules only
- Input: poll evidence (as v1, plus `poll_id`; drop `remediations_used`).
- Rule: `answers_received >= min_responses` and top wrong share `>= wrong_ratio_threshold`
  → action `explain` with `option`; else `reveal`.
- On `explain`: `known_wrong[option]` → misconception → `remediation` → `text` +
  `show_slide`, returned with the decision. TTS reads the text while the front end shows
  `show_slide`; then the correct option is revealed and the lecture returns to where it
  stopped. No re-poll; each poll triggers at most once. The backend calls the rule once
  per poll **[team]**. If it is trivial, the endpoint also guards on
  (`session_id`, `poll_id`) (Stage 8).
- Plain function (no LangGraph graph) behind an HTTP endpoint. **[team]** (Sai)
- **[team]** New action values (`explain`, `reveal`) replace `reteach` / `continue`.

### 6.2 Path B (student question)
- Same graph as Stage 4, minus `protected_check`. Mode 3 only; `AGENT_MODE` removed.
- Served through an HTTP endpoint that Sai's backend calls per question. **[team]** (Sai)
- Answer goes only to the asking student (Sai's backend routes it).
- No retry in class. Escalate reasons: `out_of_scope`, `assignment_like`,
  `low_confidence`, `unsupported`, `llm_error`.
- Retrieval filtered by `lesson_id`.
- Every decision is also written to the decision log with its text (question, answer,
  citations, escalation reason) for the report.

### 6.3 Trace records for the team data model **[team: field names with Yaksha]**

Yaksha's analytics model is a star schema. My trace JSONL is its only source, so the
trace carries enough raw records for these facts (Yaksha's dbt derives the rest):

| Fact | Grain | What my trace must provide |
|---|---|---|
| `FACT_PIPELINE_RUN` | one live decision | run id, session id, path (poll / question), segment id, misconception / remediation id (poll), final action, escalation reason, deciding node, start/end time, confidence |
| `FACT_NODE_EXECUTION` | one node per run | node sequence, node name, status (pass / fail / block / skip), latency, LLM call count |
| `FACT_LLM_CALL` | one LLM call | call id, node, model, prompt version, latency, retry count, error count |
| `FACT_RETRIEVAL` | one retrieved chunk | rank, chunk id, similarity score (cosine), cited or not, query hash |
| `FACT_CLAIM_CHECK` | one Guardian claim | claim sequence, claim hash, supporting chunk id (or -1), supported or not |
| `FACT_POLL_EVIDENCE` | one option per poll | poll id, option, response count; connected students (optional, pending Yaksha) |

**Not provided** (removed from the model by agreement): scenario key, assignment key,
max reteach, matches-expected count, support score, is-approved, token counts.

Values:
- `FINAL_ACTION`: `explain` / `reveal` / `answer` / `escalate`.
- `ESCALATION_REASON`: `remediation_limit` and `no_mapping` no longer occur.
- `BATCH` = one class session (the report filters by it).
- Prompt version = the id of the compiled DSPy program (or `uncompiled-v1`); it feeds
  `DIM_PROMPT`, which is SCD2.

Decisions are also stored with their text in the decision log (section 6.2), which the
report needs (section 8).

---

## 7. DSPy integration

### 7.1 Where DSPy sits
- DSPy replaces the prompt inside each LLM node. LangGraph keeps flow and rule nodes.
- Retrieval stays a separate LangGraph node; chunks are passed into modules as an input
  field.
- Modules: `Analyst`, `Responder`, `Guardian` (live), plus generators `Segmenter`,
  `ScriptWriter`, `PollPlacer`, `PollWriter` (with misconceptions),
  `ExplanationWriter` (remediation text + `show_slide`) (prep). Prep reuses the same
  `Guardian` module.

### 7.2 LM connection (test first, Stage 1)
- **Route A:** `dspy.LM("snowflake/<model>")` via LiteLLM → Cortex REST API.
  Auth: key-pair JWT (`SNOWFLAKE_JWT`, `SNOWFLAKE_ACCOUNT_ID`) or PAT (`pat/` prefix;
  needs network policy). May not need a warehouse → cheaper. **[verify]**
- **Route B:** custom `dspy.BaseLM` wrapping the existing `AI_COMPLETE` adapter.
- Check: models available on REST from the current account; whether DSPy's JSON/Chat
  adapter output is reliable with mistral-large3; malformed output still maps to
  `llm_error`.
- Old `dspy.Snowflake` / `SnowflakeRM` (DSPy 2.4.x) are outdated; use current `dspy.LM`.
  **[verify]** current DSPy docs.
- Model choice: the cheapest model that passes the probes, per role (live Q&A,
  generation, vision).

### 7.3 Compiling
- Phase 1: compile each module separately.

| Module | Data | Metric |
|---|---|---|
| Analyst | expanded `test_questions.json` (scope labels) | label match |
| Guardian | `guardian_cases.json` (expand) | pass/fail match |
| Responder | expanded question set | citations ⊆ retrieved, then Guardian pass |
| Generators | sample decks | Guardian pass (+ schema checks) |

- Phase 2 (if time): joint compile of the Q&A program with an end-to-end metric.
- Expand eval to 40–60 labeled questions; train/dev split.
- Validate the Guardian on human-labeled cases before using it as a metric (avoid
  circular LLM-judges-LLM). I label them myself: about 30–40 cases.
- Start small: ~10 examples, `BootstrapFewShot`, `max_bootstrapped_demos=2`; measure
  cost before scaling. MIPRO last.
- Keep DSPy cache on. Save compiled programs (`compiled/*.json`) and load at runtime.
  The program id is the prompt version in the trace (section 6.3).
- Measure latency after compiling (few-shot demos lengthen prompts).

### 7.4 Guardian check and retry with feedback (prep only)
- Every generator cites chunk ids; the Guardian sees only those chunks.
  - Scripts: every factual claim supported; transitions are not claims.
  - Polls: the question and the correct option must be supported; each wrong option
    must be shown wrong by the cited chunks.
  - Explanations: every claim must be supported.
- On fail, pass the Guardian's unsupported claims + reason to the generator as an extra
  input field (`feedback`), retry once (`prep_max_retries`).
- Fallback after the retry fails:
  - Script: the slide's own text, cleaned for TTS. If the slide has no text, the vision
    description. If there is none, a fixed sentence asking students to look at the
    slide.
  - Poll: if the poll or any of its wrong-option explanations fails, drop the whole poll
    and try the next segment end.
- Implement the loop in code (not left to the LLM) so the retry count and fallback stay
  deterministic. `dspy.Refine` is an option if it fits; **[verify]** current API.
- Record every item's outcome as its `status`; the report counts the statuses.

### 7.5 Baseline comparison (main technical result)
- Hand-written prompts (Stage 4 numbers) vs compiled modules: escalation recall,
  unsupported answers let through, Guardian catch rate / false fails, LLM calls and
  latency per question.
- Two comparisons: (a) the DSPy port on the v1 lesson against the Stage 4 numbers
  (a parity check), and (b) uncompiled vs compiled on the v2 eval set (the main result).

---

## 8. Post-class report

- Triggered by an endpoint that Sai's backend calls at the end of a session; a CLI
  command does the same.
- Output: one HTML page.
- Inputs: my decision log (question and answer text, sources), traces, poll evidence,
  manifest `status` values (counted by the report). Not from Yaksha's Gold tables, which hold only
  hashes and counts.
- Sections: attendance, poll results, triggered explanations, Q&A with sources,
  escalated questions, content quality (retries / fallbacks), system errors.
- No LLM summary. All numbers and lists are computed by code.

---

## 9. Budget ($400 trial credits)

Rough estimate: $160–460 total. Largest items: DSPy compiling and warehouse uptime.

| Item | Estimate |
|---|---|
| Parse | $5–20 |
| Generation + checks | $10–30 |
| Eval runs | $35–80 |
| DSPy compiling | $50–150 |
| Warehouse uptime | $50–150 |
| Demo / Search | < $20 |

Controls: develop in mock mode; cheap model for iteration; DSPy cache on; small
compiles first; resource monitor on the warehouse; suspend search services when idle
(including the v1 `LESSON_SEARCH`); check `CORTEX_FUNCTIONS_QUERY_USAGE_HISTORY` and
`WAREHOUSE_METERING_HISTORY` after every live stage. Re-estimate after Stage 1 from
real usage.

Approval: each live stage is approved once at its start, based on its estimated LLM
calls. Inside that stage, runs may go up to 1.5× the estimate without asking again;
beyond that, stop and ask.

Timing: the user decides when live stages run; the plan does not depend on dates or the
trial expiry. A move to another account is possible later (section 2.1).

---

## 10. New dependencies (ask before adding)

Python: `dspy`, `litellm` (via dspy), `fastapi`, `uvicorn`, `python-multipart`,
`python-pptx`, `pymupdf`. System: LibreOffice (headless).
Dev: `ruff` (lint + format). Test: `httpx` (FastAPI `TestClient`). Possibly `PyJWT`
(Route A key-pair JWT). Each is proposed when the stage that needs it starts.

---

## 11. Plan

Replaced by `docs/v2/STAGES.md`: ordered stages, each ending with something runnable,
with no week dates. Plan for completeness, not a deadline. The user decides when each
stage runs.

---

## 12. Docs to update in the repo

- `CLAUDE.md`: goal, architecture, hard rules (remove "pre-approved" / "never an
  LLM-written reteach"; add prep-time generation + checks; account portability; public
  repo rules), scope (prep service and live endpoints now in scope), folder layout,
  stages.
- `note.md`: log this direction change as a `change` entry with date.
- `interface_questions.md` new items:
  - manifest: the team structure with the `new` / `changed` fields (section 5); dropped
    polls stay with `status: "dropped"` and the front end reads only `active_poll`
    (Sai, Yaksha)
  - poll rule called once per poll by the backend (Sai)
  - Path A action values `explain` / `reveal`; poll evidence fields; `show_slide` in the
    explain decision
  - removal of `remediation_limit` / `no_mapping` reasons
  - escalation meaning in class and where escalated questions are stored
  - Bronze/Silver/Gold table names for parse output
  - prep service API shapes and slide image delivery
  - live endpoints: Q&A and poll result (Sai)
  - report endpoint and the report data source (decision log + traces)
  - trace records for the star schema (section 6.3; Yaksha)
- v1 interface items (Q-01 to Q-12) are archived in `docs/v1/interface_questions_v1.md`
  and not carried into v2; v2 items start at Q-13.
- `ARCHITECTURE.html` / `DEMO_OVERVIEW.html`: redraw for v2.

---

## 13. Decisions log (this change)

- 2026-11-04 Explanations for wrong options are all pre-generated; no live explanation
  generation. Follow-up confusion goes through the normal Q&A flow.
- 2026-11-04 Q&A answers appear only on the asking student's phone; lecture continues.
- 2026-11-04 Slides accepted as PPTX and PDF.
- 2026-11-04 `poll_count` (default 5) and `poll_answer_seconds` (default 60) are
  parameters; poll placement chosen by the LLM at prep time.
- 2026-11-04 Analyst, Responder, Guardian all kept (no merge experiment).
- 2026-11-04 Prep-time Guardian failure → one retry with Guardian feedback → fallback.
  No pre-class report; quality results go into the post-class report.
- 2026-11-04 Text-heavy pages via `AI_PARSE_DOCUMENT`; only image pages to the vision
  LLM (save tokens).
- 2026-11-04 Prep service is mine, separate from the live backend; upload and
  preprocessing run as one flow. No Airflow for now.
- 2026-11-04 Protected assignment check removed for now.

After the analysis review (`ANALYSIS.md` section 3):
- 2026-11-04 Repo `classpilot-live`, package `classpilot`. New repo, seeded with the
  cleaned v1 code. All v1 files are mine; never pushed to the team repo.
- 2026-11-04 The repo will become public. Secret check and `git ls-files` review before
  every push. Account-specific values only in `.env`; placeholders in docs, SQL, and
  committed config. `materials/` and real course content never committed; tests use a
  synthetic fixture deck.
- 2026-11-04 No deadline-driven plan; plan for completeness. Read the trial expiry in
  Stage 0.
- 2026-11-04 Each live stage is approved once at its start; up to 1.5× the estimated LLM
  calls without asking again.
- 2026-11-04 Both live paths are served by my service: Q&A endpoint per student question;
  poll rule as a plain function behind an endpoint. **[team]** (Sai)
- 2026-11-04 One objective per segment; the objective id is the segment id.
- 2026-11-04 Prep Guardian per item type: generators cite chunk ids, Guardian sees only
  those; scripts: transitions are not claims; polls: question + correct option
  supported, each wrong option shown wrong; explanations: every claim supported.
- 2026-11-04 Partial poll failure → drop the whole poll, try the next segment end.
  Every wrong option must have an explanation.
- 2026-11-04 Fewer polls than `poll_count` accepted; a poll after the last slide is
  allowed; at most one poll per segment.
- 2026-11-04 Script fallback: slide text cleaned for TTS → vision description → fixed
  "look at the slide" sentence.
- 2026-11-04 Vision only for image pages, on slides as well as references; the
  image-page check sends unsure pages to vision.
- 2026-11-04 Prep quality = manifest `status` per item (no separate summary field, see
  below). Prep runs are not written to the data model or Bronze.
- 2026-11-04 My code writes the stage, `RAW_FILES`, `PARSED_PAGES`, `LESSON_CHUNKS_V2`.
  Yaksha's dbt builds the analytics model from my trace JSONL. Prep may write its own
  stage and tables; the live path never reads event tables.
- 2026-11-04 File-hash reuse of parse results works across lessons; a generation
  parameter change regenerates but keeps the parse; a known hash is never re-parsed.
- 2026-11-04 Slide images on the prep service's local disk; in-memory job store.
- 2026-11-04 Cross-region inference accepted for now. Code stays account-portable;
  account-dependent findings recorded per account; SQL setup rerunnable on a new account.
- 2026-11-04 2-agent mode and `AGENT_MODE` removed; v1 mode-2 numbers kept as history.
- 2026-11-04 Baseline: both the v1-lesson parity check and a fresh v2 eval baseline. The
  v1 search service is suspended when not in use.
- 2026-11-04 Models: the cheapest that passes the probes, per role.
- 2026-11-04 Guardian labels: I label about 30–40 cases.
- 2026-11-04 Post-class report: endpoint called at session end + CLI; HTML; no LLM
  summary; question/answer text from my decision log, not the Gold tables.
- 2026-11-04 Correct-answer explanation removed: after a poll only the correct option is
  revealed.
- 2026-11-04 `httpx` and `PyJWT` proposed when a stage needs them. `ruff` adopted (dev,
  lint + format).
- 2026-11-04 Interface items: Q-02 dropped; Q-05, Q-06, Q-09 updated for v2; Q-08
  resolved by the trace records; Q-12 needed by the report.
- 2026-11-04 Reteach = explanation + cited slide: TTS reads the remediation text while
  the front end shows `show_slide`; then the correct option is revealed and the lecture
  returns. No re-poll, no remediation deck; each poll triggers at most once.
- 2026-11-04 Manifest uses the team's existing structure with minimal `new` / `changed`
  fields (section 5), replacing the earlier draft. **[team]**
- 2026-11-04 Trace records feed Yaksha's star schema (section 6.3): run, node, LLM call,
  retrieval, claim, poll evidence. Token counts and the other removed fields are not
  provided. **[team]** (field names)

Open points from the plan update, decided:
- 2026-11-04 Report endpoint is built in Stage 10 (where the report exists), not Stage 8.
- 2026-11-04 No `quality` summary field in the manifest; the report counts the per-item
  `status` values.
- 2026-11-04 Dropped polls stay in `questions` with `status: "dropped"`; `active_poll`
  points to another question or is `null`. **[team]** (Sai: front end reads only
  `active_poll`)
- 2026-11-04 Chunks of a file shared across lessons are copied per lesson; key =
  (`lesson_id`, `chunk_id`).
- 2026-11-04 Poll rule: the backend calls it once per poll **[team]**. If trivial, the
  Stage 8 endpoint adds a (`session_id`, `poll_id`) guard; otherwise skipped.
- 2026-11-04 "Login user" in the account-specific list is a placeholder in committed
  files; the service user and other object names stay configurable defaults.
- 2026-11-04 All v1 documents are archived in `docs/v1/` (design, dev log, interface
  items, diagrams, results). v1 interface items Q-01 to Q-12 are ignored for v2; v2 items
  start at Q-13. This replaces the earlier "update Q-05, Q-06, Q-09" entry.
- 2026-11-04 No date-driven planning: the user decides when each stage runs. The trial
  expiry no longer affects the plan or the stage order.
