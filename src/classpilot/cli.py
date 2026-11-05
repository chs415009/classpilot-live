"""Command line entry point.

python -m classpilot.cli run scenarios/01_poll_explain.json
python -m classpilot.cli run-all
python -m classpilot.cli eval
python -m classpilot.cli guardian-eval
"""

import argparse
import json
from pathlib import Path

from classpilot.runner import OUTPUT_DIR, run_eval, run_guardian_eval, run_scenario, scenario_files
from classpilot.settings import load_settings


def print_scenario(result: dict) -> None:
    status = "OK " if result["matches_expected"] else "MISMATCH"
    decision = result["decision"]
    print(f"[{status}] {result['file']}: {result['name']}")
    if decision["path"] == "poll":
        detail = (
            f"option={decision['option']} remediation={decision['remediation_id']} "
            f"show_slide={decision['show_slide']} correct={decision['correct_option']}"
        )
    else:
        detail = f"reason={decision['escalation_reason']} confidence={decision['confidence']}"
    print(f"  action={decision['action']} {detail}")
    print(
        f"  nodes={result['trace']['nodes_run']} llm_calls={result['trace']['llm_calls']} "
        f"latency_ms={result['trace']['latency_ms']}"
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="classpilot")
    sub = parser.add_subparsers(dest="command", required=True)

    run_cmd = sub.add_parser("run", help="run one scenario file and print decision + trace")
    run_cmd.add_argument("scenario", type=Path)

    sub.add_parser("run-all", help="run every file in scenarios/")
    sub.add_parser("eval", help="run eval/test_questions.json")

    sub.add_parser(
        "guardian-eval", help="run eval/guardian_cases.json straight through the Guardian"
    )

    args = parser.parse_args(argv)

    if args.command == "run":
        result = run_scenario(args.scenario)
        print(json.dumps({key: result[key] for key in ("decision", "records")}, indent=2))
        print("matches expected:", result["matches_expected"])
    elif args.command == "run-all":
        for path in scenario_files():
            print_scenario(run_scenario(path))
    elif args.command == "eval":
        backend = load_settings().backend
        result = run_eval(
            OUTPUT_DIR / f"eval_traces_{backend}.jsonl",
            OUTPUT_DIR / f"eval_decision_log_{backend}.jsonl",
        )
        out = OUTPUT_DIR / f"eval_{backend}.json"
        out.write_text(json.dumps(result, indent=2))
        print(json.dumps(result["summary"], indent=2))
        print(f"wrote {out}")
    elif args.command == "guardian-eval":
        result = run_guardian_eval()
        out = OUTPUT_DIR / f"guardian_eval_{result['backend']}.json"
        out.write_text(json.dumps(result, indent=2))
        for row in result["rows"]:
            status = (
                "OK "
                if row["verdict"] == row["expected"]
                else "MISS"
                if row["expected"] == "fail"
                else "FALSE FAIL"
            )
            print(
                f"[{status}] {row['id']} expected={row['expected']} "
                f"got={row['verdict']}: {row['reason']}"
            )
        print(json.dumps(result["summary"], indent=2))
        print(f"wrote {out}")


if __name__ == "__main__":
    main()
