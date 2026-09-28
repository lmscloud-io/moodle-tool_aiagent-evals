"""The evaluation configuration: Moodle branches, provider plugin sources, matrix cells, tiers and tasks."""

from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent

GRADERS = ("no_error", "reply_contains", "reply_matches", "tool_succeeded", "usage_recorded")
GRADERS_WITH_ARG = ("reply_contains", "reply_matches")
AUTOAPPROVE = ("none", "readonly", "safe", "all")

# Settings each provider plugin needs besides the model and the secrets, mirroring the shapes the plugin's
# own tests use (tests/provider_testcase.php). A cell's `config:` and `action:` entries override them.
PROVIDER_DEFAULTS: dict[str, dict[str, dict[str, Any]]] = {
    "aiprovider_openai": {"config": {}, "action": {"endpoint": "https://api.openai.com/v1/chat/completions"}},
    "aiprovider_azureai": {"config": {}, "action": {"apiversion": "2024-10-21"}},
    "aiprovider_anthropic": {"config": {}, "action": {"endpoint": "https://api.anthropic.com/v1/messages",
                                                      "maxtokens": 4096}},
    "aiprovider_claude": {"config": {"apiversion": "2023-06-01"},
                          "action": {"endpoint": "https://api.anthropic.com/v1/messages", "max_tokens": 4096}},
    "aiprovider_gemini": {"config": {}, "action": {
        "endpoint": "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"}},
    "aiprovider_openaicompatible": {"config": {}, "action": {}},
}
REQUIRED_PLUGIN_SETTINGS = {
    "aiprovider_openai": "openai_api_type",
    "aiprovider_azureai": "openai_api_type",
    "aiprovider_gemini": "gemini_api_type",
}
PROVIDER_LABELS = {
    "aiprovider_openai": "OpenAI",
    "aiprovider_azureai": "Azure OpenAI",
    "aiprovider_anthropic": "Anthropic",
    "aiprovider_claude": "Claude (third-party plugin)",
    "aiprovider_gemini": "Google Gemini",
    "aiprovider_openaicompatible": "OpenAI-compatible plugin",
}
API_LABELS = {
    ("openai_api_type", "chatcompletions"): "Chat Completions",
    ("openai_api_type", "responses"): "Responses API",
    ("gemini_api_type", "generatecontent"): "generateContent",
    ("gemini_api_type", "interactions"): "Interactions API",
}
DEFAULT_API_LABELS = {
    "aiprovider_anthropic": "Messages API",
    "aiprovider_claude": "Messages API",
    "aiprovider_openaicompatible": "Chat Completions",
}


class ConfigError(ValueError):
    """A configuration file is missing a field or holds a value the harness cannot use."""


@dataclass(frozen=True)
class MoodleVersion:
    branch: str
    git_ref: str
    php: str
    port: int

    @property
    def wwwroot(self) -> str:
        return f"http://localhost:{self.port}"


@dataclass(frozen=True)
class GitSource:
    repo: str
    branch: str


@dataclass(frozen=True)
class Cell:
    id: str
    provider: str
    model: str
    config: dict[str, Any] = field(default_factory=dict)
    action: dict[str, Any] = field(default_factory=dict)
    plugin_settings: dict[str, str] = field(default_factory=dict)
    secrets: dict[str, str] = field(default_factory=dict)
    label: str = ""

    def provider_label(self) -> str:
        return self.label or PROVIDER_LABELS[self.provider]

    def api_label(self) -> str:
        for key, value in self.plugin_settings.items():
            if (key, value) in API_LABELS:
                return API_LABELS[(key, value)]
        return DEFAULT_API_LABELS[self.provider]

    def action_settings(self) -> dict[str, Any]:
        """The generate_text action settings; Azure's model is its deployment name."""
        merged = {**PROVIDER_DEFAULTS[self.provider]["action"], **self.action}
        settings = {key: value.format(model=self.model) if isinstance(value, str) else value
                    for key, value in merged.items()}
        settings["deployment" if self.provider == "aiprovider_azureai" else "model"] = self.model
        return settings

    def provider_config(self) -> dict[str, Any]:
        """Provider-level settings without the secrets, which the site adds from the environment."""
        return {**PROVIDER_DEFAULTS[self.provider]["config"], **self.config}


@dataclass(frozen=True)
class Tier:
    name: str
    moodle: str
    cells: tuple[str, ...]
    trials: int


@dataclass(frozen=True)
class Grader:
    name: str
    arg: Any = None
    turn: int | None = None


@dataclass(frozen=True)
class TaskSpec:
    id: str
    description: str
    tiers: tuple[str, ...]
    user: str
    turns: tuple[str, ...]
    graders: tuple[Grader, ...]
    launch: Any = "fullscreen"
    autoapprove: str = "readonly"
    budget_seconds: int = 600
    mutates: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskSpec":
        values = dict(data)
        values["tiers"] = tuple(values["tiers"])
        values["turns"] = tuple(values["turns"])
        values["graders"] = tuple(Grader(**grader) for grader in values["graders"])
        return cls(**values)


def load_env(path: Path = ROOT / ".env") -> None:
    """Read KEY=value lines from .env into the environment, never overriding what is already set."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def _read_yaml(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def load_versions(path: Path = ROOT / "moodle.yaml") -> dict[str, MoodleVersion]:
    return {str(branch): MoodleVersion(str(branch), entry["git_ref"], str(entry["php"]), int(entry["port"]))
            for branch, entry in _read_yaml(path).items()}


def load_provider_sources(path: Path = ROOT / "providers.yaml") -> dict[str, dict[str, Any]]:
    return {component: {str(key): value for key, value in entry.items()}
            for component, entry in _read_yaml(path).items()}


def provider_source(sources: dict[str, dict[str, Any]], component: str, branch: str) -> str | GitSource | None:
    """How a provider plugin reaches a branch: "core", a GitSource to clone, "skip" when it is deliberately
    not tested there, or None when no plugin exists for that branch."""
    if component not in sources:
        raise ConfigError(f"providers.yaml has no entry for {component}")
    entry = sources[component]
    if branch in entry:
        value = entry[branch]
    elif "default" in entry:
        value = entry["default"]
    else:
        raise ConfigError(f"providers.yaml says nothing about {component} on {branch}")
    if value is None or value in ("core", "skip"):
        return value
    return GitSource(str(value["repo"]), str(value["branch"]))


def load_matrix(path: Path = ROOT / "matrix.yaml") -> tuple[list[Cell], dict[str, Tier]]:
    data = _read_yaml(path)
    cells = [_cell(entry) for entry in data["cells"]]
    ids = [cell.id for cell in cells]
    if len(set(ids)) != len(ids):
        raise ConfigError("matrix.yaml has duplicate cell ids")
    tiers = {}
    for name, entry in data["tiers"].items():
        listed = ids if entry["cells"] == "all" else [str(cell) for cell in entry["cells"]]
        unknown = sorted(set(listed) - set(ids))
        if unknown:
            raise ConfigError(f"tier {name} names unknown cells: {', '.join(unknown)}")
        if entry["moodle"] not in ("supported", "newest"):
            raise ConfigError(f"tier {name}: moodle must be 'supported' or 'newest'")
        tiers[name] = Tier(name, entry["moodle"], tuple(listed), int(entry["trials"]))
    return cells, tiers


def _cell(entry: dict[str, Any]) -> Cell:
    for key in ("id", "provider", "model"):
        if not entry.get(key):
            raise ConfigError(f"a matrix cell is missing '{key}': {entry}")
    if entry["provider"] not in PROVIDER_DEFAULTS:
        raise ConfigError(f"cell {entry['id']}: unknown provider {entry['provider']}")
    cell = Cell(
        id=str(entry["id"]),
        provider=str(entry["provider"]),
        model=str(entry["model"]),
        config=dict(entry.get("config") or {}),
        action=dict(entry.get("action") or {}),
        plugin_settings={str(k): str(v) for k, v in (entry.get("plugin_settings") or {}).items()},
        secrets={str(k): str(v) for k, v in (entry.get("secrets") or {}).items()},
        label=str(entry.get("label") or ""),
    )
    required = REQUIRED_PLUGIN_SETTINGS.get(cell.provider)
    if required and required not in cell.plugin_settings:
        raise ConfigError(f"cell {cell.id}: {cell.provider} needs plugin_settings.{required}")
    if "apikey" not in cell.secrets:
        raise ConfigError(f"cell {cell.id}: secrets.apikey is required")
    return cell


def load_tasks(directory: Path = ROOT / "tasks") -> list[TaskSpec]:
    tasks = [_task(path) for path in sorted(directory.glob("*.yaml"))]
    ids = [task.id for task in tasks]
    if len(set(ids)) != len(ids):
        raise ConfigError("two task files share an id")
    return tasks


def _task(path: Path) -> TaskSpec:
    data = _read_yaml(path) or {}
    for key in ("id", "description", "tiers", "user", "turns", "graders"):
        if not data.get(key):
            raise ConfigError(f"{path.name}: '{key}' is required")
    autoapprove = str(data.get("autoapprove", "readonly"))
    if autoapprove not in AUTOAPPROVE:
        raise ConfigError(f"{path.name}: autoapprove must be one of {', '.join(AUTOAPPROVE)}")
    return TaskSpec(
        id=str(data["id"]),
        description=str(data["description"]),
        tiers=tuple(str(tier) for tier in data["tiers"]),
        user=str(data["user"]),
        turns=tuple(str(turn) for turn in data["turns"]),
        graders=tuple(_grader(path, grader) for grader in data["graders"]),
        launch=data.get("launch", "fullscreen"),
        autoapprove=autoapprove,
        budget_seconds=int(data.get("budget_seconds", 600)),
        mutates=bool(data.get("mutates", False)),
    )


def _grader(path: Path, entry: Any) -> Grader:
    if isinstance(entry, str):
        name, arg, turn = entry, None, None
    elif isinstance(entry, dict):
        turn = entry.get("turn")
        names = [key for key in entry if key != "turn"]
        if len(names) != 1:
            raise ConfigError(f"{path.name}: a grader entry names exactly one grader: {entry}")
        name, arg = names[0], entry[names[0]]
    else:
        raise ConfigError(f"{path.name}: cannot read the grader {entry!r}")
    if name not in GRADERS:
        raise ConfigError(f"{path.name}: unknown grader '{name}'")
    if name in GRADERS_WITH_ARG and arg is None:
        raise ConfigError(f"{path.name}: grader '{name}' needs an argument")
    if name not in GRADERS_WITH_ARG and arg is not None:
        raise ConfigError(f"{path.name}: grader '{name}' takes no argument")
    return Grader(name, arg, int(turn) if turn is not None else None)


def supported_branches(version_php: str, versions: dict[str, MoodleVersion]) -> list[str]:
    match = re.search(r"\$plugin->supported\s*=\s*\[\s*(\d+)\s*,\s*(\d+)\s*\]", version_php)
    if not match:
        raise ConfigError("the build's version.php declares no $plugin->supported range")
    low, high = int(match[1]), int(match[2])
    return [branch for branch in sorted(versions, key=int) if low <= int(branch) <= high]


def plugin_release(version_php: str) -> str:
    match = re.search(r"\$plugin->release\s*=\s*'([^']+)'", version_php)
    return match[1] if match else "unknown"
