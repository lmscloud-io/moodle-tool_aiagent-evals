import csv
import json

from aiagent_evals.publish import publish, render, verdict

DESCRIPTION = "A plain question gets an answer while the agent's functions are on offer."


def run(branch, cell, provider, api, status="ran", passed=2, trials=2, rate_limited=False, model="m"):
    record = {"branch": branch, "cell": cell, "provider": provider, "api": api, "model": model, "status": status}
    if status == "ran":
        record["tasks"] = {"plain-reply": {"trials": trials, "passed": passed, "errors": 0,
                                           "rate_limited": rate_limited, "median_seconds": 3.0,
                                           "median_tokens": 1200}}
    return record


COMPAT = {
    "started": "2026-10-05T03:00:00+00:00", "distrtest_ref": "v4.5.7", "plugin_release": "4.5.7",
    "tier": "compat", "trials": 2, "tasks": {"plain-reply": DESCRIPTION},
    "runs": [
        run("405", "openai-cc", "OpenAI", "Chat Completions"),
        run("502", "openai-cc", "OpenAI", "Chat Completions", passed=0),
        run("500", "anthropic", "Anthropic", "Messages API", status="not_available"),
        run("502", "anthropic", "Anthropic", "Messages API", passed=1, rate_limited=True),
        {"branch": "501", "status": "site_failed", "problems": ["SECRET-LOOKING stderr: license refused"]},
    ],
}
MODELS = {
    "started": "2026-10-05T03:00:00+00:00", "distrtest_ref": "v4.5.7", "plugin_release": "4.5.7",
    "tier": "models", "trials": 3, "tasks": {"plain-reply": DESCRIPTION},
    "runs": [run("502", "openai-responses-gpt-6-luna", "OpenAI", "Responses API", passed=3, trials=3,
                 model="gpt-6-luna")],
}


def test_verdict_words():
    assert verdict(run("405", "c", "P", "A")) == "works"
    assert verdict(run("405", "c", "P", "A", passed=1)) == "fails"
    assert verdict(run("405", "c", "P", "A", passed=1, rate_limited=True)) == "rate limited"
    assert verdict(run("500", "c", "P", "A", status="not_available")) == "not available"
    assert verdict(run("503", "c", "P", "A", status="not_tested")) == "not tested"
    assert verdict(run("502", "c", "P", "A", status="not_configured")) == "not run"


def test_the_compatibility_table_says_words_not_failures():
    page = render([COMPAT])
    assert "| OpenAI | Chat Completions | works | not run | not run | fails |" in page
    assert "| Anthropic | Messages API | not run | not available | not run | rate limited |" in page


def test_the_models_table_shows_trials_passed():
    assert "| OpenAI | gpt-6-luna | Responses API | 3/3 | 3 | 1200 |" in render([MODELS])


def test_the_page_carries_no_problems_and_no_em_dashes():
    page = render([COMPAT, MODELS])
    assert "SECRET-LOOKING" not in page and "license refused" not in page
    assert "\u2014" not in page
    assert DESCRIPTION in page


def test_history_gains_a_row_per_task_and_cell(tmp_path):
    results = tmp_path / "r" / "results.json"
    results.parent.mkdir()
    results.write_text(json.dumps(COMPAT))
    publish([str(results)], tmp_path / "docs")
    publish([str(results)], tmp_path / "docs")
    with (tmp_path / "docs" / "evals" / "history.csv").open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 8
    assert (rows[0]["moodle"], rows[0]["cell"], rows[0]["status"]) == ("4.5", "openai-cc", "works")
    assert (tmp_path / "docs" / "evals" / "README.md").read_text(encoding="utf-8").startswith("# AI agent evaluations")
