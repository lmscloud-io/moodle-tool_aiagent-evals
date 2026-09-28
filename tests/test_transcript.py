from inspect_ai.model import ChatMessageAssistant, ChatMessageTool, ChatMessageUser

from aiagent_evals.transcript import Transcript, Turn, html_to_text

USER = {"role": "user", "content": "What is the full name of ZA101?", "messageid": 1}
CALL = {"role": "tool_call", "messageid": 2, "autorun": True, "tools": [
    {"id": "call_1", "name": "core_course_get_courses_by_field", "type": "read",
     "arguments": {"field": "shortname", "value": "ZA101"}}]}
RESULT = {"role": "tool", "denied": False, "results": [
    {"tool_call_id": "call_1", "name": "core_course_get_courses_by_field",
     "result": '{"courses":[{"fullname":"Zebra Analytics 101"}]}', "status": "succeeded"}]}
REPLY = {"role": "assistant", "content": "<p>Zebra Analytics 101</p>", "messageid": 4}


def test_html_to_text_drops_tags_and_decodes_entities():
    assert html_to_text("<p>4</p>") == "4"
    assert html_to_text("<p>Fish &amp; chips</p><p>Two</p>") == "Fish & chips\nTwo"
    assert html_to_text("<pre><code>a = 1</code></pre>") == "a = 1"
    assert html_to_text("") == ""


def test_final_reply_is_the_last_reply_that_is_not_an_error():
    bubble = {"role": "assistant", "content": "Something went wrong.", "iserror": True, "messageid": 5}
    assert Transcript("h", [USER, CALL, RESULT, REPLY]).final_reply() == "Zebra Analytics 101"
    assert Transcript("h", [USER, bubble]).final_reply() == ""


def test_error_bubbles_are_found_by_the_flag_not_the_wording():
    harmless = {"role": "assistant", "content": "<p>Let us try that again.</p>", "iserror": True}
    mentions = {"role": "assistant", "content": "<p>There was no error: the answer is 4.</p>"}
    assert Transcript("h", [USER, harmless]).errors() == ["Let us try that again."]
    assert Transcript("h", [USER, mentions]).errors() == []


def test_turns_split_at_user_messages():
    second = {"role": "user", "content": "And its short name?", "messageid": 5}
    answer = {"role": "assistant", "content": "<p>ZA101</p>", "messageid": 6}
    transcript = Transcript("h", [USER, CALL, RESULT, REPLY, second, answer])
    assert transcript.final_reply(1) == "Zebra Analytics 101"
    assert transcript.final_reply(2) == "ZA101"
    assert transcript.final_reply() == "ZA101"
    assert [r["status"] for r in transcript.tool_results(1)] == ["succeeded"]
    assert transcript.tool_results(2) == []
    assert transcript.final_reply(3) == ""


def test_function_calls_become_inspect_tool_calls():
    messages = Transcript("h", [USER, CALL, RESULT, REPLY]).to_inspect_messages()
    assert [type(m) for m in messages] == [ChatMessageUser, ChatMessageAssistant, ChatMessageTool, ChatMessageAssistant]
    [call] = messages[1].tool_calls
    assert (call.id, call.function, call.arguments) == ("call_1", "core_course_get_courses_by_field",
                                                        {"field": "shortname", "value": "ZA101"})
    assert messages[2].tool_call_id == "call_1" and messages[2].error is None
    assert messages[3].text == "Zebra Analytics 101"


def test_failed_and_denied_calls_carry_an_error():
    failed = {"role": "tool", "results": [{"tool_call_id": "c", "name": "f", "result": "{}", "status": "failed"}]}
    denied = {"role": "tool", "denied": True, "results": [{"tool_call_id": "c", "name": "f", "result": "", "status": "denied"}]}
    assert Transcript("h", [USER, failed]).to_inspect_messages()[1].error.type == "unknown"
    assert Transcript("h", [USER, denied]).to_inspect_messages()[1].error.type == "approval"


def test_arguments_given_as_a_json_string_are_decoded():
    call = {"role": "tool_call", "tools": [{"id": "c", "name": "f", "arguments": '{"a": 1}'}]}
    assert Transcript("h", [USER, call]).to_inspect_messages()[1].tool_calls[0].arguments == {"a": 1}


def test_tokens_and_rate_limits():
    limited = {"role": "assistant", "content": "Error 429: Too Many Requests", "iserror": True}
    transcript = Transcript("h", [USER, limited], usage=[{"prompttokens": 10, "completiontokens": 2},
                                                         {"prompttokens": 5, "completiontokens": None}])
    assert transcript.tokens() == (15, 2)
    assert transcript.rate_limited()


def test_round_trip_through_a_dict():
    transcript = Transcript("h", [USER, REPLY], [{"prompttokens": 1}], [Turn("reply", 2.5)])
    assert Transcript.from_dict(transcript.to_dict()) == transcript
