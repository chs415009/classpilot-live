"""Write sample API responses and a sample session export, offline (mock, no Snowflake).

    python scripts/sample_session.py            # -> outputs/samples/

It starts the service in-process (FastAPI TestClient) on a temporary data folder, preps
the committed fixture deck, asks two questions, sends two poll results, and saves what
the front end and the pipeline would receive:

    outputs/samples/frontend/*.json    one file per request/response pair
    outputs/samples/frontend/bundle.zip
    outputs/samples/pipeline/session-sample.zip   (GET /sessions/{id}/export)

The content is the synthetic fixture deck, written by mock generators: the shapes are
real, the wording is not. Needs the dev extras (`pip install -e ".[dev]"`, for httpx).
"""

import json
import shutil
import sys
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from classpilot.service.app import create_app  # noqa: E402
from classpilot.settings import load_settings  # noqa: E402

DECK = ROOT / "tests" / "fixtures" / "deck" / "fixture_deck.pdf"
OUT = ROOT / "outputs" / "samples"
LESSON, SESSION = "lesson-sample", "session-sample"


def save(folder: Path, name: str, request, response) -> dict:
    body = response.json()
    data = {"status_code": response.status_code, "request": request, "response": body}
    (folder / f"{name}.json").write_text(json.dumps(data, indent=2) + "\n")
    return body


def main() -> None:
    settings = load_settings(overrides={"backend": "mock"})
    shutil.rmtree(OUT, ignore_errors=True)
    front, pipe = OUT / "frontend", OUT / "pipeline"
    front.mkdir(parents=True)
    pipe.mkdir(parents=True)
    with tempfile.TemporaryDirectory() as tmp:
        client = TestClient(create_app(settings, Path(tmp)))

        # before class
        req = {"lesson_id": LESSON, "title": "Sample lesson (fixture deck)"}
        save(front, "01_create_lesson", req, client.post("/lessons", json=req))
        with DECK.open("rb") as f:
            r = client.post(
                f"/lessons/{LESSON}/files",
                data={"kind": "slides"},
                files={"file": (DECK.name, f, "application/pdf")},
            )
        save(front, "02_upload_slides", {"kind": "slides", "file": DECK.name}, r)
        job = save(
            front,
            "03_process",
            {"poll_count": 3},
            client.post(f"/lessons/{LESSON}/process", json={"poll_count": 3}),
        )
        save(front, "04_job_done", None, client.get(f"/jobs/{job['job_id']}"))
        manifest = save(front, "05_manifest", None, client.get(f"/lessons/{LESSON}/manifest"))
        (front / "bundle.zip").write_bytes(client.get(f"/lessons/{LESSON}/bundle").content)

        # in class: questions
        def question(event_id: str, text: str) -> dict:
            return {
                "session_id": SESSION,
                "event_id": event_id,
                "lesson_id": LESSON,
                "anonymous_learner_id": "learner-017",
                "objective_id": manifest["segments"][0]["segment_id"],
                "question_text": text,
                "submitted_at": "2026-11-06T18:31:05Z",
            }

        for name, event_id, text in [
            ("06_question_answer", "evt-001", "Why does bronze keep raw data?"),
            ("07_question_escalate", "evt-002", "When is the parking office open?"),
            ("08_question_repeat", "evt-001", "Why does bronze keep raw data?"),
        ]:
            req = question(event_id, text)
            save(front, name, req, client.post("/questions", json=req))

        # in class: polls (the first two active polls)
        polls = [
            (seg, seg["questions"][seg["active_poll"]])
            for seg in manifest["segments"]
            if seg["active_poll"]
        ]
        for name, (seg, poll), spread in [
            ("09_poll_explain", polls[0], "wrong"),
            ("10_poll_reveal", polls[1], "right"),
        ]:
            correct = poll["correct_option"]
            wrong = next(o for o in poll["options"] if o != correct)
            counts = {o: 1 for o in poll["options"]}
            counts[wrong if spread == "wrong" else correct] = 15
            req = {
                "session_id": SESSION,
                "lesson_id": LESSON,
                "poll_id": seg["active_poll"],
                "objective_id": seg["segment_id"],
                "question_id": seg["active_poll"],
                "snapshot_time": "2026-11-06T18:40:00Z",
                "connected_students": 24,
                "answers_received": sum(counts.values()),
                "option_counts": counts,
                "correct_option": correct,
            }
            save(front, name, req, client.post("/polls/result", json=req))

        # after class
        export = client.get(f"/sessions/{SESSION}/export")
        (pipe / f"{SESSION}.zip").write_bytes(export.content)
    print(f"wrote {front} ({len(list(front.iterdir()))} files) and {pipe / f'{SESSION}.zip'}")


if __name__ == "__main__":
    main()
