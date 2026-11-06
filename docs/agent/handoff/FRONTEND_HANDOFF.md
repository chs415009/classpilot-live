# Agent service: handoff for the front end and live backend

For Sai. This is what the agent service (prep, live Q&A, poll rule) gives you and what
it expects from you. The interface is kept small on purpose: everything about the UI,
Redis, WebSocket, TTS, timing, and how you store things is your choice.

Status: works end to end in mock mode. Field names are drafts (`v2-draft`) recorded in
`interface_questions.md` (Q-13, Q-14, Q-16, Q-18, Q-19). If something does not fit your
design, tell Han-Sheng; renames are cheap.

## 1. Run it locally (no Snowflake needed)

```bash
git clone <repo> && cd classpilot-live
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
uvicorn classpilot.service.app:create_app --factory --port 8000
# OpenAPI docs and a test UI: http://localhost:8000/docs
```

Mock mode is the default: no credentials, no cost, deterministic but simple answers.
Real answers (Snowflake Cortex) need Han-Sheng's `.env`; the API is identical.

Sample requests and responses, written by a mock class run:

```bash
python scripts/sample_session.py
# outputs/samples/frontend/01_create_lesson.json ... 10_poll_reveal.json, bundle.zip
```

Each file holds `status_code`, `request`, and `response`. Use them as fixtures for
your own tests. The wording is synthetic; the shapes are real.

CORS: allowed origins are `service.cors_origins` in `config/settings.yaml`
(now `http://localhost:3000` and `http://localhost:5173`). Add yours there.

## 2. The whole flow

```
BEFORE CLASS (upload page)
  POST /lessons                      create a lesson
  POST /lessons/{id}/files           upload slides (pptx/pdf) and readings (pdf/docx)
  POST /lessons/{id}/process         start prep, returns job_id
  GET  /jobs/{job_id}                poll every 1-2 s until status "done" (or "failed")
  GET  /lessons/{id}/bundle          zip: manifest.json + slides/*.png  -> store it your way

IN CLASS (your live backend calls these; nothing else)
  POST /questions                    one student question -> answer or escalate
  POST /polls/result                 one closed poll      -> explain or reveal

AFTER CLASS
  nothing required from you (the pipeline pulls the session data itself)
```

The agent service keeps no live state for you: no Redis, no WebSocket, no session
start or end call. Each live call is one HTTP request and one decision.

## 3. Before class

**Create, upload, process.** Errors are always `{"detail": "<message>"}`.

| Call | Body | Success | Errors |
|---|---|---|---|
| `POST /lessons` | `{"lesson_id"?: "info6205-l1", "title"?: "..."}` (id: lowercase, digits, `-`; generated if left out) | 201 `Lesson` | 409 id exists |
| `POST /lessons/{id}/files` | multipart: `kind` = `slides` or `reference`, `file` | 201 `LessonFile` | 404, 413 over 100 MB, 415 wrong type |
| `POST /lessons/{id}/process` | `{"poll_count"?: 0-20}` (default 5) | 202 `{job_id, lesson_id, status}` | 409 no slides, or a job is running |
| `GET /jobs/{job_id}` | | 200 `Job` | 404 |

`Job` has `status` (`queued | running | done | failed`), `step` (`queued, converting,
uploading, parsing, chunking, generating, checking, assembling, done`), `progress`
(`{done, total, detail}`, e.g. pages while parsing), `failures` (items that used a
fallback or were dropped; informational), and `error` when failed. Prep of a 14-slide
deck takes about 7 minutes on Cortex, seconds in mock. Jobs live in memory: after a
service restart, check `GET /lessons/{id}` (`has_manifest`) instead.

**Get the class content.** `GET /lessons/{id}/bundle` returns a zip with
`manifest.json` and `slides/<slide_id>.png`. Fetch it once after `done` and keep it
wherever you like. (`GET /lessons/{id}/manifest` and
`GET /lessons/{id}/slides/{slide_id}` also exist for single files.)

### What to read in the manifest

```json
{
  "lesson_id": "info6205-l1",
  "params": {"poll_answer_seconds": 60, "min_responses": 5, "wrong_ratio_threshold": 0.6},
  "slides": {
    "l1-slides-p01": {"order": 1, "image_ref": "slides/l1-slides-p01.png",
                      "script": "Welcome ...", "status": "ok"}
  },
  "segments": [{
    "segment_id": "seg-01",
    "objective": "...",
    "slides": ["l1-slides-p01", "l1-slides-p02"],
    "questions": {"q-01": {"text": "...", "options": {"A": "...", "B": "...", "C": "...", "D": "..."},
                           "correct_option": "B", "known_wrong": {...}, "segment": "seg-01",
                           "status": "ok"}},
    "active_poll": "q-01"
  }],
  "misconceptions": {...},
  "remediations": {...}
}
```

You need only:
- `slides`: play them by `order`; show `image_ref` (a path inside the bundle) and read
  `script` with TTS.
- `segments[].slides` and `segments[].active_poll`: after the **last slide of a
  segment**, if `active_poll` is not `null`, run that poll:
  `segments[].questions[active_poll]` gives `text`, `options`, and `correct_option`.
  Answer time is `params.poll_answer_seconds`.
- Ignore every question that is not the `active_poll` (dropped or spare polls stay in
  `questions` for the report; a dropped one may have empty text).
- You do not need `known_wrong`, `misconceptions`, or `remediations`: the poll
  decision returns the explanation to play.

## 4. In class: student questions

`POST /questions`, one per student question.

```json
{"session_id": "session-2026-11-06-a", "event_id": "evt-001", "lesson_id": "info6205-l1",
 "anonymous_learner_id": "learner-017", "objective_id": "seg-01",
 "question_text": "Why do we keep raw data in Bronze?", "submitted_at": "2026-11-06T18:31:05Z"}
```

- `session_id`: you create it, one per class session. The analytics pipeline groups by
  it, so keep it unique and stable for the whole class.
- `event_id`: you create it, unique per question within the session. It is the
  question's identity: sending the same (`session_id`, `event_id`) again returns the
  first decision, runs no LLM, and is not logged twice (also after a service restart;
  a repeat sent while the first is still running waits for it). So retries are safe;
  a new question needs a new `event_id`.
- `objective_id`: optional, the current `segment_id` if you know it.
- `anonymous_learner_id`: any stable pseudonym; never a name or email.

Response: always 200 with a `Decision` (unused fields are `null`):

```json
{"decision_id": "dec-5e6f7a8b", "session_id": "session-2026-11-06-a", "path": "question",
 "action": "answer", "answer_text": "We keep raw data unchanged so we can replay it.",
 "citations": ["l1-slides-p03-c1"], "confidence": 0.84, "escalation_reason": null, ...}
```

- `action: "answer"`: show `answer_text` **only to the student who asked**. `citations`
  are chunk ids; the part before `-c<N>` is the page (`l1-slides-p03` = slide 3,
  `l1-pdf-p02` = page 2 of a reading), if you want to show sources.
- `action: "escalate"`: show a message such as "Good question. It is saved for your
  professor and will be answered after class." `escalation_reason` is one of
  `out_of_scope`, `assignment_like`, `low_confidence`, `unsupported`, `llm_error`; it
  is for the professor, you do not need to show it.
- An LLM error or timeout is also a 200 `escalate` (`llm_error`), never a 5xx.
- Timing: about 5 s on average in our Cortex test (escalations by the first step take
  1-2 s, the slowest answer 15 s), at most about 30 s (the sum of the per-call
  timeouts). Show a waiting state; set your HTTP client timeout to about 35 s.
- Errors: 404 if the lesson has no manifest; 422 for a malformed body.

Questions are independent, so you can send several at once (queue them in Redis or
not; the service handles concurrent calls).

## 5. In class: polls

When a poll's answer time ends, send the counts once:

```json
{"session_id": "session-2026-11-06-a", "lesson_id": "info6205-l1", "poll_id": "q-01",
 "objective_id": "seg-01", "question_id": "q-01", "snapshot_time": "2026-11-06T18:40:00Z",
 "connected_students": 24, "answers_received": 21,
 "option_counts": {"A": 3, "B": 13, "C": 4, "D": 1}, "correct_option": "B"}
```

(`poll_id` = the `active_poll` id; `question_id` is the same value, kept from the team
README; `correct_option` must equal the manifest's.)

Response, decided by a rule, no LLM, immediate:

- `action: "explain"`: many students picked the same wrong option. Pause the lecture,
  read `remediation_text` with TTS while showing slide `show_slide` (a slide id from
  the manifest), then reveal `correct_option`, then continue where you stopped.
  (`option` is the wrong option being explained.)
- `action: "reveal"`: reveal `correct_option` and continue.

How to pause, show, and resume is yours. Each poll triggers at most once: the same
(`session_id`, `poll_id`) again returns the first decision. Errors: 404 for an unknown
or dropped `poll_id`; 422 if `correct_option` differs from the manifest.

## 6. What is yours to decide

Anything not listed above: UI, how students join, Redis and WebSocket design, the
"next slide" control, TTS voice and speed, poll timer, whether to queue questions,
where you store the bundle, retries. The professor's post-class report is deferred and
not part of this interface.

## 7. Reference

- Shapes in code: `src/classpilot/contracts/live.py` (question, poll evidence,
  decision), `src/classpilot/contracts/manifest.py`, `src/classpilot/service/schemas.py`
- Decisions and history: `interface_questions.md` Q-13, Q-14, Q-16, Q-18, Q-19
- Behavior of the whole system: `docs/v2/CLASSPILOT_BEHAVIOR.md` sections 4-5
