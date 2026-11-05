# CLAUDE.md — ClassPilot Live (team repo)

Shared instructions for everyone who works in this repo with Claude Code. Rules for one
part live in `.claude/rules/<part>.md` and load when Claude works on that part's files.
Personal preferences go in `CLAUDE.local.md` (gitignored), never in this file.

## Project

ClassPilot Live runs a full class session when the professor is unavailable: the
professor uploads slides and readings, the system generates a spoken script per slide,
polls, and an explanation for every wrong poll option (checked automatically), runs the
session with TTS and polls, answers students' private questions from the materials, and
produces one post-class report. 3-person course project (data engineering + GenAI).
Team-level behavior: `docs/v2/CLASSPILOT_BEHAVIOR.md`.

## Parts, owners, folders

| Part | Owner | Folders | Part rules |
|---|---|---|---|
| Agent part: prep service, parse layer, generators, live Q&A and poll endpoints, trace records, post-class report | Han-Sheng | `src/classpilot/`, `tests/`, `config/`, `sql/`, `scripts/`, `content/`, `scenarios/`, `eval/`, `compiled/`, `docs/agent/`, `docs/v1/`, `docs/v2/`, `pyproject.toml` | `.claude/rules/agent.md` |
| Front end + live backend (WebSocket, Redis, TTS playback, polls) | Sai | to be added, e.g. `frontend/` **[team]** | to be added |
| Data pipeline (Snowflake star schema, dbt) | Yaksha | to be added, e.g. `pipeline/` **[team]** | to be added |

Shared files: `CLAUDE.md`, `README.md`, `interface_questions.md`, `LICENSE`, `.gitignore`,
`.env.example`, `scripts/check_secrets.sh`.

- Work inside your own part's folders. To change another part's files or a shared file,
  ask its owner first (a pull request is the usual way).
- A new part adds its folder, its `.claude/rules/<part>.md` (with `paths:` for its
  folders), and a row in the table above.

## Branches

- Each person works on their own branch and merges into `main` through a pull request.
  In the early phase, Han-Sheng commits to `main` directly.
- Commit, push, or merge only when the user asks. Commit messages are in English.

## Shared rules (all parts)

- **The repo is public.** Never put credentials in code, logs, traces, docs, or commits.
  Account-specific values (account identifier, region, login user, key path) live only in
  `.env` (gitignored); committed files use placeholders. Service user and other object
  names are configurable defaults. `materials/` (real course content) and `outputs/` are
  never committed.
- **Before every push:** `scripts/check_secrets.sh --history` passes, and the user reviews
  the file list (`git ls-files`) and the commits being pushed. Release-blocking.
- **Snowflake is a shared account.** Never run anything that uses Snowflake credits
  without asking the user first (say what runs and roughly how many LLM calls). Never run
  SQL that creates, alters, suspends, or drops objects without showing it first.
- Ask before adding any dependency.
- Tests never call Snowflake or other network services.
- **Interfaces between parts** (manifest, HTTP API shapes, decision and trace records,
  table names) are recorded in `interface_questions.md`. The part that owns an interface
  may decide it first and record it there as `decided`, with the reason; any other part
  can reopen it by writing what it needs changed. Items that need another part's input
  stay `open`.
- `[verify]`: check current official docs (or a small approved probe) before relying on
  it; do not guess API names. `[team]`: an interface between parts, recorded in `interface_questions.md` as above.
- Docs, code, comments, and commit messages are in English.

## Where things are

- Team behavior: `docs/v2/CLASSPILOT_BEHAVIOR.md`
- Interface items between parts: `interface_questions.md`
- Agent part: `.claude/rules/agent.md`, `docs/v2/IMPLEMENTATION_NOTES.md`,
  `docs/v2/STAGES.md`, dev log `docs/agent/note.md`
- v1 archive (history only): `docs/v1/`
