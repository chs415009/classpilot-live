"""`prep run` / `prep generate` end to end on the fixture deck in mock mode.

The mock manifest of the fixture deck is committed (tests/fixtures/deck/manifest_mock.json)
for review and as a golden file. After an intended change, rewrite it with
`UPDATE_GOLDEN=1 pytest tests/test_prep_cli.py`.
"""

import json
import os
from pathlib import Path

import pytest

from classpilot import cli
from classpilot.contracts.manifest import load_manifest

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "deck"
DECK_PPTX = FIXTURE_DIR / "fixture_deck.pptx"
DECK_PDF = FIXTURE_DIR / "fixture_deck.pdf"
GOLDEN = FIXTURE_DIR / "manifest_mock.json"
LESSON = "fixture-lesson"


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    for name, sub in [
        ("PREP_TABLES_DIR", "tables"),
        ("CONVERT_DIR", "convert"),
        ("PARSE_REPORT_DIR", "parse"),
        ("PREP_DIR", "prep"),
    ]:
        monkeypatch.setattr(cli, name, tmp_path / sub)
    real = cli.build_parse_deps

    def with_fixture_pdf(settings):
        deps = real(settings)
        deps.convert_root = tmp_path / "convert"
        deps.pdf_for = {DECK_PPTX: DECK_PDF}  # no LibreOffice in tests
        return deps

    monkeypatch.setattr(cli, "build_parse_deps", with_fixture_pdf)
    return tmp_path


def run_cli(*argv) -> int:
    with pytest.raises(SystemExit) as code:
        cli.main(list(argv))
    return code.value.code


def test_prep_run_turns_the_fixture_deck_into_a_valid_manifest(dirs, capsys):
    assert run_cli("prep", "run", "--backend", "mock", "--lesson", LESSON, str(DECK_PPTX)) == 0
    out_dir = dirs / "prep" / LESSON
    manifest = load_manifest(out_dir / "manifest.json")  # validates against the model
    report = json.loads((out_dir / "generation_report.json").read_text())
    assert report["backend"] == "mock" and report["poll_count"] == 5
    assert sorted(p.name for p in (out_dir / "slides").iterdir()) == [
        f"fixture-deck-p{n:02d}.png" for n in range(1, 7)
    ]
    printed = capsys.readouterr().out
    assert "slides: ok 6" in printed and "active polls: 3" in printed

    produced = json.loads((out_dir / "manifest.json").read_text())
    if os.environ.get("UPDATE_GOLDEN"):
        GOLDEN.write_text(json.dumps(produced, indent=2) + "\n")
    assert produced == json.loads(GOLDEN.read_text()), "rerun with UPDATE_GOLDEN=1 if intended"
    assert manifest.lesson_id == LESSON


def test_prep_generate_with_another_poll_count_does_not_parse(dirs, monkeypatch, capsys):
    assert run_cli("prep", "run", "--lesson", LESSON, str(DECK_PPTX)) == 0

    def no_parse(settings):
        raise AssertionError("prep generate must not build the parse adapters")

    monkeypatch.setattr(cli, "build_parse_deps", no_parse)
    capsys.readouterr()
    assert run_cli("prep", "generate", "--lesson", LESSON, "--poll-count", "1") == 0
    manifest = load_manifest(dirs / "prep" / LESSON / "manifest.json")
    assert [s.active_poll for s in manifest.segments] == ["q-01", None, None]
    assert "poll_count=1" in capsys.readouterr().out


def test_prep_generate_unknown_lesson_fails_cleanly(dirs, capsys):
    assert run_cli("prep", "generate", "--lesson", "nope") == 1
    assert "no parsed slides" in capsys.readouterr().out


def test_prep_run_needs_files(dirs):
    assert run_cli("prep", "run", "--lesson", LESSON) == 2  # argparse error


def test_prep_check_reruns_the_checks_and_writes_the_review(dirs, capsys):
    assert run_cli("prep", "run", "--lesson", LESSON, str(DECK_PPTX)) == 0
    out_dir = dirs / "prep" / LESSON
    (out_dir / "review.md").unlink()
    capsys.readouterr()
    assert run_cli("prep", "check", "--lesson", LESSON) == 0
    assert "check: OK" in capsys.readouterr().out
    assert (out_dir / "review.md").read_text().startswith(f"# Generation review: {LESSON}")
    report = json.loads((out_dir / "generation_report.json").read_text())
    assert report["summary"]["script"]["items"] == 6 and "seconds" in report

    manifest = json.loads((out_dir / "manifest.json").read_text())
    manifest["remediations"]["R-01"]["show_slide"] = "fixture-deck-p06"
    (out_dir / "manifest.json").write_text(json.dumps(manifest))
    assert run_cli("prep", "check", "--lesson", LESSON) == 1
    assert "R-01: show_slide" in capsys.readouterr().out


def test_prep_check_without_a_manifest(dirs, capsys):
    assert run_cli("prep", "check", "--lesson", "nope") == 1
    assert "run prep generate first" in capsys.readouterr().out
