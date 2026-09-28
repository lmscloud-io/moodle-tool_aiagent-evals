from aiagent_evals import config
from aiagent_evals import site as sitemodule


def test_config_php_carries_the_wwwroot_and_escaped_secrets():
    text = sitemodule.render_config("http://localhost:8502", "key'with\\quote", "https://staging.example/api")
    assert "$CFG->wwwroot   = 'http://localhost:8502';" in text
    assert "define('TOOL_AIAGENT_TEST_LICENSE_KEY', 'key\\'with\\\\quote');" in text
    assert "define('TOOL_AIAGENT_TEST_API_ENDPOINT', 'https://staging.example/api');" in text
    assert "$CFG->noemailever = true;" in text
    assert "{{" not in text


def test_plugins_live_under_public_from_5_1(tmp_path, monkeypatch):
    monkeypatch.setattr(sitemodule, "SITES_DIR", tmp_path)
    versions = config.load_versions()
    public = sitemodule.Site(versions["501"], "main", "repo")
    (public.moodle_dir / "public").mkdir(parents=True)
    assert public.plugin_path("admin/tool/aiagent") == public.moodle_dir / "public" / "admin" / "tool" / "aiagent"
    flat = sitemodule.Site(versions["405"], "main", "repo")
    flat.moodle_dir.mkdir(parents=True)
    assert flat.plugin_path("admin/tool/aiagent") == flat.moodle_dir / "admin" / "tool" / "aiagent"


def test_each_branch_gets_its_own_compose_project():
    versions = config.load_versions()
    assert len({sitemodule.Site(v, "main", "repo").project for v in versions.values()}) == len(versions)
