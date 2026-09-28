import os

import pytest
from inspect_ai import eval as inspect_eval

from aiagent_evals import config, context
from aiagent_evals.config import Tier
from aiagent_evals.evaltask import build_task
from aiagent_evals.site import ADMIN_PASSWORD

pytestmark = pytest.mark.integration


def test_plain_reply_runs_end_to_end(site, tmp_path):
    cell = next(c for c in config.load_matrix()[0] if c.id == "openai-responses-gpt-6-luna")
    site.activate(cell, os.environ)
    context.current = context.RunContext(site.version.wwwroot, {"admin": ADMIN_PASSWORD}, site.usage)
    tasks = [task for task in config.load_tasks() if task.id == "plain-reply"]
    [log] = inspect_eval(build_task(Tier("compat", "newest", (cell.id,), 1), tasks), model=f"moodle/{cell.id}",
                         log_dir=str(tmp_path), display="none", max_samples=1)
    assert log.status == "success"
    [sample] = log.samples
    score = sample.scores["graded"]
    assert score.value == "C", score.explanation
    assert sample.messages[0].role == "user"


def test_course_fullname_calls_a_function(site, tmp_path):
    site.refresh_helper()
    manifest = site.seed()
    cell = next(c for c in config.load_matrix()[0] if c.id == "openai-responses-gpt-6-luna")
    site.activate(cell, os.environ)
    context.current = context.RunContext(site.version.wwwroot, site.passwords(manifest), site.usage,
                                         manifest["courses"])
    tasks = [task for task in config.load_tasks() if task.id == "course-fullname"]
    [log] = inspect_eval(build_task(Tier("compat", "newest", (cell.id,), 1), tasks), model=f"moodle/{cell.id}",
                         log_dir=str(tmp_path), display="none", max_samples=1)
    [sample] = log.samples
    assert sample.scores["graded"].value == "C", sample.scores["graded"].explanation
    assert any(getattr(message, "tool_calls", None) for message in sample.messages)
