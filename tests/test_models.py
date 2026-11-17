"""Tests for flow._models."""
from pathlib import Path

import pytest

from flow._models import (
    BatchResult,
    GenerationMode,
    GenerationResult,
    GenerationStatus,
    ParsedPrompt,
    parse_prompt_file,
)
from flow._client import _safe_filename, _make_cost_verifier
from flow._flow_ui import AgentUI


def test_parse_prompt_file_plain(tmp_path: Path):
    """Plain text: blank-line-separated blocks."""
    f = tmp_path / "prompts.txt"
    f.write_text("A golden Buddha\n\nSubhuti meditating\n\n")
    result = parse_prompt_file(f)
    assert len(result) == 2
    assert result[0].text == "A golden Buddha"
    assert result[0].tag is None
    assert result[1].text == "Subhuti meditating"


def test_parse_prompt_file_tagged(tmp_path: Path):
    """Tagged blocks with blank-line separation."""
    f = tmp_path / "prompts.txt"
    f.write_text(
        "# Comment\n\n"
        "[V1-S1] Golden Buddha on lotus throne, celestial clouds\n\n"
        "[V1-S2] Subhuti meditating, white hair, golden particles\n"
    )
    result = parse_prompt_file(f)
    assert len(result) == 2
    assert result[0].tag == "[V1-S1]"
    assert result[0].text == "Golden Buddha on lotus throne, celestial clouds"
    assert result[1].tag == "[V1-S2]"
    assert result[1].text == "Subhuti meditating, white hair, golden particles"


def test_parse_prompt_file_pipeline(tmp_path: Path):
    """Pipeline mode: image_prompt ||| video_prompt."""
    f = tmp_path / "prompts.txt"
    f.write_text(
        "[V1-S1] Temple exterior ||| Slow zoom-in with cherry blossoms falling\n\n"
        "[V1-S2] Subhuti close-up ||| Gentle camera orbit\n"
    )
    result = parse_prompt_file(f)
    assert len(result) == 2

    assert result[0].tag == "[V1-S1]"
    assert result[0].text == "Temple exterior"
    assert result[0].video_prompt == "Slow zoom-in with cherry blossoms falling"

    assert result[1].tag == "[V1-S2]"
    assert result[1].text == "Subhuti close-up"
    assert result[1].video_prompt == "Gentle camera orbit"


def test_parse_prompt_file_comments_only(tmp_path: Path):
    """A file with only comments should return empty list."""
    f = tmp_path / "prompts.txt"
    f.write_text("# Just a comment\n# Another one\n")
    result = parse_prompt_file(f)
    assert result == []


def test_safe_filename():
    """Prompt text is converted to a safe filename slug."""
    assert _safe_filename("Golden Buddha, celestial clouds!") == "golden_buddha_celestial_clouds"
    assert _safe_filename("") == "output"
    assert _safe_filename("a" * 100, max_len=50) == "a" * 50


def test_generation_result_succeeded():
    """GenerationResult.succeeded property."""
    r = GenerationResult(
        prompt="test",
        mode=GenerationMode.IMAGE,
        status=GenerationStatus.COMPLETE,
    )
    assert r.succeeded is True
    assert r.primary_file is None

    r.file_paths = [Path("/tmp/test.png")]
    assert r.primary_file == Path("/tmp/test.png")

    r.status = GenerationStatus.FAILED
    assert r.succeeded is False


def test_batch_result_add():
    """BatchResult.add correctly counts statuses."""
    batch = BatchResult(mode=GenerationMode.IMAGE, total=3)

    r1 = GenerationResult(prompt="a", mode=GenerationMode.IMAGE, status=GenerationStatus.COMPLETE)
    r2 = GenerationResult(prompt="b", mode=GenerationMode.IMAGE, status=GenerationStatus.FAILED, error="timeout")
    r3 = GenerationResult(prompt="c", mode=GenerationMode.IMAGE, status=GenerationStatus.SKIPPED, error="skipped")

    batch.add(r1)
    assert batch.completed == 1
    assert batch.failed == 0

    batch.add(r2)
    assert batch.failed == 1

    batch.add(r3)
    assert batch.skipped == 1

    assert len(batch.results) == 3


def test_parse_card_and_cost_verifier():
    """Confirmation card parser and strict HTrJv price verifier."""
    cfg = {
        "videoModels": [
            {"displayName": "Omni 1.2 Flash", "durationS": 3, "creditCost": 3},
            {"displayName": "Omni 1.2 Flash", "durationS": 10, "creditCost": 10},
            {"displayName": "Omni 1.2 Flash", "durationS": 10, "creditCost": 30},
            {"displayName": "Veo 3.1 - Lite", "durationS": 4, "creditCost": 5},
        ]
    }
    c1 = AgentUI.parse_card("我将使用 Omni 1.2 Flash 生成 3 秒视频。\n要消耗 3 个点数，开始生成这 1 个视频吗？")
    assert c1["cost"] == 3 and c1["duration_s"] == 3
    v = _make_cost_verifier(cfg)
    assert v(c1) is True
    assert v({"cost": 99, "duration_s": 3, "raw": "Omni 1.2 Flash"}) is False
    assert v({"cost": 0, "duration_s": None, "raw": "Omni 1.2 Flash"}) is False

    # Edit card without duration on card uses expected_duration_s from source video
    c_edit = AgentUI.parse_card("我将对该视频进行镜头编辑。\n要消耗 10 个点数，开始生成这 1 个视频吗？")
    v_edit = _make_cost_verifier(cfg, expected_duration_s=10, default_family="Omni 1.2 Flash")
    assert v_edit(c_edit) is True
    assert _make_cost_verifier(cfg, expected_duration_s=3, default_family="Omni 1.2 Flash")(c_edit) is False

