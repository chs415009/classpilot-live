"""Draft prep Guardian cases (scripts, polls, explanations) from stored prep runs.

Reads `outputs/prep/<run>/generation_report.json` and `manifest.json` plus the stored
parse (`outputs/parse/<lesson>.json`), and writes unlabeled cases (`expected: null`) to
a gitignored file. The reports keep each attempt's Guardian reply but not the draft or
the generator's citations, so:
- items that passed use the manifest text; failed drafts are rebuilt from the claims
  their Guardian listed (`reconstructed: true`);
- the cited chunks are the slide's (or segment's) own chunks plus every chunk the
  Guardian named.

    python scripts/draft_prep_guardian_cases.py --lesson info6205-l1 \
        --run info6205-l1.run1 --run info6205-l1 --out materials/eval/guardian_cases_prep.json
"""

import argparse
import json
from pathlib import Path

from classpilot.settings import PROJECT_ROOT

PREP_DIR = PROJECT_ROOT / "outputs" / "prep"

# Which stored items become cases: (run index, item name, attempt index or "final").
SCRIPTS_FINAL = ["p05", "p06", "p08", "p10", "p12", "p13"]
SCRIPTS_FAILED = 4  # failed script attempts with unsupported claims, rebuilt from claims
POLLS_LAST_RUN = 5
POLLS_FIRST_RUN = 1


def guardian_chunk_ids(guardian: dict | None) -> list[str]:
    if not guardian:
        return []
    ids = [c.get("chunk_id") for c in guardian.get("claims") or []]
    ids += [w.get("chunk_id") for w in guardian.get("wrong_options") or []]
    return [i for i in ids if i]


def claims_text(guardian: dict) -> str:
    seen, out = set(), []
    for c in guardian.get("claims") or []:
        text = c.get("claim", "").strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text if text.endswith((".", "?", "!")) else text + ".")
    return " ".join(out)


def stage7(attempt: dict, run: str) -> dict:
    g = attempt.get("guardian") or {}
    return {
        "run": run,
        "outcome": attempt["outcome"],
        "verdict": g.get("verdict"),
        "problems": attempt["problems"],
    }


class Drafter:
    def __init__(self, lesson: str, runs: list[str]):
        parse = json.loads((PROJECT_ROOT / "outputs" / "parse" / f"{lesson}.json").read_text())
        self.chunks = {c["chunk_id"]: c for c in parse["chunks"]}
        self.runs = []
        for run in runs:
            d = PREP_DIR / run
            report = json.loads((d / "generation_report.json").read_text())
            manifest = json.loads((d / "manifest.json").read_text())
            items = {it["item"]: it for it in report["items"]}
            self.runs.append((run, items, manifest))
        self.cases: list[dict] = []

    def chunk_list(self, ids: list[str]) -> list[dict]:
        ids = list(dict.fromkeys(i for i in ids if i in self.chunks))
        return [{"chunk_id": i, "text": self.chunks[i]["text"]} for i in ids]

    def slide_chunks(self, slide_ids: list[str]) -> list[str]:
        return [c["chunk_id"] for c in self.chunks.values() if c["page_id"] in slide_ids]

    def add(self, case: dict) -> None:
        case = {"id": f"pc-{len(self.cases) + 1:02d}", **case}
        self.cases.append(case)

    def scripts(self) -> None:
        run, items, manifest = self.runs[-1]
        for short in SCRIPTS_FINAL:
            slide = f"l1-slides-{short}"
            item = items[f"script {slide}"]
            passing = [a for a in item["attempts"] if a["outcome"] == "pass"]
            if not passing:
                continue
            ids = self.slide_chunks([slide]) + guardian_chunk_ids(passing[-1]["guardian"])
            self.add(
                {
                    "kind": "script",
                    "source": f"stage7-{run}",
                    "reconstructed": False,
                    "slide_id": slide,
                    "chunks": self.chunk_list(ids),
                    "script": manifest["slides"][slide]["script"],
                    "expected": None,
                    "unsupported": [],
                    "note": "",
                    "stage7": stage7(passing[-1], run),
                }
            )
        taken = 0
        for run, items, _ in reversed(self.runs):
            for name, item in items.items():
                if not name.startswith("script ") or taken >= SCRIPTS_FAILED:
                    continue
                for attempt in item["attempts"]:
                    g = attempt.get("guardian")
                    if attempt["outcome"] != "guardian" or not g:
                        continue
                    if not any(c.get("chunk_id") is None for c in g.get("claims") or []):
                        continue
                    slide = name.split(" ", 1)[1]
                    ids = self.slide_chunks([slide]) + guardian_chunk_ids(g)
                    self.add(
                        {
                            "kind": "script",
                            "source": f"stage7-{run}",
                            "reconstructed": True,
                            "slide_id": slide,
                            "chunks": self.chunk_list(ids),
                            "script": claims_text(g),
                            "expected": None,
                            "unsupported": [],
                            "note": "",
                            "stage7": stage7(attempt, run),
                        }
                    )
                    taken += 1
                    break

    def poll_text(self, manifest: dict, qid: str) -> tuple[dict, dict] | None:
        for seg in manifest["segments"]:
            if qid in seg["questions"]:
                return seg, seg["questions"][qid]
        return None

    def polls(self) -> None:
        for run_index, count in ((-1, POLLS_LAST_RUN), (0, POLLS_FIRST_RUN)):
            run, items, manifest = self.runs[run_index]
            names = [n for n in items if n.startswith("poll ")][:count]
            for name in names:
                qid = name.split()[1]
                found = self.poll_text(manifest, qid)
                if found is None:
                    continue
                seg, q = found
                attempt = items[name]["attempts"][-1]
                ids = self.slide_chunks(seg["slides"]) + guardian_chunk_ids(attempt["guardian"])
                wrong = sorted(set(q["options"]) - {q["correct_option"]})
                self.add(
                    {
                        "kind": "poll",
                        "source": f"stage7-{run}",
                        "reconstructed": False,
                        "chunks": self.chunk_list(ids),
                        "question": q["text"],
                        "options": q["options"],
                        "correct_option": q["correct_option"],
                        "expected": None,
                        "shown_wrong": {o: None for o in wrong},
                        "unsupported": [],
                        "note": "Poll text is the last structurally valid attempt",
                        "stage7": stage7(attempt, run),
                    }
                )

    def explanations(self) -> None:
        run, items, manifest = self.runs[-1]
        for name, item in items.items():
            if not name.startswith("explanation "):
                continue
            _, qid, option = name.split()
            found = self.poll_text(manifest, qid)
            if found is None:
                continue
            seg, q = found
            judged = [a for a in item["attempts"] if a.get("guardian")]
            # Every judged attempt of q-05 (the complete-list case); the first otherwise.
            for attempt in judged if qid == "q-05" else judged[:1]:
                g = attempt["guardian"]
                ids = self.slide_chunks(seg["slides"]) + guardian_chunk_ids(g)
                self.add(
                    {
                        "kind": "explanation",
                        "source": f"stage7-{run}",
                        "reconstructed": True,
                        "chunks": self.chunk_list(ids),
                        "question": q["text"],
                        "options": q["options"],
                        "wrong_option": option,
                        "explanation": claims_text(g),
                        "expected": None,
                        "unsupported": [],
                        "note": "",
                        "stage7": stage7(attempt, run),
                    }
                )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--lesson", required=True)
    parser.add_argument("--run", action="append", required=True, help="oldest first")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    drafter = Drafter(args.lesson, args.run)
    drafter.scripts()
    drafter.polls()
    drafter.explanations()
    data = {"set_id": f"prep-guardian-{args.lesson}", "split": "dev", "cases": drafter.cases}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    kinds = {}
    for c in drafter.cases:
        kinds[c["kind"]] = kinds.get(c["kind"], 0) + 1
    print(f"wrote {args.out}: {len(drafter.cases)} cases {kinds}")


if __name__ == "__main__":
    main()
