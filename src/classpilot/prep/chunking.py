"""Chunks for Cortex Search from parsed pages (IMPLEMENTATION_NOTES 4.3). Pure code.

Per page, in this order:
- `text_layer`: the page text (slide text layer or parsed Markdown, image markers
  removed) plus the speaker notes;
- `llm_description` (image pages only): the vision `diagram_description` when the
  model reported pictures, charts, or diagrams (`has_visuals`), and the vision
  `slide_text` when the page has no text of its own. Key concepts are not chunked:
  they summarize the page text, and as chunks they outranked the source text (Stage 5);
  they stay in PARSED_PAGES.
Each part is split at paragraph, then line, then word boundaries to at most
`max_chars`. Ids are `<page_id>-c<n>`, numbered 1.. per page in that order, so the
same pages always give the same ids. Empty pages give no chunks.
"""

import re

from classpilot.prep.records import Chunk, ParsedFile, ParsedPage

# AI_PARSE_DOCUMENT LAYOUT marks images as ![img-0.jpeg](img-0.jpeg) or ![img-0].
IMAGE_MARKER = re.compile(r"!\[[^\]]*\](\([^)]*\))?")


def clean_text(text: str) -> str:
    text = IMAGE_MARKER.sub("", text or "")
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _split_long(piece: str, max_chars: int) -> list[str]:
    """Split one paragraph that is too long: by lines, then by words."""
    parts: list[str] = []
    for line in piece.splitlines() or [piece]:
        while len(line) > max_chars:
            cut = line.rfind(" ", 0, max_chars + 1)
            cut = cut if cut > 0 else max_chars
            parts.append(line[:cut].strip())
            line = line[cut:].strip()
        if line:
            parts.append(line)
    return _pack(parts, max_chars, "\n")


def _pack(pieces: list[str], max_chars: int, joiner: str) -> list[str]:
    chunks: list[str] = []
    current = ""
    for piece in pieces:
        candidate = f"{current}{joiner}{piece}" if current else piece
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                chunks.append(current)
            current = piece
    if current:
        chunks.append(current)
    return chunks


def split_text(text: str, max_chars: int) -> list[str]:
    paragraphs: list[str] = []
    for paragraph in re.split(r"\n\s*\n", text):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        paragraphs.extend(
            [paragraph] if len(paragraph) <= max_chars else _split_long(paragraph, max_chars)
        )
    return _pack(paragraphs, max_chars, "\n\n")


def page_parts(page: ParsedPage) -> list[tuple[str, str]]:
    """(origin, text) parts of one page before splitting."""
    parts = []
    text = clean_text(page.text_layer)
    notes = clean_text(page.notes or "")
    body = "\n\n".join(p for p in (text, f"Speaker notes: {notes}" if notes else "") if p)
    if body:
        parts.append(("text_layer", body))
    vision = page.llm_description
    if vision is not None:
        pieces = []
        if not text and vision.slide_text.strip():
            pieces.append(vision.slide_text.strip())
        if vision.has_visuals and vision.diagram_description.strip():
            pieces.append(vision.diagram_description.strip())
        if pieces:
            parts.append(("llm_description", "\n\n".join(pieces)))
    return parts


def chunk_file(parsed: ParsedFile, max_chars: int) -> list[Chunk]:
    chunks = []
    for page in parsed.pages:
        n = 0
        for origin, text in page_parts(page):
            for piece in split_text(text, max_chars):
                n += 1
                chunks.append(
                    Chunk(
                        chunk_id=f"{page.page_id}-c{n}",
                        file_id=parsed.file_id,
                        source_id=parsed.source_id,
                        page_id=page.page_id,
                        page_index=page.page_index,
                        origin=origin,
                        text=piece,
                    )
                )
    return chunks
