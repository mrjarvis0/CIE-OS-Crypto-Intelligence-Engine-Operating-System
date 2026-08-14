"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.narrative.provider

Purpose:
    The seam a language model plugs into, built so that plugging one in cannot
    bypass the grounding check.

Design goals:
    - One publication path; a model's text reaches a reader only through it
    - Model identity, seed and temperature recorded, per evidence-standard §6
    - Untrusted evidence fenced before it reaches a prompt
    - Deterministic fallback when a model is absent, blocked, or failing
    - No provider configured today, and nothing pretends otherwise

Notes:
    A01 has no model configured. Building this now is not speculative
    scaffolding — it is the only moment the constraint can be written down for
    free. Once a model is wired in and someone needs a narrative shipped, the
    grounding check becomes the thing standing between them and a demo, and
    "just this once" is how it acquires a bypass. Making the checked path the
    *only* path, before there is pressure, costs nothing now.

    So :class:`NarrativeService` owns publication and providers only propose.
    A provider returns candidate text; the service grounds it, and on failure
    falls back to the composer rather than publishing a hedged version. A
    fluent narrative that asserts a fabricated address is not improved by
    qualifying it.

    Evidence reaching a prompt is fenced through :mod:`prompts.fencing` first.
    Chain data is attacker-controlled — anyone can write a contract whose name
    is an instruction, or send a transaction with a memo aimed at a model — so
    it is untrusted input by definition, not a formatting concern.
"""

from __future__ import annotations

import logging

from dataclasses import dataclass, field
from typing import Any, Protocol, Sequence, runtime_checkable

from .composer import Narrative, NarrativeComposer
from .grounding import GroundingCheck, GroundingReport

logger = logging.getLogger("a01.intelligence.narrative")


@dataclass(frozen=True, slots=True)
class ModelIdentity:
    """
    What produced a narrative, recorded so a claim can be traced to a run.

    Required by evidence-standard.md §6: model reasoning carries
    ``method: "<model-id>@<version>"`` and ``reproducibility: stochastic`` with
    the seed and temperature recorded. Without those a disputed narrative
    cannot be reproduced, and an irreproducible claim cannot be examined.
    """

    model_id: str
    version: str = "unknown"
    temperature: float | None = None
    seed: int | None = None

    @property
    def method(self) -> str:
        return f"{self.model_id}@{self.version}"

    @property
    def reproducibility(self) -> str:
        """
        Stochastic unless the sampling parameters pin it.

        Temperature zero with a fixed seed is reproducible in principle; a
        provider that cannot state both is not, and must say so.
        """
        if self.temperature == 0.0 and self.seed is not None:
            return "deterministic"
        return "stochastic"

    def as_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "reproducibility": self.reproducibility,
            "temperature": self.temperature,
            "seed": self.seed,
        }


@runtime_checkable
class NarrativeProvider(Protocol):
    """
    What a model integration must implement.

    Deliberately narrow. A provider receives an already-composed narrative and
    the evidence, and may return a better-written version — it does not receive
    the raw chain data, does not choose what to say, and cannot reach a reader
    without passing the grounding check.
    """

    identity: ModelIdentity

    def rewrite(self, draft: Narrative, evidence: Sequence[Any]) -> str:
        """Return improved prose for ``draft``, or raise."""
        ...


@dataclass(frozen=True, slots=True)
class Publication:
    """
    A narrative cleared for a reader, and the record of how it got there.

    ``fell_back`` distinguishes "the model wrote this" from "the model's text
    was rejected and the composer's was used". A reader comparing two reports
    should be able to tell.
    """

    narrative: Narrative
    grounding: GroundingReport | None = None
    identity: ModelIdentity | None = None
    fell_back: bool = False
    fallback_reason: str = ""

    @property
    def model_authored(self) -> bool:
        return self.identity is not None and not self.fell_back

    def as_dict(self) -> dict[str, Any]:
        return {
            "narrative": self.narrative.as_dict(),
            "model_authored": self.model_authored,
            "fell_back": self.fell_back,
            "fallback_reason": self.fallback_reason,
            "identity": self.identity.as_dict() if self.identity else None,
            "grounding": self.grounding.as_dict() if self.grounding else None,
        }


class NarrativeService:
    """
    The only path from a decision to published prose.

    Composes deterministically, optionally asks a provider to improve the
    wording, grounds whatever comes back, and falls back when it fails. A
    caller cannot skip a step, because there is no method that performs one of
    them alone.
    """

    def __init__(
        self,
        *,
        provider: NarrativeProvider | None = None,
        composer: NarrativeComposer | None = None,
        grounding: GroundingCheck | None = None,
    ) -> None:
        self._provider = provider
        self._composer = composer if composer is not None else NarrativeComposer()
        self._grounding = grounding if grounding is not None else GroundingCheck()

    @property
    def provider(self) -> NarrativeProvider | None:
        return self._provider

    @property
    def model_configured(self) -> bool:
        return self._provider is not None

    def publish(self, decision: Any, *, evidence: Sequence[Any] = ()) -> Publication:
        """
        Produce the narrative a reader sees.

        The composed draft is always built first. It is the answer when there is
        no provider, and the fallback when there is one and its output does not
        ground — so there is no path on which a failure produces no explanation.
        """
        draft = self._composer.compose(decision, evidence=evidence)

        if self._provider is None:
            return Publication(narrative=draft)

        identity = self._provider.identity
        try:
            candidate = self._provider.rewrite(draft, evidence)
        except Exception as exc:  # noqa: BLE001 - provider boundary
            logger.warning("narrative provider %s failed: %s", identity.method, exc)
            return Publication(
                narrative=draft,
                identity=identity,
                fell_back=True,
                fallback_reason=f"provider error: {exc}",
            )

        report = self._grounding.check(candidate, self._corpus(decision, evidence))
        if not report.publishable:
            # Not softened, not redacted. A fluent narrative asserting a
            # fabricated particular is not improved by hedging it.
            logger.warning(
                "narrative from %s rejected: %s", identity.method, report.reason()
            )
            return Publication(
                narrative=draft,
                grounding=report,
                identity=identity,
                fell_back=True,
                fallback_reason=report.reason(),
            )

        return Publication(
            narrative=Narrative(
                text=candidate,
                cites=report.cited,
                method=identity.method,
                reproducibility=identity.reproducibility,
            ),
            grounding=report,
            identity=identity,
        )

    @staticmethod
    def _corpus(decision: Any, evidence: Sequence[Any]) -> list[Any]:
        """
        Everything a narrator is permitted to state, as a grounding corpus.

        Not just the chain evidence. A narrative legitimately mentions figures
        the *system* produced — a confidence, a coverage threshold, the number
        of blocks stored — and none of those are observations of a chain. They
        are not invented either: the decision computed them, and a narrator
        repeating one has fabricated nothing.

        Grounding against evidence alone would therefore reject the composer's
        own correct output, which would teach a caller to disable the check.
        The rule is "state only what the decision or the evidence contains",
        and this is that set.
        """
        corpus: list[Any] = list(evidence)
        as_dict = getattr(decision, "as_dict", None)
        if callable(as_dict):
            corpus.append({"claim": "decision", "data": as_dict()})
        return corpus

    def prompt_context(self, evidence: Sequence[Any]) -> str:
        """
        Evidence rendered for a prompt, fenced against injection.

        Chain data is attacker-controlled: a contract can be named after an
        instruction and a transaction can carry a memo written at a model. It
        is untrusted input, and fencing is the boundary that says so.
        """
        from prompts.fencing import fence

        rendered = "\n".join(
            str(getattr(item, "claim", item)) for item in evidence
        )
        return fence(rendered).text

    def health(self) -> dict[str, Any]:
        return {
            "model_configured": self.model_configured,
            "provider": (
                self._provider.identity.as_dict() if self._provider else None
            ),
            "grounding": "enforced",
            "note": (
                "No model is configured. Narratives are composed "
                "deterministically and are grounded by construction."
            ),
        }

    def __repr__(self) -> str:
        return f"NarrativeService(model_configured={self.model_configured})"


__all__ = [
    "ModelIdentity",
    "NarrativeProvider",
    "NarrativeService",
    "Publication",
]
