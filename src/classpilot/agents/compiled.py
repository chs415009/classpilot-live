"""Compiled DSPy programs for the live agents: save, load, and build the live agents.

A program file `compiled/<program_id>.json` holds the `dspy.Predict` state (few-shot
demos and the signature, instructions included) of each compiled module, plus metadata:

    {"program_id": "...", "created_at": "...", "dspy_version": "...",
     "modules": {"analyst": <Predict.dump_state()>, ...},
     "meta": {"trainset": [...], "metric": "...", ...}}

Modules missing from `modules` stay uncompiled. The program id is the `prompt_version`
of the LLM-call trace records. `llm.compiled_program` (null = uncompiled) picks the
program at runtime. A loaded program keeps the instructions it was compiled with, even
if the signature in code changes later. Saved states never carry an LM (the agents set
the LM per call), so no model or account values reach `compiled/`.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

import dspy

from classpilot.agents.program import DSPyAgents
from classpilot.agents.signatures import SIGNATURES
from classpilot.settings import PROJECT_ROOT, Settings

COMPILED_DIR = PROJECT_ROOT / "compiled"


class CompiledProgramError(Exception):
    """The program file is missing, malformed, or does not match its id."""


def program_path(program_id: str, directory: Path = COMPILED_DIR) -> Path:
    if not program_id or "/" in program_id or program_id.startswith("."):
        raise CompiledProgramError(f"bad program id {program_id!r}")
    return directory / f"{program_id}.json"


def save_program(
    program_id: str,
    modules: dict[str, dspy.Predict],
    meta: dict,
    directory: Path = COMPILED_DIR,
) -> Path:
    unknown = set(modules) - set(SIGNATURES)
    if unknown:
        raise CompiledProgramError(f"unknown modules {sorted(unknown)}")
    states = {}
    for task, module in modules.items():
        # Never store an LM (model names, engine settings). A copy without it also
        # avoids dump_state() failing on our custom Cortex engine (DSPy 3.4).
        module = module.deepcopy()
        module.lm = None
        states[task] = module.dump_state()
    data = {
        "program_id": program_id,
        "created_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "dspy_version": dspy.__version__,
        "modules": states,
        "meta": meta,
    }
    path = program_path(program_id, directory)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    return path


def load_program(program_id: str, directory: Path = COMPILED_DIR) -> dict:
    path = program_path(program_id, directory)
    if not path.is_file():
        raise CompiledProgramError(f"no compiled program at {path}")
    data = json.loads(path.read_text())
    if data.get("program_id") != program_id:
        raise CompiledProgramError(f"{path} holds program {data.get('program_id')!r}")
    modules = data.get("modules") or {}
    unknown = set(modules) - set(SIGNATURES)
    if unknown:
        raise CompiledProgramError(f"{path}: unknown modules {sorted(unknown)}")
    if any(state.get("lm") for state in modules.values()):
        raise CompiledProgramError(f"{path}: a module state carries an LM")
    return data


def apply_program(agents: DSPyAgents, data: dict) -> DSPyAgents:
    for task, state in data["modules"].items():
        agents.modules[task].load_state(state)
    agents.prompt_version = data["program_id"]
    return agents


def live_agents(settings: Settings, lm: dspy.LM, directory: Path = COMPILED_DIR) -> DSPyAgents:
    """The live Analyst, Responder, and Guardian; compiled when `llm.compiled_program`
    names a program."""
    agents = DSPyAgents(lm)
    if settings.llm.compiled_program:
        apply_program(agents, load_program(settings.llm.compiled_program, directory))
    return agents
