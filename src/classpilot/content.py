"""Load the approved lesson content from content/."""

import json
from dataclasses import dataclass
from pathlib import Path

from classpilot.settings import PROJECT_ROOT

DEFAULT_CONTENT_DIR = PROJECT_ROOT / "content"


@dataclass
class Content:
    objectives: list[dict]
    chunks: list[dict]
    poll_questions: list[dict]
    misconception_map: dict[str, dict[str, dict]]
    remediations: list[dict]
    protected_questions: list[dict]


def load_content(content_dir: Path = DEFAULT_CONTENT_DIR) -> Content:
    def read(name: str):
        return json.loads((content_dir / name).read_text())

    lesson = read("lesson_chunks.json")
    return Content(
        objectives=lesson["objectives"],
        chunks=lesson["chunks"],
        poll_questions=read("poll_questions.json"),
        misconception_map=read("misconception_map.json"),
        remediations=read("remediations.json"),
        protected_questions=read("protected_questions.json"),
    )
