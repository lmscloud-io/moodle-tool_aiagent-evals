"""What the solver needs about the site under test. The runner sets `current` before each eval() call:
solver arguments would be written into the Inspect log, and these include passwords and a callable."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass
class RunContext:
    wwwroot: str
    passwords: dict[str, str]
    usage: Callable[[str], list[dict]]
    launches: dict[str, dict] = field(default_factory=dict)


current: RunContext | None = None
