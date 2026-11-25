"""Offline CLI & public export compatibility tests."""
from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

import flow
from flow.cli.main import cli


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def isolated_storage(tmp_path: Path):
    storage_root = tmp_path / ".flow-py"
    profile_dir = storage_root / "browser-profile"
    config_file = storage_root / "config.json"
    projects_file = storage_root / "projects.json"

    with patch("flow._storage.STORAGE_ROOT", storage_root), \
         patch("flow._storage.PROFILE_DIR", profile_dir), \
         patch("flow._storage.CONFIG_FILE", config_file), \
         patch("flow._storage.PROJECTS_FILE", projects_file):
        yield storage_root


# ── Public export compatibility ─────────────────────────────────────────────


EXPECTED_PUBLIC_SYMBOLS = {
    "FlowClient", "FlowMusicClient", "FlowAPI", "UIInterceptor", "CapturedCall",
    "GeneratedImage", "VideoJob", "VideoStatus", "Credits", "Workflow",
    "MusicCredits", "SongClip", "StemClip", "ProducerTurn",
    "FlowError", "AuthError", "NotLoggedInError", "GenerationError",
    "GenerationTimeout", "PolicyError", "DownloadError", "NoProjectError",
    "UIError", "InvalidArgumentError", "NotFoundError", "FeatureUnavailableError",
    "FlowConfig", "GenerationMode", "GenerationResult", "GenerationStatus",
    "BatchResult", "AspectRatio", "ParsedPrompt", "parse_prompt_file",
    "CAMERA_MOTIONS", "CAMERA_POSITIONS",
    "IMAGE_MODEL_NARWHAL", "IMAGE_MODEL_IMAGEN3",
    "IMAGE_AR_PORTRAIT", "IMAGE_AR_LANDSCAPE", "IMAGE_AR_SQUARE",
    "IMAGE_ROLE_START", "IMAGE_ROLE_END", "IMAGE_ROLE_REFERENCE",
    "VIDEO_MODEL_VEO31_FAST", "VIDEO_MODEL_VEO31_FAST_P",
    "VIDEO_MODEL_VEO31_STD", "VIDEO_MODEL_VEO31_STD_P",
    "VIDEO_MODEL_VEO21_T2V", "VIDEO_MODEL_VEO20_STD",
    "VIDEO_MODEL_VEO31_I2V", "VIDEO_MODEL_VEO31_I2V_P",
    "VIDEO_MODEL_VEO31_I2V_STD", "VIDEO_MODEL_VEO31_I2V_STD_P",
    "VIDEO_MODEL_VEO21_I2V", "VIDEO_MODEL_VEO20_I2V_STD",
    "VIDEO_MODEL_VEO31_SE", "VIDEO_MODEL_VEO31_SE_P",
    "VIDEO_MODEL_VEO31_SE_STD", "VIDEO_MODEL_VEO31_SE_STD_P",
    "VIDEO_MODEL_VEO21_SE",
    "VIDEO_MODEL_VEO31_R2V", "VIDEO_MODEL_VEO31_R2V_P",
    "VIDEO_MODEL_EXTEND_L", "VIDEO_MODEL_EXTEND_P",
    "VIDEO_MODEL_EXTEND_L_STD", "VIDEO_MODEL_EXTEND_P_STD",
    "VIDEO_MODEL_VEO21_EXTEND",
    "VIDEO_MODEL_RESHOOT_L", "VIDEO_MODEL_RESHOOT_P",
    "VIDEO_MODEL_INSERT", "VIDEO_MODEL_INSERT_L", "VIDEO_MODEL_INSERT_P",
    "VIDEO_MODEL_REMOVE", "VIDEO_MODEL_REMOVE_L", "VIDEO_MODEL_REMOVE_P",
    "VIDEO_MODEL_UPSCALER_1080P",
    "VIDEO_AR_LANDSCAPE", "VIDEO_AR_PORTRAIT",
    "VIDEO_RES_1080P", "VIDEO_RES_720P",
    "RESHOOT_FORWARD", "RESHOOT_BACKWARD", "RESHOOT_LEFT", "RESHOOT_RIGHT",
    "RESHOOT_UP", "RESHOOT_DOWN", "RESHOOT_DOLLY_ZOOM_IN", "RESHOOT_DOLLY_ZOOM_OUT",
    "RESHOOT_POS_CENTER", "RESHOOT_POS_LEFT", "RESHOOT_POS_RIGHT",
    "RESHOOT_POS_HIGH", "RESHOOT_POS_LOW", "RESHOOT_POS_CLOSER", "RESHOOT_POS_FURTHER",
    "CAMERA_PRESETS", "MASK_USAGE_TYPE", "create_removal_mask", "encode_mask_b64",
    "MODEL_REGISTRY", "__version__",
}


def test_public_exports_complete_and_deduplicated():
    assert len(flow.__all__) == len(set(flow.__all__))
    assert set(flow.__all__) == EXPECTED_PUBLIC_SYMBOLS
    for sym in EXPECTED_PUBLIC_SYMBOLS:
        assert hasattr(flow, sym), f"Missing public symbol: {sym}"

    mask = flow.create_removal_mask(64, 64, [(8, 8, 16, 16)])
    assert len(mask) > 0
    assert isinstance(flow.encode_mask_b64(mask), str)
    assert "veo_3_1_t2v_fast" in flow.MODEL_REGISTRY


def test_flowapi_retired_methods_point_to_flowclient():
    """Retired v0.1.0 direct-generation calls must raise a GenerationError pointing at
    FlowClient instead of a bare AttributeError."""
    api = flow.FlowAPI(browser_manager=None)
    with pytest.raises(flow.GenerationError, match="FlowClient.generate_video"):
        api.generate_video("golden lotus at dawn")
    with pytest.raises(flow.GenerationError, match="FlowClient.generate_image"):
        api.generate_image("golden lotus")
    with pytest.raises(flow.GenerationError, match="FlowClient"):
        api.extend_loop("media-1")
    # Unknown names stay a plain AttributeError; read-only queries and downloads still work
    assert not hasattr(api, "no_such_method")
    assert callable(api.get_credits) and callable(api.download)


# ── Root docs ────────────────────────────────────────────────────────────────


def test_root_docs_only_reference_existing_markdown_files():
    """Removing a root doc (e.g. a duplicate) must not leave dangling references behind."""
    root = Path(__file__).resolve().parents[1]
    docs = sorted(root.glob("*.md"))
    assert {"PATCH.md", "PORTING-BRIEF.md"} <= {d.name for d in docs}  # docs are where we look
    for doc in docs:
        for ref in re.findall(r"\b[A-Z][A-Z0-9-]*\.md\b", doc.read_text(encoding="utf-8")):
            assert (root / ref).is_file(), f"{doc.name} references missing {ref}"


# ── CLI --help & offline validation ─────────────────────────────────────────


def test_root_and_subcommands_help(runner: CliRunner):
    res = runner.invoke(cli, ["--help"])
    assert res.exit_code == 0
    for cmd in (
        "login", "logout", "status", "config", "projects", "use", "workflows",
        "credits", "models", "video", "image", "frames", "extend", "extend-loop",
        "camera", "camera-pos", "insert", "remove", "upscale", "poll",
        "download", "download-all", "batch-images", "batch-videos", "music",
    ):
        assert cmd in res.output

    ver = runner.invoke(cli, ["--version"])
    assert ver.exit_code == 0
    assert "0.1.0" in ver.output

    for sub in ("video", "image", "frames", "extend", "camera", "camera-pos", "insert", "remove", "upscale", "status", "config"):
        sub_res = runner.invoke(cli, [sub, "--help"])
        assert sub_res.exit_code == 0, f"{sub} --help failed: {sub_res.output}"


def test_music_group_and_subcommands_help(runner: CliRunner):
    res = runner.invoke(cli, ["music", "--help"])
    assert res.exit_code == 0
    for sub in (
        "status", "credits", "models", "songs", "sessions",
        "generate", "score", "chat", "lyrics",
        "extend", "cover", "replace", "trim", "stems", "download",
    ):
        assert sub in res.output
        sub_res = runner.invoke(cli, ["music", sub, "--help"])
        assert sub_res.exit_code == 0, f"music {sub} --help failed: {sub_res.output}"


def test_cli_offline_parameter_validation(runner: CliRunner):
    assert runner.invoke(cli, ["video", "test", "--aspect", "square"]).exit_code != 0
    assert runner.invoke(cli, ["video", "test", "--count", "9"]).exit_code != 0
    assert runner.invoke(cli, ["camera", "mid-1", "--motion", "invalid_move"]).exit_code != 0
    assert runner.invoke(cli, ["camera-pos", "mid-1", "--position", "diagonal"]).exit_code != 0
    assert runner.invoke(cli, ["upscale", "mid-1", "-r", "8k"]).exit_code != 0
    assert runner.invoke(cli, ["music", "generate", "jazz", "-f", "ogg"]).exit_code != 0
    assert runner.invoke(cli, ["music", "score", "/nonexistent/video.mp4"]).exit_code != 0
    assert runner.invoke(cli, ["music", "replace", "clip-1", "--start", "10"]).exit_code != 0


def test_cli_offline_config_use_and_status_no_project(runner: CliRunner, isolated_storage: Path):
    status_res = runner.invoke(cli, ["status", "--json"])
    assert status_res.exit_code == 0
    assert '"auth": "no_project"' in status_res.output

    use_res = runner.invoke(cli, ["use", "proj-offline-123"])
    assert use_res.exit_code == 0
    assert "proj-offline-123" in use_res.output

    cfg_res = runner.invoke(cli, ["config"])
    assert cfg_res.exit_code == 0
    assert "proj-offline-123" in cfg_res.output
    assert "https://flow.google.com/project/proj-offline-123" in cfg_res.output
