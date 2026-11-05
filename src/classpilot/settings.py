"""Load config/settings.yaml, with env var and per-run overrides."""

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SETTINGS_PATH = PROJECT_ROOT / "config" / "settings.yaml"


class PollSettings(BaseModel):
    # Defaults that prep writes into the manifest `params`; the live poll rule reads
    # the manifest, so a lesson keeps the values it was generated with.
    min_responses: int = 5
    wrong_ratio_threshold: float = 0.60


class QuestionSettings(BaseModel):
    confidence_threshold: float = 0.70
    retrieval_top_k: int = 3


class LLMSettings(BaseModel):
    model: str | None = None
    timeout_seconds: float = 10


class ImagePageSettings(BaseModel):
    # Areas are fractions of the page, after removing objects every page shares
    # (template drawings, logos). Stage 1: image area >= 0.10 found the image slides.
    image_area: float = 0.10  # >= this -> image
    drawing_area: float = 0.30  # >= this -> image (diagrams made of shapes)
    unsure_image_area: float = 0.02  # >= this -> unsure
    unsure_drawing_area: float = 0.10  # >= this -> unsure
    min_text_chars: int = 10  # fewer text-layer chars -> unsure (maybe text as outlines)


class ParseSettings(BaseModel):
    # Local conversion (prep/convert.py). LibreOffice runs in Docker, never on the host.
    libreoffice_image: str = "classpilot-libreoffice:1"
    libreoffice_timeout_seconds: float = 180
    render_scale: float = 2.0  # 144 dpi
    min_render_scale: float = 0.5
    png_max_bytes: int = 3_750_000  # Cortex image limit for Claude models is 3.75 MB
    # Alignment: share of a slide's python-pptx words found on its PDF page.
    alignment_min_overlap: float = 0.6
    alignment_min_words: int = 3  # slides with fewer words are not compared
    image_page: ImagePageSettings = ImagePageSettings()
    # Snowflake step (Stage 5): vision for image/unsure pages, AI_PARSE_DOCUMENT for
    # references. Timeouts are STATEMENT_TIMEOUT_IN_SECONDS (server-side cancel).
    vision_model: str = "claude-haiku-4-5"
    vision_max_tokens: int = 800
    vision_timeout_seconds: int = 60
    parse_timeout_seconds: int = 300
    # Cortex Search: at most 512 tokens per chunk (default embedding model), ~4 chars each.
    chunk_max_chars: int = 1500


class ObjectNames(BaseModel):
    # Snowflake object names of the parse layer (IMPLEMENTATION_NOTES 4.4, Q-17).
    # Role, warehouse, database, and schema come from .env.
    raw_stage: str = "RAW_MATERIALS"
    raw_files: str = "RAW_FILES"
    parsed_pages: str = "PARSED_PAGES"
    chunks: str = "LESSON_CHUNKS_V2"
    search_service: str = "LESSON_SEARCH_V2"


class Settings(BaseModel):
    backend: Literal["mock", "cortex"] = "mock"
    poll: PollSettings = PollSettings()
    question: QuestionSettings = QuestionSettings()
    llm: LLMSettings = LLMSettings()
    parse: ParseSettings = ParseSettings()
    objects: ObjectNames = ObjectNames()


def _deep_merge(base: dict, extra: dict) -> dict:
    merged = dict(base)
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_settings(path: Path = DEFAULT_SETTINGS_PATH, overrides: dict | None = None) -> Settings:
    data = yaml.safe_load(path.read_text()) if path.exists() else {}
    data = data or {}
    if os.environ.get("BACKEND"):
        data["backend"] = os.environ["BACKEND"]
    if overrides:
        data = _deep_merge(data, overrides)
    return Settings.model_validate(data)
