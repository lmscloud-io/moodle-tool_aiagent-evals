"""Run a task's turns through the chat UI's requests and record the transcript on the Inspect sample."""

from __future__ import annotations

import asyncio
import time

from inspect_ai.model import ModelOutput
from inspect_ai.solver import Generate, TaskState, solver

from . import context
from .config import TaskSpec
from .driver import MoodleChat
from .transcript import Transcript, Turn


@solver
def moodle_conversation():
    """Drive the sample's chat on the site in context.current; a DriverError makes it an Inspect error."""

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        run = context.current
        if run is None:
            raise RuntimeError("context.current is not set: the runner sets it before eval()")
        spec = TaskSpec.from_dict(state.metadata["task"])
        launch = None
        if isinstance(spec.launch, dict) and "course" in spec.launch:
            launch = run.launches[spec.launch["course"]]
        chat = MoodleChat(run.wwwroot, spec.user, run.passwords[spec.user])
        await asyncio.to_thread(chat.login)
        deadline = time.monotonic() + spec.budget_seconds
        turns: list[Turn] = []
        for message in spec.turns:
            result = await asyncio.to_thread(chat.send, message, spec.autoapprove, deadline, launch)
            turns.append(Turn(result.settled, result.seconds))
            if result.settled != "reply":
                break
        payload = await asyncio.to_thread(chat.load)
        rows = await asyncio.to_thread(run.usage, chat.hash)
        transcript = Transcript(chat.hash, list(payload.get("messages") or []), rows, turns)
        state.messages = transcript.to_inspect_messages()
        state.output = ModelOutput.from_content(model=str(state.model), content=transcript.final_reply())
        state.store.set("transcript", transcript.to_dict())
        return state

    return solve
