"""Generate a lesson's content from its stored parse and assemble the manifest (Stage 6).

Order (IMPLEMENTATION_NOTES 5): segments -> one script per slide -> poll placement ->
per placed segment one poll, then one explanation per wrong option -> manifest.

Every item goes through the same loop, in code (IMPLEMENTATION_NOTES 7.4):
generate -> structure check -> prep Guardian (only the cited chunks) -> rule. A failed
attempt sends its problems back as `feedback`; after `prep.max_retries` retries the item
takes its fallback. An LLM timeout or error fails the attempt like any other problem, so
prep never hangs and never stops on an LLM error.

Fallbacks:
- Segments: fixed groups of `prep.fallback_segment_slides` slides.
- Script: the slide's own text cleaned for TTS -> the vision description -> the fixed
  sentence (`prep.fallback_script`). Status `fallback`.
- Placement: every segment in deck order.
- Poll: if the poll or any of its explanations fails, the whole poll is dropped (it stays
  in `questions` with status `dropped`, without misconceptions) and the next candidate
  segment is tried.

Generation reads only the stored parse (`PrepTables`), never the parser, so a change of
`poll_count` or another generation parameter regenerates without re-parsing.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from classpilot.adapters.llm import LLMClient, LLMError, MalformedReplyError, call_llm
from classpilot.adapters.retrieval import RetrievalError, Retriever
from classpilot.contracts.manifest import (
    Manifest,
    ManifestParams,
    Misconception,
    Question,
    Remediation,
    Segment,
    Slide,
    Status,
)
from classpilot.contracts.prep import (
    ExplanationOutput,
    PlacementOutput,
    PollOutput,
    ScriptOutput,
    SegmenterOutput,
)
from classpilot.prep.chunking import clean_text
from classpilot.prep.records import ParsedPage
from classpilot.prep.tables import PrepTables
from classpilot.prep.tts import clean_for_tts, strip_emphasis, strip_lines, template_lines
from classpilot.rules.prep import (
    check_prep_guardian,
    explanation_problems,
    manifest_poll_problems,
    parse_output,
    placement_problems,
    poll_problems,
    prep_rule_options,
    script_problems,
    segmenter_problems,
)
from classpilot.settings import PollSettings, PrepSettings

SEGMENTER_CHUNK_CHARS = 400  # per chunk in the Segmenter prompt: the gist is enough


class GenerateError(RuntimeError):
    """The lesson cannot be generated (no parsed slides) or the result is invalid."""


# ---------- inputs ----------


@dataclass
class SlideMaterial:
    slide_id: str
    order: int  # 1-based over the whole lesson
    page: ParsedPage
    chunks: list[dict]  # {"chunk_id", "slide_id", "text"}


@dataclass
class LessonMaterial:
    lesson_id: str
    slides: list[SlideMaterial]
    chunks: dict[str, dict]  # every lesson chunk (slides and references) by id

    @property
    def slide_ids(self) -> list[str]:
        return [s.slide_id for s in self.slides]

    def retrieval_rows(self) -> list[dict]:
        return [{**c, "lesson_id": self.lesson_id} for c in self.chunks.values()]


def load_material(lesson_id: str, tables: PrepTables) -> LessonMaterial:
    files = tables.lesson_files(lesson_id)
    pages = [p for f in files if f.kind == "slides" for p in f.pages]
    if not pages:
        raise GenerateError(f"lesson {lesson_id!r} has no parsed slides; run prep parse first")
    slide_ids = {p.page_id for p in pages}
    chunks = {
        c.chunk_id: {
            "chunk_id": c.chunk_id,
            "slide_id": c.page_id if c.page_id in slide_ids else None,
            "text": c.text,
        }
        for c in tables.lesson_chunks(lesson_id)
    }
    slides = [
        SlideMaterial(p.page_id, n, p, [c for c in chunks.values() if c["slide_id"] == p.page_id])
        for n, p in enumerate(pages, start=1)
    ]
    return LessonMaterial(lesson_id, slides, chunks)


@dataclass
class GenerateDeps:
    llm: LLMClient
    retriever: Retriever
    prep: PrepSettings
    poll: PollSettings


# ---------- report ----------

Outcome = Literal["pass", "structure", "guardian", "llm_error"]


@dataclass
class Attempt:
    outcome: Outcome
    problems: list[str] = field(default_factory=list)
    latency_ms: int = 0  # generator + structure check + Guardian
    calls: int = 0  # LLM calls of this attempt (timed-out calls included)
    guardian: dict | None = None  # the Guardian's own reply (claims, verdict, reason)
    # The generator's reply (text and citations), so failed drafts can become Guardian
    # eval cases (Stage 9). None after an LLM error.
    draft: dict | None = None
    rescued: list[str] = field(default_factory=list)  # claims passed by the word check


@dataclass
class ItemReport:
    item: str  # "segments", "script <slide>", "placement", "poll <q> <seg>", "explanation ..."
    status: Status
    attempts: list[Attempt] = field(default_factory=list)
    detail: str = ""  # fallback level, drop reason, or the placement ranking
    citations: list[str] = field(default_factory=list)  # of the kept output

    @property
    def kind(self) -> str:
        return self.item.split()[0]


@dataclass
class GenerationReport:
    lesson_id: str
    poll_count: int
    llm_calls: int = 0
    items: list[ItemReport] = field(default_factory=list)

    def statuses(self, prefix: str) -> list[Status]:
        return [i.status for i in self.items if i.item.startswith(prefix)]

    def summary(self) -> dict[str, dict]:
        """Per item kind: statuses, retries, LLM calls, and latency (Stage 7 readings)."""
        out: dict[str, dict] = {}
        for item in self.items:
            row = out.setdefault(
                item.kind,
                {
                    "items": 0,
                    "statuses": {},
                    "retries": 0,
                    "llm_errors": 0,
                    "calls": 0,
                    "latency_ms": 0,
                    "max_item_latency_ms": 0,
                },
            )
            latency = sum(a.latency_ms for a in item.attempts)
            row["items"] += 1
            row["statuses"][item.status] = row["statuses"].get(item.status, 0) + 1
            row["retries"] += max(0, len(item.attempts) - 1)
            row["llm_errors"] += sum(a.outcome == "llm_error" for a in item.attempts)
            row["calls"] += sum(a.calls for a in item.attempts)
            row["latency_ms"] += latency
            row["max_item_latency_ms"] = max(row["max_item_latency_ms"], latency)
        return out


@dataclass
class GenerationResult:
    manifest: Manifest
    report: GenerationReport


class CountingLLM:
    def __init__(self, llm: LLMClient):
        self.llm, self.calls = llm, 0

    def complete(self, task: str, inputs: dict) -> dict:
        self.calls += 1
        return self.llm.complete(task, inputs)


# ---------- the retry loop ----------

# check(raw) -> (parsed output or None, attempt). It runs the structure check and the
# Guardian; only an attempt with outcome "pass" returns the output.
Check = Callable[[dict], tuple[object | None, Attempt]]


def format_feedback(problems: list[str]) -> str:
    return "\n".join(f"- {p}" for p in problems)


def with_retries(
    generate: Callable[[str], dict],
    check: Check,
    max_retries: int,
    call_count: Callable[[], int] = lambda: 0,
) -> tuple[object | None, Status | None, list[Attempt]]:
    """Up to 1 + max_retries attempts. Returns (output, ok | ok_after_retry, attempts);
    output and status are None when every attempt failed."""
    attempts: list[Attempt] = []
    feedback = ""
    for n in range(1 + max_retries):
        start, calls = time.perf_counter(), call_count()
        try:
            raw = generate(feedback)
        except LLMError as exc:
            output, attempt = None, Attempt("llm_error", [str(exc)])
        else:
            output, attempt = check(raw)
            attempt.draft = raw
        attempt.latency_ms = round((time.perf_counter() - start) * 1000)
        attempt.calls = call_count() - calls
        attempts.append(attempt)
        if attempt.outcome == "pass":
            return output, ("ok" if n == 0 else "ok_after_retry"), attempts
        # After an LLM error there is nothing the generator can fix.
        feedback = format_feedback(attempt.problems) if attempt.outcome != "llm_error" else ""
    return None, None, attempts


class Generator:
    def __init__(
        self,
        material: LessonMaterial,
        deps: GenerateDeps,
        progress: Callable[[str, int, int, str], None] | None = None,
    ):
        self.m = material
        self.progress = progress or (lambda step, done, total, detail: None)
        self.done = 0
        # segments + scripts + placement + polls; grows if dropped polls bring backups
        self.total = 2 + len(material.slides) + deps.prep.poll_count
        self.deps = deps
        self.llm = CountingLLM(deps.llm)
        self.report = GenerationReport(material.lesson_id, deps.prep.poll_count)
        # Footer/header lines of the deck, left out of the slide-text fallback.
        self.template = template_lines([s.page.text_layer for s in material.slides])

    # ----- helpers -----

    def tick(self, detail: str) -> None:
        self.done += 1
        self.total = max(self.total, self.done)
        self.progress("generating", self.done, self.total, detail)

    def call(self, task: str, inputs: dict) -> dict:
        """One LLM call; a malformed reply is asked again up to `malformed_retries` times
        (Stage 7/9: 2-3 empty or fenced replies per run). Timeouts are not retried."""
        timeout = self.deps.prep.llm_timeout_seconds
        for _ in range(self.deps.prep.malformed_retries):
            try:
                return call_llm(self.llm, task, inputs, timeout)
            except MalformedReplyError:
                continue
        return call_llm(self.llm, task, inputs, timeout)

    def retrieve(self, query: str, base: list[dict], min_references: int = 0) -> list[dict]:
        """`base` chunks plus the top `retrieval_top_k` retrieved lesson chunks, without
        duplicates, plus further reference chunks from the same search until there are
        `min_references` (Stage 7: examples in the readings did not reach the writer)."""
        prep = self.deps.prep
        depth = max(prep.retrieval_top_k, prep.retrieval_search_k if min_references else 0)
        try:
            hits = self.deps.retriever.search(query, depth, self.m.lesson_id)
        except RetrievalError:
            hits = []
        seen = {c["chunk_id"] for c in base}
        ranked = []
        for hit in hits:
            chunk = self.m.chunks.get(hit.chunk_id)
            if chunk is not None and hit.chunk_id not in seen:
                seen.add(hit.chunk_id)
                ranked.append(chunk)
        extra = ranked[: prep.retrieval_top_k]
        refs = sum(c["slide_id"] is None for c in [*base, *extra])
        for chunk in ranked[prep.retrieval_top_k :]:
            if refs >= min_references:
                break
            if chunk["slide_id"] is None:
                extra.append(chunk)
                refs += 1
        return [*base, *extra]

    def cited(self, ids: list[str]) -> list[dict]:
        return [self.m.chunks[i] for i in ids if i in self.m.chunks]

    def guardian(
        self, task: str, inputs: dict, cited: list[str], given: list[dict], **rule
    ) -> Attempt:
        """The Guardian sees the writer's cited chunks first, then every other chunk the
        writer was given (Stage 9, user decision: true content the writer forgot to cite
        is not a failure). The manifest keeps the writer's own citations."""
        ids = list(dict.fromkeys([*cited, *(c["chunk_id"] for c in given)]))
        shown = self.cited(ids)
        try:
            raw = self.call(task, {**inputs, "cited_chunks": shown})
        except LLMError as exc:
            return Attempt("llm_error", [f"Guardian: {exc}"])
        check = check_prep_guardian(
            raw,
            ids,
            chunk_texts={c["chunk_id"]: c["text"] for c in shown},
            **prep_rule_options(self.deps.prep),
            **rule,
        )
        if check.passed is None:
            return Attempt("llm_error", check.problems, guardian=raw)
        outcome = "pass" if check.passed else "guardian"
        return Attempt(outcome, check.problems, guardian=raw, rescued=check.rescued)

    def loop(self, generate, check):
        return with_retries(
            generate, check, self.deps.prep.max_retries, call_count=lambda: self.llm.calls
        )

    # ----- 1. segments -----

    def segments(self) -> list[Segment]:
        slides_in = [
            {
                "slide_id": s.slide_id,
                "chunks": [{**c, "text": c["text"][:SEGMENTER_CHUNK_CHARS]} for c in s.chunks],
            }
            for s in self.m.slides
        ]

        def check(raw):
            out = parse_output(SegmenterOutput, raw)
            if out is None:
                return None, Attempt("structure", ["The output did not match the schema."])
            problems = segmenter_problems(out, self.m.slide_ids)
            return out, Attempt("structure" if problems else "pass", problems)

        out, status, attempts = self.loop(
            lambda fb: self.call("segmenter", {"slides": slides_in, "feedback": fb}), check
        )
        if out is None:
            drafts, status, detail = self.fixed_segments(), "fallback", "fixed groups"
        else:
            drafts, detail = [(d.slides, d.objective.strip()) for d in out.segments], ""
        self.report.items.append(ItemReport("segments", status, attempts, detail))
        return [
            Segment(
                segment_id=f"seg-{n:02d}", objective=obj, slides=ids, questions={}, active_poll=None
            )
            for n, (ids, obj) in enumerate(drafts, start=1)
        ]

    def fixed_segments(self) -> list[tuple[list[str], str]]:
        size = max(1, self.deps.prep.fallback_segment_slides)
        groups = []
        for start in range(0, len(self.m.slides), size):
            group = self.m.slides[start : start + size]
            title = next(
                (t.splitlines()[0] for s in group if (t := clean_text(s.page.text_layer))), None
            )
            first, last = group[0].slide_id, group[-1].slide_id
            objective = f"Understand {title}" if title else f"Understand slides {first} to {last}"
            groups.append(([s.slide_id for s in group], objective))
        return groups

    # ----- 2. scripts -----

    def scripts(self, segments: list[Segment]) -> dict[str, Slide]:
        by_slide = {sid: seg for seg in segments for sid in seg.slides}
        total = len(self.m.slides)
        slides = {}
        for s in self.m.slides:
            seg = by_slide[s.slide_id]
            script, status = self.script(s, seg, total)
            self.tick(f"script {s.slide_id}")
            slides[s.slide_id] = Slide(
                order=s.order, image_ref=f"slides/{s.slide_id}.png", script=script, status=status
            )
        return slides

    def script(self, s: SlideMaterial, seg: Segment, total: int) -> tuple[str, Status]:
        item = f"script {s.slide_id}"
        if not s.chunks:
            text, level = self.fallback_script(s.page)
            self.report.items.append(ItemReport(item, "fallback", [], f"{level} (no chunks)"))
            return text, "fallback"

        n_in_seg = seg.slides.index(s.slide_id) + 1
        position = (
            f"slide {s.order} of {total}; slide {n_in_seg} of {len(seg.slides)} in {seg.segment_id}"
        )
        query = f"{seg.objective} {' '.join(c['text'] for c in s.chunks)}"[:500]
        chunks = self.retrieve(query, s.chunks, self.deps.prep.script_reference_chunks)
        allowed = {c["chunk_id"] for c in chunks}
        inputs = {
            "objective": seg.objective,
            "slide_id": s.slide_id,
            "position": position,
            "chunks": chunks,
        }

        def check(raw):
            out = parse_output(ScriptOutput, raw)
            if out is None:
                return None, Attempt("structure", ["The output did not match the schema."])
            out = out.model_copy(update={"script": strip_emphasis(out.script)})
            problems = script_problems(out, allowed)
            if problems:
                return None, Attempt("structure", problems)
            attempt = self.guardian(
                "script_guardian",
                {"script": out.script},
                out.citations,
                chunks,
                require_claims=False,
            )
            return out, attempt

        out, status, attempts = self.loop(
            lambda fb: self.call("script_writer", {**inputs, "feedback": fb}), check
        )
        if out is None:
            text, level = self.fallback_script(s.page)
            self.report.items.append(ItemReport(item, "fallback", attempts, level))
            return text, "fallback"
        self.report.items.append(ItemReport(item, status, attempts, citations=out.citations))
        return out.script.strip(), status

    def fallback_script(self, page: ParsedPage) -> tuple[str, str]:
        text = clean_for_tts(strip_lines(clean_text(page.text_layer), self.template))
        if text:
            return text, "slide_text"
        vision = page.llm_description
        if vision is not None:
            described = vision.diagram_description if vision.has_visuals else ""
            text = clean_for_tts(described.strip() or vision.slide_text)
            if text:
                return text, "vision_description"
        return self.deps.prep.fallback_script, "fixed_sentence"

    # ----- 3. placement -----

    def placement(self, segments: list[Segment]) -> list[str]:
        ids = [s.segment_id for s in segments]
        inputs = {
            "segments": [
                {"segment_id": s.segment_id, "objective": s.objective, "slides": s.slides}
                for s in segments
            ],
            "poll_count": self.deps.prep.poll_count,
        }

        def check(raw):
            out = parse_output(PlacementOutput, raw)
            if out is None:
                return None, Attempt("structure", ["The output did not match the schema."])
            problems = placement_problems(out, ids)
            return out, Attempt("structure" if problems else "pass", problems)

        out, status, attempts = self.loop(
            lambda fb: self.call("poll_placer", {**inputs, "feedback": fb}), check
        )
        if out is None:
            self.report.items.append(ItemReport("placement", "fallback", attempts, "deck order"))
            return ids
        ranking = f"ranked: {', '.join(out.segment_ids)}; {out.reason.strip()}"
        self.report.items.append(ItemReport("placement", status, attempts, ranking))
        return list(out.segment_ids)

    # ----- 4. polls and explanations -----

    def polls(self, segments: list[Segment], candidates: list[str]):
        by_id = {s.segment_id: s for s in segments}
        misconceptions: dict[str, Misconception] = {}
        remediations: dict[str, Remediation] = {}
        q_n = 0
        active = 0
        for seg_id in candidates:
            if active >= self.deps.prep.poll_count:
                break
            seg = by_id[seg_id]
            q_n += 1
            qid = f"q-{q_n:02d}"
            question, new_mis, new_rem = self.poll(seg, qid, len(misconceptions))
            self.tick(f"poll {qid}")
            seg.questions[qid] = question
            if question.status != "dropped":
                seg.active_poll = qid
                misconceptions.update(new_mis)
                remediations.update(new_rem)
                active += 1
        return misconceptions, remediations

    def poll(self, seg: Segment, qid: str, mis_offset: int):
        item = f"poll {qid} {seg.segment_id}"
        seg_chunks = [c for c in self.m.chunks.values() if c["slide_id"] in seg.slides]
        chunks = self.retrieve(seg.objective, seg_chunks)
        allowed = {c["chunk_id"] for c in chunks}
        last_valid: list[PollOutput] = []

        def check(raw):
            out = parse_output(PollOutput, raw)
            if out is None:
                return None, Attempt("structure", ["The output did not match the schema."])
            problems = poll_problems(out, allowed)
            if problems:
                return None, Attempt("structure", problems)
            last_valid.append(out)
            wrong = sorted(set(out.options) - {out.correct_option})
            attempt = self.guardian(
                "poll_guardian",
                {
                    "question": out.question,
                    "options": out.options,
                    "correct_option": out.correct_option,
                },
                out.citations,
                chunks,
                require_claims=True,
                wrong_options=wrong,
            )
            return out, attempt

        inputs = {"objective": seg.objective, "chunks": chunks}
        out, status, attempts = self.loop(
            lambda fb: self.call("poll_writer", {**inputs, "feedback": fb}), check
        )
        if out is None:
            self.report.items.append(ItemReport(item, "dropped", attempts, "poll failed"))
            return self.dropped_question(seg, last_valid), {}, {}

        explained: list[tuple[str, ExplanationOutput, Status, ItemReport]] = []
        for mis in sorted(out.misconceptions, key=lambda m: m.option):
            expl, expl_status, expl_attempts = self.explanation(out, mis)
            report = ItemReport(
                f"explanation {qid} {mis.option}",
                expl_status or "dropped",
                expl_attempts,
                citations=list(expl.citations) if expl else [],
            )
            explained.append((mis.option, expl, expl_status, report))

        # Stage 9 (user decision): a failed explanation no longer drops the poll. That
        # option gets no explanation; if it triggers, the correct option is revealed.
        missing = [option for option, expl, _, _ in explained if expl is None]
        detail = f"no explanation for {', '.join(missing)}" if missing else ""
        self.report.items.append(
            ItemReport(item, status, attempts, detail, citations=out.citations)
        )
        self.report.items.extend(r for *_, r in explained)
        known_wrong, new_mis, new_rem = {}, {}, {}
        by_option = {m.option: m for m in out.misconceptions}
        kept = [e for e in explained if e[1] is not None]
        for n, (option, expl, expl_status, _) in enumerate(kept, start=mis_offset + 1):
            mid, rid = f"M-{n:02d}", f"R-{n:02d}"
            known_wrong[option] = mid
            new_mis[mid] = Misconception(
                label=by_option[option].label.strip(),
                description=by_option[option].description.strip(),
                remediation=rid,
            )
            new_rem[rid] = Remediation(
                type="tts_explanation",
                title=expl.title.strip(),
                text=expl.text.strip(),
                show_slide=expl.show_slide,
                content_ref=None,
                citations=list(expl.citations),
                status=expl_status,
            )
        question = Question(
            text=out.question.strip(),
            options=dict(sorted(out.options.items())),
            correct_option=out.correct_option,
            known_wrong=known_wrong,
            segment=seg.segment_id,
            status=status,
        )
        return question, new_mis, new_rem

    @staticmethod
    def dropped_question(seg: Segment, valid: list[PollOutput]) -> Question:
        last = valid[-1] if valid else None
        return Question(
            text=last.question.strip() if last else "",
            options=dict(sorted(last.options.items())) if last else {},
            correct_option=last.correct_option if last else "",
            known_wrong={},
            segment=seg.segment_id,
            status="dropped",
        )

    def explanation(self, poll: PollOutput, mis):
        cited = self.cited(poll.citations)
        query = f"{mis.label} {mis.description} {poll.options[poll.correct_option]}"
        chunks = self.retrieve(query, cited)
        allowed = {c["chunk_id"] for c in chunks}
        chunk_slide = {c["chunk_id"]: c["slide_id"] for c in self.m.chunks.values()}
        slide_ids = set(self.m.slide_ids)
        inputs = {
            "question": poll.question,
            "options": poll.options,
            "correct_option": poll.correct_option,
            "wrong_option": mis.option,
            "misconception": {"label": mis.label, "description": mis.description},
            "chunks": chunks,
        }

        def check(raw):
            out = parse_output(ExplanationOutput, raw)
            if out is None:
                return None, Attempt("structure", ["The output did not match the schema."])
            out = out.model_copy(update={"text": strip_emphasis(out.text)})
            problems = explanation_problems(out, allowed, chunk_slide, slide_ids)
            if problems:
                return None, Attempt("structure", problems)
            attempt = self.guardian(
                "explanation_guardian",
                {
                    "question": poll.question,
                    "options": poll.options,
                    "wrong_option": mis.option,
                    "explanation": out.text,
                },
                out.citations,
                chunks,
                require_claims=True,
            )
            return out, attempt

        return self.loop(
            lambda fb: self.call("explanation_writer", {**inputs, "feedback": fb}), check
        )

    # ----- all -----

    def run(self) -> GenerationResult:
        self.progress("generating", 0, self.total, "")
        segments = self.segments()
        self.total = 2 + len(self.m.slides) + min(self.deps.prep.poll_count, len(segments))
        self.tick("segments")
        slides = self.scripts(segments)
        misconceptions, remediations = {}, {}
        if self.deps.prep.poll_count > 0:
            candidates = self.placement(segments)
            self.tick("placement")
            misconceptions, remediations = self.polls(segments, candidates)
        poll = self.deps.poll
        try:
            manifest = Manifest(
                lesson_id=self.m.lesson_id,
                params=ManifestParams(
                    poll_answer_seconds=poll.poll_answer_seconds,
                    min_responses=poll.min_responses,
                    wrong_ratio_threshold=poll.wrong_ratio_threshold,
                ),
                slides=slides,
                segments=segments,
                misconceptions=misconceptions,
                remediations=remediations,
            )
        except ValueError as exc:
            raise GenerateError(f"assembled manifest is invalid: {exc}") from exc
        problems = manifest_poll_problems(manifest, self.deps.prep.poll_count)
        if problems:
            raise GenerateError("; ".join(problems))
        self.report.llm_calls = self.llm.calls
        return GenerationResult(manifest, self.report)


def generate_lesson(lesson_id: str, tables: PrepTables, deps: GenerateDeps) -> GenerationResult:
    """Generate from the stored parse only (no parser, no re-parse)."""
    return Generator(load_material(lesson_id, tables), deps).run()
