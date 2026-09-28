import pytest

from aiagent_evals.site import SiteError

pytestmark = pytest.mark.integration


def test_preflight_passes_on_a_freshly_built_site(site):
    site.refresh_helper()
    assert site.preflight() == []


def test_usage_of_an_unknown_chat_is_an_error(site):
    site.refresh_helper()
    with pytest.raises(SiteError):
        site.usage("nosuchchat")
