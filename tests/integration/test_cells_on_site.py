import pytest

from aiagent_evals import config
from aiagent_evals.site import SiteError

pytestmark = pytest.mark.integration


def _cell(cell_id):
    return next(cell for cell in config.load_matrix()[0] if cell.id == cell_id)


def test_activating_a_cell_leaves_only_its_provider_enabled(site):
    site.refresh_helper()
    site.activate(_cell("openai-cc-gpt-6-luna"), {"OPENAI_API_KEY": "sk-not-a-real-key"})
    status = site.status()
    assert status["enabled"] == ["aiprovider_openai"]
    assert status["settings"]["openai_api_type"] == "chatcompletions"


def test_switching_cells_disables_the_previous_provider(site):
    site.refresh_helper()
    site.activate(_cell("openai-cc-gpt-6-luna"), {"OPENAI_API_KEY": "sk-not-a-real-key"})
    site.activate(_cell("gemini-generatecontent-gemini-3-flash"), {"GEMINI_API_KEY": "not-a-real-key"})
    status = site.status()
    assert status["enabled"] == ["aiprovider_gemini"]
    assert status["settings"]["gemini_api_type"] == "generatecontent"


def test_a_missing_secret_names_the_variable(site):
    with pytest.raises(SiteError, match="OPENAI_API_KEY"):
        site.activate(_cell("openai-cc-gpt-6-luna"), {})
