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
