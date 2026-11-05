"""Service API (Stage 8) with FastAPI's TestClient, mock backends only, no network.

TestClient runs background tasks before it returns the response, so a processed lesson
is done when `process` returns. The PPTX is converted with the committed fixture PDF
(no LibreOffice).
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from classpilot.adapters.llm import MockLLM
from classpilot.adapters.mock_prep import ScriptedPrepLLM
from classpilot.contracts.manifest import Manifest
from classpilot.prep.backends import make_generate_deps, make_parse_deps
from classpilot.service.app import create_app
from classpilot.service.context import default_backends
from classpilot.settings import Settings

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "deck"
DECK_PPTX = FIXTURE_DIR / "fixture_deck.pptx"
DECK_PDF = FIXTURE_DIR / "fixture_deck.pdf"
P = "fixture-deck-p"
STEPS = [
    "queued",
    "converting",
    "uploading",
    "parsing",
    "chunking",
    "generating",
    "checking",
    "assembling",
    "done",
]
FAKE_SECRETS = {
    "SNOWFLAKE_ACCOUNT": "fakeorg-fakeacct42",
    "SNOWFLAKE_USER": "FAKE_SVC_USER_XYZ",
    "SNOWFLAKE_PRIVATE_KEY_FILE": "/very/secret/path/rsa_key.p8",
    "SNOWFLAKE_PRIVATE_KEY_PASSWORD": "hunter2-not-real",
}


class FixturePdf(dict):
    """pdf_for by file name: an uploaded fixture_deck.pptx converts with the fixture PDF."""

    def get(self, path, default=None):
        return DECK_PDF if Path(path).name == DECK_PPTX.name else default


def make_client(tmp_path, settings=None, **overrides):
    settings = settings or Settings()
    backends = default_backends(settings, tmp_path)

    def parse_deps():
        deps = make_parse_deps(settings, tmp_path / "tables", tmp_path / "convert")
        deps.pdf_for = FixturePdf()
        return deps

    backends.parse_deps = parse_deps
    for name, value in overrides.items():
        setattr(backends, name, value)
    return TestClient(create_app(settings, tmp_path, backends))


@pytest.fixture
def client(tmp_path):
    return make_client(tmp_path)


def no_uploads(root: Path) -> bool:
    uploads = root / "lessons" / "l1" / "uploads"
    return not uploads.exists() or list(uploads.iterdir()) == []


def upload(client, lesson_id, path=DECK_PPTX, kind="slides", name=None, data=None):
    content = data if data is not None else path.read_bytes()
    files = {"file": (name or path.name, content, "application/octet-stream")}
    return client.post(f"/lessons/{lesson_id}/files", data={"kind": kind}, files=files)


def processed(client, lesson_id="l1", **body):
    assert client.post("/lessons", json={"lesson_id": lesson_id}).status_code == 201
    assert upload(client, lesson_id).status_code == 201
    response = client.post(f"/lessons/{lesson_id}/process", json=body or None)
    assert response.status_code == 202, response.text
    return client.get(f"/jobs/{response.json()['job_id']}").json()


# ---------- lessons ----------


def test_create_lesson_with_and_without_an_id(client):
    made = client.post("/lessons", json={"title": "Week 1"}).json()
    assert made["lesson_id"].startswith("lesson-") and made["title"] == "Week 1"
    assert client.post("/lessons").status_code == 201  # no body at all
    assert client.post("/lessons", json={"lesson_id": "info-l1"}).status_code == 201
    assert client.post("/lessons", json={"lesson_id": "info-l1"}).status_code == 409
    assert client.post("/lessons", json={"lesson_id": "Bad/Id"}).status_code == 422
    assert client.get("/lessons/info-l1").json()["files"] == []
    assert client.get("/lessons/nope").status_code == 404


# ---------- uploads: checks before any work ----------


def test_upload_slides(client):
    client.post("/lessons", json={"lesson_id": "l1"})
    body = upload(client, "l1").json()
    assert body["kind"] == "slides" and body["format"] == "pptx" and body["reused"] is False
    assert len(body["file_id"]) == 64 and body["size_bytes"] == DECK_PPTX.stat().st_size
    assert client.get("/lessons/l1").json()["files"][0]["name"] == "fixture_deck.pptx"


@pytest.mark.parametrize(
    ("kind", "name", "data", "code"),
    [
        ("slides", "notes.docx", b"PK\x03\x04 docx", 415),  # DOCX is not a slide format
        ("reference", "deck.pptx", b"PK\x03\x04 pptx", 415),
        ("slides", "deck.key", b"anything", 415),
        ("slides", "fake.pdf", b"<html>not a pdf</html>", 415),  # wrong magic bytes
        ("reference", "fake.docx", b"%PDF-1.7 not a zip", 415),
    ],
)
def test_wrong_type_is_rejected_before_any_work(tmp_path, kind, name, data, code):
    calls = []
    client = make_client(tmp_path, parse_deps=lambda: calls.append("parse"))
    client.post("/lessons", json={"lesson_id": "l1"})
    response = upload(client, "l1", kind=kind, name=name, data=data)
    assert response.status_code == code, response.text
    assert client.get("/lessons/l1").json()["files"] == []
    assert no_uploads(tmp_path) and calls == []


def test_too_large_is_413_and_nothing_is_kept(tmp_path):
    settings = Settings(service={"max_upload_mb": 1})
    client = make_client(tmp_path, settings)
    client.post("/lessons", json={"lesson_id": "l1"})
    big = b"%PDF-1.7\n" + b"0" * (1024 * 1024)
    response = upload(client, "l1", name="big.pdf", data=big)
    assert response.status_code == 413
    assert no_uploads(tmp_path)


def test_upload_path_in_the_name_is_stripped(client):
    client.post("/lessons", json={"lesson_id": "l1"})
    body = upload(client, "l1", name="../../etc/fixture_deck.pptx").json()
    assert body["name"] == "fixture_deck.pptx"


def test_upload_to_a_missing_lesson_is_404(client):
    assert upload(client, "nope").status_code == 404


# ---------- the same file twice ----------


def test_same_file_twice_in_a_lesson_is_one_entry(client):
    client.post("/lessons", json={"lesson_id": "l1"})
    upload(client, "l1")
    assert upload(client, "l1").json()["reused"] is True
    assert len(client.get("/lessons/l1").json()["files"]) == 1


def test_same_file_in_another_lesson_is_reused_and_not_parsed_again(tmp_path):
    parsers = []

    def counting_parse_deps():
        deps = make_parse_deps(Settings(), tmp_path / "tables", tmp_path / "convert")
        deps.pdf_for = FixturePdf()
        parsers.append(deps.vision)
        return deps

    client = make_client(tmp_path, parse_deps=counting_parse_deps)
    processed(client, "l1")
    client.post("/lessons", json={"lesson_id": "l2"})
    assert upload(client, "l2").json()["reused"] is True
    job = client.get(f"/jobs/{client.post('/lessons/l2/process').json()['job_id']}").json()
    assert job["status"] == "done"
    assert len(parsers[0].calls) == 2 and parsers[1].calls == []  # vision only once


# ---------- processing ----------


def test_process_runs_every_step_in_order_and_serves_manifest_and_slides(client):
    job = processed(client)
    assert job["status"] == "done", job
    assert job["steps"] == STEPS and job["error"] is None
    assert job["llm_calls"] == 38 and job["failures"] == []
    manifest = Manifest.model_validate(client.get("/lessons/l1/manifest").json())
    assert [s.active_poll for s in manifest.segments] == ["q-01", "q-02", "q-03"]
    png = client.get(f"/lessons/l1/slides/{P}01")
    assert png.status_code == 200 and png.headers["content-type"] == "image/png"
    assert png.content.startswith(b"\x89PNG")
    assert client.get(f"/lessons/l1/slides/{P}01.png").status_code == 200
    assert client.get("/lessons/l1").json()["has_manifest"] is True


def test_progress_reports_parsing_pages(tmp_path):
    seen = []
    client = make_client(tmp_path)
    store = client.app.state.ctx.jobs
    real_update = store.update

    def spy(job_id, **fields):
        if "progress" in fields:
            seen.append((fields.get("step"), fields["progress"].done, fields["progress"].total))
        real_update(job_id, **fields)

    store.update = spy
    processed(client)
    assert ("parsing", 6, 6) in seen
    generating = [(d, t) for s, d, t in seen if s == "generating"]
    assert generating[-1] == (11, 11)


def test_poll_count_in_the_request(client):
    processed(client, poll_count=1)
    manifest = client.get("/lessons/l1/manifest").json()
    assert [s["active_poll"] for s in manifest["segments"]] == ["q-01", None, None]


def test_item_failures_are_listed_in_the_job(tmp_path):
    unsupported = {
        "claims": [{"claim": "Made up.", "chunk_id": None}],
        "verdict": "fail",
        "reason": "no",
    }

    def rigged(settings, material):
        deps = make_generate_deps(settings, material)
        deps.llm = ScriptedPrepLLM({"script_guardian": [unsupported, unsupported]})
        return deps

    client = make_client(tmp_path, generate_deps=rigged)
    job = processed(client)
    assert job["status"] == "done"
    assert job["failures"] == [
        {
            "item": f"script {P}01",
            "status": "fallback",
            "detail": "slide_text",
            "problems": ["Not supported by the cited chunks: 'Made up.'"],
        }
    ]


def test_a_failing_step_fails_the_job_with_a_message_and_keeps_the_old_manifest(tmp_path):
    state = {"fail": False}

    def maybe_failing(settings, material):
        if state["fail"]:
            raise RuntimeError("generator exploded")
        return make_generate_deps(settings, material)

    client = make_client(tmp_path, generate_deps=maybe_failing)
    processed(client)
    before = client.get("/lessons/l1/manifest").json()
    state["fail"] = True
    job = client.get(f"/jobs/{client.post('/lessons/l1/process').json()['job_id']}").json()
    assert job["status"] == "failed" and job["step"] == "failed"
    assert job["error"] == "RuntimeError: generator exploded"
    assert job["steps"][-2:] == ["chunking", "failed"]
    assert client.get("/lessons/l1/manifest").json() == before


def test_process_without_slides_or_while_running_is_409(client):
    client.post("/lessons", json={"lesson_id": "l1"})
    assert client.post("/lessons/l1/process").status_code == 409  # no slides
    upload(client, "l1")
    client.app.state.ctx.jobs.create("l1", 5)  # a job still queued
    assert client.post("/lessons/l1/process").status_code == 409


def test_missing_things_are_404(client):
    assert client.get("/jobs/job-nope").status_code == 404
    assert client.get("/lessons/nope/manifest").status_code == 404
    client.post("/lessons", json={"lesson_id": "l1"})
    assert client.get("/lessons/l1/manifest").status_code == 404  # not processed yet
    processed(client, "l2")
    assert client.get(f"/lessons/l2/slides/{P}99").status_code == 404
    assert client.get("/lessons/l2/slides/..%2F..%2Flesson.json").status_code == 404
    assert client.get("/lessons/nope/slides/x-p01").status_code == 404


def test_cors_allows_the_configured_origin(client):
    response = client.options(
        "/lessons",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"},
    )
    assert response.headers.get("access-control-allow-origin") == "http://localhost:5173"
    other = client.options(
        "/lessons",
        headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "POST"},
    )
    assert "access-control-allow-origin" not in other.headers


# ---------- live: questions ----------


def question(text, lesson_id="l1", event_id="evt-1"):
    return {
        "session_id": "session-1",
        "event_id": event_id,
        "lesson_id": lesson_id,
        "anonymous_learner_id": "learner-1",
        "question_text": text,
        "submitted_at": "2026-11-05T18:31:05Z",
    }


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def test_question_is_answered_and_traced(tmp_path):
    client = make_client(tmp_path)
    processed(client)
    response = client.post("/questions", json=question("Why does bronze keep raw data?"))
    assert response.status_code == 200, response.text
    decision = response.json()
    assert decision["path"] == "question" and decision["action"] == "answer"
    assert decision["citations"] and all(c.startswith(P) for c in decision["citations"])
    records = read_jsonl(tmp_path / "traces.jsonl")
    runs = [r for r in records if r["record_type"] == "run"]
    assert [r["run_id"] for r in runs] == [decision["decision_id"]]
    assert {r["record_type"] for r in records} >= {"run", "node", "llm_call", "retrieval"}
    log = read_jsonl(tmp_path / "decision_log.jsonl")
    assert [entry["decision"]["decision_id"] for entry in log] == [decision["decision_id"]]


def test_out_of_scope_question_escalates(client):
    processed(client)
    decision = client.post("/questions", json=question("When is the parking office open?")).json()
    assert decision["action"] == "escalate" and decision["escalation_reason"] == "out_of_scope"


def test_question_llm_timeout_escalates_instead_of_hanging(tmp_path):
    settings = Settings(llm={"timeout_seconds": 0.1})
    client = make_client(tmp_path, settings, live_llm=lambda: MockLLM(delays={"analyst": 2}))
    processed(client)
    response = client.post("/questions", json=question("Why does bronze keep raw data?"))
    assert response.status_code == 200
    assert response.json()["action"] == "escalate"
    assert response.json()["escalation_reason"] == "llm_error"


def test_question_for_a_lesson_without_manifest_is_404(client):
    client.post("/lessons", json={"lesson_id": "l1"})
    assert client.post("/questions", json=question("Why?")).status_code == 404
    assert client.post("/questions", json={"lesson_id": "l1"}).status_code == 422


# ---------- live: polls ----------


def evidence(counts, poll_id="q-01", correct="B", session="session-1", lesson_id="l1"):
    return {
        "session_id": session,
        "lesson_id": lesson_id,
        "poll_id": poll_id,
        "objective_id": "seg-01",
        "question_id": poll_id,
        "snapshot_time": "2026-11-05T18:30:40Z",
        "connected_students": 24,
        "answers_received": sum(counts.values()),
        "option_counts": counts,
        "correct_option": correct,
    }


def test_poll_explain_matches_the_manifest_and_is_traced(tmp_path):
    client = make_client(tmp_path)
    processed(client)
    manifest = client.get("/lessons/l1/manifest").json()
    q01 = manifest["segments"][0]["questions"]["q-01"]
    response = client.post("/polls/result", json=evidence({"A": 15, "B": 3, "C": 1, "D": 1}))
    decision = response.json()
    mid = q01["known_wrong"]["A"]
    rid = manifest["misconceptions"][mid]["remediation"]
    remediation = manifest["remediations"][rid]
    assert decision["action"] == "explain" and decision["option"] == "A"
    assert decision["misconception_id"] == mid and decision["remediation_id"] == rid
    assert decision["remediation_text"] == remediation["text"]
    assert decision["show_slide"] == remediation["show_slide"]
    assert decision["correct_option"] == q01["correct_option"]
    records = read_jsonl(tmp_path / "traces.jsonl")
    assert {r["record_type"] for r in records} >= {"run", "node", "poll_evidence"}
    assert len(read_jsonl(tmp_path / "decision_log.jsonl")) == 1


def test_poll_reveal_when_most_answers_are_right(client):
    processed(client)
    decision = client.post("/polls/result", json=evidence({"A": 1, "B": 15, "C": 1, "D": 1}))
    assert decision.json()["action"] == "reveal"
    assert decision.json()["correct_option"] == "B" and decision.json()["remediation_text"] is None


def test_repeated_poll_result_returns_the_first_decision(tmp_path):
    client = make_client(tmp_path)
    processed(client)
    first = client.post("/polls/result", json=evidence({"A": 15, "B": 3, "C": 1, "D": 1})).json()
    again = client.post("/polls/result", json=evidence({"A": 1, "B": 19, "C": 0, "D": 0})).json()
    assert again == first
    assert len(read_jsonl(tmp_path / "decision_log.jsonl")) == 1  # not traced twice
    other = client.post("/polls/result", json=evidence({"A": 1, "B": 19}, session="session-2"))
    assert other.json()["action"] == "reveal"


def test_poll_errors(tmp_path):
    client = make_client(tmp_path)
    processed(client)
    counts = {"A": 15, "B": 3, "C": 1, "D": 1}
    assert client.post("/polls/result", json=evidence(counts, poll_id="q-99")).status_code == 404
    assert client.post("/polls/result", json=evidence(counts, lesson_id="nope")).status_code == 404
    assert client.post("/polls/result", json=evidence(counts, correct="C")).status_code == 422
    # A dropped poll is not an active poll.
    path = tmp_path / "lessons" / "l1" / "prep" / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest["segments"][0]["questions"]["q-01"].update(status="dropped", known_wrong={})
    manifest["segments"][0]["active_poll"] = None
    path.write_text(json.dumps(manifest))
    assert client.post("/polls/result", json=evidence(counts)).status_code == 404
    assert read_jsonl(tmp_path / "decision_log.jsonl") == []


# ---------- credentials never leave the service ----------


def test_no_credential_value_in_responses_traces_or_logs(tmp_path, monkeypatch, caplog):
    for key, value in FAKE_SECRETS.items():
        monkeypatch.setenv(key, value)

    def leaky(settings, material):
        raise RuntimeError(
            f"connect failed for {FAKE_SECRETS['SNOWFLAKE_USER']}"
            f"@{FAKE_SECRETS['SNOWFLAKE_ACCOUNT']} "
            f"with key {FAKE_SECRETS['SNOWFLAKE_PRIVATE_KEY_FILE']}"
        )

    client = make_client(tmp_path, generate_deps=leaky)
    texts = []
    job = processed(client)
    texts.append(json.dumps(job))
    assert job["status"] == "failed" and "<SNOWFLAKE_USER>" in job["error"]

    client2 = make_client(tmp_path / "ok")
    texts.append(json.dumps(processed(client2)))
    texts.append(client2.post("/questions", json=question("Why does bronze keep raw data?")).text)
    texts.append(client2.post("/polls/result", json=evidence({"A": 15, "B": 3})).text)
    texts.append(client2.get("/lessons/l1/manifest").text)
    for path in (tmp_path / "ok").rglob("*"):
        if path.is_file() and path.suffix in (".json", ".jsonl", ".md"):
            texts.append(path.read_text())
    texts.append(caplog.text)
    joined = "\n".join(texts)
    for value in FAKE_SECRETS.values():
        assert value not in joined
