# ClassPilot Live

ClassPilot Live runs a class session when the professor is unavailable. Before class it
turns uploaded slides and readings into a spoken script per slide, polls, and an
explanation for every wrong poll option, all checked automatically against the
materials. In class it answers students' private questions with grounded, cited answers
and triggers pre-generated explanations when many students pick the same wrong option.
After class the professor gets one auditable report.

This repo holds the prep service, parse layer, generators, live Q&A and poll endpoints,
trace records, and the post-class report (LangGraph + DSPy + Snowflake Cortex). The front
end, live backend, and data pipeline live elsewhere.

**Status:** v2 in development, built stage by stage (`docs/v2/STAGES.md`). Results so far
are exploratory (small, synthetic data).

## What works now

| Feature | Since | Backend |
|---|---|---|
| Live poll rule: poll evidence → explain (remediation text + slide) or reveal | Stage 2 | code only |
| Live student question: Analyst → retrieval → Responder → Guardian → rule (DSPy) | Stage 3 | mock, Cortex |
| Trace records (JSONL) and decision log for every live decision | Stage 2 | — |
| Local conversion: PPTX/PDF/DOCX → page text, notes, PNGs, image-page flag | Stage 4 | local + Docker |
| Parse layer: vision for image pages, AI_PARSE_DOCUMENT for references, chunks, Cortex Search | Stage 5 | mock, Cortex |
| Generators: segments, scripts, polls, explanations, each checked by the prep Guardian, retried once, then a fallback; team manifest | Stage 6 | mock (Cortex in Stage 7) |

Not yet: the HTTP service (Stage 8), compiled DSPy programs (Stage 9), the post-class
report (Stage 10).

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
4. `cp .env.example .env` and fill in the account and the key path.
5. Run `sql/02_lesson_chunks_table.sql`, then load the v1 sample chunks:
   ```bash
   pip install -e ".[dev,snowflake]"
   python scripts/load_chunks.py
   ```
6. Run `sql/03_search_service.sql`, then `python scripts/smoke_test.py --search`.

Then, for example: `BACKEND=cortex python -m classpilot.cli run-all` (v1 sample lesson).

**v2 parse objects** (stage, RAW_FILES, PARSED_PAGES, LESSON_CHUNKS_V2, search service).
SQL templates are filled from `.env` and `config/settings.yaml`; the script prints the
SQL and runs it only with `--execute`:

```bash
python scripts/run_sql.py sql/04_parse_objects.sql              # review, then --execute
python -m classpilot.cli prep parse --backend cortex --lesson l1 deck.pptx --ref reading.pdf
python scripts/run_sql.py sql/05_search_service_v2.sql          # once, after the first chunks
python scripts/search_service.py status                         # also: resume | suspend
```

Suspend the search service when it is not in use. Cost readings:
`sql/probes/stage5_cost_reading.sql` (ACCOUNT_USAGE views, which lag behind real time).

All Cortex runs use Snowflake credits; this is a shared account, so ask before running
them.
