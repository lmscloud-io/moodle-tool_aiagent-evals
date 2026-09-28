import pytest

pytestmark = pytest.mark.integration


def test_the_standard_seed_builds_the_named_world(site):
    site.refresh_helper()
    manifest = site.seed()
    assert set(manifest["courses"]) == {"ZA101", "QM201", "HS110"}
    assert manifest["courses"]["ZA101"]["contextid"] > 0
    assert manifest["courses"]["ZA101"]["url"].startswith(site.version.wwwroot + "/course/view.php?id=")
    assert {"manager1", "teacher1", "assistant1", "student01", "student20"} <= set(manifest["users"])
    assert "ZA101/Group A" in manifest["groups"]


def test_seeding_again_returns_the_same_manifest(site):
    site.refresh_helper()
    assert site.seed() == site.seed()


def test_the_admin_and_a_teacher_can_open_the_chat(site):
    site.refresh_helper()
    manifest = site.seed()
    assert site.check_logins(["admin", "teacher1"], site.passwords(manifest)) == []


def test_an_unknown_user_is_reported(site):
    assert site.check_logins(["nobody"], {}) == ["no seeded user is called nobody"]
