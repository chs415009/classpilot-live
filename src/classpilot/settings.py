"""Load config/settings.yaml, with env var and per-run overrides."""

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SETTINGS_PATH = PROJECT_ROOT / "config" / "settings.yaml"


class PollSettings(BaseModel):
    min_responses: int = 5
    wrong_ratio_threshold: float = 0.60
    max_remediations_per_objective: int = 1


class QuestionSettings(BaseModel):
    protected_similarity_threshold: float = 0.5
    confidence_threshold: float = 0.70
    retrieval_top_k: int = 3


class LLMSettings(BaseModel):
    model: str | None = None
    timeout_seconds: float = 10


class Settings(BaseModel):
    agent_mode: Literal[2, 3] = 3
    backend: Literal["mock", "cortex"] = "mock"
    poll: PollSettings = PollSettings()
    question: QuestionSettings = QuestionSettings()
    llm: LLMSettings = LLMSettings()


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
    if os.environ.get("AGENT_MODE"):
        data["agent_mode"] = int(os.environ["AGENT_MODE"])
    if os.environ.get("BACKEND"):
        data["backend"] = os.environ["BACKEND"]
    if overrides:
        data = _deep_merge(data, overrides)
    return Settings.model_validate(data)
