"""Prep rules (rules/prep.py): structure checks and the prep Guardian rule."""

import json

import pytest

from classpilot.content import DEFAULT_CONTENT_DIR
from classpilot.contracts.manifest import Manifest
from classpilot.contracts.prep import (
    ExplanationOutput,
    PlacementOutput,
    PollOutput,
    ScriptOutput,
    SegmenterOutput,
)
from classpilot.rules.prep import (
    check_prep_guardian,
    explanation_problems,
    manifest_poll_problems,
    placement_problems,
    poll_problems,
    script_problems,
    segmenter_problems,
)

SLIDES = ["d-p01", "d-p02", "d-p03", "d-p04"]
CHUNKS = {"d-p01-c1", "d-p02-c1", "d-p03-c1", "ref-p01-c1"}
CHUNK_SLIDE = {"d-p01-c1": "d-p01", "d-p02-c1": "d-p02", "d-p03-c1": "d-p03", "ref-p01-c1": None}


def segments(*groups):
    return SegmenterOutput.model_validate(
        {
            "segments": [
                {"slides": list(g), "objective": f"Objective {n}"} for n, g in enumerate(groups)
            ]
        }
    )


# ---------- Segmenter ----------


def test_segments_covering_the_deck_in_order_pass():
    assert segmenter_problems(segments(SLIDES[:2], SLIDES[2:]), SLIDES) == []


@pytest.mark.parametrize(
    ("groups", "message"),
    [
        ((), "at least one segment"),
        ((SLIDES[:2], SLIDES[3:]), "missing: d-p03"),
        ((SLIDES[:3], SLIDES[2:]), "repeated: d-p03"),
        ((SLIDES, ["d-p09"]), "Unknown slide ids: d-p09"),
        ((["d-p01", "d-p03"], ["d-p02", "d-p04"]), "consecutive slides in deck order"),
        ((SLIDES, []), "Segment 2 has no slides"),
    ],
)
def test_segment_structure_problems(groups, message):
    problems = segmenter_problems(segments(*groups), SLIDES)
    assert any(message in p for p in problems), problems


def test_segment_without_objective():
    out = SegmenterOutput.model_validate({"segments": [{"slides": SLIDES, "objective": " "}]})
    assert segmenter_problems(out, SLIDES) == ["Segment 1 has no objective."]


# ---------- ScriptWriter ----------


def test_plain_script_passes_and_may_cite_nothing():
    assert script_problems(ScriptOutput(script="Now we move on.", citations=[]), CHUNKS) == []


@pytest.mark.parametrize("script", ["Use `ref()`.", "**Bronze** keeps raw data.", "- item one"])
def test_markdown_or_backticks_in_a_script_fail(script):
    problems = script_problems(ScriptOutput(script=script, citations=["d-p01-c1"]), CHUNKS)
    assert len(problems) == 1 and "read aloud" in problems[0]


def test_script_with_unknown_citation_or_empty_text():
    problems = script_problems(ScriptOutput(script="", citations=["x-c1"]), CHUNKS)
    assert problems == ["The script is empty.", "Cite only the chunk ids given; unknown: x-c1."]


# ---------- PollPlacer ----------


def test_placement():
    seg_ids = ["seg-01", "seg-02"]
    assert placement_problems(PlacementOutput(segment_ids=["seg-02"], reason=""), seg_ids) == []
    dup = PlacementOutput(segment_ids=["seg-01", "seg-01"], reason="")
    assert "at most one poll per segment" in placement_problems(dup, seg_ids)[0]
    unknown = PlacementOutput(segment_ids=["seg-07"], reason="")
    assert placement_problems(unknown, seg_ids) == ["Unknown segment ids: seg-07."]
    assert placement_problems(PlacementOutput(segment_ids=[], reason=""), seg_ids)


# ---------- PollWriter ----------


def poll(**changes):
    data = {
        "question": "What does Bronze keep?",
        "options": {"A": "Raw data", "B": "Clean data", "C": "Aggregates", "D": "Nothing"},
        "correct_option": "A",
        "misconceptions": [
            {"option": o, "label": f"L{o}", "description": f"D{o}"} for o in ("B", "C", "D")
        ],
        "citations": ["d-p02-c1"],
    }
    data.update(changes)
    return PollOutput.model_validate(data)


def test_good_poll_passes():
    assert poll_problems(poll(), CHUNKS) == []


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"options": {"A": "x", "B": "y", "C": "z"}}, "exactly 4 options"),
        ({"options": {"A": "x", "B": "y", "C": "z", "E": "w"}}, "exactly 4 options"),
        ({"options": {"A": "x", "B": "X", "C": "z", "D": "w"}}, "different from each other"),
        ({"correct_option": "E"}, "is not one of the options"),
        ({"misconceptions": []}, "one misconception per wrong option (B, C, D); got none"),
        ({"citations": []}, "Cite at least one chunk id"),
        ({"citations": ["nope"]}, "unknown: nope"),
        ({"question": ""}, "question is empty"),
    ],
)
def test_poll_structure_problems(changes, message):
    problems = poll_problems(poll(**changes), CHUNKS)
    assert any(message in p for p in problems), problems


def test_misconception_for_the_correct_option_fails():
    bad = poll(
        misconceptions=[{"option": o, "label": "L", "description": "D"} for o in ("A", "B", "C")]
    )
    assert "got A, B, C" in poll_problems(bad, CHUNKS)[0]


# ---------- ExplanationWriter ----------


def explanation(**changes):
    data = {
        "title": "Bronze keeps raw data",
        "text": "Bronze keeps raw data exactly as it arrived.",
        "show_slide": "d-p02",
        "citations": ["d-p02-c1", "ref-p01-c1"],
    }
    data.update(changes)
    return ExplanationOutput.model_validate(data)


def check_explanation(out):
    return explanation_problems(out, CHUNKS, CHUNK_SLIDE, set(SLIDES))


def test_good_explanation_passes():
    assert check_explanation(explanation()) == []


def test_show_slide_must_be_a_real_slide():
    assert check_explanation(explanation(show_slide="ref-p01")) == [
        "show_slide 'ref-p01' is not a slide id."
    ]


def test_show_slide_must_be_the_slide_of_a_cited_chunk():
    problems = check_explanation(explanation(show_slide="d-p04"))
    assert problems == ["show_slide must be the slide of a cited chunk (d-p02); got 'd-p04'."]


def test_explanation_citing_only_references_cannot_show_a_slide():
    problems = check_explanation(explanation(citations=["ref-p01-c1"]))
    assert "none: cite a slide chunk" in problems[0]


def test_explanation_is_linted_for_tts():
    problems = check_explanation(explanation(text="Bronze `keeps` raw data."))
    assert len(problems) == 1 and "read aloud" in problems[0]


# ---------- manifest poll limits ----------


@pytest.fixture
def manifest():
    raw = json.loads((DEFAULT_CONTENT_DIR / "manifest.json").read_text())
    return Manifest.model_validate(raw)


def test_poll_count_and_one_poll_per_segment(manifest):
    # The hand-written fixture manifest has two questions in seg-02 (q-02 dropped);
    # generated manifests never do, since a dropped poll moves to another segment.
    active = sum(s.active_poll is not None for s in manifest.segments)
    assert manifest_poll_problems(manifest, poll_count=active) == ["seg-02 has 2 polls, at most 1."]
    assert manifest_poll_problems(manifest, poll_count=active - 1)[0] == (
        f"{active} active polls, at most {active - 1} allowed."
    )


# ---------- prep Guardian rule ----------


def guardian(claims, verdict="pass", wrong=None, reason="ok"):
    raw = {
        "claims": [{"claim": c, "chunk_id": cid} for c, cid in claims],
        "verdict": verdict,
        "reason": reason,
    }
    if wrong is not None:
        raw["wrong_options"] = [{"option": o, "chunk_id": cid} for o, cid in wrong]
    return raw


def test_supported_claims_pass():
    check = check_prep_guardian(guardian([("x", "c1")]), ["c1"], require_claims=True)
    assert check.passed and check.problems == []


def test_pass_verdict_with_an_unsupported_claim_fails():
    raw = guardian([("x", "c1"), ("invented", None)])
    check = check_prep_guardian(raw, ["c1"], require_claims=True)
    assert check.passed is False
    assert check.problems == ["Not supported by the cited chunks: 'invented'"]


def test_claim_citing_an_uncited_chunk_fails():
    check = check_prep_guardian(guardian([("x", "c9")]), ["c1"], require_claims=False)
    assert check.passed is False


def test_script_without_claims_passes_explanation_without_claims_fails():
    assert check_prep_guardian(guardian([]), [], require_claims=False).passed
    check = check_prep_guardian(guardian([]), [], require_claims=True)
    assert check.passed is False and "no claims" in check.problems[0]


def test_fail_verdict_without_details_uses_the_reason():
    raw = guardian([("x", "c1")], verdict="fail", reason="Too vague.")
    assert check_prep_guardian(raw, ["c1"], require_claims=True).problems == ["Too vague."]


def test_schema_mismatch_is_none():
    check = check_prep_guardian({"verdict": "pass"}, ["c1"], require_claims=True)
    assert check.passed is None
    assert check_prep_guardian(None, [], require_claims=True).passed is None


def test_poll_needs_every_wrong_option_shown_wrong():
    raw = guardian([("q", "c1")], wrong=[("B", "c1"), ("C", None), ("D", "c7")])
    check = check_prep_guardian(raw, ["c1"], require_claims=True, wrong_options=["B", "C", "D"])
    assert check.passed is False
    assert check.problems == [
        "Option C is not shown to be wrong by the cited chunks.",
        "Option D is not shown to be wrong by the cited chunks.",
    ]
    good = guardian([("q", "c1")], wrong=[("B", "c1"), ("C", "c1"), ("D", "c1")])
    assert check_prep_guardian(
        good, ["c1"], require_claims=True, wrong_options=["B", "C", "D"]
    ).passed


def test_poll_guardian_output_without_wrong_options_is_a_schema_mismatch():
    raw = guardian([("q", "c1")])
    assert check_prep_guardian(raw, ["c1"], require_claims=True, wrong_options=["B"]).passed is None


@pytest.mark.parametrize("given", ["B", "B: Clean data", "(B) Clean data", " B. Clean data"])
def test_wrong_option_key_is_read_from_the_start_of_the_option(given):
    raw = guardian([("q", "c1")], wrong=[(given, "c1"), ("C", "c1"), ("D", "c1")])
    check = check_prep_guardian(raw, ["c1"], require_claims=True, wrong_options=["B", "C", "D"])
    assert check.passed, check.problems


def test_option_text_without_a_key_is_not_matched():
    raw = guardian([("q", "c1")], wrong=[("Clean data", "c1"), ("C", "c1"), ("D", "c1")])
    check = check_prep_guardian(raw, ["c1"], require_claims=True, wrong_options=["B", "C", "D"])
    assert check.problems == ["Option B is not shown to be wrong by the cited chunks."]


# ---------- quotes (Stage 9) ----------

TEXTS = {"c1": "Encapsulation:\nBundling data and methods | in one Class."}


def quoted(claims, wrong=None):
    raw = {
        "claims": [{"claim": c, "chunk_id": cid, "quote": q} for c, cid, q in claims],
        "verdict": "pass",
        "reason": "ok",
    }
    if wrong is not None:
        raw["wrong_options"] = [{"option": o, "chunk_id": cid, "quote": q} for o, cid, q in wrong]
    return raw


@pytest.mark.parametrize(
    "quote",
    [
        "Bundling data and methods",
        "bundling data and methods in one class.",
        "Encapsulation: Bundling",
    ],
)
def test_quote_found_in_the_chunk_passes(quote):
    raw = quoted([("x", "c1", quote)])
    assert check_prep_guardian(raw, ["c1"], require_claims=True, chunk_texts=TEXTS).passed


@pytest.mark.parametrize(
    "quote", [None, "", "bundling data and objects", "methods in one class too"]
)
def test_missing_or_invented_quote_fails(quote):
    raw = quoted([("x", "c1", quote)])
    check = check_prep_guardian(raw, ["c1"], require_claims=True, chunk_texts=TEXTS)
    assert check.passed is False
    assert check.problems == ["The quote for 'x' is not in the cited chunks."]


def test_quote_must_match_whole_words():
    raw = quoted([("x", "c1", "ndling data")])
    assert not check_prep_guardian(raw, ["c1"], require_claims=True, chunk_texts=TEXTS).passed


def test_wrong_option_needs_a_quote_from_its_chunk():
    raw = quoted(
        [("q", "c1", "in one class")], wrong=[("B", "c1", "Bundling"), ("C", "c1", "nope")]
    )
    check = check_prep_guardian(
        raw, ["c1"], require_claims=True, wrong_options=["B", "C"], chunk_texts=TEXTS
    )
    assert check.problems == ["Option C is not shown to be wrong by the cited chunks."]


def test_without_chunk_texts_quotes_are_not_checked():
    raw = quoted([("x", "c1", None)])
    assert check_prep_guardian(raw, ["c1"], require_claims=True).passed


@pytest.mark.parametrize(
    "quote",
    ["Encapsulation: | in one Class", "Encapsulation ... in one class", "other chunk words"],
)
def test_quote_parts_may_skip_lines_and_come_from_any_cited_chunk(quote):
    texts = {**TEXTS, "c2": "Other chunk words."}
    raw = quoted([("x", "c1", quote)])
    assert check_prep_guardian(raw, ["c1", "c2"], require_claims=True, chunk_texts=texts).passed


def test_every_quote_part_must_be_found():
    raw = quoted([("x", "c1", "Encapsulation: | invented words")])
    assert not check_prep_guardian(raw, ["c1"], require_claims=True, chunk_texts=TEXTS).passed


def test_quote_from_an_uncited_chunk_does_not_count():
    texts = {**TEXTS, "c9": "Uncited words."}
    raw = quoted([("x", "c1", "Uncited words")])
    assert not check_prep_guardian(raw, ["c1"], require_claims=True, chunk_texts=texts).passed


def test_a_semicolon_in_generated_prose_is_not_a_problem():
    out = ScriptOutput(script="A stack is last in, first out; a queue is first in.", citations=[])
    assert script_problems(out, set()) == []


# ---------- claim kinds (Stage 9) ----------


def kinds(*claims):
    return {
        "claims": [{"claim": c, "chunk_id": cid, "quote": q, "kind": k} for c, cid, q, k in claims],
        "verdict": "pass",
        "reason": "ok",
    }


def test_framing_needs_no_chunk_up_to_the_limit():
    raw = kinds(("x", "c1", "Bundling data", "fact"), ("This will help.", None, None, "framing"))
    assert check_prep_guardian(raw, ["c1"], require_claims=True, chunk_texts=TEXTS).passed
    many = kinds(*[(f"f{n}", None, None, "framing") for n in range(3)])
    check = check_prep_guardian(many, ["c1"], require_claims=False, max_framing=2)
    assert check.problems == ["3 sentences carry no content; keep at most 2."]


def test_example_needs_the_concept_it_illustrates():
    tied = kinds(("Like a lunchbox.", "c1", "Bundling data and methods", "example"))
    assert check_prep_guardian(tied, ["c1"], require_claims=True, chunk_texts=TEXTS).passed
    loose = kinds(("Like a lunchbox.", None, None, "example"))
    check = check_prep_guardian(loose, ["c1"], require_claims=True, chunk_texts=TEXTS)
    assert check.problems == [
        "Example not tied to a concept in the cited chunks: 'Like a lunchbox.'"
    ]


# ---------- word rescue (Stage 9) ----------

BLUEPRINT = {"c1": "An ADT is language agnostic. Think of it as an architectural blueprint."}


@pytest.mark.parametrize(
    ("claim", "passed"),
    [
        ("An ADT is like a blueprint.", True),
        ("An ADT is not a blueprint.", False),  # negation the chunk lacks
        ("An ADT isn't language agnostic.", False),
        ("Blueprint.", False),  # fewer than 2 content words
        ("An ADT runs faster than a blueprint.", False),  # coverage below 0.8
    ],
)
def test_code_rescues_a_claim_the_guardian_could_not_tie(claim, passed):
    raw = kinds((claim, None, None, "example"))
    raw["verdict"] = "fail"
    raw["reason"] = f"Not tied to a chunk: {claim}"
    check = check_prep_guardian(
        raw, ["c1"], require_claims=True, chunk_texts=BLUEPRINT, rescue_coverage=0.8
    )
    assert check.passed is passed
    assert check.rescued == ([claim] if passed else [])


def test_no_rescue_without_the_setting():
    raw = kinds(("An ADT is like a blueprint.", None, None, "example"))
    assert not check_prep_guardian(raw, ["c1"], require_claims=True, chunk_texts=BLUEPRINT).passed
