"""Evaluator-only ceiling; deliberately absent from the public arm factory."""

from .fixture import LatentStep


class OracleCeiling:
    @staticmethod
    def action(latent_step: LatentStep) -> str:
        return latent_step.optimal_action
