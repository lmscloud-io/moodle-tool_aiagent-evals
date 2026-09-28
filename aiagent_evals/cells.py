"""Matrix cells as Inspect models, so logs and the viewer group results by cell (moodle/<cell id>)."""

from __future__ import annotations

from typing import Any

from inspect_ai.model import ChatMessage, GenerateConfig, ModelAPI, ModelOutput
from inspect_ai.tool import ToolChoice, ToolInfo


class MoodleCellAPI(ModelAPI):
    """Names a matrix cell. The agent under test runs inside Moodle and the moodle_conversation solver
    drives it directly, so nothing may ask this API to generate."""

    def __init__(self, model_name: str, base_url: str | None = None, api_key: str | None = None,
                 api_key_vars: list[str] = [], config: GenerateConfig = GenerateConfig(),
                 **model_args: Any) -> None:
        super().__init__(model_name, base_url, api_key, api_key_vars, config)

    async def generate(self, input: list[ChatMessage], tools: list[ToolInfo], tool_choice: ToolChoice,
                       config: GenerateConfig) -> ModelOutput:
        raise RuntimeError(f"moodle/{self.model_name} is driven by the moodle_conversation solver; "
                           "nothing may call generate()")
