import pytest

from aiagent_evals import config
from aiagent_evals.runner import branches_for, cell_status, matches, summarise


def _cells():
    return {cell.id: cell for cell in config.load_matrix()[0]}


def test_cells_that_cannot_run_say_why():
    cells, sources = _cells(), config.load_provider_sources()
    keys = {"ANTHROPIC_API_KEY": "x", "OPENAI_API_KEY": "y"}
    assert cell_status(cells["anthropic-claude-haiku-4-5"], "500", sources, keys) == "not_available"
    assert cell_status(cells["claude-claude-haiku-4-5"], "503", sources, keys) == "not_tested"
    assert cell_status(cells["openai-cc-gpt-6-luna"], "502", sources, {}) == "not_configured"
    assert cell_status(cells["openai-cc-gpt-6-luna"], "502", sources, keys) is None


def test_tiers_pick_their_branches():
    _, tiers = config.load_matrix()
    versions = config.load_versions()
    php = "$plugin->supported = [405, 502];"
    assert branches_for(tiers["compat"], php, versions) == ["405", "500", "501", "502"]
    assert branches_for(tiers["models"], php, versions) == ["502"]
    assert branches_for(tiers["compat"], php, versions, "405, 502") == ["405", "502"]
    with pytest.raises(SystemExit, match="503"):
        branches_for(tiers["compat"], php, versions, "503")


def test_filters_are_comma_separated_globs():
    assert matches("openai-cc-gpt-6-luna", "openai-*,gemini-*")
    assert matches("anything", "")
    assert not matches("kimi-cc-kimi-k2", "openai-*")


def test_summaries_count_trials_errors_and_rate_limits():
    trials = [
        {"task": "t", "error": False, "passed": True, "rate_limited": False, "seconds": 2.0, "tokens": 100},
        {"task": "t", "error": False, "passed": False, "rate_limited": True, "seconds": 4.0, "tokens": 300},
        {"task": "t", "error": True, "passed": False, "rate_limited": False, "seconds": 0.0, "tokens": 0},
    ]
    assert summarise(trials) == {"t": {"trials": 2, "passed": 1, "errors": 1, "rate_limited": True,
                                       "median_seconds": 3.0, "median_tokens": 200}}


def test_results_never_carry_secret_values(tmp_path):
    from aiagent_evals.runner import write_results

    env = {
        "OPENAI_API_KEY": "sk-secret-value-123",
        "TOOL_AIAGENT_TEST_LICENSE_KEY": "LIC-1234567",
        "DISTRTEST_REPO": "https://x-access-token:ghs_tokenvalue123@github.com/lmscloud-io/moodle-tool_aiagent-distrtest.git",
    }
    problem = ("git clone exited 128: fatal: repository 'https://x-access-token:ghs_tokenvalue123@github.com/x' "
               "not found; key sk-secret-value-123; license LIC-1234567; bare token ghs_tokenvalue123")
    write_results(tmp_path, {"runs": [{"branch": "502", "status": "site_failed", "problems": [problem]}]}, env)
    text = (tmp_path / "results.json").read_text(encoding="utf-8")
    for secret in ("sk-secret-value-123", "LIC-1234567", "ghs_tokenvalue123"):
        assert secret not in text
    assert "[redacted]" in text and "git clone exited 128" in text
