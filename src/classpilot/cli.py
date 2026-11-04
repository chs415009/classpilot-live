"""Command line entry point.

  python -m classpilot.cli run scenarios/01_poll_reteach.json [--mode 2|3]
  python -m classpilot.cli run-all [--mode 2|3]
  python -m classpilot.cli eval --mode 2|3
  python -m classpilot.cli guardian-eval
  python -m classpilot.cli report
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
    print(f"  action={decision['action']} reason={decision['escalation_reason']} "
          f"remediation={decision['remediation_id']} confidence={decision['confidence']}")
    print(f"  nodes={result['trace']['nodes_run']} llm_calls={result['trace']['llm_calls']} "
          f"latency_ms={result['trace']['latency_ms']}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="classpilot")
    sub = parser.add_subparsers(dest="command", required=True)

    run_cmd = sub.add_parser("run", help="run one scenario file and print decision + trace")
    run_cmd.add_argument("scenario", type=Path)
    run_cmd.add_argument("--mode", type=int, choices=[2, 3])

    all_cmd = sub.add_parser("run-all", help="run every file in scenarios/")
    all_cmd.add_argument("--mode", type=int, choices=[2, 3])

    eval_cmd = sub.add_parser("eval", help="run eval/test_questions.json")
    eval_cmd.add_argument("--mode", type=int, choices=[2, 3], default=3)

    sub.add_parser("guardian-eval", help="run eval/guardian_cases.json straight through the Guardian")

    sub.add_parser("report", help="run all scenarios live in mode 2 and 3, write outputs/report.html")

    args = parser.parse_args(argv)

    if args.command == "run":
        result = run_scenario(args.scenario, args.mode)
        print(json.dumps({"decision": result["decision"], "trace": result["trace"]}, indent=2))
        print("matches expected:", result["matches_expected"])
    elif args.command == "run-all":
        for path in scenario_files():
            print_scenario(run_scenario(path, args.mode))
    elif args.command == "eval":
        backend = load_settings().backend
        result = run_eval(args.mode, OUTPUT_DIR / f"eval_traces_{backend}_mode{args.mode}.jsonl")
        out = OUTPUT_DIR / f"eval_{backend}_mode{args.mode}.json"
        out.write_text(json.dumps(result, indent=2))
        print(json.dumps(result["summary"], indent=2))
        print(f"wrote {out}")
    elif args.command == "guardian-eval":
        result = run_guardian_eval()
        out = OUTPUT_DIR / f"guardian_eval_{result['backend']}.json"
        out.write_text(json.dumps(result, indent=2))
        for row in result["rows"]:
            status = "OK " if row["verdict"] == row["expected"] else "MISS" if row["expected"] == "fail" else "FALSE FAIL"
            print(f"[{status}] {row['id']} expected={row['expected']} got={row['verdict']}: {row['reason']}")
        print(json.dumps(result["summary"], indent=2))
        print(f"wrote {out}")
    elif args.command == "report":
        from classpilot.report import build_report

        print(f"wrote {build_report(on_result=print_scenario)}")


if __name__ == "__main__":
    main()
