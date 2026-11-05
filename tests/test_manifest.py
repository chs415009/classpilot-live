import copy
import json

import pytest
from pydantic import ValidationError

from classpilot.content import DEFAULT_CONTENT_DIR
from classpilot.contracts.manifest import Manifest, load_manifest

MANIFEST_PATH = DEFAULT_CONTENT_DIR / "manifest.json"


@pytest.fixture
def raw():
    return json.loads(MANIFEST_PATH.read_text())


def seg(raw, segment_id):
    return next(s for s in raw["segments"] if s["segment_id"] == segment_id)


def assert_invalid(raw, message):
    with pytest.raises(ValidationError, match=message):
        Manifest.model_validate(raw)


def test_fixture_manifest_is_valid():
    manifest = load_manifest(MANIFEST_PATH)
    assert manifest.lesson_id == "lesson-dbt-medallion"
    segment, question = manifest.find_question("q-01")
    assert segment.segment_id == "seg-02"
    assert question.known_wrong["B"] == "M-01"
    assert manifest.find_question("q-99") is None


# ---------- every wrong option is in known_wrong ----------


def test_wrong_option_missing_from_known_wrong(raw):
    del seg(raw, "seg-02")["questions"]["q-01"]["known_wrong"]["D"]
    assert_invalid(raw, "known_wrong covers")


def test_correct_option_in_known_wrong(raw):
    seg(raw, "seg-02")["questions"]["q-01"]["known_wrong"]["A"] = "M-01"
    assert_invalid(raw, "known_wrong covers")


def test_known_wrong_points_to_unknown_misconception(raw):
    seg(raw, "seg-02")["questions"]["q-01"]["known_wrong"]["B"] = "M-99"
    assert_invalid(raw, "unknown misconception 'M-99'")


def test_correct_option_must_be_an_option(raw):
    seg(raw, "seg-02")["questions"]["q-01"]["correct_option"] = "E"
    assert_invalid(raw, "correct_option 'E' not in options")


# ---------- each misconception has exactly one remediation ----------


def test_misconception_with_unknown_remediation(raw):
    raw["misconceptions"]["M-01"]["remediation"] = "R-99"
    assert_invalid(raw, "M-01: unknown remediation")


def test_misconception_with_list_of_remediations(raw):
    raw["misconceptions"]["M-01"]["remediation"] = ["R-01", "R-02"]
    assert_invalid(raw, "remediation")


def test_misconception_without_remediation(raw):
    del raw["misconceptions"]["M-01"]["remediation"]
    assert_invalid(raw, "remediation")


def test_two_misconceptions_share_a_remediation(raw):
    raw["misconceptions"]["M-02"]["remediation"] = "R-01"
    assert_invalid(raw, "already used by M-01")


# ---------- show_slide and segment slides are real slide ids ----------


def test_unknown_show_slide(raw):
    raw["remediations"]["R-01"]["show_slide"] = "dbt-medallion-p99"
    assert_invalid(raw, "R-01: unknown show_slide")


def test_unknown_segment_slide(raw):
    seg(raw, "seg-01")["slides"].append("other-deck-p01")
    assert_invalid(raw, "seg-01: unknown slide 'other-deck-p01'")


# ---------- a segment without a poll: active_poll null and questions {} ----------


def test_active_poll_without_questions(raw):
    seg(raw, "seg-01")["active_poll"] = "q-01"
    assert_invalid(raw, "seg-01: active_poll set but questions is empty")


def test_active_poll_null_with_live_question(raw):
    seg(raw, "seg-03")["active_poll"] = None
    assert_invalid(raw, "seg-03: active_poll is null but a question is not dropped")


def test_all_questions_dropped_with_null_active_poll_is_valid(raw):
    s = seg(raw, "seg-02")
    s["questions"]["q-01"]["status"] = "dropped"
    s["active_poll"] = None
    Manifest.model_validate(raw)


def test_active_poll_not_in_questions(raw):
    seg(raw, "seg-03")["active_poll"] = "q-01"
    assert_invalid(raw, "active_poll 'q-01' not in questions")


# ---------- active_poll never points to a dropped question ----------


def test_active_poll_points_to_dropped_question(raw):
    seg(raw, "seg-02")["active_poll"] = "q-02"
    assert_invalid(raw, "active_poll 'q-02' is dropped")


# ---------- other structure checks ----------


def test_question_segment_field_must_match(raw):
    seg(raw, "seg-03")["questions"]["q-03"]["segment"] = "seg-02"
    assert_invalid(raw, "segment field is 'seg-02'")


def test_duplicate_segment_ids(raw):
    raw["segments"].append(copy.deepcopy(seg(raw, "seg-01")))
    assert_invalid(raw, "segment ids are not unique")


def test_unknown_status_value(raw):
    raw["slides"]["dbt-medallion-p01"]["status"] = "approved"
    assert_invalid(raw, "status")
