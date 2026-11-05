"""Vision description of an image page: output schema, prompt, and reply parsing.

Stage 1: `response_format` cannot be combined with an image prompt on AI_COMPLETE, so
the JSON shape is written into the prompt (generated from the pydantic model, so the
two cannot drift) and the reply is parsed in code. claude-haiku-4-5 wraps the JSON in a
```json fence, which is stripped.
"""

import json
import re

from pydantic import BaseModel, ConfigDict, Field, ValidationError

PROMPT_TEXT_LIMIT = 4000  # characters of text layer / notes put into the prompt


class VisionDescription(BaseModel):
    model_config = ConfigDict(extra="ignore")

    slide_text: str = Field(description="all text visible on the page")
    diagram_description: str = Field(
        description="what the pictures, charts, or diagrams show; empty if there are none"
    )
    key_concepts: list[str] = Field(description="up to 5 short concepts shown on the page")


class VisionReplyError(ValueError):
    pass


def json_shape() -> str:
    """The reply shape for the prompt, built from VisionDescription's fields."""
    parts = []
    for name, field in VisionDescription.model_fields.items():
        hint = f"<{field.description}>"
        value = [hint] if field.annotation == list[str] else hint
        parts.append(f"{json.dumps(name)}: {json.dumps(value)}")
    return "{" + ", ".join(parts) + "}"


PROMPT = """You describe one page of course material (a lecture slide or a page of a reading) \
for a teaching system.
Describe only what is visible on the page image. Do not add outside knowledge, examples, \
or explanations that are not shown.
The page's extracted text and speaker notes are below. Use them to read text exactly; \
describe what the image shows.

Extracted text:
{text}

Speaker notes:
{notes}

Reply with JSON only, with exactly these keys:
{shape}"""


def build_prompt(text: str, notes: str | None) -> str:
    return PROMPT.format(
        text=(text or "(none)")[:PROMPT_TEXT_LIMIT],
        notes=(notes or "(none)")[:PROMPT_TEXT_LIMIT],
        shape=json_shape(),
    )


def parse_reply(raw: str) -> VisionDescription:
    body = re.sub(r"^```(?:json)?\s*|\s*```$", "", (raw or "").strip())
    try:
        data = json.loads(body)
        if isinstance(data, str):  # JSON encoded twice
            data = json.loads(re.sub(r"^```(?:json)?\s*|\s*```$", "", data.strip()))
        return VisionDescription.model_validate(data)
    except (json.JSONDecodeError, ValidationError, TypeError) as exc:
        raise VisionReplyError(f"vision reply is not the expected JSON: {body[:120]!r}") from exc
