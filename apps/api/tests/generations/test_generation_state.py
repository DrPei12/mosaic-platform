from __future__ import annotations

import pytest

from app.generations.state import InvalidGenerationTransition, assert_transition, is_terminal


def test_production_happy_path_requires_durable_order() -> None:
    for current, target in (
        ("accepted", "reserved"),
        ("reserved", "queued"),
        ("queued", "accepted"),
        ("queued", "submitted"),
        ("submitted", "running"),
        ("running", "storing"),
        ("storing", "succeeded"),
    ):
        assert_transition(current, target)  # type: ignore[arg-type]

    assert is_terminal("succeeded")


def test_submitted_unknown_cannot_repeat_chargeable_submission() -> None:
    with pytest.raises(InvalidGenerationTransition):
        assert_transition("submitted_unknown", "submitted")


def test_terminal_jobs_cannot_be_reopened() -> None:
    with pytest.raises(InvalidGenerationTransition):
        assert_transition("succeeded", "running")
