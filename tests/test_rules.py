import pytest

from classpilot import rules

GOOD_ANALYST = {"category": "in_scope", "objective_id": "seg-02", "reason": "x"}
GOOD_RESPONSE = {
    "answer_text": "Bronze keeps raw data.",
    "citations": ["chunk-01"],
    "confidence": 0.9,
    "grounded": True,
}

GOOD_GUARDIAN = {
    "claims": [{"claim": "Bronze keeps raw data.", "chunk_id": "chunk-01"}],
    "verdict": "pass",
    "reason": "x",
}


def validate(**overrides):
    kwargs = dict(
        early_reason=None,
        analyst_raw=GOOD_ANALYST,
        responder_raw=GOOD_RESPONSE,
        guardian_raw=GOOD_GUARDIAN,
        retrieved_ids=["chunk-01", "chunk-02"],
        confidence_threshold=0.7,
    )
    kwargs.update(overrides)
    return rules.validate_final(**kwargs)


# ---------- poll threshold ----------


def test_threshold_triggers_at_62_percent(make_evidence):
    result = rules.check_poll_threshold(make_evidence({"A": 3, "B": 13, "C": 4, "D": 1}), 5, 0.60)
    assert result.triggered
    assert result.top_wrong_option == "B"
    assert round(result.wrong_share, 2) == 0.62


def test_threshold_not_triggered_below_ratio(make_evidence):
    result = rules.check_poll_threshold(make_evidence({"A": 8, "B": 9, "C": 3, "D": 1}), 5, 0.60)
    assert not result.triggered


def test_threshold_not_triggered_with_too_few_answers(make_evidence):
    result = rules.check_poll_threshold(make_evidence({"A": 0, "B": 4}), 5, 0.60)
    assert not result.triggered
    assert result.wrong_share == 1.0


def test_threshold_ignores_correct_option(make_evidence):
    result = rules.check_poll_threshold(make_evidence({"A": 18, "B": 2, "C": 1}), 5, 0.60)
    assert not result.triggered
    assert result.top_wrong_option == "B"


def test_threshold_with_no_answers(make_evidence):
    result = rules.check_poll_threshold(make_evidence({"A": 0, "B": 0}, answers=0), 5, 0.60)
    assert not result.triggered


# ---------- mapping, limit, poll decision ----------


def test_decide_poll_explain_or_reveal():
    hit = rules.ThresholdResult(True, "B", 0.62)
    miss = rules.ThresholdResult(False, "B", 0.40)
    assert rules.decide_poll(hit) == rules.PollOutcome("explain", "B")
    assert rules.decide_poll(miss) == rules.PollOutcome("reveal")


def test_lookup_explanation_follows_known_wrong(content):
    manifest = content.manifest
    _, question = manifest.find_question("q-01")
    explanation = rules.lookup_explanation(manifest, question, "C")
    assert explanation == rules.Explanation(
        "M-02", "R-02", manifest.remediations["R-02"].text, "dbt-medallion-p04"
    )


def test_lookup_explanation_missing_link_is_none(content):
    manifest = content.manifest.model_copy(deep=True)
    _, question = manifest.find_question("q-01")
    assert rules.lookup_explanation(manifest, question, "A") is None  # correct option
    del manifest.misconceptions["M-01"]
    assert rules.lookup_explanation(manifest, question, "B") is None
    del manifest.remediations["R-02"]
    assert rules.lookup_explanation(manifest, question, "C") is None


# ---------- final validator ----------


def test_validator_answers_good_response():
    result = validate()
    assert result.action == "answer"
    assert result.citations == ["chunk-01"]


def test_validator_early_reason_wins():
    assert validate(early_reason="llm_error").escalation_reason == "llm_error"


def test_validator_analyst_category():
    raw = {**GOOD_ANALYST, "category": "out_of_scope"}
    assert validate(analyst_raw=raw).escalation_reason == "out_of_scope"


def test_validator_bad_schema_is_llm_error():
    assert validate(analyst_raw={"oops": 1}).escalation_reason == "llm_error"
    assert validate(responder_raw={"answer_text": "x"}).escalation_reason == "llm_error"
    bad_confidence = {**GOOD_RESPONSE, "confidence": 1.7}
    assert validate(responder_raw=bad_confidence).escalation_reason == "llm_error"


def test_validator_citation_not_retrieved():
    raw = {**GOOD_RESPONSE, "citations": ["chunk-99"]}
    assert validate(responder_raw=raw).escalation_reason == "unsupported"


def test_validator_no_citations():
    raw = {**GOOD_RESPONSE, "citations": []}
    assert validate(responder_raw=raw).escalation_reason == "unsupported"


def test_validator_self_check_fails_even_if_guardian_passes():
    raw = {**GOOD_RESPONSE, "grounded": False}
    assert validate(responder_raw=raw).escalation_reason == "unsupported"


def test_validator_low_confidence():
    raw = {**GOOD_RESPONSE, "confidence": 0.5}
    result = validate(responder_raw=raw)
    assert result.escalation_reason == "low_confidence"
    assert result.confidence == 0.5


def guardian(verdict="pass", claims=(("Bronze keeps raw data.", "chunk-01"),)):
    return {
        "claims": [{"claim": text, "chunk_id": chunk_id} for text, chunk_id in claims],
        "verdict": verdict,
        "reason": "x",
    }


def test_validator_guardian():
    assert validate(guardian_raw=guardian()).action == "answer"
    assert validate(guardian_raw=guardian("fail")).escalation_reason == "unsupported"
    assert validate(guardian_raw=None).escalation_reason == "llm_error"
    old_schema = {"verdict": "pass", "reason": "ok"}
    assert validate(guardian_raw=old_schema).escalation_reason == "llm_error"


def test_check_guardian_passes_when_every_claim_is_supported():
    claims = (("Bronze keeps raw data.", "chunk-01"), ("Silver is cleaned.", "chunk-02"))
    assert rules.check_guardian(guardian(claims=claims), ["chunk-01", "chunk-02"]).passed is True


def test_check_guardian_overrides_pass_with_unsupported_claim():
    claims = (("Bronze keeps raw data.", "chunk-01"), ("Kafka is read by Spark.", None))
    check = rules.check_guardian(guardian(claims=claims), ["chunk-01"])
    assert check.passed is False
    assert "Kafka" in check.reason


def test_check_guardian_rejects_claim_from_a_chunk_it_did_not_see():
    claims = (("Duplicates are removed in Silver.", "chunk-02"),)
    assert rules.check_guardian(guardian(claims=claims), ["chunk-05"]).passed is False


def test_check_guardian_fails_with_no_claims():
    assert rules.check_guardian(guardian(claims=()), ["chunk-01"]).passed is False


def test_check_guardian_bad_schema():
    assert rules.check_guardian({"verdict": "pass"}, ["chunk-01"]).passed is None
    assert rules.check_guardian(None, ["chunk-01"]).passed is None


def test_check_response():
    from classpilot.contracts import ResponderOutput

    def check(**overrides):
        response = ResponderOutput.model_validate({**GOOD_RESPONSE, **overrides})
        return rules.check_response(response, ["chunk-01"], 0.7)

    assert check() is None
    assert check(citations=[]) == "unsupported"
    assert check(citations=["chunk-09"]) == "unsupported"
    assert check(grounded=False) == "unsupported"
    assert check(confidence=0.3) == "low_confidence"


# ---------- Stage 9: every retrieved chunk, word rescue ----------

TEXTS = {"chunk-01": "Bronze keeps raw data exactly as it arrived, for replay."}


def test_word_rescue_passes_a_claim_the_guardian_could_not_tie():
    claims = (("Bronze keeps the raw data as it arrived.", None),)
    raw = guardian("fail", claims)
    raw["reason"] = "'Bronze keeps the raw data as it arrived' is not in a chunk."
    check = rules.check_guardian(raw, ["chunk-01"], TEXTS, 0.8)
    assert check.passed is True and check.rescued == ["Bronze keeps the raw data as it arrived."]


@pytest.mark.parametrize(
    "claim",
    ["Bronze does not keep raw data.", "Java has single inheritance only."],
)
def test_word_rescue_never_passes_negations_or_new_facts(claim):
    check = rules.check_guardian(guardian("fail", ((claim, None),)), ["chunk-01"], TEXTS, 0.8)
    assert check.passed is False


def test_without_rescue_a_fail_verdict_still_fails():
    claims = (("Bronze keeps the raw data as it arrived.", None),)
    assert rules.check_guardian(guardian("fail", claims), ["chunk-01"], TEXTS).passed is False


def test_validator_uses_retrieved_chunks_and_rescue():
    claims = (("Bronze keeps raw data.", "chunk-02"),)  # retrieved, not cited
    assert validate(guardian_raw=guardian(claims=claims)).action == "answer"


def test_a_fail_verdict_naming_an_unrescued_claim_stands():
    # v1 case gc-09: the invented claim got a chunk id, but the reason names it.
    raw = guardian(
        "fail",
        (
            ("Duplicates are removed in the Silver models.", "chunk-01"),
            ("Bronze keeps the raw data as it arrived.", None),
        ),
    )
    raw["reason"] = "The claim 'Duplicates are removed in the Silver models' is not supported."
    check = rules.check_guardian(raw, ["chunk-01"], TEXTS, 0.8)
    assert check.passed is False and check.rescued


def test_a_fail_verdict_with_a_reason_naming_no_claim_stands():
    raw = guardian("fail", (("Bronze keeps the raw data as it arrived.", None),))
    raw["reason"] = "Something is off."
    assert rules.check_guardian(raw, ["chunk-01"], TEXTS, 0.8).passed is False
