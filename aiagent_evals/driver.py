"""Drive a chat through ajax.php with the requests the chat UI sends: log in, then prepare, finish, continue."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any

import requests

LOGINTOKEN = re.compile(r'name="logintoken" value="([^"]+)"')
SESSKEY = re.compile(r'"sesskey":"([^"]+)"')
MAX_HANDOFFS = 20


class DriverError(RuntimeError):
    """The site or the harness failed, not the agent. Inspect retries such a trial and never scores it."""


@dataclass
class TurnResult:
    settled: str    # reply | error | pending_approval | timeout
    seconds: float
    payload: dict[str, Any] = field(default_factory=dict)


class MoodleChat:
    """One user's chat on one site, driven with the requests chat_actions.js and chat_ajax.js send."""

    def __init__(self, wwwroot: str, username: str, password: str, session: Any = None) -> None:
        self.wwwroot = wwwroot.rstrip("/")
        self.username = username
        self.password = password
        self.http = session if session is not None else requests.Session()
        self.sesskey = ""
        self.hash = ""
        self.synctoken = ""
        self._resumed: Any = None

    def login(self) -> None:
        """Log in through the login form, then read the sesskey from the chat page, as a browser would."""
        page = self.http.get(f"{self.wwwroot}/login/index.php", timeout=60)
        token = LOGINTOKEN.search(page.text)
        if not token:
            raise DriverError("the login page carries no logintoken")
        self.http.post(f"{self.wwwroot}/login/index.php", timeout=60,
                       data={"username": self.username, "password": self.password, "logintoken": token.group(1)})
        chat = self.http.get(f"{self.wwwroot}/admin/tool/aiagent/chat.php", timeout=60)
        sesskey = SESSKEY.search(chat.text)
        if chat.status_code != 200 or not sesskey or LOGINTOKEN.search(chat.text):
            raise DriverError(f"could not log in as {self.username} and open the chat page")
        self.sesskey = sesskey.group(1)

    def send(self, message: str, autoapprove: str, deadline: float,
             launch: dict[str, Any] | None = None) -> TurnResult:
        """Send one user message and follow the turn until it settles or the deadline passes."""
        started = time.monotonic()
        launch = launch or {}
        try:
            prep = self._action("prepare_message", {
                "message": message, "draftitemid": 0, "autoapprove": autoapprove, "skill": "",
                "placement": 0, "clonefrom": "", "context": int(launch.get("contextid", 0)),
                "url": str(launch.get("url", "")), "pageurl": "", "pagetitle": "", "pagecontextid": 0,
            }, deadline)
            if not prep.get("success"):
                raise DriverError(f"prepare_message was refused: {prep.get('errortype')} {prep.get('errormessage', '')}")
            self.hash = str(prep.get("hash") or self.hash)
            result = self._action("finish_message", {"rootid": prep["rootid"]}, deadline)
            handoffs = 0
            while result.get("success") and self._needs_continue(result):
                handoffs += 1
                if handoffs > MAX_HANDOFFS:
                    raise DriverError(f"the turn handed back continue_auto more than {MAX_HANDOFFS} times")
                result = self._action("continue_auto", {"pagecaptures": {}}, deadline)
        except requests.Timeout:
            return TurnResult("timeout", time.monotonic() - started)
        state = self.load()
        return TurnResult(self._classify(state), time.monotonic() - started, state)

    def load(self) -> dict[str, Any]:
        """The chat as the UI loads it: every message, the pending batch count, the sync token."""
        return self._action("load", {}, time.monotonic() + 60)

    def probe(self) -> None:
        """Ask ajax.php for the chat list, the cheapest request that proves it answers this user."""
        if not self._action("list", {}, time.monotonic() + 60).get("success"):
            raise DriverError(f"ajax.php refused to list the chats of {self.username}")

    def _needs_continue(self, result: dict[str, Any]) -> bool:
        """The client's two ways on: an explicit continue_auto hand-off, or a resumable batch not yet resumed."""
        if result.get("continue_auto"):
            self._resumed = result.get("messageid") or self._resumed
            return True
        pending = result.get("resume_auto_messageid")
        if result.get("resume_auto") and pending and pending != self._resumed:
            self._resumed = pending
            return True
        return False

    @staticmethod
    def _classify(state: dict[str, Any]) -> str:
        messages = state.get("messages") or []
        if messages and messages[-1].get("role") == "assistant" and messages[-1].get("iserror"):
            return "error"
        if int(state.get("pending_tool_count") or 0) > 0:
            return "pending_approval"
        return "reply"

    def _action(self, action: str, body: dict[str, Any], deadline: float) -> dict[str, Any]:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise requests.Timeout(f"no time left for {action}")
        response = self.http.post(
            f"{self.wwwroot}/admin/tool/aiagent/ajax.php",
            params={"sesskey": self.sesskey, "action": action},
            json={"hash": self.hash, "synctoken": self.synctoken, **body},
            timeout=remaining,
        )
        try:
            payload = response.json()
        except ValueError as error:
            raise DriverError(f"{action} answered HTTP {response.status_code} with non-JSON: {response.text[:300]!r}") from error
        if response.status_code != 200 or not isinstance(payload, dict):
            raise DriverError(f"{action} answered HTTP {response.status_code}")
        if payload.get("errortype") == "outofsync":
            raise DriverError(f"{action} was refused as out of sync: the driver lost track of the chat")
        if payload.get("synctoken"):
            self.synctoken = str(payload["synctoken"])
        return payload
