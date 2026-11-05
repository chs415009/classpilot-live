"""Command line entry point.

python -m classpilot.cli run scenarios/01_poll_explain.json
python -m classpilot.cli run-all
python -m classpilot.cli eval
python -m classpilot.cli guardian-eval
python -m classpilot.cli prep convert deck.pptx --ref reading.pdf --ref notes.docx
python -m classpilot.cli prep parse --lesson l1 deck.pptx --ref reading.pdf
python -m classpilot.cli prep search --lesson l1 "why keep raw data"
"""

import argparse
import json
from pathlib import Path

from classpilot.runner import OUTPUT_DIR, run_eval, run_guardian_eval, run_scenario, scenario_files
from classpilot.settings import load_settings

CONVERT_DIR = OUTPUT_DIR / "convert"
PREP_TABLES_DIR = OUTPUT_DIR / "prep_tables"  # mock-mode tables
PARSE_REPORT_DIR = OUTPUT_DIR / "parse"


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


def print_converted(result) -> None:
    pages = f"{result.page_count} pages" if result.page_count is not None else "passed through"
    extra = " (re-saved copy for LibreOffice)" if result.pptx_repaired else ""
    print(
        f"{result.source_id} [{result.kind} {result.format}] {result.original_name}: {pages}{extra}"
    )
    print(f"  file_id={result.file_id}")
    for page in result.pages:
        notes = "notes" if page.notes else "-"
        print(
            f"  {page.page_id} {page.image_flag:<6} {page.image_reason:<17} {notes:<5} "
            f"text={page.signals.text_chars} image={page.signals.image_area} "
            f"drawing={page.signals.drawing_area} png={page.png_bytes // 1024} KB"
        )


def run_prep_convert(args) -> int:
    from classpilot.prep.convert import ConvertError, convert_files
    from classpilot.prep.libreoffice import LibreOfficeError
    from classpilot.prep.pages import AlignmentError

    try:
        results = convert_files(
            args.files, args.ref, args.out, load_settings().parse, source=args.source
        )
    except AlignmentError as exc:
        print(f"alignment error: {exc}")
        print(exc.report.model_dump_json(indent=2))
        return 1
    except (ConvertError, LibreOfficeError) as exc:
        print(f"error: {exc}")
        return 1
    for result in results:
        print_converted(result)
    print(f"wrote {args.out}/<file_id[:16]>/convert.json")
    return 0


def build_parse_deps(settings):
    """Mock adapters and local tables, or Snowflake (BACKEND=cortex)."""
    from classpilot.adapters import parse as adapters
    from classpilot.prep.parse import ParseDeps
    from classpilot.prep.tables import LocalTables, SnowflakeTables

    cfg = settings.parse
    if settings.backend == "mock":
        stage = adapters.MockStage()
        return ParseDeps(
            stage,
            adapters.MockParser(stage),
            adapters.MockVision(),
            LocalTables(PREP_TABLES_DIR),
            cfg,
            CONVERT_DIR,
        )
    from classpilot.adapters.snowflake import shared_connection

    conn, stage_name = shared_connection(), settings.objects.raw_stage
    return ParseDeps(
        adapters.SnowflakeStage(conn, stage_name),
        adapters.CortexParser(conn, stage_name, cfg.parse_timeout_seconds),
        adapters.CortexVision(
            conn, stage_name, cfg.vision_model, cfg.vision_max_tokens, cfg.vision_timeout_seconds
        ),
        SnowflakeTables(conn, settings.objects),
        cfg,
        CONVERT_DIR,
    )


def run_prep_parse(args) -> int:
    from dataclasses import asdict

    from classpilot.prep.convert import ConvertError
    from classpilot.prep.libreoffice import LibreOfficeError
    from classpilot.prep.pages import AlignmentError
    from classpilot.prep.parse import ParseError, parse_lesson

    settings = load_settings()
    deps = build_parse_deps(settings)
    try:
        reports = parse_lesson(args.lesson, args.files, args.ref, deps, source=args.source)
    except (ParseError, ConvertError, LibreOfficeError, AlignmentError) as exc:
        print(f"error: {exc}")
        return 1
    print(f"backend={settings.backend} lesson={args.lesson}")
    for r in reports:
        state = "reused (known hash)" if r.reused else f"parsed, {r.parse_calls} parse calls"
        fallback = ", parse failed: local text used" if r.parse_fallback else ""
        print(f"{r.source_id} [{r.kind}] {r.original_name}: {r.pages} pages, {state}{fallback}")
        print(f"  vision: {len(r.vision_pages)} pages {r.vision_pages}, failed {r.vision_failed}")
        print(f"  chunks: {r.chunks}")
    PARSE_REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = PARSE_REPORT_DIR / f"{args.lesson}.json"
    chunks = deps.tables.lesson_chunks(args.lesson)
    out.write_text(
        json.dumps(
            {
                "lesson_id": args.lesson,
                "backend": settings.backend,
                "files": [asdict(r) for r in reports],
                "chunks": [c.model_dump() for c in chunks],
            },
            indent=2,
        )
    )
    print(f"wrote {out}")
    return 0


def run_prep_search(args) -> int:
    from classpilot.adapters.retrieval import CortexSearchRetriever, MockRetriever

    settings = load_settings()
    if settings.backend == "mock":
        from classpilot.prep.tables import LocalTables

        rows = [
            {"chunk_id": c.chunk_id, "text": c.text, "lesson_id": args.lesson}
            for c in LocalTables(PREP_TABLES_DIR).lesson_chunks(args.lesson)
        ]
        retriever = MockRetriever(rows)
    else:
        retriever = CortexSearchRetriever(settings, service_name=settings.objects.search_service)
    for query in args.queries:
        print(f"query: {query}")
        for hit in retriever.search(query, args.top_k, args.lesson):
            print(f"  {hit.score:6.3f} {hit.chunk_id}: {hit.text[:100]!r}")
    return 0


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

    prep_cmd = sub.add_parser("prep", help="prep steps (before class)")
    prep_sub = prep_cmd.add_subparsers(dest="prep_command", required=True)
    convert_cmd = prep_sub.add_parser(
        "convert", help="local conversion: text, notes, PNGs, image-page flags"
    )
    convert_cmd.add_argument("files", nargs="*", type=Path, help="slides (PPTX or PDF)")
    convert_cmd.add_argument(
        "--ref", action="append", default=[], type=Path, help="reference (PDF or DOCX)"
    )
    convert_cmd.add_argument("--source", help="source id for a single file")
    convert_cmd.add_argument("--out", type=Path, default=CONVERT_DIR)
    parse_cmd = prep_sub.add_parser(
        "parse", help="convert, parse, describe image pages, chunk, and load a lesson"
    )
    parse_cmd.add_argument("--lesson", required=True, help="lesson id")
    parse_cmd.add_argument("files", nargs="*", type=Path, help="slides (PPTX or PDF)")
    parse_cmd.add_argument(
        "--ref", action="append", default=[], type=Path, help="reference (PDF or DOCX)"
    )
    parse_cmd.add_argument("--source", help="source id for a single new file")
    search_cmd = prep_sub.add_parser("search", help="search a lesson's chunks")
    search_cmd.add_argument("--lesson", required=True)
    search_cmd.add_argument("queries", nargs="+")
    search_cmd.add_argument("--top-k", type=int, default=3)

    args = parser.parse_args(argv)

    if args.command == "prep":
        if args.prep_command == "search":
            raise SystemExit(run_prep_search(args))
        if not args.files and not args.ref:
            parser.error(f"prep {args.prep_command} needs at least one file")
        run = run_prep_parse if args.prep_command == "parse" else run_prep_convert
        raise SystemExit(run(args))
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
