"""The JSON examples in the docs must validate against the pydantic models."""

import json
import re

import pytest

from classpilot.contracts import Decision, PollEvidence, StudentQuestion
from classpilot.contracts.manifest import Manifest
from classpilot.contracts.trace import RECORD_MODELS
from classpilot.settings import PROJECT_ROOT

AGENT_RULES = PROJECT_ROOT / ".claude" / "rules" / "agent.md"
IMPLEMENTATION_NOTES = PROJECT_ROOT / "docs" / "v2" / "IMPLEMENTATION_NOTES.md"
JSON_BLOCK = re.compile(r"```json\n(.*?)```", re.DOTALL)


def json_blocks(path) -> list[dict]:
    blocks = []
    for block in JSON_BLOCK.findall(path.read_text()):
        without_comments = re.sub(r"\s*//.*$", "", block, flags=re.MULTILINE)
        blocks.append(json.loads(without_comments))
    return blocks


def model_for(example: dict):
    if "record_type" in example:
        return RECORD_MODELS[example["record_type"]]
    if "segments" in example:
        return Manifest
    if "decision_id" in example:
        return Decision
    if "option_counts" in example:
        return PollEvidence
    if "question_text" in example:
        return StudentQuestion
    raise AssertionError(f"no model for example with keys {sorted(example)}")


AGENT_EXAMPLES = json_blocks(AGENT_RULES)


def test_agent_rules_have_every_contract_example():
    models = {model_for(e).__name__ for e in AGENT_EXAMPLES}
    assert {"PollEvidence", "StudentQuestion", "Decision", "RunRecord", "NodeRecord"} <= models


@pytest.mark.parametrize("example", AGENT_EXAMPLES, ids=lambda e: model_for(e).__name__)
def test_agent_rules_example_validates(example):
    validated = model_for(example).model_validate(example)
    if isinstance(validated, Decision):
        # Examples list every decision field, so the docs show the full shape.
        assert set(example) == set(Decision.model_fields)


def test_manifest_example_in_implementation_notes_validates():
    manifests = [e for e in json_blocks(IMPLEMENTATION_NOTES) if "segments" in e]
    assert len(manifests) == 1
    Manifest.model_validate(manifests[0])
