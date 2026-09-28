import pytest
import requests

pytestmark = pytest.mark.integration


def test_the_site_serves_its_login_page(site):
    response = requests.get(f"{site.version.wwwroot}/login/index.php", timeout=30)
    assert response.status_code == 200
    assert 'name="logintoken"' in response.text


def test_the_helper_plugin_is_installed(site):
    out = site.cli("admin/cli/cfg.php", "--component=local_aiagentevals", "--name=version").stdout
    assert out.strip() == "2026092800"
