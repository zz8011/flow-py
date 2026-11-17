"""Unit tests for Google Flow Music (flowmusic.app) models and helpers."""
from __future__ import annotations

from flow._music import SongClip, _extract_clip_ids_from_returns
from flow._music_rpc import INSTRUMENTAL_MARKER, lyrics_id_for_text


def test_lyrics_id_for_text():
    assert lyrics_id_for_text("") == ""
    assert lyrics_id_for_text("   ") == ""
    assert lyrics_id_for_text(INSTRUMENTAL_MARKER) == ""

    uid1 = lyrics_id_for_text("[Verse]\nHello world")
    uid2 = lyrics_id_for_text("[Verse]\nHello world")
    uid3 = lyrics_id_for_text("[Verse]\nDifferent line")
    assert len(uid1) == 36
    assert uid1 == uid2
    assert uid1 != uid3


def test_song_clip_from_api():
    raw = {
        "id": "16c43bc6-d27d-40e5-89f2-86c45087d3f1",
        "title": "晨光街角",
        "op_type": "audio__create_song",
        "duration": {"status": "completed", "value": "120.704"},
        "lyrics": {"status": "completed", "value": {"id": "abc", "text": "[Verse]\n清晨"}},
        "operation": {
            "op_type": "audio__create_song",
            "sound_prompt": "acoustic folk, 96 bpm",
            "conversation_id": "conv-123",
        },
        "audio_url": "https://storage.googleapis.com/producer-app-public/clips/16c43bc6.m4a",
        "wav_url": "https://storage.googleapis.com/producer-app-public/clips/16c43bc6.wav",
        "image_url": "https://storage.googleapis.com/producer-app-public/assets/16c43bc6.jpg",
    }
    clip = SongClip.from_api(raw)
    assert clip.id == "16c43bc6-d27d-40e5-89f2-86c45087d3f1"
    assert clip.title == "晨光街角"
    assert clip.complete is True
    assert abs(clip.duration_s - 120.704) < 1e-3
    assert clip.lyrics == "[Verse]\n清晨"
    assert clip.sound_prompt == "acoustic folk, 96 bpm"
    assert clip.conversation_id == "conv-123"


def test_extract_clip_ids_from_returns():
    returns = [
        {"content": {"clip_id": "16c43bc6-d27d-40e5-89f2-86c45087d3f1"}},
        {"content": {"result_clip_id": "795334bd-bec8-4d90-95d5-02ed227388e0"}},
        {
            "content": {
                "clip_outputs": [
                    {"clip_id": "bf46f906-54cb-4cce-878b-366a33b83c71", "title": "Ext"}
                ]
            }
        },
    ]
    ids = _extract_clip_ids_from_returns(returns)
    assert ids == [
        "16c43bc6-d27d-40e5-89f2-86c45087d3f1",
        "795334bd-bec8-4d90-95d5-02ed227388e0",
        "bf46f906-54cb-4cce-878b-366a33b83c71",
    ]
