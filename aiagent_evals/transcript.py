"""One trial's record: what the chat UI showed (the `load` payload) plus the chat's usage rows."""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any

from inspect_ai.model import ChatMessage, ChatMessageAssistant, ChatMessageTool, ChatMessageUser
from inspect_ai.tool import ToolCall, ToolCallError

SUCCEEDED = "succeeded"   # constants::TOOL_STATUS_SUCCEEDED in the plugin.
FAILED = "failed"
DENIED = "denied"
RATE_LIMIT = re.compile(r"rate.?limit|too many requests|\b429\b|quota", re.IGNORECASE)
_BLOCK_TAGS = {"p", "div", "br", "li", "ul", "ol", "pre", "table", "tr", "blockquote",
               "h1", "h2", "h3", "h4", "h5", "h6"}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def html_to_text(markup: str) -> str:
    """The text of the HTML the chat renders: tags dropped, entities decoded, blank lines removed."""
    parser = _TextExtractor()
    parser.feed(markup or "")
    parser.close()
    lines = (" ".join(line.split()) for line in "".join(parser.parts).splitlines())
    return "\n".join(line for line in lines if line)


@dataclass
class Turn:
    settled: str    # reply | error | pending_approval | timeout
    seconds: float


@dataclass
class Transcript:
    chat_hash: str
    entries: list[dict[str, Any]]
    usage: list[dict[str, Any]] = field(default_factory=list)
    turns: list[Turn] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"chat_hash": self.chat_hash, "entries": self.entries, "usage": self.usage,
                "turns": [{"settled": turn.settled, "seconds": turn.seconds} for turn in self.turns]}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Transcript":
        return cls(str(data["chat_hash"]), list(data["entries"]), list(data.get("usage") or []),
                   [Turn(str(turn["settled"]), float(turn["seconds"])) for turn in data.get("turns") or []])

    def turn_entries(self, turn: int | None = None) -> list[dict[str, Any]]:
        """Entries of one turn (1-based), from its user message up to the next; the last turn when None."""
        starts = [index for index, entry in enumerate(self.entries) if entry.get("role") == "user"]
        number = len(starts) if turn is None else turn
        if not 1 <= number <= len(starts):
            return []
        end = starts[number] if number < len(starts) else len(self.entries)
        return self.entries[starts[number - 1]:end]

    def _scope(self, turn: int | None) -> list[dict[str, Any]]:
        return self.entries if turn is None else self.turn_entries(turn)

    def final_reply(self, turn: int | None = None) -> str:
        """Text of the turn's last reply that is not an error bubble; empty when there is none."""
        for entry in reversed(self.turn_entries(turn)):
            if entry.get("role") == "assistant" and not entry.get("iserror"):
                return html_to_text(str(entry.get("content", "")))
        return ""

    def errors(self, turn: int | None = None) -> list[str]:
        """Text of every error bubble, found by the payload's iserror flag and never by wording."""
        return [html_to_text(str(entry.get("content", ""))) for entry in self._scope(turn)
                if entry.get("role") == "assistant" and entry.get("iserror")]

    def tool_results(self, turn: int | None = None) -> list[dict[str, Any]]:
        return [result for entry in self._scope(turn) if entry.get("role") == "tool"
                for result in entry.get("results") or []]

    def tokens(self) -> tuple[int, int]:
        return (sum(int(row.get("prompttokens") or 0) for row in self.usage),
                sum(int(row.get("completiontokens") or 0) for row in self.usage))

    def rate_limited(self) -> bool:
        return any(RATE_LIMIT.search(text) for text in self.errors())

    def to_inspect_messages(self) -> list[ChatMessage]:
        """The chat as Inspect messages, so its viewer shows function calls and their results natively."""
        messages: list[ChatMessage] = []
        for entry in self.entries:
            role = entry.get("role")
            if role == "user":
                messages.append(ChatMessageUser(content=html.unescape(str(entry.get("content", "")))))
            elif role == "assistant":
                text = html_to_text(str(entry.get("content", "")))
                messages.append(ChatMessageAssistant(content=f"[error bubble] {text}" if entry.get("iserror") else text))
            elif role == "tool_call":
                calls = [ToolCall(id=str(tool.get("id", "")), function=str(tool.get("name", "")),
                                  arguments=_arguments(tool.get("arguments")))
                         for tool in entry.get("tools") or []]
                messages.append(ChatMessageAssistant(content="", tool_calls=calls))
            elif role == "tool":
                for result in entry.get("results") or []:
                    messages.append(ChatMessageTool(
                        content=_text(result.get("result")),
                        tool_call_id=str(result.get("tool_call_id", "")),
                        function=str(result.get("name", "")),
                        error=_error(str(result.get("status", "")), bool(entry.get("denied"))),
                    ))
        return messages


def _arguments(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value:
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return {"raw": value}
        return decoded if isinstance(decoded, dict) else {"value": decoded}
    return {}


def _text(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value)


def _error(status: str, denied: bool) -> ToolCallError | None:
    if status == DENIED or denied:
        return ToolCallError("approval", "The user denied the function call.")
    if status == FAILED:
        return ToolCallError("unknown", "The function call failed.")
    return None
