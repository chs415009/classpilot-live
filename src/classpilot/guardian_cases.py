"""Labeled Guardian cases (live answers and prep items) and the Guardian eval over them.

A case file (Stage 9 format) carries the cited chunks of every case, so cases from any
lesson can sit in one file:

    {"set_id": "...", "split": "train" | "dev", "cases": [
      {"id", "kind": "live" | "script" | "poll" | "explanation", "source",
       "reconstructed": false, "chunks": [{"chunk_id", "text"}],
       # live:        question_text, answer_text
       # script:      script
       # poll:        question, options, correct_option
       # explanation: question, options, wrong_option, explanation
       "expected": "pass" | "fail" | null,          # the human label
       "shown_wrong": {"B": true | false | null},   # poll only: per wrong option
       "unsupported": [],                           # optional: claims judged unsupported
       "note": ""}]}

Labels are written by the user; a set is used as a metric only when every case is
labeled (`label_problems` is empty). `reconstructed` cases rebuild a Stage 7 draft that
was not stored, from the claims its Guardian listed. The v1 file
(`eval/guardian_cases.json`, a plain list of live cases on the fixture lesson) is read
as a train set.
"""

import json
import statistics
import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from classpilot import rules
from classpilot.adapters.llm import LLMClient, LLMError, call_llm
from classpilot.content import load_content
from classpilot.nodes.guardian import run_guardian
from classpilot.rules.prep import check_prep_guardian, option_key, quote_found
from classpilot.settings import PROJECT_ROOT, Settings

V1_CASES_PATH = PROJECT_ROOT / "eval" / "guardian_cases.json"
TRAIN_CASES_PATH = PROJECT_ROOT / "eval" / "guardian_cases_train.json"
PREP_CASES_PATH = PROJECT_ROOT / "materials" / "eval" / "guardian_cases_prep.json"
LIVE_DEV_CASES_PATH = PROJECT_ROOT / "materials" / "eval" / "guardian_cases_live_dev.json"

Kind = Literal["live", "script", "poll", "explanation"]
PREP_TASKS = {
    "script": "script_guardian",
    "poll": "poll_guardian",
    "explanation": "explanation_guardian",
}


class CaseChunk(BaseModel):
    chunk_id: str
    text: str


class GuardianCase(BaseModel):
    id: str
    kind: Kind
    source: str = ""
    reconstructed: bool = False
    chunks: list[CaseChunk]
    question_text: str | None = None
    answer_text: str | None = None
    slide_id: str | None = None
    script: str | None = None
    question: str | None = None
    options: dict[str, str] | None = None
    correct_option: str | None = None
    wrong_option: str | None = None
    explanation: str | None = None
    expected: Literal["pass", "fail"] | None = None
    shown_wrong: dict[str, bool | None] | None = None
    unsupported: list[str] = []
    note: str = ""
    stage7: dict | None = None  # what the Stage 7 Guardian said (context, not a label)

    @property
    def chunk_ids(self) -> list[str]:
        return [c.chunk_id for c in self.chunks]

    @property
    def wrong_options(self) -> list[str]:
        return sorted(set(self.options or {}) - {self.correct_option})


REQUIRED = {
    "live": ("question_text", "answer_text"),
    "script": ("script",),
    "poll": ("question", "options", "correct_option"),
    "explanation": ("question", "options", "wrong_option", "explanation"),
}


class CaseSet(BaseModel):
    set_id: str
    split: Literal["train", "dev"]
    cases: list[GuardianCase]


def load_cases(path: Path) -> CaseSet:
    data = json.loads(Path(path).read_text())
    if isinstance(data, list):  # v1 format: live cases citing fixture-lesson chunks
        chunks = {c["chunk_id"]: c["text"] for c in load_content().chunks}
        cases = [
            {
                "id": c["id"],
                "kind": "live",
                "source": "v1",
                "chunks": [{"chunk_id": i, "text": chunks[i]} for i in c["cited_chunk_ids"]],
                "question_text": c["question_text"],
                "answer_text": c["answer_text"],
                "expected": c["expected"],
                "note": c.get("note", ""),
            }
            for c in data
        ]
        data = {"set_id": "v1-guardian-cases", "split": "train", "cases": cases}
    case_set = CaseSet.model_validate(data)
    ids = [c.id for c in case_set.cases]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{path}: duplicate case ids")
    for case in case_set.cases:
        missing = [f for f in REQUIRED[case.kind] if getattr(case, f) in (None, "")]
        if missing:
            raise ValueError(f"{path}: {case.id} ({case.kind}) lacks {missing}")
        if case.kind == "poll" and set(case.shown_wrong or {}) != set(case.wrong_options):
            raise ValueError(f"{path}: {case.id} shown_wrong must list {case.wrong_options}")
    return case_set


def label_problems(case_set: CaseSet) -> list[str]:
    """Why the set cannot be used as a metric yet (empty when fully labeled)."""
    problems = []
    for case in case_set.cases:
        if case.expected is None:
            problems.append(f"{case.id}: expected is not labeled")
        if case.kind == "poll":
            open_options = [k for k, v in (case.shown_wrong or {}).items() if v is None]
            if open_options:
                problems.append(f"{case.id}: shown_wrong not labeled for {open_options}")
            elif case.expected == "pass" and not all(case.shown_wrong.values()):
                problems.append(f"{case.id}: pass, but a wrong option is not shown wrong")
    return problems


# ---------- running the Guardian on a case ----------


def prep_inputs(case: GuardianCase) -> dict:
    cited = [{"chunk_id": c.chunk_id, "text": c.text} for c in case.chunks]
    if case.kind == "script":
        return {"script": case.script, "cited_chunks": cited}
    if case.kind == "poll":
        return {
            "question": case.question,
            "options": case.options,
            "correct_option": case.correct_option,
            "cited_chunks": cited,
        }
    return {
        "question": case.question,
        "options": case.options,
        "wrong_option": case.wrong_option,
        "explanation": case.explanation,
        "cited_chunks": cited,
    }


def run_case(case: GuardianCase, llm: LLMClient, timeout_s: float, max_framing: int = 2) -> dict:
    """The Guardian's verdict on one case, decided by the same rule code as in use."""
    row = {"id": case.id, "kind": case.kind, "expected": case.expected, "note": case.note}
    if case.kind == "live":
        result = run_guardian(
            case.question_text,
            case.answer_text,
            [c.model_dump() for c in case.chunks],
            llm,
            timeout_s,
        )
        if result.error is not None:
            return {
                **row,
                "verdict": "error",
                "reason": result.error,
                "raw": None,
                "latency_ms": result.latency_ms,
            }
        check = rules.check_guardian(result.raw, case.chunk_ids)
        verdict = {True: "pass", False: "fail", None: "error"}[check.passed]
        return {
            **row,
            "verdict": verdict,
            "reason": check.reason,
            "raw": result.raw,
            "latency_ms": result.latency_ms,
        }

    start = time.perf_counter()
    try:
        raw = call_llm(llm, PREP_TASKS[case.kind], prep_inputs(case), timeout_s)
    except LLMError as exc:
        raw, check, error = None, None, str(exc)
    else:
        error = None
        check = check_prep_guardian(
            raw,
            case.chunk_ids,
            require_claims=case.kind != "script",
            wrong_options=case.wrong_options if case.kind == "poll" else None,
            chunk_texts={c.chunk_id: c.text for c in case.chunks},
            max_framing=max_framing,
        )
    latency = round((time.perf_counter() - start) * 1000)
    if error is not None or check.passed is None:
        reason = error or "; ".join(check.problems)
        return {**row, "verdict": "error", "reason": reason, "raw": raw, "latency_ms": latency}
    out = {
        **row,
        "verdict": "pass" if check.passed else "fail",
        "reason": "; ".join(check.problems),
        "raw": raw,
        "latency_ms": latency,
    }
    if case.kind == "poll":
        texts = {c.chunk_id: c.text for c in case.chunks}
        shown = {
            option_key(w.get("option", ""))
            for w in raw.get("wrong_options") or []
            if isinstance(w, dict)
            and w.get("chunk_id") in texts
            and quote_found(w.get("quote"), list(texts.values()))
        }
        out["shown_wrong"] = {o: o in shown for o in case.wrong_options}
        out["expected_shown_wrong"] = case.shown_wrong
    return out


def summarize_cases(rows: list[dict]) -> dict:
    def block(rs: list[dict]) -> dict:
        should_fail = [r for r in rs if r["expected"] == "fail"]
        should_pass = [r for r in rs if r["expected"] == "pass"]
        return {
            "cases": len(rs),
            "caught": sum(r["verdict"] == "fail" for r in should_fail),
            "should_fail": len(should_fail),
            # Errors are listed on their own: in use they fail closed (escalate / retry).
            "missed": [r["id"] for r in should_fail if r["verdict"] == "pass"],
            "false_fails": [r["id"] for r in should_pass if r["verdict"] == "fail"],
            "errors": [r["id"] for r in rs if r["verdict"] == "error"],
            "error_rate": round(sum(r["verdict"] == "error" for r in rs) / len(rs), 3),
            "latency_ms_avg": round(statistics.mean(r["latency_ms"] for r in rs), 1),
        }

    summary = block(rows)
    kinds = sorted({r["kind"] for r in rows})
    if len(kinds) > 1:
        summary["by_kind"] = {k: block([r for r in rows if r["kind"] == k]) for k in kinds}
    options = [
        (r["id"], o, got, r["expected_shown_wrong"][o])
        for r in rows
        if "shown_wrong" in r
        for o, got in r["shown_wrong"].items()
    ]
    if options:
        summary["poll_options"] = {
            "options": len(options),
            "agree": sum(got == want for _, _, got, want in options),
            "accepted_but_labeled_not_shown": [
                f"{i}:{o}" for i, o, got, want in options if got and want is False
            ],
            "rejected_but_labeled_shown": [
                f"{i}:{o}" for i, o, got, want in options if not got and want is True
            ],
        }
    return summary


def guardian_llms(settings: Settings, kinds: set[str]) -> dict[str, LLMClient]:
    """The live Guardian's LLM for live cases, the prep LLM for prep cases."""
    out: dict[str, LLMClient] = {}
    if settings.backend == "mock":
        from classpilot.adapters.llm import MockLLM
        from classpilot.adapters.mock_prep import MockPrepLLM

        live, prep = MockLLM(), MockPrepLLM()
    else:
        from classpilot.adapters.cortex_engine import make_cortex_lm, make_prep_lm
        from classpilot.agents.compiled import live_agents, prep_agents

        live = live_agents(settings, make_cortex_lm(settings)) if "live" in kinds else None
        prep = prep_agents(settings, make_prep_lm(settings)) if kinds - {"live"} else None
    for kind in kinds:
        out[kind] = live if kind == "live" else prep
    return out


def run_case_eval(
    case_set: CaseSet, settings: Settings, llms: dict[str, LLMClient] | None = None
) -> dict:
    problems = label_problems(case_set)
    if problems:
        raise ValueError("unlabeled cases: " + "; ".join(problems))
    kinds = {c.kind for c in case_set.cases}
    llms = llms or guardian_llms(settings, kinds)
    rows = []
    for case in case_set.cases:
        live = case.kind == "live"
        timeout = settings.llm.timeout_seconds if live else settings.prep.llm_timeout_seconds
        rows.append(run_case(case, llms[case.kind], timeout, settings.prep.max_framing_claims))
    return {
        "backend": settings.backend,
        "set_id": case_set.set_id,
        "split": case_set.split,
        "prompt_version": next(
            (getattr(llm, "prompt_version", None) for llm in llms.values() if llm), None
        ),
        "summary": summarize_cases(rows),
        "rows": rows,
    }


# ---------- labeling sheet ----------

SHEET_HELP = """How to label: edit the JSON file, not this sheet. Set `expected` to
"pass" or "fail": pass only if every factual claim is stated by the listed chunks.
Differences in wording, transitions, content-free motivation sentences (at most 2), and
sentences that only describe the slide ("this slide lists the main topics") are not
claims. The writer's own example or analogy passes if it fits an idea the chunks state.
New knowledge and wrong facts fail, and so does true content found only in chunks not
listed here. A live answer must also not give finished graded work. For polls, also set
each wrong option in `shown_wrong` to true if the chunks show it is wrong (a closed,
complete list in a chunk that leaves the option out counts; a list of examples does
not), and `expected` to "pass" only if the question, the correct option, and every wrong
option are covered. Optional: copy unsupported claims into `unsupported`, and add a
`note`. Reconstructed items were rebuilt from the claims a Stage 7 Guardian listed;
judge the text as shown. The chunks are the ones the Guardian sees in this eval (they
may differ from what the Stage 7 generator cited); label against them only. The Stage 7
verdict is in the JSON (`stage7`) but not here, so it does not steer the label."""


def case_sheet(case_set: CaseSet) -> str:
    lines = [f"# Labeling sheet: {case_set.set_id} ({len(case_set.cases)} cases)", "", SHEET_HELP]
    for case in case_set.cases:
        flag = ", reconstructed" if case.reconstructed else ""
        where = f", slide {case.slide_id}" if case.slide_id else ""
        lines += ["", f"## {case.id} - {case.kind}{where} ({case.source}{flag})", ""]
        lines.append("Chunks:")
        lines += [f"- `{c.chunk_id}`: {' / '.join(c.text.split(chr(10)))}" for c in case.chunks]
        lines.append("")
        if case.kind == "live":
            lines += [f"**Question:** {case.question_text}", "", f"**Answer:** {case.answer_text}"]
        elif case.kind == "script":
            lines.append(f"**Script:** {case.script}")
        else:
            lines.append(f"**Poll:** {case.question}")
            for key, text in sorted(case.options.items()):
                mark = " (correct)" if key == case.correct_option else ""
                mark = " (students picked this)" if key == case.wrong_option else mark
                lines.append(f"- {key}: {text}{mark}")
            if case.kind == "explanation":
                lines += ["", f"**Explanation:** {case.explanation}"]
        fill = "`expected`" + (
            ", `shown_wrong` " + str(case.wrong_options) if case.kind == "poll" else ""
        )
        lines += ["", f"Fill in: {fill}" + (f". Note: {case.note}" if case.note else "")]
    return "\n".join(lines) + "\n"
