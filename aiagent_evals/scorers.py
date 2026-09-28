"""Code graders. A trial passes when every grader its task lists passes."""

from __future__ import annotations

import re
from dataclasses import dataclass

from inspect_ai.scorer import CORRECT, INCORRECT, Score, Target, accuracy, scorer
from inspect_ai.solver import TaskState

from .config import Grader, TaskSpec
from .transcript import SUCCEEDED, Transcript


@dataclass(frozen=True)
class GraderResult:
    name: str
    passed: bool
    reason: str = ""


def _no_error(t: Transcript, grader: Grader) -> GraderResult:
    first = grader.turn or 1
    turns = t.turns if grader.turn is None else t.turns[grader.turn - 1:grader.turn]
    for number, turn in enumerate(turns, start=first):
        if turn.settled == "timeout":
            return GraderResult(grader.name, False, f"turn {number} ran out of time")
        if turn.settled == "pending_approval":
            return GraderResult(grader.name, False, f"turn {number} stopped at a function call waiting for approval")
    errors = t.errors(grader.turn)
    if errors:
        return GraderResult(grader.name, False, "error bubble: " + errors[-1][:200])
    return GraderResult(grader.name, True)


def _reply_contains(t: Transcript, grader: Grader) -> GraderResult:
    reply = t.final_reply(grader.turn)
    passed = str(grader.arg) in reply
    return GraderResult(grader.name, passed, "" if passed else f"the reply lacks {grader.arg!r}: {reply[:200]!r}")


def _reply_matches(t: Transcript, grader: Grader) -> GraderResult:
    reply = t.final_reply(grader.turn)
    passed = re.search(str(grader.arg), reply) is not None
    return GraderResult(grader.name, passed, "" if passed else f"the reply does not match {grader.arg!r}: {reply[:200]!r}")


def _tool_succeeded(t: Transcript, grader: Grader) -> GraderResult:
    passed = any(result.get("status") == SUCCEEDED for result in t.tool_results(grader.turn))
    return GraderResult(grader.name, passed, "" if passed else "no function call succeeded")


def _usage_recorded(t: Transcript, grader: Grader) -> GraderResult:
    passed = any((row.get("prompttokens") or 0) > 0 and (row.get("completiontokens") or 0) > 0 and row.get("model")
                 for row in t.usage)
    return GraderResult(grader.name, passed, "" if passed else "no usage row with tokens and a model")


GRADERS = {
    "no_error": _no_error,
    "reply_contains": _reply_contains,
    "reply_matches": _reply_matches,
    "tool_succeeded": _tool_succeeded,
    "usage_recorded": _usage_recorded,
}


def grade(transcript: Transcript, graders: tuple[Grader, ...]) -> list[GraderResult]:
    return [GRADERS[grader.name](transcript, grader) for grader in graders]


@scorer(metrics=[accuracy()])
def graded():
    """CORRECT when every grader the sample's task lists passes; each verdict rides in the metadata."""

    async def score(state: TaskState, target: Target) -> Score:
        transcript = Transcript.from_dict(state.store.get("transcript"))
        spec = TaskSpec.from_dict(state.metadata["task"])
        results = grade(transcript, spec.graders)
        failed = [result for result in results if not result.passed]
        prompt, completion = transcript.tokens()
        return Score(
            value=INCORRECT if failed else CORRECT,
            answer=transcript.final_reply(),
            explanation="; ".join(f"{r.name}: {r.reason}" for r in failed) or "every grader passed",
            metadata={
                "graders": [[result.name, result.passed] for result in results],
                "rate_limited": transcript.rate_limited(),
                "seconds": sum(turn.seconds for turn in transcript.turns),
                "prompt_tokens": prompt,
                "completion_tokens": completion,
                "llm_calls": len(transcript.usage),
            },
        )

    return score
