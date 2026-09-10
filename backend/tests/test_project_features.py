from __future__ import annotations

import tempfile
from pathlib import Path

from app.agents.editor_intelligence import prompt_preferences
from app.services.editor_intelligence import music_structure, story_chapters


def test_prompt_preferences_detects_user_intent() -> None:
    pref = prompt_preferences("Viaggio emozionante tra amici, dinamico ma con finale lento", "cinematic")
    assert pref["people"] > 0
    assert pref["emotional"] > 0
    assert pref["fast"] > 0
    assert pref["slow"] > 0


def test_story_chapters_groups_semantic_sequences() -> None:
    media = [
        {"id": "a", "vision_analysis": {"scene_type": "people", "people_count": 2}},
        {"id": "b", "vision_analysis": {"scene_type": "people", "people_count": 1}},
        {"id": "c", "vision_analysis": {"scene_type": "landscape", "people_count": 0}},
    ]
    chapters = story_chapters(media)
    assert chapters
    assert chapters[0]["title"] == "Persone"
    assert "a" in chapters[0]["media_ids"]


def test_music_structure_returns_sections_and_climax() -> None:
    result = music_structure({"duration_sec": 16, "bpm": 120, "energy_curve": [0.1] * 4 + [0.5] * 4 + [0.9] * 4 + [0.3] * 4})
    assert len(result["sections"]) == 4
    assert result["climax_sec"] >= 8
    assert result["peak_energy"] == 0.9
