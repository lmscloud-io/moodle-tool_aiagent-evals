import os
import time

import pytest

from aiagent_evals import config
from aiagent_evals.driver import MoodleChat
from aiagent_evals.site import ADMIN_PASSWORD
from aiagent_evals.transcript import Transcript

pytestmark = pytest.mark.integration


def test_a_real_turn_through_ajax_php(site):
    cell = next(c for c in config.load_matrix()[0] if c.id == "openai-responses-gpt-6-luna")
    site.activate(cell, os.environ)
    chat = MoodleChat(site.version.wwwroot, "admin", ADMIN_PASSWORD)
    chat.login()
    result = chat.send("What is 2+2? Reply with only the number.", "readonly", time.monotonic() + 180)
    assert result.settled == "reply", result.payload
    assert Transcript(chat.hash, result.payload["messages"]).final_reply().strip() == "4"
    assert site.usage(chat.hash), "the turn wrote no usage row"
