import json
import time

import pytest
import requests

from aiagent_evals.driver import DriverError, MoodleChat

WWWROOT = "http://localhost:8502"
LOGIN_PAGE = '<form><input type="hidden" name="logintoken" value="tok123"></form>'
CHAT_PAGE = '<script>M.cfg = {"wwwroot":"http://localhost:8502","sesskey":"sk456"};</script>'
REPLY = {"role": "assistant", "content": "<p>4</p>", "messageid": 3}
USER = {"role": "user", "content": "What is 2+2?", "messageid": 2}


class FakeResponse:
    def __init__(self, payload=None, status=200, text=None):
        self.status_code = status
        self._payload = payload
        self.text = text if text is not None else json.dumps(payload)

    def json(self):
        if self._payload is None:
            raise ValueError("not JSON")
        return self._payload


class FakeSession:
    """Answers GETs by path and ajax.php POSTs from a per-action queue; records every call."""

    def __init__(self, actions, chat_page=CHAT_PAGE):
        self.pages = {"/login/index.php": FakeResponse(text=LOGIN_PAGE), "/admin/tool/aiagent/chat.php": FakeResponse(text=chat_page)}
        self.actions = {name: list(answers) for name, answers in actions.items()}
        self.calls = []

    def get(self, url, timeout=None):
        return self.pages[url[len(WWWROOT):]]

    def post(self, url, params=None, json=None, data=None, timeout=None):
        if params is None:
            self.calls.append(("login", data))
            return FakeResponse(text="<html>welcome</html>")
        self.calls.append((params["action"], json))
        assert params["sesskey"] == "sk456"
        answer = self.actions[params["action"]].pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


def chat(actions, **kwargs):
    driver = MoodleChat(WWWROOT, "admin", "pw", session=FakeSession(actions, **kwargs))
    driver.login()
    return driver


def later():
    return time.monotonic() + 60


def test_login_posts_the_token_and_reads_the_sesskey():
    driver = chat({})
    assert driver.http.calls == [("login", {"username": "admin", "password": "pw", "logintoken": "tok123"})]
    assert driver.sesskey == "sk456"


def test_a_failed_login_is_a_driver_error():
    with pytest.raises(DriverError, match="log in as admin"):
        chat({}, chat_page=LOGIN_PAGE)


def test_send_follows_continue_auto_and_carries_the_sync_token():
    driver = chat({
        "prepare_message": [FakeResponse({"success": True, "hash": "h1", "rootid": 7, "synctoken": "t1"})],
        "finish_message": [FakeResponse({"success": True, "continue_auto": True, "messageid": 9, "synctoken": "t2"})],
        "continue_auto": [FakeResponse({"success": True, "synctoken": "t3"})],
        "load": [FakeResponse({"success": True, "messages": [USER, REPLY], "pending_tool_count": 0, "synctoken": "t3"})],
    })
    result = driver.send("What is 2+2?", "readonly", later())
    assert result.settled == "reply"
    actions = [(name, body) for name, body in driver.http.calls if name != "login"]
    assert [name for name, _ in actions] == ["prepare_message", "finish_message", "continue_auto", "load"]
    assert actions[0][1]["message"] == "What is 2+2?" and actions[0][1]["autoapprove"] == "readonly"
    assert actions[1][1] == {"hash": "h1", "synctoken": "t1", "rootid": 7}
    assert actions[2][1] == {"hash": "h1", "synctoken": "t2", "pagecaptures": {}}


def test_a_turn_waiting_for_approval_settles_without_looping():
    driver = chat({
        "prepare_message": [FakeResponse({"success": True, "hash": "h1", "rootid": 7, "synctoken": "t1"})],
        "finish_message": [FakeResponse({"success": True, "synctoken": "t2"})],
        "load": [FakeResponse({"success": True, "messages": [USER], "pending_tool_count": 1, "synctoken": "t2"})],
    })
    assert driver.send("Delete ZA101", "readonly", later()).settled == "pending_approval"
    assert "continue_auto" not in [name for name, _ in driver.http.calls]


def test_a_provider_error_settles_as_an_error_bubble():
    bubble = {"role": "assistant", "content": "The AI provider returned an error.", "iserror": True, "messageid": 5}
    driver = chat({
        "prepare_message": [FakeResponse({"success": True, "hash": "h1", "rootid": 7, "synctoken": "t1"})],
        "finish_message": [FakeResponse({"success": False, "errortype": "providererror", "messageid": 5, "hash": "h1"})],
        "load": [FakeResponse({"success": True, "messages": [USER, bubble], "pending_tool_count": 0, "synctoken": "t2"})],
    })
    assert driver.send("What is 2+2?", "readonly", later()).settled == "error"


def test_a_non_json_answer_is_a_driver_error():
    driver = chat({
        "prepare_message": [FakeResponse({"success": True, "hash": "h1", "rootid": 7, "synctoken": "t1"})],
        "finish_message": [FakeResponse(status=500, text="<html>Fatal error</html>")],
    })
    with pytest.raises(DriverError, match="non-JSON"):
        driver.send("What is 2+2?", "readonly", later())


def test_out_of_sync_is_a_driver_error():
    driver = chat({
        "prepare_message": [FakeResponse({"success": False, "errortype": "outofsync", "hash": "h1"})],
    })
    with pytest.raises(DriverError, match="out of sync"):
        driver.send("What is 2+2?", "readonly", later())


def test_a_refused_prepare_is_a_driver_error():
    driver = chat({
        "prepare_message": [FakeResponse({"success": False, "errortype": "nopermission", "errormessage": "No", "hash": ""})],
    })
    with pytest.raises(DriverError, match="nopermission"):
        driver.send("What is 2+2?", "readonly", later())


def test_a_timeout_settles_as_timeout():
    driver = chat({
        "prepare_message": [FakeResponse({"success": True, "hash": "h1", "rootid": 7, "synctoken": "t1"})],
        "finish_message": [requests.Timeout("slow provider")],
    })
    assert driver.send("What is 2+2?", "readonly", later()).settled == "timeout"


def test_a_resumable_batch_is_resumed_once():
    driver = chat({
        "prepare_message": [FakeResponse({"success": True, "hash": "h1", "rootid": 7, "synctoken": "t1"})],
        "finish_message": [FakeResponse({"success": True, "resume_auto": True, "resume_auto_messageid": 11, "synctoken": "t2"})],
        "continue_auto": [FakeResponse({"success": True, "resume_auto": True, "resume_auto_messageid": 11, "synctoken": "t3"})],
        "load": [FakeResponse({"success": True, "messages": [USER, REPLY], "pending_tool_count": 0, "synctoken": "t3"})],
    })
    assert driver.send("What is 2+2?", "readonly", later()).settled == "reply"
    assert [name for name, _ in driver.http.calls].count("continue_auto") == 1


def test_probe_asks_ajax_php_for_the_chat_list():
    driver = chat({"list": [FakeResponse({"success": True, "hash": "", "conversations": []}),
                            FakeResponse({"success": False, "errortype": "nopermission", "hash": ""})]})
    driver.probe()
    assert driver.http.calls[-1][0] == "list"
    with pytest.raises(DriverError, match="list"):
        driver.probe()


def test_a_course_launch_is_sent_like_the_course_page_launcher():
    driver = chat({
        "prepare_message": [FakeResponse({"success": True, "hash": "h1", "rootid": 7, "synctoken": "t1"})],
        "finish_message": [FakeResponse({"success": True, "synctoken": "t2"})],
        "load": [FakeResponse({"success": True, "messages": [USER, REPLY], "pending_tool_count": 0})],
    })
    driver.send("Hi", "readonly", later(), {"contextid": 42, "url": "http://localhost:8502/course/view.php?id=3"})
    prepare = next(body for name, body in driver.http.calls if name == "prepare_message")
    assert prepare["context"] == 42 and prepare["url"].endswith("/course/view.php?id=3")
