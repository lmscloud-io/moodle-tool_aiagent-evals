"""The public scoreboard: evals/README.md and evals/history.csv in a checkout of the docs repo.

Only verdict words, model names, counts, times and token numbers are published: never transcripts, prompts,
error texts or site problems, which stay in the private results.
"""

from __future__ import annotations

import csv
import glob
import json
import statistics
from pathlib import Path
from typing import Any

BRANCH_LABELS = {"405": "4.5", "500": "5.0", "501": "5.1", "502": "5.2", "503": "5.3"}
STATUS_WORDS = {"not_available": "not available", "not_tested": "not tested"}
HISTORY_FIELDS = ["date", "plugin_release", "tier", "moodle", "cell", "provider", "api", "model", "task",
                  "trials", "passed", "status"]


def verdict(run: dict[str, Any]) -> str:
    """How the scoreboard words one cell run."""
    if run["status"] != "ran":
        return STATUS_WORDS.get(run["status"], "not run")
    tasks = list(run["tasks"].values())
    if not tasks or any(task["trials"] == 0 for task in tasks):
        return "not run"
    if all(task["passed"] == task["trials"] for task in tasks):
        return "works"
    if any(task["rate_limited"] for task in tasks):
        return "rate limited"
    return "fails"


def load_results(patterns: list[str]) -> list[dict[str, Any]]:
    paths = sorted({path for pattern in patterns for path in glob.glob(pattern)})
    if not paths:
        raise SystemExit("no results.json matched")
    return [json.loads(Path(path).read_text(encoding="utf-8")) for path in paths]


def _cell_runs(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [run for result in results for run in result["runs"] if "cell" in run]


def _label(branch: str) -> str:
    return BRANCH_LABELS.get(branch, branch)


def _median(values: list[Any]) -> str:
    present = [value for value in values if value is not None]
    return f"{statistics.median(present):g}" if present else ""


def _compat_table(results: list[dict[str, Any]]) -> list[str]:
    branches = sorted({run["branch"] for result in results for run in result["runs"]}, key=int)
    rows: dict[tuple[str, str], dict[str, str]] = {}
    for run in _cell_runs(results):
        rows.setdefault((run["provider"], run["api"]), {})[run["branch"]] = verdict(run)
    lines = [
        "## Compatibility", "",
        "Every provider plugin and API mode on every supported Moodle version, with one low-cost model each.", "",
        "| Provider | API | " + " | ".join(f"Moodle {_label(branch)}" for branch in branches) + " |",
        "|" + "---|" * (len(branches) + 2),
    ]
    for (provider, api), verdicts in sorted(rows.items()):
        lines.append(f"| {provider} | {api} | " + " | ".join(verdicts.get(b, "not run") for b in branches) + " |")
    return lines + [""]


def _models_table(results: list[dict[str, Any]]) -> list[str]:
    runs = _cell_runs(results)
    task_ids = sorted({task for run in runs if run["status"] == "ran" for task in run["tasks"]})
    branch = max((run["branch"] for run in runs), key=int, default="")
    lines = [
        "## Models", "",
        f"Every listed model on Moodle {_label(branch)}. Each check shows the trials that passed out of those run.", "",
        "| Provider | Model | API | " + " | ".join(task_ids) + " | Median seconds | Median tokens |",
        "|" + "---|" * (len(task_ids) + 5),
    ]
    for run in sorted(runs, key=lambda item: (item["provider"], item["model"], item["api"])):
        if run["status"] == "ran":
            checks = [f"{run['tasks'][t]['passed']}/{run['tasks'][t]['trials']}" if t in run["tasks"] else "not run"
                      for t in task_ids]
            seconds = _median([task["median_seconds"] for task in run["tasks"].values()])
            tokens = _median([task["median_tokens"] for task in run["tasks"].values()])
        else:
            checks, seconds, tokens = [verdict(run)] * len(task_ids), "", ""
        lines.append(f"| {run['provider']} | {run['model']} | {run['api']} | " + " | ".join(checks)
                     + f" | {seconds} | {tokens} |")
    return lines + [""]


def render(results: list[dict[str, Any]]) -> str:
    first = results[0]
    lines = [
        "# AI agent evaluations", "",
        "Whether the AI agent for Moodle works with each AI provider, model and API mode, measured on real Moodle",
        "sites running the plugin's release build. Each check sends real questions to the agent and grades the",
        "answers automatically.", "",
        f"Plugin version {first['plugin_release']}, measured on {first['started'][:10]}.", "",
    ]
    compat = [result for result in results if result["tier"] == "compat"]
    models = [result for result in results if result["tier"] == "models"]
    if compat:
        lines += _compat_table(compat)
    if models:
        lines += _models_table(models)
    descriptions: dict[str, str] = {}
    for result in results:
        descriptions.update(result.get("tasks", {}))
    lines += ["## What the checks do", ""]
    lines += [f"- **{task_id}:** {text}" for task_id, text in sorted(descriptions.items())]
    lines += [
        "", "## How to read the tables", "",
        "- **works:** every check passed in every trial.",
        "- **fails:** at least one check failed at least once.",
        "- **rate limited:** the AI provider refused requests for exceeding its rate limit, so the result says "
        "nothing about compatibility.",
        "- **not available:** no plugin for this provider exists for that Moodle version.",
        "- **not tested:** a plugin exists but is not tested there, because Moodle includes its own.",
        "- **not run:** the check could not be run this time.", "",
    ]
    return "\n".join(lines)


def history_rows(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for result in results:
        for run in result["runs"]:
            if "cell" not in run:
                continue
            base = {"date": result["started"][:10], "plugin_release": result["plugin_release"],
                    "tier": result["tier"], "moodle": _label(run["branch"]), "cell": run["cell"],
                    "provider": run["provider"], "api": run["api"], "model": run["model"], "status": verdict(run)}
            if run["status"] == "ran":
                for task_id, task in sorted(run["tasks"].items()):
                    rows.append({**base, "task": task_id, "trials": task["trials"], "passed": task["passed"]})
            else:
                rows.append({**base, "task": "", "trials": 0, "passed": 0})
    return rows


def publish(patterns: list[str], docs_dir: Path) -> None:
    results = load_results(patterns)
    folder = docs_dir / "evals"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "README.md").write_text(render(results), encoding="utf-8")
    history = folder / "history.csv"
    is_new = not history.exists()
    with history.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=HISTORY_FIELDS)
        if is_new:
            writer.writeheader()
        writer.writerows(history_rows(results))
