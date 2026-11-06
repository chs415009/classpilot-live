"""Draft live Guardian cases from a stored question-set eval (Stage 9, labeling round 2).

Every question whose answer reached the Guardian becomes a case: the question, the
Responder's answer, and the chunks the live Guardian sees (Stage 9): the cited ones
first, then the other retrieved ones from the eval's trace file (texts from the question
set's lesson snapshot). New labels start empty (`expected: null`); labels already in
`--out` are kept for the same source. The baseline Guardian's verdict is kept in
`stage7` (the field the labeling sheet hides). The output holds real course content, so
it goes to a gitignored file.

    python scripts/draft_live_guardian_cases.py \
        --eval outputs/eval_questions_dev_cortex.json \
        --set materials/eval/questions_dev.json \
        --traces outputs/eval_traces_questions_dev_cortex.jsonl \
        --out materials/eval/guardian_cases_live_dev.json
"""

import argparse
import json
from pathlib import Path


def retrieved_by_question(trace_lines: list[dict]) -> dict[str, list[str]]:
    """Question event id -> retrieved chunk ids, from run and retrieval records."""
    runs = {r["run_id"]: r["input_ref"] for r in trace_lines if r.get("record_type") == "run"}
    out: dict[str, list[str]] = {}
    for r in trace_lines:
        if r.get("record_type") == "retrieval" and r["run_id"] in runs:
            out.setdefault(runs[r["run_id"]], []).append(r["chunk_id"])
    return out


def draft(eval_result: dict, question_set: dict, retrieved: dict[str, list[str]]) -> list[dict]:
    texts = {c["chunk_id"]: c["text"] for c in question_set["lesson"]["chunks"]}
    cases = []
    for row in eval_result["rows"]:
        guardian = row["details"].get("guardian")
        responder = row["details"].get("responder")
        if not guardian or not responder:
            continue
        cited = [c for c in responder.get("citations") or [] if c in texts]
        ref = next((k for k in retrieved if k.endswith(row["id"])), None)
        shown = list(dict.fromkeys([*cited, *(retrieved.get(ref) or [])]))
        shown = [c for c in shown if c in texts]
        cases.append(
            {
                "id": f"lc-{len(cases) + 1:02d}",
                "kind": "live",
                "source": f"stage9-{eval_result['set_id']}-{row['id']}",
                "reconstructed": False,
                "chunks": [{"chunk_id": c, "text": texts[c]} for c in shown],
                "question_text": row["question_text"],
                "answer_text": responder["answer_text"],
                "expected": None,
                "unsupported": [],
                "note": "",
                "stage7": {
                    "run": eval_result["prompt_version"],
                    "verdict": guardian.get("verdict"),
                    "problems": [guardian.get("reason") or ""],
                },
            }
        )
    return cases


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--eval", type=Path, required=True)
    parser.add_argument("--set", type=Path, required=True)
    parser.add_argument("--traces", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    eval_result = json.loads(args.eval.read_text())
    question_set = json.loads(args.set.read_text())
    lines = [json.loads(line) for line in args.traces.read_text().splitlines() if line.strip()]
    cases = draft(eval_result, question_set, retrieved_by_question(lines))
    if args.out.exists():  # keep labels made on an earlier draft
        old = {c["source"]: c for c in json.loads(args.out.read_text())["cases"]}
        for case in cases:
            if case["source"] in old:
                for key in ("expected", "unsupported", "note"):
                    case[key] = old[case["source"]][key]
    data = {"set_id": f"live-guardian-{question_set['set_id']}", "split": "dev", "cases": cases}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {args.out}: {len(cases)} cases")


if __name__ == "__main__":
    main()
