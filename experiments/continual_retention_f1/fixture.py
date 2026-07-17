from __future__ import annotations

import random
from dataclasses import dataclass

from .contracts import RawObservation


@dataclass(frozen=True)
class EpisodeConfig:
    blocks_per_phase: int = 4
    contexts: int = 8
    actions: int = 4


@dataclass(frozen=True)
class PublicStep:
    observation: RawObservation


@dataclass(frozen=True)
class LatentStep:
    phase: str
    context_index: int
    optimal_action: str
    reward_draw: float


@dataclass(frozen=True)
class EpisodePlan:
    public_steps: tuple[PublicStep, ...]
    latent_steps: tuple[LatentStep, ...]
    changed_contexts: tuple[int, ...]
    unchanged_contexts: tuple[int, ...]


class EvaluatorFixture:
    @staticmethod
    def build(seed: int, config: EpisodeConfig = EpisodeConfig()) -> EpisodePlan:
        if config.contexts != 8 or config.actions != 4:
            raise ValueError(
                "qualification fixture is fixed at 8 contexts and 4 actions"
            )
        rng = random.Random(seed)
        dims = [f"f-{rng.getrandbits(64):016x}" for _ in range(8)]
        vals = [f"v-{rng.getrandbits(64):016x}" for _ in range(8)]
        actions = [f"a-{rng.getrandbits(64):016x}" for _ in range(4)]
        changed = tuple(sorted(rng.sample(range(8), 4)))
        unchanged = tuple(i for i in range(8) if i not in changed)
        a_truth = {i: i % 4 for i in range(8)}
        b_truth = {i: ((i + 1) % 4 if i in changed else i % 4) for i in range(8)}
        public: list[PublicStep] = []
        latent: list[LatentStep] = []
        for phase in ("A1", "B", "A2"):
            truth = b_truth if phase == "B" else a_truth
            for _ in range(config.blocks_per_phase):
                order = list(range(8))
                rng.shuffle(order)
                for context in order:
                    observation = RawObservation(
                        ((dims[context], vals[context]),), tuple(actions)
                    )
                    public.append(PublicStep(observation))
                    latent.append(
                        LatentStep(
                            phase, context, actions[truth[context]], rng.random()
                        )
                    )
        return EpisodePlan(tuple(public), tuple(latent), changed, unchanged)
