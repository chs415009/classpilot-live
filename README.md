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

**Status:** v2 in development. The code currently still implements the v1 agent demo
(poll trigger + student question flow, mock or Cortex backend) under the new package
name; v2 behavior arrives stage by stage (`docs/v2/STAGES.md`). Results so far are
exploratory (small, synthetic data).

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

Then, for example: `BACKEND=cortex python -m classpilot.cli run-all`. Live runs use
Snowflake credits.
