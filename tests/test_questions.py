from __future__ import annotations

import pytest
from agent.questions import (
    apply_safe_defaults,
    calculate_brief_completion,
    calculate_priority,
    select_questions,
)

def test_priority_calculation():
    # Missing field score: impact * uncertainty(1.0) * blocking
    score_duration = calculate_priority("duration_seconds", confidence=0.0, is_missing=True, is_conflict=False)
    # duration has impact 5, blocking True (2) -> 5 * 1.0 * 2 = 10.0
    assert score_duration == 10.0

    # Conflict items should get top priority (+100.0)
    score_conflict = calculate_priority("duration_seconds", confidence=0.5, is_missing=False, is_conflict=True)
    assert score_conflict > 100.0

def test_select_questions_filtering_known():
    # 18.1: If already specified 45s vertical no dialogue, do not ask duration, aspect ratio, dialogue
    known = {
        "duration_seconds": 45,
        "aspect_ratio": "9:16",
        "dialogue_mode": "none",
        "logline": "45秒竖屏无对白动作短片",
    }
    confidence = {
        "duration_seconds": 1.0,
        "aspect_ratio": 1.0,
        "dialogue_mode": 1.0,
    }
    questions = select_questions(known, conflicts=[], confidence=confidence, asked_fields=set(), max_questions=3)

    asked_fields = [q.field for q in questions]
    assert "duration_seconds" not in asked_fields
    assert "aspect_ratio" not in asked_fields
    assert "dialogue_mode" not in asked_fields

def test_conflict_prioritization():
    # 18.1: Conflict prioritized over missing items
    known = {"duration_seconds": 30}
    conflicts = ["duration_seconds"]
    confidence = {"duration_seconds": 0.5}

    questions = select_questions(known, conflicts=conflicts, confidence=confidence, asked_fields=set(), max_questions=3)
    assert len(questions) > 0
    assert questions[0].field == "duration_seconds"

def test_safe_defaults_application():
    # 18.1: Three rounds stop and records low-risk defaults
    partial_known = {
        "logline": "赛博朋克雨夜追凶",
        "protagonist": "私家侦探",
    }
    completed, assumptions = apply_safe_defaults(partial_known, [])

    assert completed["duration_seconds"] == 45
    assert completed["aspect_ratio"] == "16:9"
    assert completed["dialogue_mode"] == "voiceover"
    assert len(assumptions) >= 3

def test_brief_completion_calculation():
    empty_brief = {}
    assert calculate_brief_completion(empty_brief) == 0.0

    full_brief = {
        "logline": "test",
        "duration_seconds": 45,
        "aspect_ratio": "16:9",
        "visual_style": "cinematic",
        "protagonist": "hero",
        "protagonist_goal": "survive",
        "conflict": "monster",
        "ending": "open",
        "dialogue_mode": "voiceover"
    }
    assert calculate_brief_completion(full_brief) == 1.0
