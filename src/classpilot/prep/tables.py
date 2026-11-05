"""Prep tables: RAW_FILES (Bronze), PARSED_PAGES (Silver), LESSON_CHUNKS_V2 (Gold).

`LocalTables` keeps the same records as JSON files (mock mode and tests);
`SnowflakeTables` reads and writes the tables created by sql/04. Only prep writes them;
the live path reads chunks through the search service.
"""

import json
import re
from pathlib import Path
from typing import Protocol

from classpilot.prep.records import Chunk, ParsedFile, ParsedPage
from classpilot.settings import ObjectNames

IDENTIFIER = re.compile(r"^[A-Z_][A-Z0-9_$]*$")


class PrepTables(Protocol):
    def known_file(self, file_id: str) -> ParsedFile | None: ...

    def source_owner(self, source_id: str) -> str | None: ...  # file_id using the id

    def save_parsed(self, parsed: ParsedFile) -> None: ...

    def register_file(self, lesson_id: str, parsed: ParsedFile) -> None: ...

    def replace_chunks(self, lesson_id: str, file_id: str, chunks: list[Chunk]) -> None: ...

    def lesson_chunks(self, lesson_id: str) -> list[Chunk]: ...

    def lesson_files(self, lesson_id: str) -> list[ParsedFile]: ...  # in upload order

    def refresh_search(self) -> bool: ...  # False when the service does not exist yet


class LocalTables:
    """JSON files under `root`: parsed/<file_id>.json, raw_files.json, chunks/<lesson>.json."""

    def __init__(self, root: Path):
        self.root = root
        self.refreshes = 0

    def _read(self, path: Path, default):
        return json.loads(path.read_text()) if path.exists() else default

    def _write(self, path: Path, data) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2))

    def known_file(self, file_id: str) -> ParsedFile | None:
        path = self.root / "parsed" / f"{file_id}.json"
        return ParsedFile.model_validate_json(path.read_text()) if path.exists() else None

    def source_owner(self, source_id: str) -> str | None:
        for path in sorted((self.root / "parsed").glob("*.json")):
            parsed = ParsedFile.model_validate_json(path.read_text())
            if parsed.source_id == source_id:
                return parsed.file_id
        return None

    def save_parsed(self, parsed: ParsedFile) -> None:
        self._write(self.root / "parsed" / f"{parsed.file_id}.json", parsed.model_dump())

    def register_file(self, lesson_id: str, parsed: ParsedFile) -> None:
        rows = [
            r
            for r in self._read(self.root / "raw_files.json", [])
            if (r["lesson_id"], r["file_id"]) != (lesson_id, parsed.file_id)
        ]
        rows.append(
            {
                "lesson_id": lesson_id,
                "file_id": parsed.file_id,
                "source_id": parsed.source_id,
                "kind": parsed.kind,
                "format": parsed.format,
                "original_name": parsed.original_name,
                "stage_path": parsed.stage_path,
                "page_count": parsed.page_count,
            }
        )
        self._write(self.root / "raw_files.json", rows)

    def raw_files(self) -> list[dict]:
        return self._read(self.root / "raw_files.json", [])

    def replace_chunks(self, lesson_id: str, file_id: str, chunks: list[Chunk]) -> None:
        path = self.root / "chunks" / f"{lesson_id}.json"
        rows = [r for r in self._read(path, []) if r["file_id"] != file_id]
        rows.extend(c.model_dump() for c in chunks)
        self._write(path, rows)

    def lesson_chunks(self, lesson_id: str) -> list[Chunk]:
        rows = self._read(self.root / "chunks" / f"{lesson_id}.json", [])
        return [Chunk.model_validate(r) for r in rows]

    def lesson_files(self, lesson_id: str) -> list[ParsedFile]:
        ids = [r["file_id"] for r in self.raw_files() if r["lesson_id"] == lesson_id]
        return [f for f in (self.known_file(i) for i in ids) if f is not None]

    def refresh_search(self) -> bool:
        self.refreshes += 1
        return True


class SnowflakeTables:
    def __init__(self, connection, objects: ObjectNames):
        names = [objects.raw_files, objects.parsed_pages, objects.chunks, objects.search_service]
        if not all(IDENTIFIER.match(n) for n in names):
            raise ValueError(f"object names must be plain identifiers: {names}")
        self.connection, self.o = connection, objects

    def _rows(self, sql: str, params: tuple = ()) -> list[tuple]:
        cursor = self.connection.cursor()
        try:
            return cursor.execute(sql, params).fetchall()
        finally:
            cursor.close()

    def _exec(self, sql: str, params: tuple = ()) -> None:
        cursor = self.connection.cursor()
        try:
            cursor.execute(sql, params)
        finally:
            cursor.close()

    def known_file(self, file_id: str) -> ParsedFile | None:
        files = self._rows(
            f"SELECT SOURCE_ID, KIND, FORMAT, ORIGINAL_NAME, STAGE_PATH, PAGE_COUNT "
            f"FROM {self.o.raw_files} WHERE FILE_ID = %s LIMIT 1",
            (file_id,),
        )
        pages = self._rows(
            f"SELECT PAGE_INDEX, PAGE_ID, TEXT_LAYER, NOTES, LLM_DESCRIPTION, IMAGE_FLAG, "
            f"PARSE_METHOD FROM {self.o.parsed_pages} WHERE FILE_ID = %s ORDER BY PAGE_INDEX",
            (file_id,),
        )
        if not files or not pages:
            return None
        source_id, kind, fmt, name, stage_path, page_count = files[0]
        return ParsedFile(
            file_id=file_id,
            source_id=source_id,
            kind=kind,
            format=fmt,
            original_name=name or "",
            stage_path=stage_path,
            page_count=int(page_count),
            pages=[
                ParsedPage(
                    page_index=int(index),
                    page_id=page_id,
                    text_layer=text or "",
                    notes=notes,
                    llm_description=json.loads(vision) if vision else None,
                    image_flag=flag,
                    parse_method=method,
                )
                for index, page_id, text, notes, vision, flag, method in pages
            ],
        )

    def source_owner(self, source_id: str) -> str | None:
        rows = self._rows(
            f"SELECT FILE_ID FROM {self.o.raw_files} WHERE SOURCE_ID = %s LIMIT 1", (source_id,)
        )
        return rows[0][0] if rows else None

    def save_parsed(self, parsed: ParsedFile) -> None:
        self._exec(f"DELETE FROM {self.o.parsed_pages} WHERE FILE_ID = %s", (parsed.file_id,))
        cursor = self.connection.cursor()
        try:
            for page in parsed.pages:
                vision = page.llm_description.model_dump_json() if page.llm_description else None
                cursor.execute(
                    f"INSERT INTO {self.o.parsed_pages} (FILE_ID, PAGE_INDEX, PAGE_ID, "
                    "TEXT_LAYER, NOTES, LLM_DESCRIPTION, IMAGE_FLAG, PARSE_METHOD, PARSED_AT) "
                    "SELECT %s, %s, %s, %s, %s, PARSE_JSON(%s), %s, %s, CURRENT_TIMESTAMP()",
                    (
                        parsed.file_id,
                        page.page_index,
                        page.page_id,
                        page.text_layer,
                        page.notes,
                        vision,
                        page.image_flag,
                        page.parse_method,
                    ),
                )
        finally:
            cursor.close()

    def register_file(self, lesson_id: str, parsed: ParsedFile) -> None:
        self._exec(
            f"DELETE FROM {self.o.raw_files} WHERE LESSON_ID = %s AND FILE_ID = %s",
            (lesson_id, parsed.file_id),
        )
        self._exec(
            f"INSERT INTO {self.o.raw_files} (LESSON_ID, FILE_ID, SOURCE_ID, KIND, FORMAT, "
            "ORIGINAL_NAME, SHA256, STAGE_PATH, PAGE_COUNT, UPLOADED_AT) "
            "SELECT %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP()",
            (
                lesson_id,
                parsed.file_id,
                parsed.source_id,
                parsed.kind,
                parsed.format,
                parsed.original_name,
                parsed.file_id,
                parsed.stage_path,
                parsed.page_count,
            ),
        )

    def replace_chunks(self, lesson_id: str, file_id: str, chunks: list[Chunk]) -> None:
        self._exec(
            f"DELETE FROM {self.o.chunks} WHERE LESSON_ID = %s AND FILE_ID = %s",
            (lesson_id, file_id),
        )
        if not chunks:
            return
        cursor = self.connection.cursor()
        try:
            cursor.executemany(
                f"INSERT INTO {self.o.chunks} (LESSON_ID, CHUNK_ID, FILE_ID, SOURCE_ID, "
                "PAGE_ID, PAGE_INDEX, ORIGIN, CHUNK_TEXT, LOADED_AT) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP())",
                [
                    (
                        lesson_id,
                        c.chunk_id,
                        c.file_id,
                        c.source_id,
                        c.page_id,
                        c.page_index,
                        c.origin,
                        c.text,
                    )
                    for c in chunks
                ],
            )
        finally:
            cursor.close()

    def lesson_chunks(self, lesson_id: str) -> list[Chunk]:
        rows = self._rows(
            f"SELECT CHUNK_ID, FILE_ID, SOURCE_ID, PAGE_ID, PAGE_INDEX, ORIGIN, CHUNK_TEXT "
            f"FROM {self.o.chunks} WHERE LESSON_ID = %s ORDER BY FILE_ID, PAGE_INDEX, CHUNK_ID",
            (lesson_id,),
        )
        keys = ("chunk_id", "file_id", "source_id", "page_id", "page_index", "origin", "text")
        return [Chunk.model_validate(dict(zip(keys, row, strict=True))) for row in rows]

    def lesson_files(self, lesson_id: str) -> list[ParsedFile]:
        rows = self._rows(
            f"SELECT FILE_ID FROM {self.o.raw_files} WHERE LESSON_ID = %s "
            f"ORDER BY UPLOADED_AT, FILE_ID",
            (lesson_id,),
        )
        files = (self.known_file(row[0]) for row in rows)
        return [f for f in files if f is not None]

    def refresh_search(self) -> bool:
        try:
            self._exec(f"ALTER CORTEX SEARCH SERVICE {self.o.search_service} REFRESH")
        except Exception as exc:
            if "does not exist" in str(exc):
                return False
            raise
        return True
