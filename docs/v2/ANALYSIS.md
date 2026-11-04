# ClassPilot Live v2: Analysis of the v1 code base

Status: draft for review, written 2026-11-04. Inputs: `CLAUDE.md`, `note.md`,
`interface_questions.md` (v1), `docs/v2/CLASSPILOT_BEHAVIOR.md`,
`docs/v2/IMPLEMENTATION_NOTES.md`, and the current tree. Where v1 and v2 conflict, v2
wins. Unclear points are listed as questions in section 3. They are not resolved here.

State of v1 at the time of writing: 85 tests pass (`pytest`, mock only, 2.5 s).
Python 3.12.0, langgraph 1.2.16, pydantic 2.14.1, snowflake-connector-python 5.0.0,
snowflake.core 1.13.2.

---

## 1. Reuse map

Legend: **keep** = carry over as is (rename the package only). **adapt** = carry over
and change. **replace** = rewrite; ideas or text may carry over but the code does not.
**delete** = do not carry over.

### 1.1 Source (`src/agents_demo/`, ~1,750 lines)

| File | Verdict | Reason |
|---|---|---|
| `__init__.py` | keep | Empty package marker. |
| `contracts.py` | adapt | `Action` gets `explain` / `reveal` in place of `continue` / `reteach`. Drop `no_mapping` / `remediation_limit` and `Decision.remediation_id`. `PollEvidence` gets `poll_id` and loses `remediations_used`. `AnalystOutput` / `ResponderOutput` / `GuardianOutput` stay as the typed outputs of the DSPy modules. Add manifest and prep models. All of this is draft until the team agrees. |
| `rules.py` | adapt | Keep: `check_poll_threshold` (the v2 rule is the same), `parse_or_none`, `check_guardian`, `check_response`, `validate_final` (drop the `agent_mode` branch; mode 3 only). Delete: `lookup_remediation`, `remediation_limit_reached`, `check_protected`. Replace `decide_poll` with explain/reveal. Add prep rules (retry, fallback, drop, schema checks). |
| `graph.py` | adapt | Path B keeps its routing, the Guardian skip, and the trace building. Remove `protected_check`, move retrieval into its own node, keep mode 3 only, pass `lesson_id`. Path A shrinks to one rule plus an explanation lookup in the manifest. A LangGraph graph is optional there (see Q7). |
| `nodes/__init__.py` | keep | `NodeResult` and `elapsed_ms` still fit. |
| `nodes/analyst.py` | replace | The prompt becomes a DSPy signature. Keep the try/except → `NodeResult(error)` wrapper pattern. |
| `nodes/responder.py` | replace | Same as the analyst. Retrieval moves out into its own graph node (IMPLEMENTATION_NOTES 7.1). |
| `nodes/guardian.py` | replace | Same, but reuse the Stage 4 strict-rule wording as the signature instructions. It produced 8/8 catches and is the baseline to keep. |
| `adapters/__init__.py` | adapt | The factory now has to build DSPy LMs and parse/stage adapters as well. |
| `adapters/llm.py` | adapt | Keep `LLMError` and the `call_llm` timeout wrapper. Keep the `MockLLM` logic as the base for mock programs, ported to the new interface. `CortexLLM` (`AI_COMPLETE`) is the basis for DSPy Route B. `TASK_SCHEMAS` stays only if Route B keeps using `response_format`. |
| `adapters/retrieval.py` | adapt | Add the `lesson_id` filter and the new columns (`source_id`, `page_index`, `origin`). `RetrievalError` and `MockRetriever` stay. |
| `adapters/snowflake.py` | keep | `.env` loading, key-pair loading, and the shared connection still fit. A JWT helper may be added if Route A needs one. |
| `content.py` | replace | v2 content comes from parse output and the manifest, not from hand-written `content/`. A fixture loader replaces it. |
| `settings.py` | adapt | Add `poll_count`, `poll_answer_seconds`, `prep_max_retries`, and model settings. Remove `agent_mode`, `protected_similarity_threshold`, `max_remediations_per_objective`. |
| `text.py` | keep | `coverage` and `split_sentences` drive the mocks. `jaccard` was used only by the protected check, so it can go. |
| `trace.py` | keep | One JSONL line per decision still applies. Add a decisions file once Q-12 is agreed. |
| `runner.py` | adapt | Keep the scenario, eval, and Guardian-eval runners. Remove the per-mode loop. Add a prep fixture runner. |
| `cli.py` | adapt | Keep `run`, `run-all`, `eval`, `guardian-eval`. Drop `--mode`. Add `prep` commands. `report` changes meaning (see the next row). |
| `report.py` | replace | The v1 report compares mode 2 and mode 3 scenario runs. v2 needs a post-class report with different inputs and sections. Its CSS and token theming can be reused. |

### 1.2 Tests (`tests/`, 70 functions, 85 cases)

| File | Verdict | Reason |
|---|---|---|
| `conftest.py` | adapt | Keep `force_mock_backend` (the tests-never-call-Snowflake guard). Fixtures switch to v2 content. |
| `test_rules.py` | adapt | Keep the threshold, validator, `check_guardian`, and `check_response` tests (about 20). Delete the remediation and protected tests (`test_lookup_remediation`, `test_remediation_limit`, `test_decide_poll`, `test_protected_*`). |
| `test_graph.py` | adapt | Keep the error → escalate tests, the Guardian skip, the trace, and the details tests. Delete the poll-reteach and unmapped tests, the protected test, the mode 2 vs 3 comparison, and the v1 report tests. |
| `test_nodes.py` | replace | Rewrite the node tests for DSPy modules with mocks. Keep the same test intents (classify, cite, low confidence, timeout, retrieval error, Guardian catches). |
| `test_adapters.py` | adapt | Keep the `call_llm`, `CortexLLM` fake-connection, and Cortex Search mapping tests, and add the filter. `test_response_format_matches_contract` (the TASK_SCHEMAS sync check) becomes a sync check between DSPy signatures and the pydantic models. |

### 1.3 Data, config, and eval

| File | Verdict | Reason |
|---|---|---|
| `config/settings.yaml` | adapt | Use the v2 parameter table (BEHAVIOR section 8). |
| `content/lesson_chunks.json` | adapt | Move to `tests/fixtures/` as hand-written chunks for mock tests. It is also the v1 lesson behind the Stage 4 baseline (see Q19). |
| `content/poll_questions.json` | replace | Becomes polls inside a fixture manifest, with pre-generated explanations. |
| `content/misconception_map.json` | delete | v2 has no misconception map. |
| `content/remediations.json` | delete | v2 has no remediation branches. |
| `content/protected_questions.json` | delete | v2 drops the protected check (future work). |
| `scenarios/01_poll_reteach.json`, `01b_*` | adapt | Become poll `explain` and `reveal` scenarios. |
| `scenarios/01c_poll_remediation_limit.json` | delete | v2 has no remediation limit. |
| `scenarios/02`, `03a`, `04a`, `04b`, `05` | adapt | Remove `agent_mode` and add `lesson_id`. The behavior they check is unchanged. |
| `scenarios/03b_question_assignment.json` | adapt | Now caught by the Analyst instead of the rule, so the expected `nodes_run` changes. |
| `eval/test_questions.json` | adapt | Expand to 40–60 questions with a train/dev split. The v1 labels were written for the mock (note.md, Stage 4). |
| `eval/guardian_cases.json` | adapt | Keep all 12 cases and expand them, adding prep-content cases (scripts, polls, explanations). gc-06 is a real Cortex answer. |
| `outputs/eval_cortex_mode3.json`, `guardian_eval_cortex.json`, `eval_cortex_mode2.json` | keep (archive) | These are the Stage 4 baseline. Copy them to `docs/v1/results/`. No account identifiers were found in them. `guardian_eval_cortex_baseline.json`, named in note.md, is not in `outputs/`; its numbers survive in note.md only. |
| `outputs/traces.jsonl`, `eval_traces_*`, `report.html` | delete | Regenerable. |
| `outputs/report.html.backuo` | delete | A stray backup with a typo in its name. |

### 1.4 SQL and scripts

| File | Verdict | Reason |
|---|---|---|
| `sql/00_check_account.sql` | keep (archive) | Account setup is done. It stays as the record of the one-time steps. |
| `sql/01_setup_objects.sql` | adapt | Role, warehouse, and service user stay. v2 needs new grants (CREATE STAGE, tables) for the prep objects. Any change is shown before it runs. |
| `sql/02_lesson_chunks_table.sql` | replace | The v2 `LESSON_CHUNKS` has new columns (`source_id`, `page_index`, `origin`, `lesson_id`). Use a new name such as `LESSON_CHUNKS_V2` so the v1 baseline table keeps working until Q19 is settled. |
| `sql/03_search_service.sql` | replace | New search service over the v2 table with a `lesson_id` filter. Filter syntax and target lag are `[verify]` items. |
| `scripts/load_chunks.py` | replace | In v2, chunks are loaded by the prep pipeline from parse output. |
| `scripts/smoke_test.py` | adapt | Still useful as a connection check. The search part follows the new columns and filter. |

### 1.5 Docs and project files

| File | Verdict | Reason |
|---|---|---|
| `CLAUDE.md` | replace | Becomes `docs/v1/CLAUDE_v1.md`. A new v2 `CLAUDE.md` is written in Stage 0. |
| `note.md` | keep | Full history. Redact the account locator on line 135 first (section 2.3). |
| `interface_questions.md` | adapt | Keep Q-01 to Q-12 and update their statuses (Q-02 → dropped). Add the v2 items. |
| `README.md` | replace | Rewrite for v2. The Snowflake key-pair setup steps carry over. |
| `ARCHITECTURE.html`, `DEMO_OVERVIEW.html` | keep (archive) | Move to `docs/v1/`. Redraw for v2 later (IMPLEMENTATION_NOTES section 12). |
| `pyproject.toml` | adapt | New name and package. v2 dependencies are added one by one, each with approval. |
| `.env.example` | adapt | Add the Route A (REST/JWT) variables if that route is chosen. |
| `.gitignore` | adapt | Add `materials/`, `.DS_Store`, and `*.pub` (the public key is harmless, but it does not belong in the repo). |
| `.env`, `.venv/`, `.pytest_cache/`, `src/agents_demo.egg-info/`, `__pycache__/` | delete (never copy) | Local or secret. |

### 1.6 Summary

- About 60% of the v1 source lines carry over in some form, but only about 10% unchanged:
  the connection helper, trace, text helpers, and node result type.
- The parts with real value are the rule layer (validator, `check_guardian`,
  `check_response`), the Path B routing, the error → escalate handling, the adapters'
  Cortex details (all verified live in Stage 3), the Guardian wording, and the
  Guardian-eval method.
- Everything about branches, remediation, protected questions, and mode 2 goes.
- The prep service, parse layer, generators, manifest, and post-class report are all
  new. They will be most of the v2 code.

---

## 2. Repository decision

### 2.1 Recommendation: **B. New private repo**, seeded with a cleaned copy of the v1 code

The first commit holds the v1 code as is, renamed and cleaned, with tests passing. The
v2 changes then show up as normal diffs on top of it.

Reasons:

1. **There is no git history to keep.** `agents_demo/` is not a git repository
   (`git rev-parse` fails, and no `.git` exists). "Reuse with history" is not an
   option, so the choice is only about which folder becomes the repo.
2. **The layout and name do not fit v2.** The package is `agents_demo`, and the tree
   is built around one LangGraph demo. v2 is a prep service, a parse layer,
   generators, live agents, and a report. A new repo lets the package be renamed
   (proposed: `classpilot`) and the layout set once, instead of moving files around
   inside the old folder.
3. **Safer by construction.** Copying named files into a new folder means `.env`,
   `outputs/`, `.venv/`, egg-info, and the stray backup can never be committed by
   mistake. Running `git init` inside `agents_demo/` relies on `.gitignore` being
   right every time.
4. **v1 stays intact as a reference.** `agents_demo/` remains a frozen, working v1 that
   can still be run against the v1 `LESSON_SEARCH` for the baseline comparison.
5. **Code survival does not argue for A.** Most kept code is adapted, not reused as
   is (section 1.6), so a new repo loses nothing.

### 2.2 History and secret scan

- **Git history:** none, because the folder is not a git repository. Nothing to scan.
  If this code was ever pushed elsewhere (for example the shared team repo), that
  history is outside this folder and was not checked (see Q2).
- **Current tree** (excluding `.env` and `.venv`), searched for private keys, account
  hosts and locators, emails, `/Users/` paths, passwords, and tokens:

| Finding | Where | Risk | Action |
|---|---|---|---|
| Account locator (value redacted in this copy) | `note.md:135` | An account identifier, not a secret. Should not be public. | Replaced with `<account locator>` in Stage 0. |
| `.env` with real account, user, and key path (8 keys; values not printed) | `.env` (gitignored) | Credentials config | Never copy. |
| Private key file | a key folder outside the repo | Secret | Already outside the tree. `.gitignore` also blocks `*.p8`, `*.pem`, and `rsa_key*`. |
| Private key path (value redacted in this copy) | `.env.example`, `README.md` | No secret, but account-specific | Replaced with placeholders in Stage 0 (public repo). |
| Object names (`CLASSPILOT_*`), account region (value redacted in this copy) | `sql/`, `note.md`, `README.md`, `ARCHITECTURE.html`, `config/` | Low; reveals the setup, not access | Region replaced with placeholders in Stage 0. Object names stay as configurable defaults. |
| Teammate first names (Sai, Yaksha) and your name | `docs/v2/*.md` | Personal data | Fine for a private repo. Ask the teammates before going public (Q4). |
| Your email | not found in the tree | — | — |
| `outputs/*.json` (Cortex runs) | gitignored | Synthetic lesson text only. Error strings carry no account host. | Only the archived baseline JSONs are copied. |

- **Not checked:** the real course slides that will be used as test material are not
  in the tree yet. They may hold third-party copyright or student names (Q3). They go
  in a gitignored `materials/` folder.

### 2.3 Must-clean list (applies to the copy, not to `agents_demo/`)

1. Replace the account locator in `note.md` with `<account locator>` (done in Stage 0,
   together with region and key-path placeholders across all committed files).
2. Do not copy `.env`, `outputs/` (except the baseline JSONs), `.venv/`,
   `.pytest_cache/`, `*.egg-info/`, `__pycache__/`, or `report.html.backuo`.
3. `.gitignore` covers `.env`, `.venv/`, `outputs/`, `materials/`, `*.p8`, `*.pem`,
   `rsa_key*`, `*.pub`, `.DS_Store`, `__pycache__/`, `*.egg-info/`, and `.pytest_cache/`.
4. Run the grep-based secret check (`scripts/check_secrets.sh`, a plain shell script,
   not a new tool) on the tree and on `git log -p` before the first push.
5. The repo starts **private**. Before any push, review the `git ls-files` list together.

### 2.4 Ownership

- No file shows signs of coming from a teammate. All v1 files were written in this
  folder, according to note.md (Stages 1–4). Without git history this cannot be proven.
- `contracts.py` and `CLAUDE.md` say field names "follow the team README". That README
  is not in this folder; only the field names were borrowed. Contracts are drafts
  until the team agrees.
- `docs/v2/CLASSPILOT_BEHAVIOR.md` describes the teammates' parts (front end, backend,
  pipeline). Its system-level content is shared team design, not only yours. Keep it,
  but it has the same visibility concern (Q4).
- Course slides from earlier courses belong to their authors or the university, not
  to the team (Q3).

### 2.5 Why private

- Course slides and AI-generated reference material may be committed by mistake.
  `materials/` is gitignored, but private is the safe default.
- The repo holds teammate names and team design that the teammates have not agreed to
  publish.
- Course policy on public code for graded team projects is unknown (Q4).
- Account object names and the region are visible.

Going public is a separate later decision, after a review.

### 2.6 Files to carry over and the new layout

Carry over: everything marked keep, adapt, or archive in section 1. In Stage 0 the
v1 data that the tests still need (`misconception_map.json`, `remediations.json`,
`protected_questions.json`) is also copied, so the first commit is a green v1. Stage 2
then deletes it in a visible diff.

Proposed layout (the repo and package names are open, see Q1):

```
classpilot/                      # repo root (name TBD)
  CLAUDE.md  README.md  note.md  interface_questions.md
  pyproject.toml  .env.example  .gitignore
  config/settings.yaml
  docs/
    v1/  CLAUDE_v1.md  ARCHITECTURE_v1.html  DEMO_OVERVIEW_v1.html  results/  (Stage 4 JSONs)
    v2/  CLASSPILOT_BEHAVIOR.md  IMPLEMENTATION_NOTES.md  ANALYSIS.md  STAGES.md
  sql/                           # numbered; each file shown before it runs
  scripts/                       # smoke tests, live probes, check_secrets.sh
  src/classpilot/
    contracts/                   # live.py (poll, question, decision, trace), manifest.py, prep.py
    settings.py  trace.py  text.py  cli.py
    rules/                       # poll.py, question.py (validator, guardian, response), prep.py
    adapters/                    # snowflake.py, llm.py (DSPy LM + mock), retrieval.py, stage.py, parse.py
    agents/                      # DSPy signatures + modules: analyst, responder, guardian
    live/                        # poll.py (Path A), question_graph.py (Path B, LangGraph)
    prep/                        # convert.py, parse.py, chunking.py, generate/, check.py, manifest.py, pipeline.py
    service/                     # FastAPI app, routes, job store
    report/                      # post-class report
  compiled/                      # saved DSPy programs (committed)
  eval/                          # questions, guardian cases, splits
  tests/  fixtures/              # synthetic fixture deck, chunks, manifest, session
  materials/                     # gitignored: real course slides and references
  outputs/                       # gitignored
```

Build the sub-packages only when a stage needs them. Stage 0 renames the v1 modules
and keeps them flat; later stages move them into this layout as they change.

---

## 3. Questions for you

### Repository and ownership
1. **Names.** What should the repo and the Python package be called? (Proposal: repo
   `classpilot-live`, package `classpilot`.)
2. **Origin of v1.** Was any file in `agents_demo/` written by a teammate or copied
   from the shared team repo? Was this folder ever pushed to the team repo? If so, v1
   history exists there and was not scanned. The "team README" the field names
   follow is not here either.
3. **Course slides.** Who owns the "slides from earlier courses"? Can they be
   committed even to a private repo? Proposal: real material stays in gitignored
   `materials/`, and tests use a small synthetic fixture deck that I generate.
4. **Visibility later.** Are you planning to make the repo public at some point? If so,
   teammates should agree to their names and team design appearing, and course
   policy on public project code should be checked.

### Schedule and budget
5. **Deadline and trial.** What is the course deadline, and when does the trial end?
   The account was opened around 2026-10-20; a 30-day trial would end around Nov 19,
   which falls inside week 3, when the DSPy compile is planned. This decides whether the
   compile moves earlier or a backup account is set up first.
6. **Cost limit.** Is there a spend cap per live stage below which I can run without
   asking again inside that stage (for example "up to N LLM calls")? Or should I ask
   before every live run?

### Live system boundaries
7. **Live interfaces.** How does Sai's backend reach the Q&A agent: an HTTP endpoint on
   the prep service, a separate live-agent service, or an imported library? The API
   table in IMPLEMENTATION_NOTES section 3 has only prep endpoints. Who runs the poll
   rule: Sai's backend (it is pure code) or my service? If it is mine, a plain function
   is enough; it does not need a LangGraph graph.
8. **Objectives vs segments.** Are learning objectives generated together with the
   segments, one per segment? The manifest uses `objective_id: "seg-02"`, while the
   `SEGMENTS` table has `segment_id` and `objective` text. Is the objective id the same
   as the segment id? The Analyst's in-scope and out-of-scope decision depends on these
   generated objectives.

### Prep-time quality checks
9. **What the Guardian checks per item type.** The v1 Guardian assumes every
   sentence is a factual claim backed by a cited chunk. That does not fit prep
   content directly:
   - Scripts have transitions ("Let's move on to…").
   - Polls have wrong options that are false on purpose.
   - Wrong-option explanations say why something is wrong.

   What should "supported" mean for each type, and which chunks does the Guardian
   see: only the chunks the generator cited (as in v1), or all chunks of that slide or
   segment? Proposal:
   - Every generator cites chunk ids, and the Guardian sees only those chunks.
   - Scripts: transitions are not claims.
   - Polls: the question and the correct option must be supported, and each wrong
     option must be shown wrong by the cited chunks.
   - Explanations: every claim must be supported.
10. **Partial poll failure.** If the explanation for one wrong option fails twice, do we
    drop just that explanation or the whole poll? If only the explanation is dropped
    and that option then triggers the rule, the class hears nothing. Proposal: drop the
    whole poll and try the next segment end.
11. **Too few segments.** If the deck has fewer segment ends than `poll_count`, should
    we accept fewer polls? Is a poll allowed after the last slide? Should there be a
    minimum gap between polls?
12. **Script fallback with no text.** "Read the slide's own text" fails on image-only
    slides, and raw slide text may contain code or symbols that TTS reads literally.
    What is the fallback for those slides: the vision description, a fixed sentence,
    or silence?
13. **Vision scope for slides.** IMPLEMENTATION_NOTES 4.2 sends every slide image to the
    vision LLM. The decisions log says "only image pages to the vision LLM". Does the
    log apply to slides too, or only to reference documents?
14. **Prep trace.** BEHAVIOR 6.1 says "every retry and fallback is recorded". Is the
    manifest `status` plus a `quality` summary enough, or do we need a prep trace JSONL
    (one record per attempt) that Yaksha also loads into Bronze? `[team]`

### Data and Snowflake
15. **Who writes which tables.** The prep service would `PUT` to a Bronze stage and
    write `PARSED_PAGES` (Silver) and the Gold tables. Yaksha owns Bronze/Silver/Gold
    and dbt. Which tables does my Python write directly, and which do Yaksha's dbt
    models build? The v1 hard rule "Snowflake is used only for LLM calls and Cortex
    Search" no longer holds. Proposed new rule: prep may write its own stage and
    tables; the live path never reads event tables.
16. **Re-upload reuse scope.** Does "same file is not re-processed" apply across lessons
    or only within one lesson? If `poll_count` changes, should we re-generate but keep
    the parse? Vision output is not deterministic, so re-parsing could change the
    `llm_description` chunk ids. Is "never re-parse a known hash" acceptable as the way
    to keep chunk ids stable?
17. **Slide image storage.** Where do slide PNGs live: on the prep service's disk, or in a
    Snowflake stage that is fetched on request? This decides whether the job store and
    images survive a restart.
18. **Data residency.** Q-10 is still open. v2 sends whole course decks (not only
    synthetic text) to cross-region inference (`ANY_REGION`). Is that acceptable for the
    earlier-course slides?

### Agents and eval
19. **Remove mode 2?** v2 fixes three agents. Can I remove the 2-agent code path and
    the `AGENT_MODE` toggle entirely, keeping the v1 mode-2 numbers only in note.md and
    `docs/v1/results/`?
20. **Baseline lesson.** The Stage 4 baseline (11 questions, 5 chunks, mistral-large3)
    uses the v1 lesson and the v1 `LESSON_SEARCH`. For the "hand-written vs compiled"
    comparison, do we (a) keep the v1 lesson and service alive and compare on that set,
    or (b) re-run the hand-written prompts on the new v2 eval set as a fresh baseline
    and compare there? Proposal: both. (a) checks that the DSPy port did not regress
    (Stage 3); (b) is the main result (Stage 9).
21. **Models.** Can I pick the cheapest model that passes the probes, per role (live
    Q&A, generation, vision)? Or do you want one model everywhere? mistral-large3 is
    not a vision model, so slides need a second model.
22. **Guardian labels.** IMPLEMENTATION_NOTES 7.3 asks for human-labeled Guardian cases
    before the Guardian is used as a metric. Who labels them (you alone, or the team),
    and roughly how many?

### Report and display
23. **Post-class report.** Who triggers it: an end-of-session call from Sai's backend,
    or a CLI run? What format: an HTML page served by the prep service, or a file? Is the
    LLM summary in scope, or should the report be numbers and lists only?
24. **Correct-answer explanation.** BEHAVIOR 5.2 step 5 says the correct answer and its
    short explanation are "shown". Is it shown as text only, or also read by TTS? If TTS
    reads it, it needs the same TTS-friendly rules as scripts.

### Tooling
25. **Extra dependencies.** FastAPI's `TestClient` needs `httpx`, and Route A may need
    `PyJWT` for the key-pair JWT. Neither is in the IMPLEMENTATION_NOTES section 10
    list. OK to propose them when the stage needs them?
26. **Lint and format.** Should we adopt a lint/format tool (for example `ruff`), or
    stay without one as in v1?
27. **Old interface items.** In Stage 0, can I mark Q-02 (protected list) as dropped
    and update Q-05, Q-06, and Q-09 for v2 (for example, `poll_id` may solve Q-09)? Q-01,
    Q-03, Q-04, Q-07, Q-08, Q-10, Q-11, and Q-12 would stay open.
