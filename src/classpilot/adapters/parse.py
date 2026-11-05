"""Snowflake step of the parse layer: stage PUT, AI_PARSE_DOCUMENT, and vision AI_COMPLETE.

Each adapter has a mock that returns canned output (tests and BACKEND=mock) and a
Cortex version on the connector connection. Timeouts use
STATEMENT_TIMEOUT_IN_SECONDS, which cancels Cortex functions server-side (Stage 1).
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol

import pypdfium2 as pdfium

TIMEOUT_CODES = ("000630", "000604")  # statement timeout, statement canceled
STAGE_DIR = re.compile(r"^[A-Za-z0-9_/-]+$")
STAGE_NAME = re.compile(r"^[A-Z_][A-Z0-9_$]*$")


class SnowflakeStepError(RuntimeError):
    def __init__(self, message: str, kind: Literal["timeout", "error"]):
        super().__init__(message)
        self.kind = kind


@dataclass
class ParsedPageText:
    page_index: int  # 1-based
    content: str  # Markdown (LAYOUT mode)


class StageAdapter(Protocol):
    def put(self, local: Path, stage_dir: str) -> str: ...  # returns the stage path

    def refresh(self) -> None: ...


class DocumentParser(Protocol):
    def parse(self, stage_path: str) -> list[ParsedPageText]: ...


class VisionDescriber(Protocol):
    def describe(self, stage_path: str, prompt: str) -> str: ...  # raw model reply


# --- mocks ------------------------------------------------------------------------------


@dataclass
class MockStage:
    files: dict[str, Path] = field(default_factory=dict)
    refreshes: int = 0

    def put(self, local: Path, stage_dir: str) -> str:
        path = f"{stage_dir}/{local.name}"
        self.files[path] = local
        return path

    def refresh(self) -> None:
        self.refreshes += 1


@dataclass
class MockParser:
    """PDF: the local text layer as one Markdown block per page. DOCX: one canned page."""

    stage: MockStage
    calls: list[str] = field(default_factory=list)

    def parse(self, stage_path: str) -> list[ParsedPageText]:
        self.calls.append(stage_path)
        local = self.stage.files[stage_path]
        if local.suffix.lower() == ".docx":
            return [ParsedPageText(1, f"Mock parse of {local.name}.")]
        pdf = pdfium.PdfDocument(str(local))
        try:
            return [
                ParsedPageText(i, page.get_textpage().get_text_range().replace("\r\n", "\n"))
                for i, page in enumerate(pdf, start=1)
            ]
        finally:
            pdf.close()


@dataclass
class MockVision:
    """Canned description per page image (named p<NN>.png by prep convert)."""

    replies: dict[str, str] = field(default_factory=dict)  # stage path -> raw reply
    calls: list[str] = field(default_factory=list)

    def describe(self, stage_path: str, prompt: str) -> str:
        self.calls.append(stage_path)
        if stage_path in self.replies:
            return self.replies[stage_path]
        page = Path(stage_path).stem
        return (
            "```json\n"
            + json.dumps(
                {
                    "slide_text": "",
                    "diagram_description": f"Mock description of page {page}.",
                    "key_concepts": [f"concept of {page}"],
                }
            )
            + "\n```"
        )


# --- Cortex -----------------------------------------------------------------------------


def _set_timeout(cursor, seconds: int) -> None:
    cursor.execute(f"ALTER SESSION SET STATEMENT_TIMEOUT_IN_SECONDS = {int(seconds)}")


def _run(connection, timeout: int, sql: str, params: tuple):
    cursor = connection.cursor()
    try:
        _set_timeout(cursor, timeout)
        return cursor.execute(sql, params).fetchone()
    except Exception as exc:
        message = str(exc)[:300]
        kind = "timeout" if any(code in message for code in TIMEOUT_CODES) else "error"
        raise SnowflakeStepError(message, kind) from exc
    finally:
        cursor.close()


class SnowflakeStage:
    def __init__(self, connection, stage: str):
        if not STAGE_NAME.match(stage):
            raise ValueError(f"stage name is not a plain identifier: {stage!r}")
        self.connection, self.stage = connection, stage

    def put(self, local: Path, stage_dir: str) -> str:
        path = local.resolve()
        if "'" in str(path) or not STAGE_DIR.match(stage_dir):
            raise ValueError(f"unsafe path for PUT: {local.name} -> {stage_dir}")
        cursor = self.connection.cursor()
        try:
            cursor.execute(
                f"PUT 'file://{path}' @{self.stage}/{stage_dir} "
                "AUTO_COMPRESS = FALSE OVERWRITE = TRUE"
            )
        finally:
            cursor.close()
        return f"{stage_dir}/{local.name}"

    def refresh(self) -> None:
        cursor = self.connection.cursor()
        try:
            cursor.execute(f"ALTER STAGE {self.stage} REFRESH")
        finally:
            cursor.close()


class CortexParser:
    """AI_PARSE_DOCUMENT in LAYOUT mode with page_split; `index` is 0-based in the reply."""

    def __init__(self, connection, stage: str, timeout_seconds: int):
        self.connection, self.stage, self.timeout = connection, stage, timeout_seconds
        self.sql = (
            f"SELECT AI_PARSE_DOCUMENT(TO_FILE('@{stage}', %s), "
            "{'mode': 'LAYOUT', 'page_split': TRUE})"
        )

    def parse(self, stage_path: str) -> list[ParsedPageText]:
        row = _run(self.connection, self.timeout, self.sql, (stage_path,))
        result = json.loads(row[0]) if row and isinstance(row[0], str) else (row or [None])[0]
        if not isinstance(result, dict) or "pages" not in result:
            raise SnowflakeStepError(
                f"AI_PARSE_DOCUMENT returned no pages: {result!r}"[:300], "error"
            )
        return [
            ParsedPageText(int(page["index"]) + 1, page.get("content") or "")
            for page in result["pages"]
        ]


class CortexVision:
    """Single-file AI_COMPLETE with the page PNG (no response_format with images)."""

    def __init__(self, connection, stage: str, model: str, max_tokens: int, timeout_seconds: int):
        self.connection, self.model, self.timeout = connection, model, timeout_seconds
        self.sql = (
            f"SELECT AI_COMPLETE(%s, %s, TO_FILE('@{stage}', %s), "
            f"{{'temperature': 0, 'max_tokens': {int(max_tokens)}}})"
        )

    def describe(self, stage_path: str, prompt: str) -> str:
        row = _run(self.connection, self.timeout, self.sql, (self.model, prompt, stage_path))
        raw = row[0] if row else None
        if raw is None:
            raise SnowflakeStepError("AI_COMPLETE returned nothing", "error")
        return json.loads(raw) if isinstance(raw, str) and raw.startswith('"') else str(raw)
