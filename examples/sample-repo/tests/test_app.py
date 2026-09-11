"""pytest suite for the sample repo — this is what Alfred runs inside both
containers. Keep it dependency-light so it passes on baseline and candidate."""

from __future__ import annotations

import importlib

import pytest

from knowledge_base import answer_question


def test_refund_answer():
    assert "30 days" in answer_question("What is your refund policy?")


def test_hours_answer():
    assert "9am-5pm" in answer_question("What are your business hours?")


def test_unknown_question_is_honest():
    answer = answer_question("Do you ship to Mars?")
    assert "don't have that answer" in answer


def test_answer_is_deterministic():
    assert answer_question("refund") == answer_question("refund")


def test_knowledge_base_importable():
    import knowledge_base

    importlib.reload(knowledge_base)
    assert callable(knowledge_base.answer_question)


@pytest.mark.parametrize(
    "msg,fragment",
    [
        ("refund please", "30 days"),
        ("business hours?", "9am-5pm"),
        ("shipping time", "3-5 business days"),
    ],
)
def test_lookup_fragments(msg, fragment):
    assert fragment in answer_question(msg)
