# ClassPilot Live: agent demo

Learning demo of the agent part of ClassPilot Live (LangGraph + Snowflake Cortex),
run on mock JSON input. Not production code. Design and data contracts are in
[CLAUDE.md](CLAUDE.md).

## Setup

Python 3.12.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Everything runs offline in mock mode (the default). To use Snowflake Cortex instead,
finish "Snowflake setup" below, then:

```bash
pip install -e ".[dev,snowflake]"
BACKEND=cortex python -m agents_demo.cli run scenarios/02_question_in_scope.json
BACKEND=cortex python -m agents_demo.cli run-all --mode 3   # manual check of the real backend
```

`pytest` always uses mocks and never calls Snowflake.

## Snowflake setup (Stage 2)

Account: trial, `<account region>`. Run in this order:

1. `sql/00_check_account.sql` in Snowsight (ACCOUNTADMIN). Trial accounts need a credit
   card added before AI features work. LLM calls need cross-region inference (see file).
2. Create a key pair outside the repo:
   ```bash
   mkdir -p <KEY_DIR> && cd <KEY_DIR>
   openssl genrsa 2048 | openssl pkcs8 -topk8 -inform PEM -out rsa_key.p8 -nocrypt
   openssl rsa -in rsa_key.p8 -pubout -out rsa_key.pub
   chmod 600 rsa_key.p8
   ```
3. `sql/01_setup_objects.sql`: paste the public key (without BEGIN/END lines) and your
   user name where marked.
4. `cp .env.example .env` and fill in `SNOWFLAKE_ACCOUNT`.
5. `sql/02_lesson_chunks_table.sql`, then load the chunks:
   ```bash
   pip install -e ".[dev,snowflake]"
   python scripts/load_chunks.py
   ```
6. `sql/03_search_service.sql`, then:
   ```bash
   python scripts/smoke_test.py --search
   ```

## Run

```bash
# one scenario: prints the decision and the trace record
python -m agents_demo.cli run scenarios/01_poll_reteach.json
python -m agents_demo.cli run scenarios/05_unsupported_answer.json --mode 3

# all scenarios
python -m agents_demo.cli run-all --mode 2

# labeled eval set (eval/test_questions.json)
python -m agents_demo.cli eval --mode 2
python -m agents_demo.cli eval --mode 3

# hand-written answers straight to the Guardian (eval/guardian_cases.json)
python -m agents_demo.cli guardian-eval

# all scenarios, run live in mode 2 and 3 -> outputs/report.html
python -m agents_demo.cli report

pytest
```

Traces are written as JSONL to `outputs/` (one record per decision).

## Scenarios

| File | What it shows |
|---|---|
| `01_poll_reteach` | 62% chose the same wrong option -> reteach with mapped branch R-03 |
| `01b_poll_below_threshold` | 43% -> continue |
| `01c_poll_remediation_limit` | remediation already used -> escalate |
| `02_question_in_scope` | answer with citations |
| `03a_question_out_of_scope` | analyst says out_of_scope -> escalate |
| `03b_question_assignment` | protected-question rule -> escalate, 0 LLM calls |
| `04a_llm_timeout` | responder times out -> escalate (`llm_error`), no hang |
| `04b_low_confidence` | not covered by approved chunks -> escalate |
| `05_unsupported_answer` | 2-agent lets an unsupported answer through, 3-agent Guardian catches it |

## How the mock works

`MockLLM` (in `adapters/llm.py`) uses simple word-overlap rules instead of a model,
so runs are deterministic. It also scripts one known LLM failure on purpose: when the
approved chunks only partly cover a question, the mock responder adds an unsupported
sentence and claims it is grounded. That is what the Guardian comparison measures.
So mock results show **how the flow behaves**, not how often a real model fails.
All results are exploratory (small, synthetic set).

## Where things live

- `rules.py`: all thresholds and the final validator (the only place that decides)
- `graph.py`: the LangGraph flows (poll path, question path with 2/3-agent mode)
- `nodes/`: analyst, responder, guardian (prompts + LLM call with timeout)
- `adapters/`: mock and Cortex backends (`AI_COMPLETE` with JSON schema output,
  Cortex Search via `snowflake-core`, shared connection in `adapters/snowflake.py`)
- `contracts.py`: pydantic models for the shared JSON contracts
