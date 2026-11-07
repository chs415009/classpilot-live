# ClassPilot Live

ClassPilot Live runs a class session when the professor is unavailable. Before class it
turns uploaded slides and readings into a spoken script per slide, polls, and an
explanation for every wrong poll option, all checked automatically against the
materials. In class it answers students' private questions with grounded, cited answers
and triggers pre-generated explanations when many students pick the same wrong option.
After class the professor gets one auditable report (deferred for now; see below).

This repo holds the prep service, parse layer, generators, live Q&A and poll endpoints,
trace records, and a dev report for demos (LangGraph + DSPy + Snowflake Cortex). The front
end, live backend, and data pipeline live elsewhere.

**Status:** v2 in development, built stage by stage (`docs/v2/STAGES.md`). Results so far
are exploratory (small, synthetic data).

## What works now

| Feature | Since | Backend |
|---|---|---|
| Live poll rule: poll evidence → explain (remediation text + slide) or reveal | Stage 2 | code only |
| Live student question: retrieval → Analyst → Responder → Guardian → rule (DSPy; retrieval first since Stage 12) | Stage 3 | mock, Cortex |
| Trace records (JSONL) and decision log for every live decision | Stage 2 | — |
| Local conversion: PPTX/PDF/DOCX → page text, notes, PNGs, image-page flag | Stage 4 | local + Docker |
| Parse layer: vision for image pages, AI_PARSE_DOCUMENT for references, chunks, Cortex Search | Stage 5 | mock, Cortex |
| Generators: segments, scripts, polls, explanations, each checked by the prep Guardian (claims with quotes checked by code), retried twice, then a fallback; a wrong option whose explanation fails reveals only; team manifest | Stage 6-12 | mock, Cortex (L1-L4 with `prep-v6`: 63 of 67 scripts, 19 polls, 40 of 57 wrong options explained) |
| Eval sets (train: synthetic, committed; dev: real lesson, gitignored), labeled Guardian cases with a labeling sheet | Stage 9 | mock, Cortex |
| Compiled DSPy programs (`compiled/`, synthetic demos only): `live-qa-v5` (Analyst, Responder, Guardian) and `prep-v6` (writers, script and explanation Guardians), loaded behind `llm.compiled_program` / `prep.compiled_program` | Stage 9, 12 | Cortex |
| Live Q&A quality (Stage 12): retrieval before the Analyst, Guardian bar "rewording, direct conclusions, and tied examples pass", Guardian deadline, one repeat after a malformed reply | Stage 12 | mock, Cortex |
| DSPy experiments: `optimize-guardian` (random search or GEPA on labeled synthetic cases, scored on labeled dev cases) | Stage 12 | Cortex |
| Service API: lessons, uploads, background prep jobs with progress, manifest, slide images, `POST /questions`, `POST /polls/result` | Stage 8 | mock (Cortex: same code, not yet run live) |
| Dev report (demo entry): prep a lesson folder, run its fixed test questions, static HTML with collapsible details and an index of runs | Stage 10 | mock, Cortex |
| Handoff to the other parts: lesson bundle zip, repeat-safe live calls, session export zip (traces, decision log, manifests) | Stage 11 | mock |

Not yet: the professor's post-class report is deferred (who builds it, and from which
tables, is decided later). The trace, the decision log, and the manifest statuses hold
its data.

## Docs

| File | What |
|---|---|
| `docs/v2/CLASSPILOT_BEHAVIOR.md` | What v2 must do |
| `docs/v2/IMPLEMENTATION_NOTES.md` | How: components, manifest, trace records, API, DSPy plan, decisions log |
| `docs/v2/STAGES.md` | Stage plan with checks and exit gates |
| `docs/v2/ANALYSIS.md` | v1 reuse map and repository decision |
| `docs/agent/note.md` | Agent part dev log: changes, findings, results per stage |
| `CLAUDE.md`, `.claude/rules/` | Instructions for Claude Code: shared rules, per-part rules |
| `interface_questions.md` | Interface items to agree with the team |
| `docs/agent/handoff/` | Handoff notes for the front end (`FRONTEND_HANDOFF.md`) and the pipeline (`PIPELINE_HANDOFF.md`); sample data: `python scripts/sample_session.py` → `outputs/samples/` |
| `docs/v1/` | v1 archive: design, dev log, interface items, diagrams, Stage 4 Cortex results |

## Setup

Python 3.12.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Everything runs offline in mock mode (the default). `pytest` always uses mocks and never
calls Snowflake.

```bash
pytest
ruff check . && ruff format --check .
python -m classpilot.cli run-all                       # all scenarios, mock
python -m classpilot.cli run scenarios/02_question_in_scope.json
python -m classpilot.cli eval                          # labeled eval set
python -m classpilot.cli guardian-eval                 # Guardian-only cases
scripts/check_secrets.sh --history                     # before every push
```

## Prep pipeline (before class)

Nothing is installed on the host besides Python and Docker: PPTX → PDF runs in a
LibreOffice Docker image. Without the image, PDF slides and references still work,
and the LibreOffice tests are skipped.

```bash
scripts/libreoffice/build.sh                           # once: builds classpilot-libreoffice:1

# whole pipeline: convert -> parse -> chunk -> generate -> check -> manifest
python -m classpilot.cli prep run --backend mock --lesson l1 deck.pptx --ref reading.pdf

# or step by step
python -m classpilot.cli prep convert deck.pptx --ref reading.pdf   # local only
python -m classpilot.cli prep parse --lesson l1 deck.pptx --ref reading.pdf
python -m classpilot.cli prep search --lesson l1 "why keep raw data"
python -m classpilot.cli prep generate --lesson l1 --poll-count 3   # from the stored parse
python -m classpilot.cli prep check --lesson l1                     # checks + review sheet
```

`prep generate` and `prep run` end with the same checks as `prep check`: the manifest
validates, every item has a status, every citation is a chunk of the lesson, every
`show_slide` is a slide of a cited chunk, scripts and explanations pass the TTS lint,
and no `active_poll` points to a dropped poll. `--backend mock|cortex` overrides
`BACKEND` (default mock). A file hash that was parsed
before is never parsed again, also for another lesson, and `prep generate` reads only
the stored parse, so changing `--poll-count` costs no parse calls.

| Output (all under `outputs/`, gitignored) | What |
|---|---|
| `convert/<file_id[:16]>/` | `convert.json` (page ids, text, notes, image-page flag), one PNG per page |
| `prep_tables/` | mock-mode tables (RAW_FILES, PARSED_PAGES, LESSON_CHUNKS_V2 as JSON) |
| `parse/<lesson>.json` | parse report and chunks |
| `prep/<lesson>/manifest.json` | the team manifest (`docs/v2/IMPLEMENTATION_NOTES.md` section 5) |
| `prep/<lesson>/generation_report.json` | every attempt of every item (problems, Guardian reply, calls, latency) and readings per item type |
| `prep/<lesson>/review.md` | review sheet: readings, placement, scripts, polls with misconceptions and explanations, Guardian decisions, cited chunks |
| `prep/<lesson>/slides/` | slide PNGs named by slide id |

Settings (thresholds, `poll_count`, retries, timeouts, models, object names):
`config/settings.yaml`. An example manifest from the mock: `tests/fixtures/deck/manifest_mock.json`.

## Dev report (demo entry, Stage 10)

Each lesson is a local folder (gitignored, real course content):

```
materials/lessons/<lesson_id>/
  slides/               *.pptx | *.pdf
  refs/                 *.pdf | *.docx
  test_questions.json   fixed, hand-written test questions (format below)
  lesson.yaml           optional: title, poll_count
```

```bash
python -m classpilot.cli dev --list                          # lesson folders, last run
python -m classpilot.cli dev l1                              # mock: prep + test questions
BACKEND=cortex python -m classpilot.cli dev l1               # live (after approval): ~100-170 calls
BACKEND=cortex python -m classpilot.cli dev l1 --skip-prep   # questions only: ~30
open outputs/dev/index.html                                  # every run, newest first
```

One run writes `outputs/dev/<lesson_id>/<run_id>/`: `report.html`, `results.json` (all
data behind the page), the slide images, and the real `traces.jsonl` /
`decision_log.jsonl` of the test questions. The report has an overview (status counts,
wrong options without an explanation, questions as expected, latency, program ids),
then scripts, polls with each wrong option's explanation, and the test questions
(mismatches first); long parts are collapsed. Code computes every number; no LLM writes
any of it. `--skip-prep` reuses the lesson's last prep and must use the same backend.

Test questions (`test_questions.json`), 3 per category: `direct`, `reworded`
(rewording or a direct inference), `partial` (a full answer needs facts the materials
never state, so escalate), `out_of_scope`. A question matches when the action equals
`expected_action` and, on escalate, the reason is in `accepted_reasons`:

```json
{"lesson_id": "l1", "questions": [
  {"question_id": "tq-07", "category": "partial",
   "question_text": "What is the difference between private, protected, and public in Java?",
   "expected_action": "escalate", "accepted_reasons": ["unsupported", "low_confidence"],
   "sources": ["l1-pdf-p03-c2"], "why": "The reading never mentions protected."}]}
```

A synthetic example for the fixture deck is `tests/fixtures/deck/test_questions.json`.

### Demo: L1-L4 with and without DSPy (Stage 12)

`outputs/dev/index.html` lists two full runs per lesson (prep + 12 test questions), same
code: one with the compiled programs (`live-qa-v5`, `prep-v6`) and one without
(`uncompiled-v4` live, `uncompiled-v2` prep); each report shows its program ids. The prep
outputs are `outputs/prep/l<n>/` (compiled) and `outputs/prep/l<n>.uncompiled/`.

| Lesson | Questions as expected (DSPy / none) | Script fallbacks | Wrong options explained |
|---|---|---|---|
| L1 (tuned on) | 12 / 8 of 12 | 0 / 2 of 14 | 12/12 / 7/12 |
| L2 | 11 / 11 | 1 / 1 of 18 | 10/15 / 10/15 |
| L3 | 11 / 11 | 0 / 8 of 18 | 11/15 / 5/15 |
| L4 | 10 / 9 | 3 / 3 of 17 | 7/15 / 6/15 |

Single runs; a lesson moves by about 2 questions between runs. To rerun the baseline,
set both `compiled_program` values in `config/settings.yaml` to `null` (the prep output
of `l<n>` is overwritten, so copy it first). Details: `docs/agent/note.md`, Stage 12.

## Eval, compile, and DSPy experiments (Stages 9 and 12)

```bash
# labeled question sets (train is synthetic and committed; dev is under materials/)
python -m classpilot.cli eval --set eval/questions_train.json
BACKEND=cortex python -m classpilot.cli eval --set materials/eval/questions_dev.json \
    [--compiled-program live-qa-v5]                  # needs the search service resumed

# Guardian cases: write a labeling sheet, then evaluate labeled cases
python -m classpilot.cli guardian-sheet eval/guardian_cases_train.json   # -> outputs/labeling/
python -m classpilot.cli guardian-eval --cases eval/guardian_cases_train.json [--prep-model M]

# compile with BootstrapFewShot on the synthetic trainsets (BACKEND=cortex, after approval)
python -m classpilot.cli compile --side prep --program-id <id>
python -m classpilot.cli compile --side live --program-id <id> [--task analyst|responder|guardian]

# Guardian experiments (Stage 12): train = labeled synthetic cases, val = labeled dev cases
BACKEND=cortex python -m classpilot.cli optimize-guardian --method eval --program uncompiled \
    --program live-qa-v5 --runs 2                                  # score programs on val
BACKEND=cortex python -m classpilot.cli optimize-guardian --method rs --program-id <id>
BACKEND=cortex python -m classpilot.cli optimize-guardian --method rs --kind script \
    --base prep-v6 --program-id <id>                               # prep Guardians: script|poll|explanation
BACKEND=cortex python -m classpilot.cli optimize-guardian --method gepa --program-id <id>

python scripts/search_service.py status|resume|suspend   # suspend after every live run
```

The service and the CLI use the programs named in `config/settings.yaml`
(`llm.compiled_program: live-qa-v5`, `prep.compiled_program: prep-v6`; `null` runs the
uncompiled prompts); a program id becomes `prompt_version` in the trace. Results go to
`outputs/optimize/`; a saved program is checked for course content (`leak_problems`).
Cases and question sets built from real course material (`materials/`) are never
committed. Helper scripts: `scripts/eval_lesson_snapshot.py` (dev set from a parsed
lesson), `scripts/draft_prep_guardian_cases.py` and `scripts/draft_live_guardian_cases.py`
(unlabeled cases from stored runs).

## Service (FastAPI)

```bash
uvicorn classpilot.service.app:create_app --factory --port 8000   # BACKEND=mock by default
# API docs: http://localhost:8000/docs
L=lesson-demo
curl -X POST localhost:8000/lessons -H 'content-type: application/json' -d "{\"lesson_id\":\"$L\"}"
curl -X POST localhost:8000/lessons/$L/files -F kind=slides -F file=@deck.pptx
curl -X POST localhost:8000/lessons/$L/files -F kind=reference -F file=@reading.pdf
curl -X POST localhost:8000/lessons/$L/process -H 'content-type: application/json' -d '{"poll_count":5}'
curl localhost:8000/jobs/<job_id>                 # step, progress, failures
curl localhost:8000/lessons/$L/manifest
curl -o p01.png localhost:8000/lessons/$L/slides/<slide_id>
curl -o $L.zip localhost:8000/lessons/$L/bundle   # manifest + every slide PNG, before class
curl -o s1.zip localhost:8000/sessions/<session_id>/export   # after class, for the pipeline
python -m classpilot.cli export <session_id>       # same zip -> outputs/exports/
```

Live: `POST /questions` (StudentQuestion → Decision) and `POST /polls/result`
(PollEvidence → Decision). Calls are stateless; a repeated (`session_id`, `event_id`) or
(`session_id`, `poll_id`) returns the first decision, also after a restart. The session
export holds that session's `traces.jsonl`, `decision_log.jsonl`, and each lesson's
manifest and generation report. Shapes and error codes: `interface_questions.md` Q-18,
Q-19, Q-22.
Data (lessons, uploads, manifests, slide images, `traces.jsonl`, `decision_log.jsonl`)
goes to `outputs/service/` (`service.data_dir`); CORS origins are `service.cors_origins`.
Credentials stay in the service's `.env` and never appear in a response.

## Snowflake (optional, Cortex backend)

Account-specific values go only into `.env` (copy `.env.example`); never commit them.

1. Run `sql/00_check_account.sql` in Snowsight (ACCOUNTADMIN). Trial accounts need a
   credit card added before AI features work. LLM calls may need cross-region inference
   (see the file).
2. Create a key pair in a folder outside the repo:
   ```bash
   mkdir -p <KEY_DIR> && cd <KEY_DIR>
   openssl genrsa 2048 | openssl pkcs8 -topk8 -inform PEM -out rsa_key.p8 -nocrypt
   openssl rsa -in rsa_key.p8 -pubout -out rsa_key.pub
   chmod 600 rsa_key.p8
   ```
3. Run `sql/01_setup_objects.sql`: paste the public key (without BEGIN/END lines) and your
   login user name where marked.
4. `cp .env.example .env`, fill in the account and the key path, then
   `pip install -e ".[dev,snowflake]"` and `python scripts/smoke_test.py`.
5. Create the parse objects (stage, RAW_FILES, PARSED_PAGES, LESSON_CHUNKS_V2) and, after
   the first lesson is parsed, the search service. SQL templates are filled from `.env`
   and `config/settings.yaml`; the script prints the SQL and runs it only with `--execute`:

   ```bash
   python scripts/run_sql.py sql/04_parse_objects.sql              # review, then --execute
   python -m classpilot.cli prep parse --backend cortex --lesson l1 deck.pptx --ref reading.pdf
   python scripts/run_sql.py sql/05_search_service_v2.sql          # once, after the first chunks
   python scripts/search_service.py status                         # also: resume | suspend
   python scripts/smoke_test.py --search l1 "what is a stack"      # chunks per lesson + a query
   ```

With `BACKEND=cortex`, the fixture lesson in `content/` (scenarios, `cli eval`) uses the
Cortex LLM but reads its chunks locally; only prepped lessons use Cortex Search.

Suspend the search service when it is not in use. Cost readings:
`sql/probes/cost_reading.sql`, run in Snowsight as ACCOUNTADMIN (ACCOUNT_USAGE views lag
behind real time; the service user cannot read them).

All Cortex runs use Snowflake credits; this is a shared account, so ask before running
them.
