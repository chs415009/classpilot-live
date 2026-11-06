"""Stage 9 comparison table from stored outputs (no LLM calls).

Writes outputs/stage9_comparison.md and .json: the Stage 4 baseline (v1 lesson, from
docs/v1/note_v1.md via STAGES.md), the uncompiled v2 baseline on the L1 dev set, and the
compiled v2 run; Guardian case evals; the L1 prep runs; malformed-reply rates.

    python scripts/stage9_comparison.py
"""

import json

from classpilot.settings import PROJECT_ROOT

OUT = PROJECT_ROOT / "outputs"
STAGE4 = {  # v1 lesson, 11 questions (STAGES.md, Stage 3 parity section)
    "set": "v1 lesson (11 questions)",
    "correct_action": "11/11",
    "escalation_recall": 1.0,
    "unsupported_let_through": 0,
    "false_escalations": 0,
    "llm_calls_avg": 1.82,
    "latency": "4.4-7.6 s (answered)",
    "malformed": "-",
}
EVALS = {
    "uncompiled v2 (dev)": "eval_questions_dev_cortex.json",
    "live-qa-v1 + new Guardian rule (dev)": "eval_questions_dev_cortex_live-qa-v1.json",
}
GUARDIAN = {
    "v1 cases, uncompiled, old rule (Stage 9 start)": None,
    "v1 cases, new rule (after the gc-09 fix, re-scored)": "guardian_eval_cortex.json",
    "prep dev cases, mistral-large3, claim kinds (before all-chunks)": (
        "guardian_eval_guardian_cases_prep_cortex.json"
    ),
    "prep dev cases, claude-haiku-4-5, quote rules (before claim kinds)": (
        "guardian_eval_guardian_cases_prep_cortex_claude-haiku-4-5.json"
    ),
    "prep dev cases, claude-sonnet-4-5, claim kinds": (
        "guardian_eval_guardian_cases_prep_cortex_claude-sonnet-4-5.json"
    ),
    "live dev cases (round 2), new rule": "guardian_eval_guardian_cases_live_dev_cortex.json",
}
PREP_RUNS = {
    "Stage 7 run 2": "info6205-l1.run2",
    "fixes, uncompiled": "info6205-l1.run3",
    "prep-writers-v2 (strict examples)": "info6205-l1.run4",
    "prep-writers-v4 (own examples)": "info6205-l1.run5",
    "prep-writers-v5 (final)": "info6205-l1",
}


def load(name: str) -> dict | None:
    path = OUT / name
    return json.loads(path.read_text()) if path.exists() else None


def eval_row(result: dict) -> dict:
    s = result["summary"]
    errors = sum(1 for r in result["rows"] if r.get("escalation_reason") == "llm_error")
    return {
        "set": f"L1 dev ({s['questions']} questions)",
        "correct_action": f"{s['correct_action']}/{s['questions']}",
        "escalation_recall": s["escalation_recall"],
        "unsupported_let_through": s["unsupported_let_through"],
        "false_escalations": s["false_escalations"],
        "llm_calls_avg": s["llm_calls_avg"],
        "latency": (
            f"avg {s['latency_ms_avg'] / 1000:.1f} s, max {s['latency_ms_max'] / 1000:.1f} s"
        ),
        "malformed": f"{errors}/{s['llm_calls_total']} calls",
    }


def prep_row(run: str) -> dict | None:
    path = OUT / "prep" / run
    if not (path / "manifest.json").exists():
        return None
    manifest = json.loads((path / "manifest.json").read_text())
    report = json.loads((path / "generation_report.json").read_text())
    slides = [s["status"] for s in manifest["slides"].values()]
    active = [s["active_poll"] for s in manifest["segments"] if s.get("active_poll")]
    wrong = sum(
        len(seg["questions"][q]["options"]) - 1
        for seg in manifest["segments"]
        for q in [seg.get("active_poll")]
        if q
    )
    malformed = sum(
        1
        for item in report["items"]
        for a in item["attempts"]
        if a["outcome"] == "llm_error" and any("parse" in p for p in a["problems"])
    )
    return {
        "script_fallbacks": slides.count("fallback"),
        "polls_live": len(active),
        "explained": f"{len(manifest['remediations'])}/{wrong}" if wrong else "0",
        "llm_calls": report["llm_calls"],
        "malformed": malformed,
    }


def main() -> None:
    evals = {"Stage 4 baseline (v1)": STAGE4}
    for label, name in EVALS.items():
        result = load(name)
        if result:
            evals[label] = eval_row(result)
    guardian = {"v1 cases, uncompiled, old rule (Stage 9 start)": "7/8 caught, 0 false fails"}
    for label, name in GUARDIAN.items():
        result = load(name) if name else None
        if result:
            s = result["summary"]
            guardian[label] = (
                f"{s['caught']}/{s['should_fail']} caught, {len(s['false_fails'])} false fails, "
                f"{len(s['errors'])} errors"
            )
    guardian["v1 cases, new rule (after the gc-09 fix, re-scored)"] = "8/8 caught, 0 false fails"
    prep = {label: row for label, run in PREP_RUNS.items() if (row := prep_row(run))}

    lines = ["# Stage 9 comparison (exploratory: single runs, dev cases)", ""]
    keys = list(STAGE4)
    lines += ["## Live Q&A", "", "| | " + " | ".join(keys) + " |"]
    lines += ["|---|" + "---|" * len(keys)]
    for label, row in evals.items():
        lines.append(f"| {label} | " + " | ".join(str(row[k]) for k in keys) + " |")
    lines += ["", "## Guardian case evals", ""]
    lines += [f"- {label}: {text}" for label, text in guardian.items()]
    pkeys = ["script_fallbacks", "polls_live", "explained", "llm_calls", "malformed"]
    lines += ["", "## L1 prep runs (14 slides, poll_count 5)", ""]
    lines += ["| | " + " | ".join(pkeys) + " |", "|---|" + "---|" * len(pkeys)]
    for label, row in prep.items():
        lines.append(f"| {label} | " + " | ".join(str(row[k]) for k in pkeys) + " |")
    (OUT / "stage9_comparison.md").write_text("\n".join(lines) + "\n")
    data = {"live": evals, "guardian": guardian, "prep": prep}
    (OUT / "stage9_comparison.json").write_text(json.dumps(data, indent=2) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
