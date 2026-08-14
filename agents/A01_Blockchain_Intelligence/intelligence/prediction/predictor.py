"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.prediction.predictor

Purpose:
    Central prediction orchestrator.
"""

from __future__ import annotations

from typing import Any, Callable

from ..schemas.prediction import Prediction
from ..utils.helpers import new_id


class Predictor:
    """
    Runs registered prediction models over a subject.
    """

    def __init__(self) -> None:
        self._models: dict[str, Callable[..., Prediction]] = {}

    def register(self, name: str, model: Callable[..., Prediction]) -> "Predictor":
        """
        Register a named prediction model.
        """
        self._models[name] = model
        return self

    def predict(self, metric: str, subject: dict[str, Any], **kwargs: Any) -> Prediction:
        """
        Run the model for the given metric.
        """
        model = self._models.get(metric)
        if model is None:
            raise ValueError(f"no prediction model for metric: {metric}")
        prediction = model(subject, **kwargs)
        return prediction
