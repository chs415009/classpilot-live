"""The prep generators and the prep Guardian as DSPy modules behind `LLMClient`.

As for the live agents (`program.py`): the generation code passes structured inputs
(the same ones the mock reads), this class formats them into the signature's text
fields, runs one `dspy.Predict`, and returns the outputs as a plain, unchecked dict.
`call_llm` turns every exception into `LLMError`; the prep rules check the dict.

Structured inputs (a chunk is `{"chunk_id", "slide_id" (None for references), "text"}`):
- segmenter: slides [{slide_id, chunks}], feedback
- script_writer: objective, slide_id, position, chunks, feedback
- poll_placer: segments [{segment_id, objective, slides}], poll_count, feedback
- poll_writer: objective, chunks, feedback
- explanation_writer: question, options, correct_option, wrong_option,
  misconception {label, description}, chunks, feedback
- script_guardian: script, cited_chunks
- poll_guardian: question, options, correct_option, cited_chunks
- explanation_guardian: question, options, wrong_option, explanation, cited_chunks
"""

import dspy
from dspy.utils.exceptions import AdapterParseError

from classpilot.adapters.llm import MalformedReplyError
from classpilot.agents.prep_signatures import PREP_SIGNATURES
from classpilot.agents.program import RulesFirstChatAdapter, _none_if_null

NO_FEEDBACK = "(none)"


def _one_line(text: str) -> str:
    # Keep line structure visible on a single prompt line.
    return " | ".join(line.strip() for line in text.splitlines() if line.strip())


def prep_chunk_lines(chunks: list[dict]) -> str:
    lines = []
    for c in chunks:
        where = c.get("slide_id") or "reference"
        lines.append(f"[{c['chunk_id']}] ({where}) {_one_line(c['text'])}")
    return "\n".join(lines) or "(none)"


def guardian_chunk_lines(chunks: list[dict]) -> str:
    return "\n".join(f"[{c['chunk_id']}] {_one_line(c['text'])}" for c in chunks) or "(none)"


def option_lines(options: dict[str, str]) -> str:
    return "\n".join(f"{key}: {text}" for key, text in sorted(options.items()))


def _feedback(inputs: dict) -> str:
    return inputs.get("feedback") or NO_FEEDBACK


def prep_signature_inputs(task: str, inputs: dict) -> dict:
    if task == "segmenter":
        blocks = [f"[{s['slide_id']}]\n{prep_chunk_lines(s['chunks'])}" for s in inputs["slides"]]
        return {"slides": "\n\n".join(blocks), "feedback": _feedback(inputs)}
    if task == "script_writer":
        return {
            "objective": inputs["objective"],
            "slide": f"{inputs['slide_id']}: {inputs['position']}",
            "chunks": prep_chunk_lines(inputs["chunks"]),
            "feedback": _feedback(inputs),
        }
    if task == "poll_placer":
        lines = [
            f"- {s['segment_id']} (slides {s['slides'][0]}..{s['slides'][-1]}): {s['objective']}"
            for s in inputs["segments"]
        ]
        return {
            "segments": "\n".join(lines),
            "poll_count": inputs["poll_count"],
            "feedback": _feedback(inputs),
        }
    if task == "poll_writer":
        return {
            "objective": inputs["objective"],
            "chunks": prep_chunk_lines(inputs["chunks"]),
            "feedback": _feedback(inputs),
        }
    if task == "explanation_writer":
        m = inputs["misconception"]
        return {
            "question": inputs["question"],
            "options": option_lines(inputs["options"]),
            "correct_option": inputs["correct_option"],
            "wrong_option": inputs["wrong_option"],
            "misconception": f"{m['label']}: {m['description']}",
            "chunks": prep_chunk_lines(inputs["chunks"]),
            "feedback": _feedback(inputs),
        }
    if task == "script_guardian":
        return {
            "chunks": guardian_chunk_lines(inputs["cited_chunks"]),
            "script": inputs["script"],
        }
    if task == "poll_guardian":
        return {
            "chunks": guardian_chunk_lines(inputs["cited_chunks"]),
            "question": inputs["question"],
            "options": option_lines(inputs["options"]),
            "correct_option": inputs["correct_option"],
        }
    if task == "explanation_guardian":
        wrong = inputs["wrong_option"]
        return {
            "chunks": guardian_chunk_lines(inputs["cited_chunks"]),
            "question": inputs["question"],
            "wrong_option": f"{wrong}: {inputs['options'][wrong]}",
            "explanation": inputs["explanation"],
        }
    raise KeyError(task)


def _plain(value):
    """Pydantic outputs to dicts; null strings in chunk ids to None (Stage 1 finding)."""
    if hasattr(value, "model_dump"):
        value = value.model_dump()
    if isinstance(value, list):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        out = {k: _plain(v) for k, v in value.items()}
        if "chunk_id" in out:
            out["chunk_id"] = _none_if_null(out["chunk_id"])
        return out
    return value


def prep_prediction_dict(task: str, prediction: dspy.Prediction) -> dict:
    signature, _ = PREP_SIGNATURES[task]
    return {name: _plain(getattr(prediction, name, None)) for name in signature.output_fields}


class DSPyPrepAgents:
    """The prep generators and Guardians as uncompiled `dspy.Predict` modules."""

    def __init__(self, lm: dspy.LM, adapter: dspy.Adapter | None = None):
        self.lm = lm
        self.adapter = adapter or RulesFirstChatAdapter(use_json_adapter_fallback=False)
        self.modules = {task: dspy.Predict(sig) for task, (sig, _) in PREP_SIGNATURES.items()}

    def complete(self, task: str, inputs: dict) -> dict:
        with dspy.context(lm=self.lm, adapter=self.adapter):
            try:
                prediction = self.modules[task](**prep_signature_inputs(task, inputs))
            except AdapterParseError as exc:
                raise MalformedReplyError(f"{task}: malformed reply: {exc}") from exc
        return prep_prediction_dict(task, prediction)
