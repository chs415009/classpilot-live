# Development notes (v2)

Log of changes, decisions, findings, and open questions per stage. Newest entries at the
bottom of each stage. Stage plan: `docs/v2/STAGES.md`. The v1 log (Stages 1-4, including
the Stage 4 baseline numbers) is archived in `docs/v1/note_v1.md`.

Entry format: `- YYYY-MM-DD [type] text` where type is one of `change` (differs from
CLAUDE.md or the plan), `decision`, `finding`, `todo`, `question`, `result`.

---

Design: `docs/v2/CLASSPILOT_BEHAVIOR.md` (behavior), `docs/v2/IMPLEMENTATION_NOTES.md`
(implementation, decisions log in section 13), `docs/v2/ANALYSIS.md` (v1 reuse map, repo
decision), `docs/v2/STAGES.md` (stage plan). v1 rules and contracts: `docs/v1/CLAUDE_v1.md`.

## Stage 0: Repository setup and v2 docs

- 2026-11-04 [change] Direction change to v2: the professor only uploads materials and
  reads the post-class report. The system generates per-slide scripts, polls,
  misconceptions, and explanations before class and checks them automatically (Guardian,
  one retry with feedback, fallback). No pre-approved branches, no professor review, no
  protected-question check, no 2-agent mode. New parts: prep service, parse layer,
  generators, live endpoints, trace records for the team star schema, post-class report.
- 2026-11-04 [decision] New repo `classpilot-live`, package `classpilot`, seeded with the
  cleaned v1 code (ANALYSIS.md section 2). The old `agents_demo/` folder was never a git
  repository, so there was no history to carry or scan. It stays as the local v1
  reference.
- 2026-11-04 [decision] The repo will become public. Account locator, region, and key
  path replaced with placeholders before the first commit. Service user and other object
  names stay as configurable defaults. `scripts/check_secrets.sh` (grep-based) is
  release-blocking before every push.
- 2026-11-04 [change] `ruff` adopted (dev): rules E, F, I, B, UP; line length 100. The
  prompt files (`nodes/*.py`) and `report.py` ignore E501 so the v1 prompt text stays
  byte-identical to the Stage 4 baseline (checked) until DSPy replaces it. `zip(...,
  strict=True)` added in `scripts/smoke_test.py` (B905).
- 2026-11-04 [finding] (docs, checked 2026-11-04) `IDENTIFIER($var)` with a session
  variable is documented by example only for `USE SCHEMA`, `CREATE TABLE`, `INSERT`,
  `SELECT`, `DROP TABLE`; the docs say "in some cases" and do not list `CREATE WAREHOUSE`,
  `USE ROLE`, `GRANT`, `CREATE USER`, or `CREATE CORTEX SEARCH SERVICE`.
  https://docs.snowflake.com/en/sql-reference/identifier-literal ,
  https://docs.snowflake.com/en/sql-reference/session-variables
- 2026-11-04 [change] Because of that finding, the Stage 0 task "SQL object names become
  variables" is deferred: the v1 SQL keeps its object names as defaults (with
  `IF NOT EXISTS`, still rerunnable on a new account). Stage 5 rewrites the SQL and checks
  variable support with a small probe (with approval) before relying on it.
- 2026-11-04 [question] Git author email of the commits is a personal address, which is
  public once pushed. Use a GitHub noreply address for this repo? The `--history` mode of
  the secret check fails until this is decided.
  -> [decision] User: keep the personal git email (public by choice). The history check
  allows the address from `git config user.email` (not written into the repo) plus
  noreply addresses.
- 2026-11-04 [change] User: all v1 docs are archived and v1 interface items are ignored.
  The v1 dev log moved to `docs/v1/note_v1.md` and v1 items Q-01 to Q-12 to
  `docs/v1/interface_questions_v1.md`. `interface_questions.md` keeps only v2 items
  (Q-13 to Q-21; numbering continues so archived references stay unique). References to
  v1 items in CLAUDE.md and the v2 docs were removed.
- 2026-11-04 [change] User: no date-driven planning; the user decides when stages run.
  Removed the trial-expiry check from Stage 0 and the trial-date dependency of Stages 1
  and 9.
