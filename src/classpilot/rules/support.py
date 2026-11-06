"""Code checks shared by the prep and live Guardian rules (Stage 9)."""

import re

from classpilot.text import content_words

NEGATIONS = {"not", "no", "never", "none", "nor", "cannot", "without"}
_NEGATION_WORDS = re.compile(r"[a-z]+n['’]t\b|\b(?:" + "|".join(sorted(NEGATIONS)) + r")\b")


def _negations(text: str) -> set[str]:
    return set(_NEGATION_WORDS.findall(text.lower()))


# Words that frame a comparison or set a tone; they carry no content of their own.
RESCUE_IGNORED = {
    "like",
    "just",
    "actually",
    "really",
    "basically",
    "simply",
    "think",
    "imagine",
    "picture",
    "example",
    "kind",
    "way",
    "thing",
    "things",
    "lot",
}


def rescued_by_words(claim: str, chunk_texts: list[str], min_coverage: float) -> bool:
    """Code check for a claim the Guardian left without a chunk (Stage 9: 17% of its
    "unsupported" claims were in a cited chunk). True if at least `min_coverage` of the
    claim's content words (2 or more; comparison and tone words such as "like" do not
    count) are in one chunk, and the claim has no negation that chunk lacks (so "an ADT
    is not a blueprint" is not rescued by "think of it as a blueprint")."""
    words = set(content_words(claim)) - RESCUE_IGNORED
    if len(words) < 2:
        return False
    for text in chunk_texts:
        share = len(words & set(content_words(text))) / len(words)
        if share >= min_coverage and _negations(claim) <= _negations(text):
            return True
    return False


def _mentions(reason: str, claim: str) -> bool:
    words = set(content_words(claim)) - RESCUE_IGNORED
    if not words:
        return False
    return len(words & set(content_words(reason))) / len(words) >= 0.8


def fail_verdict_explained_by(reason: str, rescued: list[str], others: list[str]) -> bool:
    """May code overrule a "fail" verdict after rescuing `rescued`? Only if the
    Guardian's reason names a rescued claim and no other claim. Stage 9 (v1 case gc-09):
    the Guardian tied an invented claim to a chunk but named it as unsupported in its
    reason, while code rescued a different, true claim; the verdict must stand."""
    if not rescued or any(_mentions(reason, c) for c in others):
        return False
    return any(_mentions(reason, c) for c in rescued)
