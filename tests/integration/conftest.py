import os

import pytest

from aiagent_evals import config
from aiagent_evals.site import Site


@pytest.fixture(scope="session")
def site() -> Site:
    """The evaluation site for EVAL_MOODLE (default 502), built or reused with the .env settings."""
    config.load_env()
    version = config.load_versions()[os.environ.get("EVAL_MOODLE", "502")]
    built = Site(version, os.environ.get("DISTRTEST_REF", "main"), os.environ["DISTRTEST_REPO"])
    built.ensure(os.environ["TOOL_AIAGENT_TEST_LICENSE_KEY"], os.environ["TOOL_AIAGENT_TEST_API_ENDPOINT_STAGING"])
    return built
