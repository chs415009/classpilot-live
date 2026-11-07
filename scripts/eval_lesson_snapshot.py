"""Write a lesson snapshot (objectives + chunks) for an eval question set.

Objectives come from a prep manifest's segments, chunks from a stored parse
(`outputs/parse/<lesson>.json`). The snapshot keeps the eval labels valid when a later
prep run changes the segments. Real lessons go under `materials/eval/` (gitignored).

    python scripts/eval_lesson_snapshot.py --lesson l1 \
        --out materials/eval/questions_dev.json

An existing file keeps its questions; only the lesson block is replaced.
"""

import argparse
import json
from pathlib import Path

from classpilot.settings import PROJECT_ROOT
from classpilot.text import content_words

MAX_KEYWORDS = 40  # per objective, for the mock Analyst only (as in the service)


def snapshot(manifest: dict, parse: dict) -> dict:
    chunks = parse["chunks"]
    objectives = []
    for seg in manifest["segments"]:
        words = content_words(seg["objective"])
        words += [
            w for c in chunks if c["page_id"] in seg["slides"] for w in content_words(c["text"])
        ]
        objectives.append(
            {
                "objective_id": seg["segment_id"],
                "title": seg["objective"],
                "keywords": list(dict.fromkeys(words))[:MAX_KEYWORDS],
            }
        )
    return {
        "lesson_id": manifest["lesson_id"],
        "objectives": objectives,
        "chunks": [{"chunk_id": c["chunk_id"], "text": c["text"]} for c in chunks],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--lesson", required=True)
    parser.add_argument("--manifest", type=Path, help="default outputs/prep/<lesson>/manifest.json")
    parser.add_argument("--parse", type=Path, help="default outputs/parse/<lesson>.json")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--set-id", help="default dev-<lesson>")
    args = parser.parse_args()

    manifest_path = (
        args.manifest or PROJECT_ROOT / "outputs" / "prep" / args.lesson / "manifest.json"
    )
    parse_path = args.parse or PROJECT_ROOT / "outputs" / "parse" / f"{args.lesson}.json"
    lesson = snapshot(json.loads(manifest_path.read_text()), json.loads(parse_path.read_text()))

    data = json.loads(args.out.read_text()) if args.out.exists() else {}
    data = {
        "set_id": data.get("set_id", args.set_id or f"dev-{args.lesson}"),
        "split": data.get("split", "dev"),
        "retrieval": data.get("retrieval", "search"),
        "note": data.get("note", "Real course content: never commit."),
        "lesson": lesson,
        "questions": data.get("questions", []),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    print(
        f"wrote {args.out}: {len(lesson['objectives'])} objectives, {len(lesson['chunks'])} chunks"
    )


if __name__ == "__main__":
    main()
