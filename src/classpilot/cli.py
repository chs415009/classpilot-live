"""Command line entry point.

python -m classpilot.cli run scenarios/01_poll_explain.json
python -m classpilot.cli run-all
python -m classpilot.cli eval
python -m classpilot.cli guardian-eval
python -m classpilot.cli prep convert deck.pptx --ref reading.pdf --ref notes.docx
python -m classpilot.cli prep parse --lesson l1 deck.pptx --ref reading.pdf
python -m classpilot.cli prep search --lesson l1 "why keep raw data"
python -m classpilot.cli prep generate --lesson l1 --poll-count 3
python -m classpilot.cli prep check --lesson l1
python -m classpilot.cli prep run --backend mock --lesson l1 deck.pptx --ref reading.pdf
"""

import argparse
import json
import time
from pathlib import Path

from classpilot.runner import OUTPUT_DIR, run_eval, run_guardian_eval, run_scenario, scenario_files
from classpilot.settings import load_settings

CONVERT_DIR = OUTPUT_DIR / "convert"
PREP_TABLES_DIR = OUTPUT_DIR / "prep_tables"  # mock-mode tables
PARSE_REPORT_DIR = OUTPUT_DIR / "parse"
PREP_DIR = OUTPUT_DIR / "prep"  # <lesson>/manifest.json, generation_report.json, slides/


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


def prep_settings(args):
    overrides = {}
    if getattr(args, "backend", None):
        overrides["backend"] = args.backend
    if getattr(args, "poll_count", None) is not None:
        overrides["prep"] = {"poll_count": args.poll_count}
    return load_settings(overrides=overrides)


def parse_step(args, settings, deps) -> bool:
    from dataclasses import asdict

    from classpilot.prep.convert import ConvertError
    from classpilot.prep.libreoffice import LibreOfficeError
    from classpilot.prep.pages import AlignmentError
    from classpilot.prep.parse import ParseError, parse_lesson

    try:
        reports = parse_lesson(args.lesson, args.files, args.ref, deps, source=args.source)
    except (ParseError, ConvertError, LibreOfficeError, AlignmentError) as exc:
        print(f"error: {exc}")
        return False
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
    return True


def run_prep_parse(args) -> int:
    settings = prep_settings(args)
    return 0 if parse_step(args, settings, build_parse_deps(settings)) else 1


def build_generate_deps(settings, tables, material):
    """Mock generators and retrieval, or DSPy on Cortex and Cortex Search (BACKEND=cortex)."""
    from classpilot.adapters.retrieval import CortexSearchRetriever, MockRetriever
    from classpilot.prep.generate import GenerateDeps

    if settings.backend == "mock":
        from classpilot.adapters.mock_prep import MockPrepLLM

        llm, retriever = MockPrepLLM(), MockRetriever(material.retrieval_rows())
    else:
        from classpilot.adapters.cortex_engine import make_prep_lm
        from classpilot.agents.prep_program import DSPyPrepAgents

        llm = DSPyPrepAgents(make_prep_lm(settings))
        retriever = CortexSearchRetriever(settings, service_name=settings.objects.search_service)
    return GenerateDeps(llm, retriever, settings.prep, settings.poll)


def copy_slide_images(lesson_id: str, tables, out_dir: Path) -> tuple[int, int]:
    """Slide PNGs from the local conversion into <out>/slides/<slide_id>.png."""
    import shutil

    copied = missing = 0
    (out_dir / "slides").mkdir(parents=True, exist_ok=True)
    for parsed in tables.lesson_files(lesson_id):
        if parsed.kind != "slides":
            continue
        for page in parsed.pages:
            png = CONVERT_DIR / parsed.file_id[:16] / "pages" / f"p{page.page_index:02d}.png"
            if png.is_file():
                shutil.copyfile(png, out_dir / "slides" / f"{page.page_id}.png")
                copied += 1
            else:
                missing += 1
    return copied, missing


def generate_step(lesson_id: str, settings, tables) -> bool:
    from collections import Counter
    from dataclasses import asdict

    from classpilot.prep.generate import GenerateError, Generator, load_material

    try:
        material = load_material(lesson_id, tables)
        deps = build_generate_deps(settings, tables, material)
        start = time.perf_counter()
        result = Generator(material, deps).run()
        seconds = round(time.perf_counter() - start, 1)
    except GenerateError as exc:
        print(f"error: {exc}")
        return False
    out_dir = PREP_DIR / lesson_id
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "manifest.json").write_text(result.manifest.model_dump_json(indent=2))
    report = {
        "backend": settings.backend,
        "seconds": seconds,
        **asdict(result.report),
        "summary": result.report.summary(),
    }
    (out_dir / "generation_report.json").write_text(json.dumps(report, indent=2))
    copied, missing = copy_slide_images(lesson_id, tables, out_dir)

    m = result.manifest
    print(
        f"generate: backend={settings.backend} lesson={lesson_id} poll_count={deps.prep.poll_count}"
    )
    print(f"  segments: {len(m.segments)} ({result.report.items[0].status})")
    kinds = {"slides": [s.status for s in m.slides.values()]}
    kinds["polls"] = [q.status for s in m.segments for q in s.questions.values()]
    kinds["explanations"] = [r.status for r in m.remediations.values()]
    for kind, statuses in kinds.items():
        counts = ", ".join(f"{k} {v}" for k, v in sorted(Counter(statuses).items())) or "none"
        print(f"  {kind}: {counts}")
    active = [s.active_poll for s in m.segments if s.active_poll]
    print(f"  active polls: {len(active)} {active}")
    print(
        f"  LLM calls: {result.report.llm_calls} in {seconds} s; "
        f"slide images: {copied} copied, {missing} missing"
    )
    print(f"wrote {out_dir}/manifest.json and generation_report.json")
    return check_step(lesson_id, tables, deps.prep.poll_count)


def check_step(lesson_id: str, tables, poll_count: int) -> bool:
    """Stage 7 checks on the stored manifest, then the review sheet."""
    from classpilot.contracts.manifest import load_manifest
    from classpilot.prep.checks import manifest_check_problems
    from classpilot.prep.review import render_review

    out_dir = PREP_DIR / lesson_id
    if not (out_dir / "manifest.json").is_file():
        print(f"error: no manifest for {lesson_id!r}; run prep generate first")
        return False
    try:
        manifest = load_manifest(out_dir / "manifest.json")
    except ValueError as exc:
        print(f"check: manifest does not validate: {exc}")
        return False
    report = json.loads((out_dir / "generation_report.json").read_text())
    chunks = tables.lesson_chunks(lesson_id)
    pages = {c.chunk_id: c.page_id for c in chunks}
    problems = manifest_check_problems(manifest, report, pages, poll_count)
    review = render_review(manifest, report, {c.chunk_id: c.text for c in chunks})
    (out_dir / "review.md").write_text(review)
    if problems:
        print(f"check: {len(problems)} problem(s)")
        for problem in problems:
            print(f"  - {problem}")
    else:
        print(f"check: OK (manifest, statuses, {len(pages)} lesson chunks, show_slide, TTS lint)")
    print(f"wrote {out_dir}/review.md")
    return not problems


def run_prep_check(args) -> int:
    settings = prep_settings(args)
    report = PREP_DIR / args.lesson / "generation_report.json"
    poll_count = settings.prep.poll_count
    if report.is_file():
        poll_count = json.loads(report.read_text()).get("poll_count", poll_count)
    return 0 if check_step(args.lesson, prep_tables(settings), poll_count) else 1


def prep_tables(settings):
    from classpilot.prep.tables import LocalTables, SnowflakeTables

    if settings.backend == "mock":
        return LocalTables(PREP_TABLES_DIR)
    from classpilot.adapters.snowflake import shared_connection

    return SnowflakeTables(shared_connection(), settings.objects)


def run_prep_generate(args) -> int:
    settings = prep_settings(args)
    return 0 if generate_step(args.lesson, settings, prep_tables(settings)) else 1


def run_prep_run(args) -> int:
    """convert -> parse -> chunk -> generate -> check -> manifest, in one command."""
    settings = prep_settings(args)
    deps = build_parse_deps(settings)
    if not parse_step(args, settings, deps):
        return 1
    return 0 if generate_step(args.lesson, settings, deps.tables) else 1


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
    run_cmd_p = prep_sub.add_parser(
        "run", help="the whole prep pipeline: parse (as prep parse), then generate"
    )
    run_cmd_p.add_argument("--lesson", required=True, help="lesson id")
    run_cmd_p.add_argument("files", nargs="*", type=Path, help="slides (PPTX or PDF)")
    run_cmd_p.add_argument(
        "--ref", action="append", default=[], type=Path, help="reference (PDF or DOCX)"
    )
    run_cmd_p.add_argument("--source", help="source id for a single new file")
    generate_cmd = prep_sub.add_parser(
        "generate", help="generate scripts, polls, explanations and the manifest from the parse"
    )
    generate_cmd.add_argument("--lesson", required=True, help="lesson id")
    check_cmd = prep_sub.add_parser(
        "check", help="check a generated manifest against the lesson chunks; write review.md"
    )
    check_cmd.add_argument("--lesson", required=True, help="lesson id")
    for cmd in (parse_cmd, run_cmd_p, generate_cmd, check_cmd):
        cmd.add_argument("--backend", choices=["mock", "cortex"], help="overrides BACKEND")
    for cmd in (run_cmd_p, generate_cmd):
        cmd.add_argument("--poll-count", type=int, help="overrides prep.poll_count")
    search_cmd = prep_sub.add_parser("search", help="search a lesson's chunks")
    search_cmd.add_argument("--lesson", required=True)
    search_cmd.add_argument("queries", nargs="+")
    search_cmd.add_argument("--top-k", type=int, default=3)

    args = parser.parse_args(argv)

    if args.command == "prep":
        if args.prep_command == "search":
            raise SystemExit(run_prep_search(args))
        if args.prep_command == "generate":
            raise SystemExit(run_prep_generate(args))
        if args.prep_command == "check":
            raise SystemExit(run_prep_check(args))
        if not args.files and not args.ref:
            parser.error(f"prep {args.prep_command} needs at least one file")
        run = {"parse": run_prep_parse, "run": run_prep_run, "convert": run_prep_convert}
        raise SystemExit(run[args.prep_command](args))
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
