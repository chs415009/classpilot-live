"""Deterministic stand-ins for the prep generators and the prep Guardian (no LLM).

`MockPrepLLM` builds every output from the chunk text, so `prep generate` runs offline
and produces a valid manifest. Its text is not meant to be good teaching content; it
shows how the flow behaves. Its Guardians use word overlap, like the live mock.

`ScriptedPrepLLM` replays queued replies (or errors) per task, then falls back to the
mock. Tests use it to drive each retry and fallback path, and it records every call so
they can check what reached the generator (for example the feedback on a retry).
"""

import re
import time
from collections import defaultdict, deque

from classpilot.adapters.llm import LLMError
from classpilot.contracts.prep import OPTION_LETTERS
from classpilot.prep.tts import clean_for_tts
from classpilot.text import coverage, split_sentences

NOTES = re.compile(r"(?:^|\n\n)Speaker notes: ", re.MULTILINE)
SUPPORT_THRESHOLD = 0.6
MOCK_SEGMENT_SLIDES = 2
DISTRACTORS = (
    "It applies only to spreadsheets",
    "It is optional and usually skipped",
    "It was replaced by manual checks",
)


def _body_and_notes(text: str) -> tuple[str, str]:
    parts = NOTES.split(text, maxsplit=1)
    return parts[0].strip(), (parts[1].strip() if len(parts) > 1 else "")


def _title(chunks: list[dict]) -> str | None:
    for c in chunks:
        body, _ = _body_and_notes(c["text"])
        if body:
            return body.splitlines()[0].strip()
    return None


def _supported_by(sentence: str, chunks: list[dict]) -> str | None:
    for c in chunks:
        for text in (c["text"], clean_for_tts(c["text"])):
            if coverage(sentence, text) >= SUPPORT_THRESHOLD:
                return c["chunk_id"]
    return None


def _claims(text: str, chunks: list[dict]) -> list[dict]:
    return [{"claim": s, "chunk_id": _supported_by(s, chunks)} for s in split_sentences(text)]


def _verdict(claims: list[dict]) -> dict:
    unsupported = [c["claim"] for c in claims if c["chunk_id"] is None]
    return {
        "verdict": "fail" if unsupported else "pass",
        "reason": (
            f"Not supported by cited chunks: {unsupported[0]!r}"
            if unsupported
            else "Every claim is supported by the cited chunks."
        ),
    }


class MockPrepLLM:
    def __init__(
        self, delays: dict[str, float] | None = None, errors: dict[str, str] | None = None
    ):
        self.delays = delays or {}
        self.errors = errors or {}

    def complete(self, task: str, inputs: dict) -> dict:
        if task in self.delays:
            time.sleep(self.delays[task])
        if task in self.errors:
            raise LLMError(self.errors[task])
        return getattr(self, f"_{task}")(inputs)

    # ---------- generators ----------

    @staticmethod
    def _segmenter(inputs: dict) -> dict:
        slides = inputs["slides"]
        segments = []
        for start in range(0, len(slides), MOCK_SEGMENT_SLIDES):
            group = slides[start : start + MOCK_SEGMENT_SLIDES]
            title = _title([c for s in group for c in s["chunks"]])
            ids = [s["slide_id"] for s in group]
            objective = f"Explain {title}" if title else f"Explain slides {ids[0]} to {ids[-1]}"
            segments.append({"slides": ids, "objective": objective})
        return {"segments": segments}

    @staticmethod
    def _script_writer(inputs: dict) -> dict:
        own = [c for c in inputs["chunks"] if c.get("slide_id") == inputs["slide_id"]]
        if not own:
            return {"script": "Now let's look at this slide.", "citations": []}
        body, notes = _body_and_notes(own[0]["text"])
        return {"script": clean_for_tts(notes or body), "citations": [own[0]["chunk_id"]]}

    @staticmethod
    def _poll_placer(inputs: dict) -> dict:
        return {
            "segment_ids": [s["segment_id"] for s in inputs["segments"]],
            "reason": "Mock: every segment, in deck order.",
        }

    @staticmethod
    def _poll_writer(inputs: dict) -> dict:
        chunk = next((c for c in inputs["chunks"] if c.get("slide_id")), inputs["chunks"][0])
        body, notes = _body_and_notes(chunk["text"])
        lines = [line.strip() for line in body.splitlines() if line.strip()]
        candidates = [ln for ln in lines[1:] if len(ln.split()) >= 3] or lines or [notes]
        correct_text = clean_for_tts(candidates[0]).rstrip(".")
        title = lines[0] if lines else "this segment"
        correct = OPTION_LETTERS[len(inputs["objective"]) % len(OPTION_LETTERS)]
        wrong = [o for o in OPTION_LETTERS if o != correct]
        options = {correct: correct_text, **dict(zip(wrong, DISTRACTORS, strict=True))}
        return {
            "question": f"Which statement matches the slide {title}?",
            "options": dict(sorted(options.items())),
            "correct_option": correct,
            "misconceptions": [
                {
                    "option": o,
                    "label": f"Believes: {text}",
                    "description": f"The student thinks that {text[0].lower()}{text[1:]}.",
                }
                for o, text in zip(wrong, DISTRACTORS, strict=True)
            ],
            "citations": [chunk["chunk_id"]],
        }

    @staticmethod
    def _explanation_writer(inputs: dict) -> dict:
        chunk = next((c for c in inputs["chunks"] if c.get("slide_id")), inputs["chunks"][0])
        correct_text = inputs["options"][inputs["correct_option"]]
        return {
            "title": f"Why option {inputs['wrong_option']} is wrong",
            "text": f"{correct_text}.",
            "show_slide": chunk.get("slide_id") or "",
            "citations": [chunk["chunk_id"]],
        }

    # ---------- prep Guardian ----------

    @staticmethod
    def _script_guardian(inputs: dict) -> dict:
        claims = _claims(inputs["script"], inputs["cited_chunks"])
        return {"claims": claims, **_verdict(claims)}

    @staticmethod
    def _poll_guardian(inputs: dict) -> dict:
        correct = inputs["options"][inputs["correct_option"]]
        claims = _claims(f"{correct}.", inputs["cited_chunks"])
        first = inputs["cited_chunks"][0]["chunk_id"] if inputs["cited_chunks"] else None
        # The mock cannot judge wrongness: the first cited chunk "shows" every wrong option.
        wrong = [
            {"option": o, "chunk_id": first}
            for o in sorted(inputs["options"])
            if o != inputs["correct_option"]
        ]
        return {"claims": claims, "wrong_options": wrong, **_verdict(claims)}

    @staticmethod
    def _explanation_guardian(inputs: dict) -> dict:
        claims = _claims(inputs["explanation"], inputs["cited_chunks"])
        return {"claims": claims, **_verdict(claims)}


class ScriptedPrepLLM:
    """Queued replies per task (a dict, or an exception to raise), then the mock.

    A reply may also be `("sleep", seconds)` to simulate a slow call.
    """

    def __init__(self, script: dict[str, list] | None = None, fallback=None):
        self.queues = defaultdict(deque, {k: deque(v) for k, v in (script or {}).items()})
        self.fallback = fallback or MockPrepLLM()
        self.calls: list[tuple[str, dict]] = []

    def complete(self, task: str, inputs: dict) -> dict:
        self.calls.append((task, inputs))
        if self.queues[task]:
            reply = self.queues[task].popleft()
            if isinstance(reply, Exception):
                raise reply
            if isinstance(reply, tuple) and reply[0] == "sleep":
                time.sleep(reply[1])
                return self.fallback.complete(task, inputs)
            return reply
        return self.fallback.complete(task, inputs)

    def count(self, task: str) -> int:
        return sum(1 for t, _ in self.calls if t == task)

    def inputs_of(self, task: str) -> list[dict]:
        return [i for t, i in self.calls if t == task]
