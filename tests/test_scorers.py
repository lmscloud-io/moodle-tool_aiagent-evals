import asyncio
from types import SimpleNamespace

from inspect_ai.scorer import INCORRECT, Target

from aiagent_evals.config import Grader, TaskSpec
from aiagent_evals.scorers import grade, graded
from aiagent_evals.transcript import Transcript, Turn

USER = {"role": "user", "content": "What is 2+2?", "messageid": 1}
REPLY = {"role": "assistant", "content": "<p>4</p>", "messageid": 2}
USAGE = [{"prompttokens": 900, "completiontokens": 3, "model": "gpt-6-luna"}]


def transcript(entries, settled=("reply",), usage=USAGE):
    return Transcript("h1", list(entries), list(usage), [Turn(state, 1.5) for state in settled])


def verdicts(t, *graders):
    return [(result.name, result.passed) for result in grade(t, tuple(graders))]


def test_a_clean_reply_passes_the_phase_1_graders():
    t = transcript([USER, REPLY])
    assert verdicts(t, Grader("no_error"), Grader("reply_matches", r"^\s*4\s*$"), Grader("usage_recorded")) == [
        ("no_error", True), ("reply_matches", True), ("usage_recorded", True)]


def test_no_error_goes_by_the_flag_not_the_wording():
    bubble = {"role": "assistant", "content": "Let us try that again.", "iserror": True, "messageid": 3}
    mentions = {"role": "assistant", "content": "<p>No error: the answer is 4.</p>", "messageid": 3}
    assert verdicts(transcript([USER, bubble], ("error",)), Grader("no_error")) == [("no_error", False)]
    assert verdicts(transcript([USER, mentions]), Grader("no_error")) == [("no_error", True)]


def test_a_turn_waiting_for_approval_fails_no_error_with_a_reason():
    [result] = grade(transcript([USER], ("pending_approval",)), (Grader("no_error"),))
    assert not result.passed and "waiting for approval" in result.reason


def test_a_timeout_fails_no_error():
    [result] = grade(transcript([USER], ("timeout",)), (Grader("no_error"),))
    assert not result.passed and "time" in result.reason


def test_tool_succeeded_needs_a_succeeded_result():
    call = {"role": "tool_call", "tools": [{"id": "c1", "name": "f", "arguments": {}}], "messageid": 2}
    good = {"role": "tool", "results": [{"tool_call_id": "c1", "name": "f", "result": "{}", "status": "succeeded"}]}
    bad = {"role": "tool", "results": [{"tool_call_id": "c1", "name": "f", "result": "{}", "status": "failed"}]}
    assert verdicts(transcript([USER, call, good, REPLY]), Grader("tool_succeeded")) == [("tool_succeeded", True)]
    assert verdicts(transcript([USER, call, bad, REPLY]), Grader("tool_succeeded")) == [("tool_succeeded", False)]


def test_usage_recorded_needs_tokens_and_a_model():
    assert verdicts(transcript([USER, REPLY], usage=[]), Grader("usage_recorded")) == [("usage_recorded", False)]


def test_the_scorer_combines_graders_and_reports_metadata():
    spec = TaskSpec("plain-reply", "d", ("compat",), "admin", ("What is 2+2?",),
                    (Grader("no_error"), Grader("reply_contains", "5")))
    state = SimpleNamespace(store={"transcript": transcript([USER, REPLY]).to_dict()},
                            metadata={"task": spec.to_dict()})
    score = asyncio.run(graded()(state, Target("")))
    assert score.value == INCORRECT
    assert "reply_contains" in score.explanation
    assert score.metadata["prompt_tokens"] == 900 and score.metadata["llm_calls"] == 1
    assert score.metadata["graders"] == [["no_error", True], ["reply_contains", False]]
