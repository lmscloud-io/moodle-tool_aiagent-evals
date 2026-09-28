"""The Inspect task for one tier: its samples are the task files that belong to the tier."""

from __future__ import annotations

from inspect_ai import Epochs, Task
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.scorer import mean_score, pass_k

from .config import TaskSpec, Tier
from .scorers import graded
from .solver import moodle_conversation


def build_task(tier: Tier, tasks: list[TaskSpec]) -> Task:
    samples = [Sample(input=spec.turns[0], id=spec.id, metadata={"task": spec.to_dict()})
               for spec in tasks if tier.name in spec.tiers]
    if not samples:
        raise ValueError(f"no task belongs to the {tier.name} tier")
    return Task(
        name=f"aiagent-{tier.name}",
        dataset=MemoryDataset(samples),
        solver=moodle_conversation(),
        scorer=graded(),
        epochs=Epochs(tier.trials, [pass_k(tier.trials), mean_score()]),
    )
