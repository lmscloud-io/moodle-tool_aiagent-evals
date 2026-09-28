"""The module Inspect loads through the aiagent_evals entry point (see pyproject.toml)."""

from inspect_ai.model import modelapi


@modelapi(name="moodle")
def moodle():
    from .cells import MoodleCellAPI

    return MoodleCellAPI
