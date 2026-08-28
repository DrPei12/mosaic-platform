"""Compare-and-swap state machine for durable generation jobs."""

from __future__ import annotations

from typing import Final

from app.contracts.generations import GenerationStatus

TERMINAL_STATUSES: Final[frozenset[GenerationStatus]] = frozenset(
    {"succeeded", "failed", "cancelled", "expired"}
)

# Submission is deliberately one-way.  In particular, submitted_unknown has
# no transition back to submitted: a worker must reconcile the provider task
# or fail closed instead of blindly repeating a chargeable POST.
ALLOWED_TRANSITIONS: Final[dict[GenerationStatus, frozenset[GenerationStatus]]] = {
    "accepted": frozenset({"reserved", "failed", "cancelled", "expired"}),
    "reserved": frozenset({"queued", "failed", "cancelled", "expired"}),
    # Admission saturation is the only non-terminal path back to accepted:
    # the acceptance hold remains attached, but no Provider call exists yet.
    "queued": frozenset({"accepted", "submitted", "failed", "cancelled", "expired"}),
    "submitted": frozenset({"running", "submitted_unknown", "failed", "cancelled"}),
    "submitted_unknown": frozenset({"running", "failed", "cancelled", "expired"}),
    "running": frozenset({"storing", "succeeded", "failed", "cancelled", "expired"}),
    "storing": frozenset({"succeeded", "failed", "expired"}),
    "succeeded": frozenset(),
    "failed": frozenset(),
    "cancelled": frozenset(),
    "expired": frozenset(),
}


class InvalidGenerationTransition(ValueError):
    """Raised before a CAS update for an impossible state transition."""


def assert_transition(current: GenerationStatus, target: GenerationStatus) -> None:
    if target not in ALLOWED_TRANSITIONS[current]:
        raise InvalidGenerationTransition(f"cannot transition {current} to {target}")


def is_terminal(status: GenerationStatus) -> bool:
    return status in TERMINAL_STATUSES


__all__ = [
    "ALLOWED_TRANSITIONS",
    "TERMINAL_STATUSES",
    "InvalidGenerationTransition",
    "assert_transition",
    "is_terminal",
]
