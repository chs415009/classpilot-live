"""Compile the prep writers and the live Analyst, Responder, and Guardian with DSPy
BootstrapFewShot (Stage 9; the Guardian since Stage 12).

Trainsets are synthetic (`eval/prep_train.json`, `eval/questions_train.json`), so the
demos saved to `compiled/` hold no course content. Each metric is the check the system
itself makes, so only outputs that pass become demos:
- writers: structure check, then the uncompiled prep Guardian, then the Guardian rule;
- analyst: the category matches the label (escalations other than out_of_scope are
  decided later, so the Analyst should say in_scope);
- responder (answer questions only): `rules.check_response`, then the uncompiled live
  Guardian on the retrieved chunks, then `rules.check_guardian`;
- guardian: `rules.check_guardian` on its output gives the user's label (pass or fail)
  for a labeled synthetic case (`eval/guardian_cases_train.json`), so only outputs
  that lead code to the right verdict become demos.

    python -m classpilot.cli compile --side prep --program-id <id>   # BACKEND=cortex
    python -m classpilot.cli compile --side live --program-id <id> [--task guardian]

BootstrapFewShot goes through the items in order and stops after `max_demos` passes.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

import dspy
from dspy.teleprompt import BootstrapFewShot

from classpilot.adapters.llm import LLMClient, LLMError, call_llm
from classpilot.adapters.retrieval import MockRetriever
from classpilot.agents.prep_program import (
    NO_FEEDBACK,
    prep_prediction_dict,
    prep_signature_inputs,
)
from classpilot.agents.prep_signatures import PREP_SIGNATURES
from classpilot.agents.program import RulesFirstChatAdapter, prediction_dict, signature_inputs
from classpilot.agents.signatures import SIGNATURES
from classpilot.contracts import ResponderOutput
from classpilot.contracts.prep import ExplanationOutput, ScriptOutput
from classpilot.eval_sets import TRAIN_SET_PATH, load_question_set
from classpilot.prep.tts import tidy_generated
from classpilot.rules.prep import (
    check_prep_guardian,
    explanation_problems,
    parse_output,
    script_problems,
)
from classpilot.rules.question import check_guardian, check_response, parse_or_none
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
    item: WriterItem,
    raw: dict,
    guardian: LLMClient,
    timeout_s: float,
    rule_options: dict | None = None,
) -> list[str]:
    """Problems of one writer output, as a prep run would find them; [] = pass. As in a
    prep run, the Guardian sees the cited chunks first, then the other given chunks."""
    allowed = {c["chunk_id"] for c in item.chunks}
    by_id = {c["chunk_id"]: c for c in item.chunks}
    if item.task == "script_writer":
        out = parse_output(ScriptOutput, raw)
        if out is None:
            return ["The output did not match the schema."]
        out = out.model_copy(update={"script": tidy_generated(out.script)})
        problems = script_problems(out, allowed)
        task, inputs, require = "script_guardian", {"script": out.script}, False
    else:
        out = parse_output(ExplanationOutput, raw)
        if out is None:
            return ["The output did not match the schema."]
        out = out.model_copy(update={"text": tidy_generated(out.text)})
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
    ids = list(dict.fromkeys([*(c for c in out.citations if c in by_id), *by_id]))
    shown = [by_id[i] for i in ids]
    try:
        raw_g = call_llm(guardian, task, {**inputs, "cited_chunks": shown}, timeout_s)
    except LLMError as exc:
        return [f"Guardian: {exc}"]
    texts = {c["chunk_id"]: c["text"] for c in shown}
    check = check_prep_guardian(
        raw_g, ids, require_claims=require, chunk_texts=texts, **(rule_options or {})
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
    rule_options: dict | None = None,
) -> dspy.Predict:
    """BootstrapFewShot over `items` in file order; returns the Predict with demos."""
    log = log if log is not None else CompileLog()

    def metric(example, prediction, trace=None) -> bool:
        item = items[example.item_index]
        raw = prep_prediction_dict(task, prediction)
        problems = writer_check(item, raw, guardian, timeout_s, rule_options)
        log.tried.append({"task": task, "item": item.item_id, "problems": problems})
        return not problems

    trainset = [to_example(item, n) for n, item in enumerate(items)]
    return bootstrap(PREP_SIGNATURES[task][0], trainset, metric, lm, max_demos)


def bootstrap(signature, trainset: list[dspy.Example], metric, lm: dspy.LM, max_demos: int):
    optimizer = BootstrapFewShot(
        metric=metric,
        max_bootstrapped_demos=max_demos,
        max_labeled_demos=0,  # no hand-written outputs; demos come only from passing runs
        max_rounds=1,
        max_errors=len(trainset),
    )
    adapter = RulesFirstChatAdapter(use_json_adapter_fallback=False)
    with dspy.context(lm=lm, adapter=adapter):
        return optimizer.compile(dspy.Predict(signature), trainset=trainset)


# ---------- live Analyst and Responder ----------

LIVE_TASKS = ("analyst", "responder", "guardian")
GUARDIAN_TRAIN_PATH = PROJECT_ROOT / "eval" / "guardian_cases_train.json"
# Tried first, so the demos show what the dev baseline got wrong: a question about an
# example or a sub-topic the objective titles do not name is still in scope (tr-09), so
# is a course topic the chunks do not cover (tr-17, Stage 12); logistics are not (tr-12).
ANALYST_FIRST = ("tr-09", "tr-17", "tr-12", "tr-06", "tr-08")
RESPONDER_FIRST = ("tr-09", "tr-04", "tr-05")


@dataclass
class LiveItem:
    task: str
    item_id: str
    inputs: dict  # structured node inputs, as the live graph passes them
    expected: str | None = None  # analyst: the category; guardian: the label (pass/fail)
    chunks: list[dict] = field(default_factory=list)  # responder, guardian: the chunks


def analyst_category(expected_reason: str | None) -> str:
    return "out_of_scope" if expected_reason == "out_of_scope" else "in_scope"


def _first(items: list[LiveItem], ids: tuple[str, ...]) -> list[LiveItem]:
    rank = {item_id: n for n, item_id in enumerate(ids)}
    return sorted(items, key=lambda i: rank.get(i.item_id, len(ids)))


def load_live_trainset(
    path: Path = TRAIN_SET_PATH, top_k: int = 3, analyst_chunk_chars: int = 600
) -> dict[str, list[LiveItem]]:
    qset = load_question_set(path)
    if qset.split != "train":
        raise ValueError(f"{path}: split must be 'train'")
    objectives = [
        {"objective_id": o["objective_id"], "title": o["title"]} for o in qset.content.objectives
    ]
    retriever = MockRetriever(qset.content.chunks)
    analyst, responder = [], []
    for q in qset.questions:
        # Stage 12: retrieval runs before the Analyst, which sees the chunks (cut short).
        hits = retriever.search(q.question_text, top_k, qset.content.lesson_id)
        shown = [{"chunk_id": h.chunk_id, "text": h.text[:analyst_chunk_chars]} for h in hits]
        analyst.append(
            LiveItem(
                "analyst",
                q.id,
                {"question_text": q.question_text, "objectives": objectives, "chunks": shown},
                expected=analyst_category(q.expected_reason),
            )
        )
        if q.expected_action == "answer":
            chunks = [{"chunk_id": h.chunk_id, "text": h.text, "score": h.score} for h in hits]
            responder.append(
                LiveItem(
                    "responder",
                    q.id,
                    {"question_text": q.question_text, "chunks": chunks},
                    chunks=chunks,
                )
            )
    return {
        "analyst": _first(analyst, ANALYST_FIRST),
        "responder": _first(responder, RESPONDER_FIRST),
    }


def load_guardian_trainset(path: Path = GUARDIAN_TRAIN_PATH) -> list[LiveItem]:
    """Labeled live Guardian cases, fail and pass alternating, so the first passing
    outputs (the demos) show both verdicts."""
    from classpilot.guardian_cases import load_cases

    cases = [c for c in load_cases(path).cases if c.kind == "live" and c.expected]
    fails = [c for c in cases if c.expected == "fail"]
    passes = [c for c in cases if c.expected == "pass"]
    ordered = [c for pair in zip(fails, passes, strict=False) for c in pair]
    ordered += fails[len(passes) :] + passes[len(fails) :]
    items = []
    for c in ordered:
        chunks = [{"chunk_id": ch.chunk_id, "text": ch.text} for ch in c.chunks]
        inputs = {
            "question_text": c.question_text,
            "answer_text": c.answer_text,
            "cited_chunks": chunks,
        }
        items.append(LiveItem("guardian", c.id, inputs, expected=c.expected, chunks=chunks))
    return items


def guardian_label_check(item: LiveItem, raw: dict, rescue_coverage: float | None) -> list[str]:
    """Problems of one Guardian output: the code verdict must match the user's label."""
    ids = [c["chunk_id"] for c in item.chunks]
    texts = {c["chunk_id"]: c["text"] for c in item.chunks}
    check = check_guardian(raw, ids, texts, rescue_coverage)
    if check.passed is None:
        return ["The output did not match the schema."]
    got = "pass" if check.passed else "fail"
    return [] if got == item.expected else [f"verdict {got}, label {item.expected}"]


def responder_check(
    item: LiveItem,
    raw: dict,
    guardian: LLMClient,
    timeout_s: float,
    confidence_threshold: float,
    rescue_coverage: float | None,
) -> list[str]:
    """Problems of one Responder output, as the live validator would find them."""
    response = parse_or_none(ResponderOutput, raw)
    if response is None:
        return ["The output did not match the schema."]
    ids = [c["chunk_id"] for c in item.chunks]
    reason = check_response(response, ids, confidence_threshold)
    if reason is not None:
        return [f"check_response: {reason}"]
    shown = sorted(item.chunks, key=lambda c: c["chunk_id"] not in response.citations)
    inputs = {
        "question_text": item.inputs["question_text"],
        "answer_text": response.answer_text,
        "cited_chunks": shown,
    }
    try:
        raw_g = call_llm(guardian, "guardian", inputs, timeout_s)
    except LLMError as exc:
        return [f"Guardian: {exc}"]
    texts = {c["chunk_id"]: c["text"] for c in item.chunks}
    check = check_guardian(raw_g, ids, texts, rescue_coverage)
    return [] if check.passed else [f"Guardian: {check.reason}"]


def compile_live(
    task: str,
    items: list[LiveItem],
    lm: dspy.LM,
    max_demos: int = 2,
    log: CompileLog | None = None,
    guardian: LLMClient | None = None,
    timeout_s: float = 10,
    confidence_threshold: float = 0.7,
    rescue_coverage: float | None = None,
) -> dspy.Predict:
    """BootstrapFewShot for a live module (items in the order given)."""
    log = log if log is not None else CompileLog()

    def metric(example, prediction, trace=None) -> bool:
        item = items[example.item_index]
        raw = prediction_dict(task, prediction)
        if task == "analyst":
            got = raw.get("category")
            problems = [] if got == item.expected else [f"category {got}, label {item.expected}"]
        elif task == "guardian":
            problems = guardian_label_check(item, raw, rescue_coverage)
        else:
            problems = responder_check(
                item, raw, guardian, timeout_s, confidence_threshold, rescue_coverage
            )
        log.tried.append({"task": task, "item": item.item_id, "problems": problems})
        return not problems

    trainset = []
    for n, item in enumerate(items):
        fields = signature_inputs(task, item.inputs)
        trainset.append(dspy.Example(**fields, item_index=n).with_inputs(*fields))
    return bootstrap(SIGNATURES[task][0], trainset, metric, lm, max_demos)
