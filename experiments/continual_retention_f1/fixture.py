from __future__ import annotations

import random
from dataclasses import dataclass

from .contracts import RawObservation


@dataclass(frozen=True)
class EpisodeConfig:
    blocks_per_phase: int = 4
    contexts: int = 8
    actions: int = 4
    max_extra_blocks: int = 2
    correction_lag: int = 2


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
    phase_lengths: tuple[int, int, int]
    corrupted_turn: int
    correction_delivery_turn: int


class EvaluatorFixture:
    @staticmethod
    def build(seed: int, config: EpisodeConfig = EpisodeConfig()) -> EpisodePlan:
        if config.contexts != 8 or config.actions != 4 or config.blocks_per_phase < 2:
            raise ValueError(
                "qualification fixture requires 8 contexts, 4 actions, >=2 blocks"
            )
        rng = random.Random(seed)
        dims = [f"f-{rng.getrandbits(64):016x}" for _ in range(config.contexts)]
        vals = [f"v-{rng.getrandbits(64):016x}" for _ in range(config.contexts)]
        actions = [f"a-{rng.getrandbits(64):016x}" for _ in range(config.actions)]
        changed = tuple(
            sorted(rng.sample(range(config.contexts), config.contexts // 2))
        )
        unchanged = tuple(
            index for index in range(config.contexts) if index not in changed
        )
        a_truth = {index: index % config.actions for index in range(config.contexts)}
        derangement = list(range(config.actions))
        rng.shuffle(derangement)
        if any(index == value for index, value in enumerate(derangement)):
            derangement = [
                (index + 1) % config.actions for index in range(config.actions)
            ]
        b_truth = {
            index: derangement[a_truth[index]] if index in changed else a_truth[index]
            for index in range(config.contexts)
        }
        public: list[PublicStep] = []
        latent: list[LatentStep] = []
        phase_lengths: list[int] = []
        for phase in ("A1", "B", "A2"):
            truth = b_truth if phase == "B" else a_truth
            blocks = config.blocks_per_phase + rng.randint(0, config.max_extra_blocks)
            phase_contexts = list(range(config.contexts))
            phase_contexts.extend(
                rng.randrange(config.contexts)
                for _ in range(blocks * config.contexts - config.contexts)
            )
            rng.shuffle(phase_contexts)
            phase_lengths.append(len(phase_contexts))
            for context in phase_contexts:
                observation = RawObservation(
                    ((dims[context], vals[context]),), tuple(actions)
                )
                public.append(PublicStep(observation))
                latent.append(
                    LatentStep(
                        phase,
                        context,
                        actions[truth[context]],
                        rng.random(),
                    )
                )
        a1_length = phase_lengths[0]
        corrupted_turn = rng.randrange(max(1, a1_length // 3), max(2, a1_length - 4))
        correction_delivery_turn = corrupted_turn + 2 + config.correction_lag
        return EpisodePlan(
            tuple(public),
            tuple(latent),
            changed,
            unchanged,
            (phase_lengths[0], phase_lengths[1], phase_lengths[2]),
            corrupted_turn,
            correction_delivery_turn,
        )
