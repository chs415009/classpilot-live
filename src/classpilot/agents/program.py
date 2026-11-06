"""The live agents as DSPy modules behind the `LLMClient` interface.

Nodes pass structured inputs (the same ones the mock reads); this class formats them
into the signature's text fields, runs one `dspy.Predict`, and returns the outputs as
a plain dict. The dict is unchecked: the validator parses it with the pydantic models.
Errors are not caught here; `call_llm` turns every exception into `LLMError`.
"""

import re
import textwrap

import dspy

from classpilot.agents.signatures import SIGNATURES
from classpilot.contracts.trace import PROMPT_VERSION

NULL_STRINGS = {"", "none", "null"}


def _none_if_null(value):
    # ChatAdapter returns an optional str field as the string "None" (Stage 1 finding).
    if isinstance(value, str) and value.strip().lower() in NULL_STRINGS:
        return None
    return value


def chunk_lines(chunks: list[dict]) -> str:
    return "\n".join(f"[{c['chunk_id']}] {c['text']}" for c in chunks) or "(none)"


def signature_inputs(task: str, inputs: dict) -> dict:
    if task == "analyst":
        objectives = "\n".join(f"- {o['objective_id']}: {o['title']}" for o in inputs["objectives"])
        return {"objectives": objectives, "question": inputs["question_text"]}
    if task == "responder":
        return {"chunks": chunk_lines(inputs["chunks"]), "question": inputs["question_text"]}
    if task == "guardian":
        return {
            "chunks": chunk_lines(inputs["cited_chunks"]),
            "question": inputs["question_text"],
            "answer": inputs["answer_text"],
        }
    raise KeyError(task)


def prediction_dict(task: str, prediction: dspy.Prediction) -> dict:
    signature, _ = SIGNATURES[task]
    out = {}
    for name in signature.output_fields:
        value = getattr(prediction, name, None)
        if name == "claims" and isinstance(value, list):
            value = [c.model_dump() if hasattr(c, "model_dump") else c for c in value]
            for claim in value:
                if isinstance(claim, dict):
                    claim["chunk_id"] = _none_if_null(claim.get("chunk_id"))
        out[name] = _none_if_null(value) if name == "objective_id" else value
    return out


FENCE_LINE = re.compile(r"^[ \t]*```[A-Za-z]*[ \t]*$", re.MULTILINE)


class RulesFirstChatAdapter(dspy.ChatAdapter):
    """ChatAdapter with the signature's instructions at the top of the system message.

    The stock ChatAdapter puts them last, after the field lists and format template. On
    the v1 Guardian cases that cost 2-3 of 8 catches against the Stage 4 baseline, whose
    prompt led with the strict rules (Stage 3 finding, docs/agent/note.md).
    """

    def parse(self, signature: type[dspy.Signature], completion: str) -> dict:
        # Stage 9: mistral-large3 sometimes wraps a field's JSON value in a ``` fence,
        # which the stock parser rejects. Fence lines carry no content; drop them.
        return super().parse(signature, FENCE_LINE.sub("", completion))

    def format_system_message(self, signature: type[dspy.Signature]) -> str:
        return (
            f"{textwrap.dedent(signature.instructions).strip()}\n\n"
            f"{self.format_field_description(signature)}\n"
            f"{self.format_field_structure(signature)}"
        )


class DSPyAgents:
    """Analyst, Responder, and Guardian as uncompiled `dspy.Predict` modules."""

    prompt_version = PROMPT_VERSION

    def __init__(self, lm: dspy.LM, adapter: dspy.Adapter | None = None):
        self.lm = lm
        self.adapter = adapter or RulesFirstChatAdapter(use_json_adapter_fallback=False)
        self.modules = {task: dspy.Predict(sig) for task, (sig, _) in SIGNATURES.items()}

    def complete(self, task: str, inputs: dict) -> dict:
        # dspy.context is per thread; call_llm runs this in its worker thread.
        with dspy.context(lm=self.lm, adapter=self.adapter):
            prediction = self.modules[task](**signature_inputs(task, inputs))
        return prediction_dict(task, prediction)
