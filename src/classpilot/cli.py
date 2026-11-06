"""Command line entry point.

python -m classpilot.cli run scenarios/01_poll_explain.json
python -m classpilot.cli run-all
python -m classpilot.cli eval
python -m classpilot.cli guardian-eval
BACKEND=cortex python -m classpilot.cli compile --program-id prep-writers-v1
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
    from classpilot.prep.backends import make_parse_deps

    return make_parse_deps(settings, PREP_TABLES_DIR, CONVERT_DIR)


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
    from classpilot.prep.backends import make_generate_deps

    return make_generate_deps(settings, material)


def generate_step(lesson_id: str, settings, tables) -> bool:
    from collections import Counter

    from classpilot.prep.generate import GenerateError, Generator, load_material
    from classpilot.prep.outputs import copy_slide_images, write_generation

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
    write_generation(out_dir, result, settings.backend, seconds)
    copied, missing = copy_slide_images(lesson_id, tables, CONVERT_DIR, out_dir)

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
    from classpilot.prep.outputs import check_and_review

    out_dir = PREP_DIR / lesson_id
    if not (out_dir / "manifest.json").is_file():
        print(f"error: no manifest for {lesson_id!r}; run prep generate first")
        return False
    try:
        problems, n_chunks = check_and_review(out_dir, lesson_id, tables, poll_count)
    except ValueError as exc:
        print(f"check: manifest does not validate: {exc}")
        return False
    if problems:
        print(f"check: {len(problems)} problem(s)")
        for problem in problems:
            print(f"  - {problem}")
    else:
        print(f"check: OK (manifest, statuses, {n_chunks} lesson chunks, show_slide, TTS lint)")
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
    from classpilot.prep.backends import make_tables

    return make_tables(settings, PREP_TABLES_DIR)


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


def run_guardian_eval_file(path: Path | None, overrides: dict | None) -> None:
    result = run_guardian_eval(path, overrides)
    tag = result["backend"] if path is None else f"{path.stem}_{result['backend']}"
    if overrides:
        tag += f"_{overrides['prep']['model']}"
    out = OUTPUT_DIR / f"guardian_eval_{tag}.json"
    out.write_text(json.dumps(result, indent=2))
    for row in result["rows"]:
        if row["verdict"] == row["expected"]:
            status = "OK "
        elif row["verdict"] == "error":
            status = "ERROR"
        else:
            status = "MISS" if row["expected"] == "fail" else "FALSE FAIL"
        print(
            f"[{status}] {row['id']} ({row['kind']}) expected={row['expected']} "
            f"got={row['verdict']}: {row['reason']}"
        )
    print(json.dumps(result["summary"], indent=2))
    print(f"wrote {out}")


def run_compile(args) -> int:
    """Compile the prep writers on the synthetic trainset and save compiled/<id>.json."""
    from classpilot.adapters.cortex_engine import make_prep_lm
    from classpilot.agents.compiled import COMPILED_DIR, program_path, save_program
    from classpilot.agents.prep_program import DSPyPrepAgents
    from classpilot.compiling import CompileLog, compile_writer, load_prep_trainset

    settings = load_settings()
    if settings.backend != "cortex":
        print("compile calls the LLM: run it with BACKEND=cortex (after approval)")
        return 2
    if program_path(args.program_id).exists() and not args.overwrite:
        print(f"{program_path(args.program_id)} exists; pass --overwrite to replace it")
        return 2
    items = load_prep_trainset(args.train)
    guardian = DSPyPrepAgents(make_prep_lm(settings))  # uncompiled Guardian as the metric
    log, modules = CompileLog(), {}
    start = time.perf_counter()
    for task in args.task:
        modules[task] = compile_writer(
            task,
            items[task],
            make_prep_lm(settings),
            guardian,
            settings.prep.llm_timeout_seconds,
            args.max_demos,
            log,
        )
        print(f"{task}: {len(modules[task].demos)} demos")
    meta = {
        "trainset": args.train.name,
        "metric": "structure check + uncompiled prep Guardian + Guardian rule (quotes)",
        "optimizer": "BootstrapFewShot",
        "max_bootstrapped_demos": args.max_demos,
        "model": settings.prep.model or settings.llm.model,
        "tried": log.tried,
    }
    path = save_program(args.program_id, modules, meta, COMPILED_DIR)
    seconds = round(time.perf_counter() - start, 1)
    print(f"tried {len(log.tried)} examples in {seconds} s; wrote {path}")
    return 0


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="classpilot")
    sub = parser.add_subparsers(dest="command", required=True)

    run_cmd = sub.add_parser("run", help="run one scenario file and print decision + trace")
    run_cmd.add_argument("scenario", type=Path)

    sub.add_parser("run-all", help="run every file in scenarios/")
    eval_cmd = sub.add_parser(
        "eval", help="run a labeled question set (default: v1 eval/test_questions.json)"
    )
    eval_cmd.add_argument(
        "--set", type=Path, help="question set file, e.g. eval/questions_train.json"
    )

    guardian_cmd = sub.add_parser(
        "guardian-eval",
        help="run labeled Guardian cases straight through the Guardian (default: v1 cases)",
    )
    guardian_cmd.add_argument(
        "--cases", type=Path, action="append", help="case file; repeat for several"
    )
    guardian_cmd.add_argument(
        "--prep-model", help="Cortex model for the prep Guardian (overrides prep.model)"
    )

    sheet_cmd = sub.add_parser(
        "guardian-sheet", help="write a labeling sheet for a Guardian case file (outputs/)"
    )
    sheet_cmd.add_argument("cases", type=Path)

    compile_cmd = sub.add_parser(
        "compile", help="compile the prep writers on the synthetic trainset (BACKEND=cortex)"
    )
    compile_cmd.add_argument("--program-id", required=True, help="compiled/<id>.json")
    compile_cmd.add_argument(
        "--task",
        action="append",
        choices=["script_writer", "explanation_writer"],
        help="writer to compile; repeat for both (default: both)",
    )
    compile_cmd.add_argument("--train", type=Path, default=Path("eval/prep_train.json"))
    compile_cmd.add_argument("--max-demos", type=int, default=2)
    compile_cmd.add_argument("--overwrite", action="store_true")

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
    if args.command == "compile":
        args.task = args.task or ["script_writer", "explanation_writer"]
        raise SystemExit(run_compile(args))

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
        tag = backend if args.set is None else f"{args.set.stem}_{backend}"
        result = run_eval(
            OUTPUT_DIR / f"eval_traces_{tag}.jsonl",
            OUTPUT_DIR / f"eval_decision_log_{tag}.jsonl",
            set_path=args.set,
        )
        out = OUTPUT_DIR / f"eval_{tag}.json"
        out.write_text(json.dumps(result, indent=2))
        print(json.dumps(result["summary"], indent=2))
        print(f"wrote {out}")
    elif args.command == "guardian-sheet":
        from classpilot.guardian_cases import case_sheet, label_problems, load_cases

        case_set = load_cases(args.cases)
        out = OUTPUT_DIR / "labeling" / f"{args.cases.stem}.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(case_sheet(case_set))
        print(f"wrote {out}; {len(label_problems(case_set))} labels still open")
    elif args.command == "guardian-eval":
        overrides = {"prep": {"model": args.prep_model}} if args.prep_model else None
        for path in args.cases or [None]:
            run_guardian_eval_file(path, overrides)


if __name__ == "__main__":
    main()
