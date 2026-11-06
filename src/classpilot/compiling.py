"""Compile the prep writers with DSPy BootstrapFewShot (Stage 9).

The trainset is synthetic (`eval/prep_train.json` + the synthetic lesson), so the demos
saved to `compiled/` hold no course content. The metric is the same check a prep run
makes: the structure check, then the prep Guardian on the cited chunks, then the
Guardian rule in code (quotes included). Only writer outputs that pass become demos.

    python -m classpilot.cli compile --program-id prep-writers-v1   # BACKEND=cortex

Each tried example costs one writer call and one Guardian call; BootstrapFewShot stops
after `max_demos` passing examples per writer.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

import dspy
from dspy.teleprompt import BootstrapFewShot

from classpilot.adapters.llm import LLMClient, LLMError, call_llm
from classpilot.agents.prep_program import (
    NO_FEEDBACK,
    prep_prediction_dict,
    prep_signature_inputs,
)
from classpilot.agents.prep_signatures import PREP_SIGNATURES
from classpilot.agents.program import RulesFirstChatAdapter
from classpilot.contracts.prep import ExplanationOutput, ScriptOutput
from classpilot.prep.tts import strip_emphasis
from classpilot.rules.prep import (
    check_prep_guardian,
    explanation_problems,
    parse_output,
    script_problems,
)
from classpilot.settings import PROJECT_ROOT

PREP_TRAIN_PATH = PROJECT_ROOT / "eval" / "prep_train.json"
WRITERS = ("script_writer", "explanation_writer")


@dataclass
class WriterItem:
    """One training input of a writer, in the structured form the prep run passes."""

    task: str
    item_id: str
    inputs: dict  # structured writer inputs, without feedback
    chunks: list[dict]
    slide_ids: set[str] = field(default_factory=set)


def load_prep_trainset(path: Path = PREP_TRAIN_PATH) -> dict[str, list[WriterItem]]:
    data = json.loads(Path(path).read_text())
    if data.get("split") != "train":
        raise ValueError(f"{path}: split must be 'train'")
    lesson = json.loads((PROJECT_ROOT / data["lesson_file"]).read_text())["lesson"]
    refs = {
        c["chunk_id"]: {"chunk_id": c["chunk_id"], "slide_id": None, "text": c["text"]}
        for c in lesson["chunks"]
    }
    slides = {}
    for s in data["slides"]:
        chunk = {"chunk_id": f"{s['slide_id']}-c1", "slide_id": s["slide_id"], "text": s["text"]}
        slides[s["slide_id"]] = (s, chunk)
    slide_ids = set(slides)

    def ref_chunks(ids: list[str]) -> list[dict]:
        missing = [i for i in ids if i not in refs]
        if missing:
            raise ValueError(f"{path}: unknown reference chunks {missing}")
        return [refs[i] for i in ids]

    items: dict[str, list[WriterItem]] = {"script_writer": [], "explanation_writer": []}
    for s, chunk in slides.values():
        chunks = [chunk, *ref_chunks(s["references"])]
        inputs = {
            "objective": s["objective"],
            "slide_id": s["slide_id"],
            "position": s["position"],
            "chunks": chunks,
        }
        items["script_writer"].append(
            WriterItem("script_writer", s["slide_id"], inputs, chunks, slide_ids)
        )
    for e in data["explanations"]:
        chunks = [slides[sid][1] for sid in e["slides"]] + ref_chunks(e["references"])
        wrong = e["wrong_option"]
        if wrong == e["correct_option"] or wrong not in e["options"]:
            raise ValueError(f"{path}: {e['id']} wrong_option {wrong!r}")
        inputs = {
            "question": e["question"],
            "options": e["options"],
            "correct_option": e["correct_option"],
            "wrong_option": wrong,
            "misconception": e["misconception"],
            "chunks": chunks,
        }
        items["explanation_writer"].append(
            WriterItem("explanation_writer", e["id"], inputs, chunks, slide_ids)
        )
    return items


def to_example(item: WriterItem, index: int) -> dspy.Example:
    fields = prep_signature_inputs(item.task, {**item.inputs, "feedback": NO_FEEDBACK})
    return dspy.Example(**fields, item_index=index).with_inputs(*fields)


def writer_check(
    item: WriterItem, raw: dict, guardian: LLMClient, timeout_s: float, max_framing: int = 2
) -> list[str]:
    """Problems of one writer output, as a prep run would find them; [] = pass."""
    allowed = {c["chunk_id"] for c in item.chunks}
    by_id = {c["chunk_id"]: c for c in item.chunks}
    if item.task == "script_writer":
        out = parse_output(ScriptOutput, raw)
        if out is None:
            return ["The output did not match the schema."]
        out = out.model_copy(update={"script": strip_emphasis(out.script)})
        problems = script_problems(out, allowed)
        task, inputs, require = "script_guardian", {"script": out.script}, False
    else:
        out = parse_output(ExplanationOutput, raw)
        if out is None:
            return ["The output did not match the schema."]
        out = out.model_copy(update={"text": strip_emphasis(out.text)})
        chunk_slide = {c["chunk_id"]: c["slide_id"] for c in item.chunks}
        problems = explanation_problems(out, allowed, chunk_slide, item.slide_ids)
        task = "explanation_guardian"
        inputs = {
            "question": item.inputs["question"],
            "options": item.inputs["options"],
            "wrong_option": item.inputs["wrong_option"],
            "explanation": out.text,
        }
        require = True
    if problems:
        return problems
    cited = [by_id[c] for c in out.citations if c in by_id]
    try:
        raw_g = call_llm(guardian, task, {**inputs, "cited_chunks": cited}, timeout_s)
    except LLMError as exc:
        return [f"Guardian: {exc}"]
    texts = {c["chunk_id"]: c["text"] for c in cited}
    check = check_prep_guardian(
        raw_g, out.citations, require_claims=require, chunk_texts=texts, max_framing=max_framing
    )
    return check.problems if check.passed is not None else ["Guardian output unusable."]


@dataclass
class CompileLog:
    tried: list[dict] = field(default_factory=list)  # item id, passed, problems


def compile_writer(
    task: str,
    items: list[WriterItem],
    lm: dspy.LM,
    guardian: LLMClient,
    timeout_s: float,
    max_demos: int = 2,
    log: CompileLog | None = None,
) -> dspy.Predict:
    """BootstrapFewShot over `items` in file order; returns the Predict with demos."""
    log = log if log is not None else CompileLog()

    def metric(example, prediction, trace=None) -> bool:
        item = items[example.item_index]
        problems = writer_check(item, prep_prediction_dict(task, prediction), guardian, timeout_s)
        log.tried.append({"task": task, "item": item.item_id, "problems": problems})
        return not problems

    optimizer = BootstrapFewShot(
        metric=metric,
        max_bootstrapped_demos=max_demos,
        max_labeled_demos=0,  # no hand-written outputs; demos come only from passing runs
        max_rounds=1,
        max_errors=len(items),
    )
    student = dspy.Predict(PREP_SIGNATURES[task][0])
    trainset = [to_example(item, n) for n, item in enumerate(items)]
    adapter = RulesFirstChatAdapter(use_json_adapter_fallback=False)
    with dspy.context(lm=lm, adapter=adapter):
        compiled = optimizer.compile(student, trainset=trainset)
    return compiled
