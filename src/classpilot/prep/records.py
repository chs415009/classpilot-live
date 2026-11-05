"""Parse-layer records: parsed files and pages (Silver) and lesson chunks (Gold)."""

from typing import Literal

from pydantic import BaseModel

from classpilot.prep.convert import FileFormat, FileKind
from classpilot.prep.pages import ImageFlag
from classpilot.prep.vision import VisionDescription

# Where the page text came from, plus "+vision" when an image page got a description
# and "+vision_failed" when the vision call failed (the page then keeps its text only).
TextSource = Literal["local_text", "ai_parse_layout", "local_text_fallback"]
VisionStatus = Literal["", "+vision", "+vision_failed"]
Origin = Literal["text_layer", "llm_description"]


class ParsedPage(BaseModel):
    page_index: int  # 1-based
    page_id: str  # <source>-p<NN>
    text_layer: str
    notes: str | None
    llm_description: VisionDescription | None
    image_flag: ImageFlag | None  # None: no local page image (DOCX)
    parse_method: str  # TextSource + VisionStatus, e.g. "local_text+vision"


class ParsedFile(BaseModel):
    file_id: str
    source_id: str
    kind: FileKind
    format: FileFormat
    original_name: str
    stage_path: str
    page_count: int
    pages: list[ParsedPage]


class Chunk(BaseModel):
    chunk_id: str  # <source>-p<NN>-c<n>
    file_id: str
    source_id: str
    page_id: str
    page_index: int
    origin: Origin
    text: str
