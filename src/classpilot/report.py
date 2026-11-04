"""Build outputs/report.html: run every scenario live and compare 2-agent vs 3-agent mode."""

import time
from collections.abc import Callable
from html import escape
from pathlib import Path

from classpilot.runner import OUTPUT_DIR, run_scenario, scenario_files
from classpilot.settings import load_settings
from classpilot.trace import utc_now

CSS = """
:root { --bg:#fbfbfa; --fg:#1d1d1f; --muted:#6b6b70; --line:#e3e3e0; --card:#ffffff;
        --ok:#1f7a3a; --bad:#b3261e; --warn:#8a5a00; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#151517; --fg:#ececee; --muted:#9a9aa2; --line:#2c2c31; --card:#1c1c1f;
          --ok:#5cc47a; --bad:#ff7b72; --warn:#e3b341; }
}
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--fg);
       font:15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
main { max-width: 1100px; margin: 0 auto; padding: 32px 16px 64px; }
h1 { font-size: 24px; margin: 0 0 4px; }
.muted { color: var(--muted); }
.small { font-size: 12.5px; }
.banner { border:1px solid var(--warn); color:var(--warn); border-radius:8px; padding:10px 14px; margin:16px 0; }
.table-wrap { overflow-x:auto; border:1px solid var(--line); border-radius:10px; background:var(--card); }
table { border-collapse: collapse; width:100%; font-size:13.5px; }
th, td { text-align:left; padding:10px 12px; border-bottom:1px solid var(--line); vertical-align:top; }
th { color:var(--muted); font-weight:600; white-space:nowrap; }
tr:last-child td { border-bottom:none; }
td.mode { min-width: 220px; }
.ok { color:var(--ok); font-weight:600; } .bad { color:var(--bad); font-weight:600; }
.warn { color:var(--warn); font-weight:600; }
details summary { cursor:pointer; color:var(--muted); font-size:12.5px; }
details div { margin-top:4px; font-size:12.5px; }
"""


def _scenario_cell(result: dict, scenario_input: str) -> str:
    return (
        f"<b>{escape(result['file'])}</b><br>{escape(result['name'])}"
        f"<div class='muted small'>{escape(scenario_input)}</div>"
    )


def _expected_cell(expected: dict) -> str:
    parts = [expected.get("action", "")]
    parts += [str(v) for k, v in expected.items() if k != "action"]
    return escape(" · ".join(p for p in parts if p))


def _status_css(result: dict) -> str:
    # ok = matches expected; warn = right action, different reason; bad = wrong action.
    if result["matches_expected"]:
        return "ok"
    expected_action = result["expected"].get("action")
    return "warn" if expected_action in (None, result["decision"]["action"]) else "bad"


def _mode_cell(result: dict) -> str:
    d, t = result["decision"], result["trace"]
    css = _status_css(result)
    detail = d["remediation_id"] or d["escalation_reason"] or ", ".join(d["citations"] or [])
    confidence = f" · conf {d['confidence']}" if d["confidence"] is not None else ""
    seconds = t["latency_ms"]["total"] / 1000
    html = (
        f"<span class='{css}'>{escape(d['action'])}</span>"
        f"{' · ' + escape(detail) if detail else ''}{escape(confidence)}"
        f"<div class='muted small'>{t['llm_calls']} LLM calls · {seconds:.1f} s</div>"
    )
    if d["answer_text"]:
        html += f"<details><summary>answer</summary><div>{escape(d['answer_text'])}</div></details>"
    return html


def _input_text(result: dict) -> str:
    data = result["input"]
    if result["decision"]["path"] == "poll":
        counts = ", ".join(f"{k}: {v}" for k, v in data["option_counts"].items())
        return f"{counts} (correct {data['correct_option']})"
    return f"“{data['question_text']}”"


def build_report(
    out_path: Path = OUTPUT_DIR / "report.html", on_result: Callable[[dict], None] | None = None
) -> Path:
    """Run every scenario now (poll once, question scenarios in mode 2 and 3) and write the page."""
    settings = load_settings()
    start = time.perf_counter()
    rows = []
    for path in scenario_files():
        two = run_scenario(path, 2, trace_path=None)
        if on_result:
            on_result(two)
        if two["decision"]["path"] == "poll":
            mode_cells = f"<td class='mode' colspan='2'>{_mode_cell(two)}<div class='muted small'>Poll path is rules only (no agents), so it is the same in both modes.</div></td>"
        else:
            three = run_scenario(path, 3, trace_path=None)
            if on_result:
                on_result(three)
            mode_cells = f"<td class='mode'>{_mode_cell(two)}</td><td class='mode'>{_mode_cell(three)}</td>"
        rows.append(
            f"<tr><td>{_scenario_cell(two, _input_text(two))}</td>"
            f"<td>{_expected_cell(two['expected'])}</td>{mode_cells}</tr>"
        )
    run_seconds = time.perf_counter() - start

    backend = settings.backend
    model = f" · model <b>{escape(settings.llm.model or '-')}</b>" if backend == "cortex" else ""
    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ClassPilot Agent Demo</title><style>{CSS}</style></head>
<body><main>
<h1>ClassPilot Live: scenario results</h1>
<div class="muted">Backend <b>{escape(backend)}</b>{model} · run {escape(utc_now())} · took {run_seconds:.0f} s</div>
<div class="banner">Exploratory: {len(scenario_files())} synthetic scenarios, one live run each.
Expected values were written for the mock backend, so a real model can differ.
<span class="ok">Green</span> = as expected · <span class="warn">yellow</span> = right action, different reason ·
<span class="bad">red</span> = wrong action.</div>
<div class="table-wrap"><table>
<tr><th>Scenario</th><th>Expected</th><th>2-agent mode</th><th>3-agent mode (+ Guardian)</th></tr>
{''.join(rows)}
</table></div>
</main></body></html>
"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html)
    return out_path
