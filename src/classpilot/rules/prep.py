"""Prep rules (Stage 6): structure checks per generated item and the prep Guardian rule.

Every check returns a list of problems in plain sentences. An empty list passes; a
non-empty list fails the attempt and goes back to the generator as its `feedback`.
The LLM never decides: a Guardian "pass" next to an unsupported claim still fails.
"""

import re
from dataclasses import dataclass, field

from pydantic import BaseModel, ValidationError

from classpilot.contracts.manifest import Manifest
from classpilot.contracts.prep import (
    OPTION_LETTERS,
    ExplanationOutput,
    PlacementOutput,
    PollGuardianOutput,
    PollOutput,
    PrepGuardianOutput,
    ScriptOutput,
    SegmenterOutput,
)
from classpilot.prep.tts import generated_text_issues
from classpilot.text import content_words


def parse_output[M: BaseModel](model: type[M], raw: dict | None) -> M | None:
    if raw is None:
        return None
    try:
        return model.model_validate(raw)
    except ValidationError:
        return None


def _citation_problems(citations: list[str], allowed: set[str], required: bool) -> list[str]:
    problems = []
    if required and not citations:
        problems.append("Cite at least one chunk id.")
    unknown = [c for c in citations if c not in allowed]
    if unknown:
        problems.append(f"Cite only the chunk ids given; unknown: {', '.join(unknown)}.")
    return problems


def _tts_problems(what: str, text: str) -> list[str]:
    issues = generated_text_issues(text)
    if not issues:
        return []
    return [
        f"The {what} is read aloud: no Markdown, backticks, or code symbols "
        f"(found: {', '.join(issues)}). Spell code and symbols out in words."
    ]


# ---------- structure checks ----------


def segmenter_problems(out: SegmenterOutput, slide_ids: list[str]) -> list[str]:
    """Segments cover every slide exactly once, consecutive and in deck order."""
    if not out.segments:
        return ["Return at least one segment."]
    problems = []
    for n, seg in enumerate(out.segments, start=1):
        if not seg.slides:
            problems.append(f"Segment {n} has no slides.")
        if not seg.objective.strip():
            problems.append(f"Segment {n} has no objective.")
    listed = [s for seg in out.segments for s in seg.slides]
    unknown = [s for s in listed if s not in slide_ids]
    if unknown:
        problems.append(f"Unknown slide ids: {', '.join(unknown)}.")
    missing = [s for s in slide_ids if s not in listed]
    if missing:
        problems.append(f"Every slide must be in a segment; missing: {', '.join(missing)}.")
    repeated = sorted({s for s in listed if listed.count(s) > 1})
    if repeated:
        problems.append(f"Each slide belongs to one segment; repeated: {', '.join(repeated)}.")
    if not (unknown or missing or repeated) and listed != slide_ids:
        problems.append("Segments must hold consecutive slides in deck order.")
    return problems


def script_problems(out: ScriptOutput, allowed_chunks: set[str]) -> list[str]:
    problems = [] if out.script.strip() else ["The script is empty."]
    problems += _tts_problems("script", out.script)
    return problems + _citation_problems(out.citations, allowed_chunks, required=False)


def placement_problems(out: PlacementOutput, segment_ids: list[str]) -> list[str]:
    if not out.segment_ids:
        return ["Name at least one segment."]
    problems = []
    unknown = [s for s in out.segment_ids if s not in segment_ids]
    if unknown:
        problems.append(f"Unknown segment ids: {', '.join(unknown)}.")
    if len(set(out.segment_ids)) != len(out.segment_ids):
        problems.append("Name each segment at most once (at most one poll per segment).")
    return problems


def poll_problems(out: PollOutput, allowed_chunks: set[str]) -> list[str]:
    problems = [] if out.question.strip() else ["The question is empty."]
    if sorted(out.options) != list(OPTION_LETTERS):
        problems.append(f"Give exactly 4 options keyed {', '.join(OPTION_LETTERS)}.")
    texts = [t.strip().lower() for t in out.options.values()]
    if any(not t for t in texts):
        problems.append("Every option needs text.")
    elif len(set(texts)) != len(texts):
        problems.append("Options must be different from each other.")
    if out.correct_option not in out.options:
        problems.append(f"correct_option {out.correct_option!r} is not one of the options.")
    wrong = sorted(set(out.options) - {out.correct_option})
    covered = [m.option for m in out.misconceptions]
    if sorted(covered) != wrong:
        problems.append(
            f"Give exactly one misconception per wrong option ({', '.join(wrong)}); "
            f"got {', '.join(covered) or 'none'}."
        )
    if any(not (m.label.strip() and m.description.strip()) for m in out.misconceptions):
        problems.append("Every misconception needs a label and a description.")
    return problems + _citation_problems(out.citations, allowed_chunks, required=True)


def explanation_problems(
    out: ExplanationOutput,
    allowed_chunks: set[str],
    chunk_slide: dict[str, str | None],
    slide_ids: set[str],
) -> list[str]:
    """`chunk_slide` maps a chunk id to its slide id (None for reference pages)."""
    problems = [] if out.text.strip() else ["The explanation text is empty."]
    problems += _tts_problems("explanation", out.text)
    problems += _citation_problems(out.citations, allowed_chunks, required=True)
    cited_slides = {chunk_slide.get(c) for c in out.citations} - {None}
    if out.show_slide not in slide_ids:
        problems.append(f"show_slide {out.show_slide!r} is not a slide id.")
    elif out.show_slide not in cited_slides:
        options = ", ".join(sorted(cited_slides)) or "none: cite a slide chunk"
        problems.append(
            f"show_slide must be the slide of a cited chunk ({options}); got {out.show_slide!r}."
        )
    return problems


def manifest_poll_problems(manifest: Manifest, poll_count: int) -> list[str]:
    """At most `poll_count` active polls and at most one poll (of any status) per segment."""
    problems = []
    active = [s.active_poll for s in manifest.segments if s.active_poll is not None]
    if len(active) > poll_count:
        problems.append(f"{len(active)} active polls, at most {poll_count} allowed.")
    for seg in manifest.segments:
        if len(seg.questions) > 1:
            problems.append(f"{seg.segment_id} has {len(seg.questions)} polls, at most 1.")
    return problems


# ---------- prep Guardian rule ----------


def prep_rule_options(prep) -> dict:
    """The Guardian rule's settings from `PrepSettings` (framing limit, word rescue)."""
    return {"max_framing": prep.max_framing_claims, "rescue_coverage": prep.rescue_coverage}


OPTION_KEY = re.compile(r"^\s*\(?([A-D])\b")


def option_key(text: str) -> str:
    """'A', 'A: text', '(A) text' -> 'A'. Stage 7: the Guardian echoed 'A: <text>'
    because the options are shown to it in that form. Anything else stays as given."""
    match = OPTION_KEY.match(text)
    return match.group(1) if match else text.strip()


_NON_WORD = re.compile(r"[^0-9a-z]+")
_QUOTE_CHARS = str.maketrans({"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"'})


def normalize_words(text: str) -> str:
    """Lower case, words only: punctuation, line breaks, and the ' | ' line joins of the
    prompt do not count when a quote is matched against a chunk."""
    return " ".join(_NON_WORD.sub(" ", text.translate(_QUOTE_CHARS).lower()).split())


_QUOTE_GAP = re.compile(r"\s*(?:\||\.\.\.|\u2026)\s*")


def quote_found(quote: str | None, chunk_texts: list[str]) -> bool:
    """Every part of the quote is word for word in one of the cited chunks. Parts are
    split at ' | ' (the prompt's line joins) and '...'. Stage 9: the Guardian joined
    lines of a list with ' | ' and sometimes named a different cited chunk than the one
    it quoted."""
    texts = [f" {normalize_words(t)} " for t in chunk_texts]
    parts = [normalize_words(p) for p in _QUOTE_GAP.split(quote or "")]
    parts = [p for p in parts if p]
    return bool(parts) and all(any(f" {p} " in t for t in texts) for p in parts)


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


@dataclass
class PrepCheck:
    passed: bool | None  # None: the Guardian output does not match the schema
    problems: list[str] = field(default_factory=list)
    rescued: list[str] = field(default_factory=list)  # claims passed by `rescued_by_words`


def check_prep_guardian(
    raw: dict | None,
    cited_ids: list[str],
    *,
    require_claims: bool,
    wrong_options: list[str] | None = None,
    chunk_texts: dict[str, str] | None = None,
    max_framing: int = 2,
    rescue_coverage: float | None = None,
) -> PrepCheck:
    """Pass only if the Guardian says pass AND its claim list backs that up.

    Every claim needs a cited chunk. Scripts may have no claims at all (transitions are
    not claims); explanations and polls need at least one. For a poll
    (`wrong_options` given), every wrong option also needs a cited chunk that shows it
    is wrong.

    With `chunk_texts` (chunk id -> text), each claim and wrong-option check must also
    quote the cited chunks word for word (case and punctuation aside; `quote_found`); a
    missing or invented quote fails it. Stage 9: a Guardian named a chunk for a claim
    the chunk does not state. A real quote that does not mean the claim still passes.

    A claim of kind "framing" (no fact: transition, motivation) needs no chunk, up to
    `max_framing` per item; an "example" is checked like a fact, against the concept it
    illustrates (Stage 9, user decision). With `rescue_coverage` and `chunk_texts`, a
    fact or example the Guardian could not tie to a chunk passes if code finds its
    words in a cited chunk (`rescued_by_words`).
    """
    model = PollGuardianOutput if wrong_options is not None else PrepGuardianOutput
    output = parse_output(model, raw)
    if output is None:
        return PrepCheck(None, ["The Guardian output did not match the schema."])
    cited = set(cited_ids)

    def quoted(chunk_id: str | None, quote: str | None) -> bool:
        if chunk_id not in cited:
            return False
        return chunk_texts is None or quote_found(
            quote, [chunk_texts[i] for i in cited_ids if i in chunk_texts]
        )

    cited_texts = [chunk_texts[i] for i in cited_ids if chunk_texts and i in chunk_texts]

    def rescue(claim: str) -> bool:
        return rescue_coverage is not None and rescued_by_words(claim, cited_texts, rescue_coverage)

    problems, rescued = [], []
    framing = [c for c in output.claims if c.kind == "framing"]
    if len(framing) > max_framing:
        problems.append(f"{len(framing)} sentences carry no content; keep at most {max_framing}.")
    for c in output.claims:
        if c.kind == "framing":
            continue
        if c.chunk_id not in cited or not quoted(c.chunk_id, c.quote):
            if rescue(c.claim):
                rescued.append(c.claim)
                continue
        if c.chunk_id not in cited:
            what = (
                "Example not tied to a concept in" if c.kind == "example" else ("Not supported by")
            )
            problems.append(f"{what} the cited chunks: {c.claim!r}")
        elif not quoted(c.chunk_id, c.quote):
            problems.append(f"The quote for {c.claim!r} is not in the cited chunks.")
    if require_claims and not output.claims:
        problems.append("The Guardian found no claims to check.")
    if wrong_options is not None:
        shown = {option_key(w.option) for w in output.wrong_options if quoted(w.chunk_id, w.quote)}
        problems += [
            f"Option {o} is not shown to be wrong by the cited chunks."
            for o in wrong_options
            if o not in shown
        ]
    if output.verdict != "pass" and not problems and not rescued:
        problems.append(output.reason or "The Guardian failed the item.")
    return PrepCheck(not problems, problems, rescued)
