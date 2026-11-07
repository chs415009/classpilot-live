"""Command line entry point.

python -m classpilot.cli run scenarios/01_poll_explain.json
python -m classpilot.cli run-all
python -m classpilot.cli eval
python -m classpilot.cli guardian-eval
BACKEND=cortex python -m classpilot.cli compile --side live --program-id <id>
BACKEND=cortex python -m classpilot.cli optimize-guardian --method eval --program live-qa-v5
python -m classpilot.cli prep convert deck.pptx --ref reading.pdf --ref notes.docx
python -m classpilot.cli prep parse --lesson l1 deck.pptx --ref reading.pdf
python -m classpilot.cli prep search --lesson l1 "why keep raw data"
python -m classpilot.cli prep generate --lesson l1 --poll-count 3
python -m classpilot.cli prep check --lesson l1
python -m classpilot.cli prep run --backend mock --lesson l1 deck.pptx --ref reading.pdf
python -m classpilot.cli dev l1 [--backend cortex] [--skip-prep]
python -m classpilot.cli dev --list
python -m classpilot.cli export <session_id> [--data-dir outputs/service]
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
DEV_DIR = OUTPUT_DIR / "dev"  # <lesson>/<run>/report.html, results.json; index.html


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
    prep = {}
    if getattr(args, "poll_count", None) is not None:
        prep["poll_count"] = args.poll_count
    if getattr(args, "compiled_program", None):
        prep["compiled_program"] = args.compiled_program
    if prep:
        overrides["prep"] = prep
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
        retriever = CortexSearchRetriever(settings)
    for query in args.queries:
        print(f"query: {query}")
        for hit in retriever.search(query, args.top_k, args.lesson):
            print(f"  {hit.score:6.3f} {hit.chunk_id}: {hit.text[:100]!r}")
    return 0


def live_adapters(settings, content):
    """The live LLM and retriever of a prepped lesson, as the service uses them."""
    from classpilot.adapters.retrieval import CortexSearchRetriever, MockRetriever

    if settings.backend == "cortex":
        from classpilot.agents.compiled import cortex_live_agents

        retriever = CortexSearchRetriever(settings)
        return cortex_live_agents(settings), retriever
    from classpilot.adapters.llm import MockLLM

    return MockLLM(), MockRetriever(content.chunks)


def run_dev_list(args) -> int:
    from classpilot.dev.lessons import LessonError, list_lessons, load_lesson

    names = list_lessons(args.lessons_dir)
    if not names:
        print(f"no lesson folders in {args.lessons_dir}")
    for name in names:
        try:
            folder = load_lesson(name, args.lessons_dir)
        except LessonError as exc:
            print(f"{name}: not usable ({exc})")
            continue
        has_q = "test_questions.json" if folder.questions_path.is_file() else "no test questions"
        runs = sorted((DEV_DIR / name).glob("*/results.json"))
        last = runs[-1].parent.name if runs else "never run"
        files = ", ".join(p.name for p in folder.slides + folder.refs)
        print(f"{name}: {files} · {has_q} · last run {last}")
    return 0


def run_dev(args) -> int:
    """Demo entry (Stage 10): prep a lesson folder, run its test questions, write the
    dev report. With --skip-prep the last prep output of the lesson is reused."""
    import shutil
    from datetime import UTC, datetime

    from classpilot.content import lesson_content
    from classpilot.contracts.manifest import load_manifest
    from classpilot.dev.lessons import LessonError, load_lesson, load_questions
    from classpilot.dev.live_run import run_questions
    from classpilot.dev.report import render_report, summarize, write_index
    from classpilot.live.question_graph import Deps
    from classpilot.prep.convert import file_sha256
    from classpilot.prep.outputs import check_and_review
    from classpilot.trace import utc_now

    try:
        folder = load_lesson(args.lesson, args.lessons_dir)
        qset = load_questions(folder.questions_path, folder.lesson_id)
    except LessonError as exc:
        print(f"error: {exc}")
        return 1
    lesson = folder.lesson_id
    settings = prep_settings(argparse.Namespace(backend=args.backend, poll_count=folder.poll_count))
    prep_dir = PREP_DIR / lesson
    manifest_path = prep_dir / "manifest.json"
    print(f"dev: lesson={lesson} backend={settings.backend} questions={len(qset.questions)}")

    if args.skip_prep:
        tables = prep_tables(settings)
    else:
        started = time.time()
        deps = build_parse_deps(settings)
        parse_args = argparse.Namespace(
            lesson=lesson, files=folder.slides, ref=folder.refs, source=None
        )
        if not parse_step(parse_args, settings, deps):
            return 1
        generate_step(lesson, settings, deps.tables)  # False also when only checks fail
        tables = deps.tables
        if not manifest_path.is_file() or manifest_path.stat().st_mtime < started:
            print("error: prep wrote no new manifest; see the errors above")
            return 1
    if not manifest_path.is_file():
        print(f"error: no manifest for {lesson!r}; run without --skip-prep first")
        return 1
    gen_path = prep_dir / "generation_report.json"
    gen = json.loads(gen_path.read_text()) if gen_path.is_file() else None
    prep_backend = (gen or {}).get("backend")
    if args.skip_prep and prep_backend and prep_backend != settings.backend:
        # Its chunks live in the other backend's tables; checks would fail on all of them.
        print(
            f"error: the last prep of {lesson!r} ran on {prep_backend}; "
            f"use --backend {prep_backend}, or run without --skip-prep"
        )
        return 1
    try:
        manifest = load_manifest(manifest_path)
        poll_count = (gen or {}).get("poll_count", settings.prep.poll_count)
        problems, _ = check_and_review(prep_dir, lesson, tables, poll_count)
    except ValueError as exc:
        print(f"error: manifest does not validate: {exc}")
        return 1
    chunks = tables.lesson_chunks(lesson)
    content = lesson_content(lesson, manifest, chunks)
    llm, retriever = live_adapters(settings, content)
    # Tables keep every file ever added to the lesson; flag the ones the folder lacks.
    folder_ids = {file_sha256(p) for p in folder.slides + folder.refs}
    extra = [f.original_name for f in tables.lesson_files(lesson) if f.file_id not in folder_ids]
    if extra:
        print(f"warning: the lesson also holds files not in the folder: {', '.join(extra)}")

    run_id = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    run_dir = DEV_DIR / lesson / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    if (prep_dir / "slides").is_dir():
        shutil.copytree(prep_dir / "slides", run_dir / "slides", dirs_exist_ok=True)
    for name in ("manifest.json", "generation_report.json", "review.md"):
        if (prep_dir / name).is_file():
            shutil.copy2(prep_dir / name, run_dir / name)

    def show(row: dict) -> None:
        mark = "OK   " if row["match"] else "CHECK"
        reason = f" {row['escalation_reason']}" if row["escalation_reason"] else ""
        print(f"  [{mark}] {row['question_id']} {row['category']}: {row['action']}{reason}")

    start = time.perf_counter()
    rows = run_questions(
        qset,
        Deps(settings, content, llm, retriever),
        f"dev-{run_id}",
        run_dir / "traces.jsonl",
        run_dir / "decision_log.jsonl",
        on_row=show,
    )
    live_seconds = round(time.perf_counter() - start, 1)
    data = {
        "run_id": run_id,
        "lesson_id": lesson,
        "title": folder.title,
        "created_at": utc_now(),
        "backend": settings.backend,
        "files": {
            "slides": [p.name for p in folder.slides],
            "refs": [p.name for p in folder.refs],
        },
        "prep": {
            "ran": not args.skip_prep,
            "model": (settings.prep.model or settings.llm.model)
            if (gen or {}).get("backend") == "cortex"
            else "mock",
            "manifest": manifest.model_dump(mode="json"),
            "generation_report": gen,
            "check_problems": problems,
            "extra_files": extra,
        },
        "live": {
            "seconds": live_seconds,
            "prompt_versions": sorted({v for r in rows for v in r["prompt_versions"]}),
            "models": sorted({m for r in rows for m in r["models"]}),
            "rows": rows,
        },
        "chunks": {c.chunk_id: c.text for c in chunks},
    }
    (run_dir / "results.json").write_text(json.dumps(data, indent=2, ensure_ascii=False))
    (run_dir / "report.html").write_text(render_report(data))
    index = write_index(DEV_DIR)
    q = summarize(data)["questions"]
    print(f"questions: {q['match']}/{q['total']} as expected, {q['llm_calls']} LLM calls")
    print(f"wrote {run_dir / 'report.html'}")
    print(f"index {index}")
    return 0


def run_export(args) -> int:
    """The service's session export (same zip as GET /sessions/{id}/export, Q-22)."""
    from classpilot.service.exports import session_export
    from classpilot.service.store import LessonStore, now, safe_name
    from classpilot.settings import PROJECT_ROOT

    data_dir = args.data_dir or PROJECT_ROOT / load_settings().service.data_dir
    result = session_export(
        args.session_id,
        data_dir / "traces.jsonl",
        data_dir / "decision_log.jsonl",
        LessonStore(data_dir).prep_dir,
        now(),
    )
    if result is None:
        print(f"error: session {args.session_id!r} has no decisions in {data_dir}")
        return 1
    data, summary = result
    out = args.out or OUTPUT_DIR / "exports" / f"{safe_name(args.session_id)}.zip"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    print(
        f"session {summary['session_id']}: {summary['decisions']} decisions "
        f"({summary['questions']} questions, {summary['polls']} polls), "
        f"{summary['trace_records']} trace records, lessons {', '.join(summary['lessons'])}"
    )
    print(f"wrote {out}")
    return 0


def run_guardian_eval_file(path: Path | None, overrides: dict | None) -> None:
    result = run_guardian_eval(path, overrides)
    tag = result["backend"] if path is None else f"{path.stem}_{result['backend']}"
    if overrides:
        tag += f"_{overrides['prep']['model']}"
    # Stage 12: the prompt version is in the name, so runs never overwrite each other.
    out = OUTPUT_DIR / f"guardian_eval_{tag}_{result['prompt_version']}.json"
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


def run_compile_live(args, settings) -> tuple[dict, dict]:
    """Analyst and Responder on the synthetic train questions, the Guardian on labeled
    synthetic cases; returns (modules, meta)."""
    from classpilot.adapters.cortex_engine import make_cortex_lm
    from classpilot.agents.program import DSPyAgents
    from classpilot.compiling import (
        CompileLog,
        compile_live,
        load_guardian_trainset,
        load_live_trainset,
    )

    q = settings.question
    items = load_live_trainset(args.train, q.retrieval_top_k, q.analyst_chunk_chars)
    if "guardian" in args.task:
        items["guardian"] = load_guardian_trainset(args.guardian_train)
    guardian_lm = make_cortex_lm(settings, timeout_s=q.guardian_timeout_seconds)
    guardian = DSPyAgents(guardian_lm)  # uncompiled live Guardian as the Responder metric
    log, modules = CompileLog(), {}
    for task in args.task:
        modules[task] = compile_live(
            task,
            items[task],
            guardian_lm if task == "guardian" else make_cortex_lm(settings),
            {"analyst": args.analyst_demos, "guardian": args.guardian_demos}.get(
                task, args.max_demos
            ),
            log,
            guardian,
            q.guardian_timeout_seconds if task == "guardian" else settings.llm.timeout_seconds,
            settings.question.confidence_threshold,
            settings.question.guardian_rescue_coverage,
        )
        print(f"{task}: {len(modules[task].demos)} demos")
    meta = {
        "trainset": args.train.name,
        "guardian_trainset": args.guardian_train.name if "guardian" in args.task else None,
        "metric": "analyst: category label; responder: check_response + uncompiled Guardian "
        "+ check_guardian (retrieved chunks, word rescue); guardian: check_guardian verdict "
        "= the user's label",
        "optimizer": "BootstrapFewShot",
        "max_bootstrapped_demos": args.max_demos,
        "model": settings.llm.model,
        "tried": log.tried,
    }
    return modules, meta


class CountingEngine:
    """Counts the LLM calls of a DSPy custom engine (Stage 12 experiment budget)."""

    def __init__(self, inner):
        self.inner, self.calls = inner, 0

    def complete(self, request):
        self.calls += 1
        return self.inner.complete(request)


def run_optimize_guardian(args) -> int:
    """Stage 12 DSPy experiment on the live Guardian: eval, random search, or GEPA."""
    import dspy

    from classpilot import optimize as opt
    from classpilot.adapters.cortex_engine import CortexCompleteEngine, statement_seconds
    from classpilot.adapters.snowflake import llm_connection
    from classpilot.agents.compiled import program_path
    from classpilot.agents.program import RulesFirstChatAdapter

    settings = load_settings()
    if settings.backend != "cortex":
        print("optimize-guardian calls the LLM: run it with BACKEND=cortex (after approval)")
        return 2
    q, stamp = settings.question, time.strftime("%Y%m%d-%H%M%S")
    out_dir = OUTPUT_DIR / "optimize"
    rescue = q.guardian_rescue_coverage

    def counted_lm(model: str, timeout_s: float, max_tokens: int = 1024):
        conn = llm_connection(statement_seconds(timeout_s))
        engine = CountingEngine(CortexCompleteEngine(conn, timeout_s, max_tokens=max_tokens))
        return dspy.LM(model, engine=engine, cache=False, num_retries=0), engine

    adapter = RulesFirstChatAdapter(use_json_adapter_fallback=False)
    live = args.kind == "live"
    if live:
        lm, engine = counted_lm(settings.llm.model, q.guardian_timeout_seconds)
        train = [opt.to_example(i) for i in opt.load_items(opt.TRAIN_PATH)]
        val = [opt.to_example(i) for p in opt.VAL_PATHS for i in opt.load_items(p)]
    else:
        from classpilot.rules.prep import prep_rule_options

        prep, prep_rules = settings.prep, prep_rule_options(settings.prep)
        lm, engine = counted_lm(
            prep.model or settings.llm.model, prep.llm_timeout_seconds, prep.max_tokens
        )
        train = opt.prep_examples(opt.PREP_TRAIN_PATH, args.kind)
        val = opt.prep_examples(opt.PREP_VAL_PATH, args.kind)

    def program_for(program_id: str | None) -> dspy.Module:
        if live:
            return opt.GuardianProgram(opt.guardian_predict(program_id))
        return opt.PrepGuardianProgram(opt.prep_guardian_predict(program_id, args.kind))

    def score(program: dspy.Module) -> dict:
        with dspy.context(lm=lm, adapter=adapter):
            if live:
                return opt.evaluate(program, val, rescue)
            return opt.evaluate_prep(program, val, prep_rules)

    if args.method == "eval":
        for program_id in args.program:
            for run in range(1, args.runs + 1):
                result = score(program_for(None if program_id == "uncompiled" else program_id))
                result |= {"program": program_id, "kind": args.kind, "run": run}
                result["llm_calls"] = engine.calls
                name = f"eval_{args.kind}_{program_id}_run{run}_{stamp}"
                path = opt.write_result(name, result, out_dir)
                print(f"{program_id} run {run}: {json.dumps(result['summary'])}")
                print(f"  wrote {path}")
        print(f"LLM calls: {engine.calls}")
        return 0

    if program_path(args.program_id).exists() and not args.overwrite:
        print(f"{program_path(args.program_id)} exists; pass --overwrite to replace it")
        return 2
    start, extra = time.perf_counter(), {}
    if args.method == "rs":
        from dspy.teleprompt import BootstrapFewShotWithRandomSearch

        student = program_for(None)
        optimizer = BootstrapFewShotWithRandomSearch(
            metric=opt.make_metric(rescue) if live else opt.make_prep_metric(prep_rules),
            max_bootstrapped_demos=args.max_demos,
            max_labeled_demos=0,
            num_candidate_programs=args.candidates,
            num_threads=1,
        )
        # Seeds: -1 = first-passing demos (like plain BootstrapFewShot), 0.. = shuffled demo sets.
        # -3/-2 (zero-shot, labeled-only) are skipped: the uncompiled baseline covers them.
        restrict = list(range(-1, args.candidates))
        with dspy.context(lm=lm, adapter=adapter):
            best = optimizer.compile(student, trainset=train, valset=val, restrict=restrict)
        extra["candidate_scores"] = [
            {"score": c.get("score"), "demos": len(c["program"].guardian.demos)}
            for c in getattr(best, "candidate_programs", [])
        ]
        meta = {"optimizer": "BootstrapFewShotWithRandomSearch", "candidates": args.candidates}
    else:  # gepa
        from dspy.teleprompt import GEPA

        if not live:
            print("GEPA is wired for the live Guardian only")
            return 2

        reflection_lm, reflection_engine = counted_lm(args.reflection_model, 120, 4000)
        student = opt.GuardianProgram(opt.guardian_predict(args.base))
        optimizer = GEPA(
            metric=opt.make_feedback_metric(rescue),
            max_metric_calls=args.max_metric_calls,
            reflection_lm=reflection_lm,
            num_threads=1,
            track_stats=True,
            seed=0,
            log_dir=str(out_dir / f"gepa_{stamp}"),
        )
        with dspy.context(lm=lm, adapter=adapter):
            best = optimizer.compile(student, trainset=train, valset=val)
        extra["reflection_calls"] = reflection_engine.calls
        details = getattr(best, "detailed_results", None)
        if details is not None:
            extra["val_aggregate_scores"] = list(getattr(details, "val_aggregate_scores", []))
        meta = {"optimizer": "GEPA", "max_metric_calls": args.max_metric_calls}
        meta["reflection_model"] = args.reflection_model
        meta["start_program"] = args.base
    meta |= {
        "kind": args.kind,
        "trainset": (opt.TRAIN_PATH if live else opt.PREP_TRAIN_PATH).name,
        "valset": [p.name for p in opt.VAL_PATHS] if live else [opt.PREP_VAL_PATH.name],
        "metric": "check_guardian verdict = label" if live else "check_prep_guardian = label",
        "model": settings.llm.model if live else (settings.prep.model or settings.llm.model),
    }
    if live:
        path = opt.save_live_program(args.program_id, args.base, best.guardian, meta)
        forbidden = opt.dev_texts(opt.VAL_PATHS)
    else:
        from classpilot.guardian_cases import PREP_TASKS

        task = PREP_TASKS[args.kind]
        path = opt.save_prep_program(args.program_id, args.base, {task: best.guardian}, meta)
        forbidden = [str(v) for e in val for k, v in e.inputs().items() if k != "chunks"]
    leaks = opt.leak_problems(path, forbidden)
    seconds = round(time.perf_counter() - start, 1)
    result = {
        "method": args.method,
        "program_id": args.program_id,
        "seconds": seconds,
        "guardian_calls": engine.calls,
        "leaks": leaks,
        "instructions": best.guardian.signature.instructions,
        "demos": len(best.guardian.demos),
        **extra,
    }
    out = opt.write_result(f"{args.method}_{args.program_id}_{stamp}", result, out_dir)
    print(json.dumps({k: v for k, v in result.items() if k != "instructions"}, indent=2))
    print(f"wrote {path} and {out}")
    if leaks:
        print("LEAK: course content in the saved program; do not commit it")
        return 1
    return 0


def run_compile(args) -> int:
    """Compile the prep writers or the live Analyst/Responder on a synthetic trainset and
    save compiled/<id>.json."""
    from classpilot.adapters.cortex_engine import make_prep_lm
    from classpilot.agents.compiled import COMPILED_DIR, program_path, save_program
    from classpilot.agents.prep_program import DSPyPrepAgents
    from classpilot.compiling import CompileLog, compile_writer, load_prep_trainset
    from classpilot.rules.prep import prep_rule_options

    settings = load_settings()
    if settings.backend != "cortex":
        print("compile calls the LLM: run it with BACKEND=cortex (after approval)")
        return 2
    if program_path(args.program_id).exists() and not args.overwrite:
        print(f"{program_path(args.program_id)} exists; pass --overwrite to replace it")
        return 2
    start = time.perf_counter()
    if args.side == "live":
        modules, meta = run_compile_live(args, settings)
        path = save_program(args.program_id, modules, meta, COMPILED_DIR)
        seconds = round(time.perf_counter() - start, 1)
        print(f"tried {len(meta['tried'])} examples in {seconds} s; wrote {path}")
        return 0
    items = load_prep_trainset(args.train)
    guardian = DSPyPrepAgents(make_prep_lm(settings))  # uncompiled Guardian as the metric
    log, modules = CompileLog(), {}
    for task in args.task:
        modules[task] = compile_writer(
            task,
            items[task],
            make_prep_lm(settings),
            guardian,
            settings.prep.llm_timeout_seconds,
            args.max_demos,
            log,
            prep_rule_options(settings.prep),
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
    eval_cmd.add_argument(
        "--compiled-program", help="compiled/<id>.json for the live agents (Stage 9)"
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

    opt_cmd = sub.add_parser(
        "optimize-guardian", help="Stage 12 DSPy experiment on the live Guardian (cortex)"
    )
    opt_cmd.add_argument("--method", choices=["eval", "rs", "gepa"], required=True)
    opt_cmd.add_argument(
        "--kind", choices=["live", "script", "poll", "explanation"], default="live"
    )
    opt_cmd.add_argument(
        "--program", action="append", default=[], help="eval: program id or 'uncompiled'"
    )
    opt_cmd.add_argument("--runs", type=int, default=1, help="eval: runs per program")
    opt_cmd.add_argument("--program-id", help="rs/gepa: compiled/<id>.json to write")
    opt_cmd.add_argument(
        "--base",
        help="program the new Guardian joins (live default: live-qa-v5; prep: e.g. prep-v6)",
    )
    opt_cmd.add_argument("--candidates", type=int, default=4, help="rs: shuffled demo sets")
    opt_cmd.add_argument("--max-demos", type=int, default=3)
    opt_cmd.add_argument("--max-metric-calls", type=int, default=200, help="gepa budget")
    opt_cmd.add_argument("--reflection-model", default="claude-sonnet-4-5")
    opt_cmd.add_argument("--overwrite", action="store_true")

    compile_cmd = sub.add_parser(
        "compile", help="compile prep writers or live agents on a synthetic trainset (cortex)"
    )
    compile_cmd.add_argument("--program-id", required=True, help="compiled/<id>.json")
    compile_cmd.add_argument("--side", choices=["prep", "live"], default="prep")
    compile_cmd.add_argument(
        "--task",
        action="append",
        choices=["script_writer", "explanation_writer", "analyst", "responder", "guardian"],
        help="module to compile; repeat for several (default: both of the side)",
    )
    compile_cmd.add_argument(
        "--train",
        type=Path,
        help="trainset (default: eval/prep_train.json or eval/questions_train.json)",
    )
    compile_cmd.add_argument(
        "--guardian-train",
        type=Path,
        default=Path("eval/guardian_cases_train.json"),
        help="live: labeled Guardian cases for --task guardian",
    )
    compile_cmd.add_argument("--max-demos", type=int, default=2)
    compile_cmd.add_argument(
        "--guardian-demos", type=int, default=3, help="live: demos for the Guardian (fail and pass)"
    )
    compile_cmd.add_argument(
        "--analyst-demos", type=int, default=3, help="live: demos for the short Analyst prompt"
    )
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
        cmd.add_argument(
            "--compiled-program", help="compiled/<id>.json for the prep writers (Stage 9)"
        )
    search_cmd = prep_sub.add_parser("search", help="search a lesson's chunks")
    search_cmd.add_argument("--lesson", required=True)
    search_cmd.add_argument("queries", nargs="+")
    search_cmd.add_argument("--top-k", type=int, default=3)

    from classpilot.dev.lessons import LESSONS_DIR

    dev_cmd = sub.add_parser(
        "dev", help="demo entry: prep a lesson folder, run its test questions, write the dev report"
    )
    dev_cmd.add_argument("lesson", nargs="?", help="folder name under materials/lessons/")
    dev_cmd.add_argument("--list", action="store_true", help="list the lesson folders")
    dev_cmd.add_argument("--backend", choices=["mock", "cortex"], help="overrides BACKEND")
    dev_cmd.add_argument(
        "--skip-prep", action="store_true", help="reuse the last prep output; questions only"
    )
    dev_cmd.add_argument("--lessons-dir", type=Path, default=LESSONS_DIR)

    export_cmd = sub.add_parser(
        "export", help="zip one session's traces, decision log, and lesson manifests"
    )
    export_cmd.add_argument("session_id")
    export_cmd.add_argument("--data-dir", type=Path, help="default: service.data_dir")
    export_cmd.add_argument("--out", type=Path, help="default: outputs/exports/<session>.zip")

    args = parser.parse_args(argv)
    if args.command == "export":
        raise SystemExit(run_export(args))
    if args.command == "dev":
        if args.list:
            raise SystemExit(run_dev_list(args))
        if not args.lesson:
            parser.error("dev needs a lesson (or --list)")
        raise SystemExit(run_dev(args))
    if args.command == "optimize-guardian":
        if args.base is None and args.kind == "live":
            args.base = "live-qa-v5"
        if args.method == "eval" and not args.program:
            parser.error("--method eval needs --program")
        if args.method != "eval" and not args.program_id:
            parser.error(f"--method {args.method} needs --program-id")
        raise SystemExit(run_optimize_guardian(args))
    if args.command == "compile":
        defaults = {
            "prep": (["script_writer", "explanation_writer"], "eval/prep_train.json"),
            "live": (["analyst", "responder"], "eval/questions_train.json"),
        }
        tasks, train = defaults[args.side]
        args.task = args.task or tasks
        if args.side == "live":
            tasks = [*tasks, "guardian"]  # the Guardian only on request (Stage 12)
        args.train = args.train or Path(train)
        if not set(args.task) <= set(tasks):
            parser.error(f"--side {args.side} compiles {', '.join(tasks)}")
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
        from classpilot.contracts.trace import PROMPT_VERSION

        settings = load_settings()
        tag = settings.backend if args.set is None else f"{args.set.stem}_{settings.backend}"
        overrides = None
        if args.compiled_program:
            overrides = {"llm": {"compiled_program": args.compiled_program}}
        # Stage 12: always name the program, so runs never overwrite each other.
        tag = f"{tag}_{args.compiled_program or settings.llm.compiled_program or PROMPT_VERSION}"
        result = run_eval(
            OUTPUT_DIR / f"eval_traces_{tag}.jsonl",
            OUTPUT_DIR / f"eval_decision_log_{tag}.jsonl",
            set_path=args.set,
            overrides=overrides,
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
