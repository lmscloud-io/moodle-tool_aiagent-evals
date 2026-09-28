import pytest

from aiagent_evals import config


def test_provider_sources_follow_the_spec_table():
    sources = config.load_provider_sources()
    assert config.provider_source(sources, "aiprovider_openai", "405") == "core"
    assert config.provider_source(sources, "aiprovider_anthropic", "500") is None
    assert config.provider_source(sources, "aiprovider_anthropic", "503") == "core"
    assert config.provider_source(sources, "aiprovider_claude", "503") == "skip"
    assert config.provider_source(sources, "aiprovider_claude", "501") == config.GitSource(
        "https://github.com/ashishptl21/moodle-aiprovider_claude.git", "main")
    assert config.provider_source(sources, "aiprovider_gemini", "502") == "core"
    assert config.provider_source(sources, "aiprovider_openaicompatible", "405") == config.GitSource(
        "https://github.com/lmscloud-io/moodle-aiprovider_openaicompatible.git", "moodle405")
    assert config.provider_source(sources, "aiprovider_openaicompatible", "501") == config.GitSource(
        "https://github.com/ADORSYS-GIS/moodle-aiprovider_openaicompatible.git", "main")


def test_unknown_provider_is_a_config_error():
    with pytest.raises(config.ConfigError, match="aiprovider_nope"):
        config.provider_source(config.load_provider_sources(), "aiprovider_nope", "502")


def test_supported_branches_come_from_version_php():
    versions = config.load_versions()
    assert config.supported_branches("$plugin->supported    = [405, 502];", versions) == ["405", "500", "501", "502"]
    assert config.supported_branches("$plugin->supported = [405, 503];", versions)[-1] == "503"


def test_version_php_without_a_range_is_rejected():
    with pytest.raises(config.ConfigError):
        config.supported_branches("<?php", config.load_versions())


def test_plugin_release_is_read_from_version_php():
    assert config.plugin_release("$plugin->release      = '4.5.6';") == "4.5.6"


def test_wwwroot_follows_the_port():
    assert config.load_versions()["502"].wwwroot == "http://localhost:8502"


def test_matrix_loads_and_tiers_name_real_cells():
    cells, tiers = config.load_matrix()
    ids = [cell.id for cell in cells]
    assert tiers["models"].cells == tuple(ids)
    assert set(tiers["compat"].cells) <= set(ids)
    assert tiers["compat"].trials == 2 and tiers["models"].trials == 3


def test_cells_carry_each_providers_settings():
    cells = {cell.id: cell for cell in config.load_matrix()[0]}
    azure = cells["azureai-cc-gpt-6-luna"]
    assert azure.action_settings()["deployment"] == "gpt-6-luna"
    assert "model" not in azure.action_settings()
    gemini = cells["gemini-generatecontent-gemini-3-flash"]
    assert gemini.action_settings()["endpoint"].endswith("/models/gemini-3-flash-preview:generateContent")
    assert cells["openai-cc-gpt-6-luna"].action_settings()["endpoint"] == "https://api.openai.com/v1/chat/completions"
    assert cells["kimi-cc-kimi-k2-6"].provider_config() == {"apiendpoint": "https://api.moonshot.ai/v1"}
    assert cells["openai-responses-gpt-6-luna"].api_label() == "Responses API"
    assert cells["anthropic-claude-haiku-4-5"].api_label() == "Messages API"
    assert cells["kimi-cc-kimi-k2-6"].provider_label() == "Kimi (OpenAI-compatible plugin, Moonshot)"


def test_an_openai_cell_without_an_api_type_is_rejected(tmp_path):
    (tmp_path / "matrix.yaml").write_text(
        "cells:\n  - {id: x, provider: aiprovider_openai, model: m, secrets: {apikey: K}}\n"
        "tiers: {compat: {moodle: supported, trials: 1, cells: all}}\n")
    with pytest.raises(config.ConfigError, match="openai_api_type"):
        config.load_matrix(tmp_path / "matrix.yaml")


def test_task_defaults_and_grader_forms(tmp_path):
    (tmp_path / "t.yaml").write_text(
        "id: t\ndescription: d\ntiers: [compat]\nuser: admin\nturns: ['hi']\n"
        "graders: [no_error, {reply_matches: '^4$'}, {reply_contains: x, turn: 1}]\n")
    [task] = config.load_tasks(tmp_path)
    assert (task.launch, task.autoapprove, task.budget_seconds, task.mutates) == ("fullscreen", "readonly", 600, False)
    assert task.graders == (config.Grader("no_error"), config.Grader("reply_matches", "^4$"),
                            config.Grader("reply_contains", "x", 1))
    assert config.TaskSpec.from_dict(task.to_dict()) == task


def test_unknown_grader_is_rejected(tmp_path):
    (tmp_path / "t.yaml").write_text(
        "id: t\ndescription: d\ntiers: [compat]\nuser: admin\nturns: ['hi']\ngraders: [telepathy]\n")
    with pytest.raises(config.ConfigError, match="telepathy"):
        config.load_tasks(tmp_path)


def test_grader_argument_rules(tmp_path):
    (tmp_path / "t.yaml").write_text(
        "id: t\ndescription: d\ntiers: [compat]\nuser: admin\nturns: ['hi']\ngraders: [reply_contains]\n")
    with pytest.raises(config.ConfigError, match="needs"):
        config.load_tasks(tmp_path)


def test_the_committed_tasks_load():
    assert "plain-reply" in [task.id for task in config.load_tasks()]
