"""Stage 12 DSPy experiment (STAGES task 5b): optimize the live Guardian with a searching
optimizer and compare it with the hand-written prompt.

- train: labeled synthetic Guardian cases (`eval/guardian_cases_train.json`, committed).
  Only these become demos or reach GEPA's reflection, so `compiled/` holds no course
  content (`leak_problems` checks the saved file).
- val: the v1 cases (fixture lesson) and the labeled L1 live dev cases (gitignored);
  they only score candidates.
- metric: the code verdict (`rules.check_guardian`) equals the label. GEPA also gets the
  case note as text feedback.

Optimizers ([verify] on the installed DSPy 3.4.1): `BootstrapFewShotWithRandomSearch`
(candidate demo sets scored on val) and `GEPA` (instructions rewritten by a reflection
LM from the feedback; `max_metric_calls` caps the budget).
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path

import dspy

from classpilot.agents.compiled import COMPILED_DIR, apply_program, load_program, save_program
from classpilot.agents.program import DSPyAgents, prediction_dict, signature_inputs
from classpilot.agents.signatures import GuardianSignature
from classpilot.guardian_cases import load_cases
from classpilot.rules.question import check_guardian
from classpilot.settings import PROJECT_ROOT

TRAIN_PATH = PROJECT_ROOT / "eval" / "guardian_cases_train.json"
VAL_PATHS = [
    PROJECT_ROOT / "eval" / "guardian_cases.json",
    PROJECT_ROOT / "materials" / "eval" / "guardian_cases_live_dev.json",
]
REAL_CHUNK_ID = re.compile(r"\bl\d+-(?:slides|pdf|ref)[-\w]*-p\d+", re.IGNORECASE)


@dataclass
class GuardianItem:
    case_id: str
    set_id: str
    chunks: list[dict]
    question: str
    answer: str
    label: str  # pass | fail
    note: str


def load_items(path: Path) -> list[GuardianItem]:
    case_set = load_cases(path)
    return [
        GuardianItem(
            c.id,
            case_set.set_id,
            [{"chunk_id": ch.chunk_id, "text": ch.text} for ch in c.chunks],
            c.question_text or "",
            c.answer_text or "",
            c.expected,
            c.note or "",
        )
        for c in case_set.cases
        if c.kind == "live" and c.expected
    ]


def to_example(item: GuardianItem) -> dspy.Example:
    fields = signature_inputs(
        "guardian",
        {"question_text": item.question, "answer_text": item.answer, "cited_chunks": item.chunks},
    )
    return dspy.Example(
        **fields,
        label=item.label,
        note=item.note,
        case_id=item.case_id,
        set_id=item.set_id,
        chunk_texts={c["chunk_id"]: c["text"] for c in item.chunks},
    ).with_inputs(*fields)


class GuardianProgram(dspy.Module):
    """The live Guardian as a one-predictor DSPy program, for the optimizers."""

    def __init__(self, predict: dspy.Predict | None = None):
        super().__init__()
        self.guardian = predict if predict is not None else dspy.Predict(GuardianSignature)

    def forward(self, chunks: str, question: str, answer: str) -> dspy.Prediction:
        return self.guardian(chunks=chunks, question=question, answer=answer)


def code_verdict(example: dspy.Example, pred: dspy.Prediction, rescue: float | None) -> str | None:
    """pass | fail as the live validator would decide it; None if the output is unusable."""
    raw = prediction_dict("guardian", pred)
    ids = list(example.chunk_texts)
    check = check_guardian(raw, ids, example.chunk_texts, rescue)
    if check.passed is None:
        return None
    return "pass" if check.passed else "fail"


def make_metric(rescue: float | None):
    def metric(example, pred, trace=None) -> float:
        return 1.0 if code_verdict(example, pred, rescue) == example.label else 0.0

    return metric


def make_feedback_metric(rescue: float | None):
    """GEPA metric: the score plus why, in words, from the label and the case note."""

    def metric(gold, pred, trace=None, pred_name=None, pred_trace=None) -> dspy.Prediction:
        got = code_verdict(gold, pred, rescue)
        if got == gold.label:
            text = f"Correct: the answer should {gold.label}, and your claims lead to {got}."
            return dspy.Prediction(score=1.0, feedback=text)
        raw = prediction_dict("guardian", pred)
        claims = raw.get("claims") if isinstance(raw.get("claims"), list) else []
        untied = [c.get("claim") for c in claims if isinstance(c, dict) and not c.get("chunk_id")]
        if got is None:
            outcome = "your output could not be used (wrong format or no claims)"
        elif got == "fail":
            outcome = f"your claims lead to fail; claims you left without a chunk: {untied}"
        else:
            outcome = "your claims lead to pass: you tied every claim to a chunk"
        text = (
            f"Wrong: the answer should {gold.label}, but {outcome}. "
            f"Why it should {gold.label}: {gold.note}"
        )
        return dspy.Prediction(score=0.0, feedback=text)

    return metric


def evaluate(program: dspy.Module, examples: list[dspy.Example], rescue: float | None) -> dict:
    """Run `program` on each example (inside the caller's dspy.context) and score it."""
    rows = []
    for ex in examples:
        try:
            pred = program(**ex.inputs())
            got = code_verdict(ex, pred, rescue)
        except Exception as exc:  # an LLM error counts as a wrong verdict
            got, pred = None, None
            error = str(exc)[:200]
        else:
            error = None
        rows.append(
            {"case_id": ex.case_id, "set_id": ex.set_id, "label": ex.label, "got": got or "error"}
            | ({"error": error} if error else {})
        )
    return {"rows": rows, "summary": summarize(rows)}


def summarize(rows: list[dict]) -> dict:
    out = {"cases": len(rows), "correct": sum(r["got"] == r["label"] for r in rows)}
    for set_id in sorted({r["set_id"] for r in rows}):
        sub = [r for r in rows if r["set_id"] == set_id]
        fails = [r for r in sub if r["label"] == "fail"]
        out[set_id] = {
            "caught": sum(r["got"] == "fail" for r in fails),
            "should_fail": len(fails),
            "false_fails": [
                r["case_id"] for r in sub if r["label"] == "pass" and r["got"] != "pass"
            ],
            "missed": [r["case_id"] for r in fails if r["got"] != "fail"],
        }
    return out


def guardian_predict(program_id: str | None, directory: Path = COMPILED_DIR) -> dspy.Predict:
    """The Guardian predictor of a compiled live program, or the uncompiled one."""
    agents = DSPyAgents(None)
    if program_id:
        apply_program(agents, load_program(program_id, directory))
    return agents.modules["guardian"]


def save_live_program(
    program_id: str,
    base_id: str,
    guardian: dspy.Predict,
    meta: dict,
    directory: Path = COMPILED_DIR,
) -> Path:
    """A live program: the Analyst and Responder of `base_id` plus the new Guardian."""
    agents = apply_program(DSPyAgents(None), load_program(base_id, directory))
    modules = {"analyst": agents.modules["analyst"], "responder": agents.modules["responder"]}
    modules["guardian"] = guardian
    return save_program(program_id, modules, {"base_program": base_id, **meta}, directory)


def leak_problems(path: Path, forbidden: list[str]) -> list[str]:
    """Course content in a saved program: real chunk ids (`l1-pdf-p02`) or any of the
    `forbidden` texts (dev questions and answers), compared case-insensitively."""
    text = Path(path).read_text()
    problems = [f"real chunk id {m}" for m in sorted(set(REAL_CHUNK_ID.findall(text)))]
    low = " ".join(text.lower().split())
    for snippet in forbidden:
        key = " ".join(snippet.lower().split())[:60]
        if len(key) >= 20 and key in low:
            problems.append(f"dev text: {key!r}")
    return problems


def dev_texts(paths: list[Path]) -> list[str]:
    """Questions and answers of the real (gitignored) val cases, for `leak_problems`."""
    texts = []
    for path in paths:
        if "materials" not in Path(path).parts:
            continue
        for item in load_items(path):
            texts += [item.question, item.answer]
    return texts


def write_result(name: str, result: dict, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{name}.json"
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    return path


# ---------- prep Guardians (Stage 12 Part B) ----------

PREP_TRAIN_PATH = PROJECT_ROOT / "eval" / "guardian_cases_prep_train.json"
PREP_VAL_PATH = PROJECT_ROOT / "materials" / "eval" / "guardian_cases_prep.json"


def prep_examples(path: Path, kind: str) -> list[dspy.Example]:
    """Labeled prep Guardian cases of one kind (script, poll, explanation) as examples."""
    from classpilot.agents.prep_program import prep_signature_inputs
    from classpilot.guardian_cases import PREP_TASKS, prep_inputs

    case_set = load_cases(path)
    out = []
    for c in case_set.cases:
        if c.kind != kind or not c.expected:
            continue
        fields = prep_signature_inputs(PREP_TASKS[kind], prep_inputs(c))
        out.append(
            dspy.Example(
                **fields,
                label=c.expected,
                note=c.note or "",
                case_id=c.id,
                set_id=case_set.set_id,
                kind=kind,
                chunk_texts={ch.chunk_id: ch.text for ch in c.chunks},
                wrong_options=c.wrong_options if kind == "poll" else None,
            ).with_inputs(*fields)
        )
    return out


class PrepGuardianProgram(dspy.Module):
    """One prep Guardian (script, poll, or explanation) as a one-predictor program."""

    def __init__(self, predict: dspy.Predict):
        super().__init__()
        self.guardian = predict

    def forward(self, **inputs) -> dspy.Prediction:
        return self.guardian(**inputs)


def prep_code_verdict(example: dspy.Example, pred: dspy.Prediction, prep_rules: dict) -> str | None:
    """pass | fail as the prep rule decides it; None if the output is unusable."""
    from classpilot.agents.prep_program import prep_prediction_dict
    from classpilot.guardian_cases import PREP_TASKS
    from classpilot.rules.prep import check_prep_guardian

    raw = prep_prediction_dict(PREP_TASKS[example.kind], pred)
    check = check_prep_guardian(
        raw,
        list(example.chunk_texts),
        require_claims=example.kind != "script",
        wrong_options=example.wrong_options,
        chunk_texts=example.chunk_texts,
        **prep_rules,
    )
    if check.passed is None:
        return None
    return "pass" if check.passed else "fail"


def make_prep_metric(prep_rules: dict):
    def metric(example, pred, trace=None) -> float:
        return 1.0 if prep_code_verdict(example, pred, prep_rules) == example.label else 0.0

    return metric


def evaluate_prep(program: dspy.Module, examples: list[dspy.Example], prep_rules: dict) -> dict:
    rows = []
    for ex in examples:
        error = None
        try:
            got = prep_code_verdict(ex, program(**ex.inputs()), prep_rules)
        except Exception as exc:  # an LLM error counts as a wrong verdict
            got, error = None, str(exc)[:200]
        rows.append(
            {"case_id": ex.case_id, "set_id": ex.set_id, "label": ex.label, "got": got or "error"}
            | ({"error": error} if error else {})
        )
    return {"rows": rows, "summary": summarize(rows)}


def prep_guardian_predict(program_id: str | None, kind: str, directory: Path = COMPILED_DIR):
    from classpilot.agents.prep_program import DSPyPrepAgents
    from classpilot.guardian_cases import PREP_TASKS

    agents = DSPyPrepAgents(None)
    if program_id:
        apply_program(agents, load_program(program_id, directory))
    return agents.modules[PREP_TASKS[kind]]


def save_prep_program(
    program_id: str,
    base_id: str | None,
    new_modules: dict[str, dspy.Predict],
    meta: dict,
    directory: Path = COMPILED_DIR,
) -> Path:
    """A prep program: the compiled modules of `base_id` plus (or replaced by) `new_modules`."""
    modules: dict[str, dspy.Predict] = {}
    if base_id:
        from classpilot.agents.prep_program import DSPyPrepAgents

        data = load_program(base_id, directory)
        agents = apply_program(DSPyPrepAgents(None), data)
        modules = {task: agents.modules[task] for task in data["modules"]}
    modules.update(new_modules)
    return save_program(program_id, modules, {"base_program": base_id, **meta}, directory)
