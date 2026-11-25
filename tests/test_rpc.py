"""Offline unit tests for flow._rpc (batchexecute transport, HTrJv pricing, media parsing)."""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from flow._exceptions import AuthError, FlowError
from flow._rpc import (
    RPC_CREDITS,
    RPC_MEDIA,
    RPC_MODEL_CONFIG,
    RPC_PROJECTS,
    RPC_PROJECT_MEDIA,
    FlowRPC,
    _find_duration,
    _parse_batch_response,
)


def _make_rpc_with_call(side_effect_or_return):
    bm = SimpleNamespace(page=AsyncMock(), context=SimpleNamespace())
    rpc = FlowRPC(bm)
    if callable(side_effect_or_return):
        rpc.call = AsyncMock(side_effect=side_effect_or_return)
    else:
        rpc.call = AsyncMock(return_value=side_effect_or_return)
    return rpc


# ── _parse_batch_response ───────────────────────────────────────────────────


def test_parse_batch_response_valid_and_malformed():
    assert _parse_batch_response("") == {}
    assert _parse_batch_response(")]}'\n") == {}

    inner_credits = json.dumps([24860, 2, 3, 3, None, 24860, [1763424000, 0]])
    inner_projects = json.dumps([[["proj-1", ["Demo", None, None, "https://thumb"]]]])
    raw = "\n".join(
        [
            ")]}'",
            "123",
            json.dumps([["wrb.fr", RPC_CREDITS, inner_credits, None, None, None, "generic"]]),
            "not-valid-json",
            json.dumps({"not": "a list"}),
            json.dumps([["other.op", "ignored", "{}"]]),
            json.dumps([["wrb.fr", RPC_PROJECTS, inner_projects]]),
            json.dumps([["wrb.fr", "raw_str", "not-json-inner"]]),
        ]
    )

    parsed = _parse_batch_response(raw)
    assert parsed[RPC_CREDITS][0] == 24860
    assert parsed[RPC_CREDITS][2] == 3
    assert parsed[RPC_PROJECTS][0][0][0] == "proj-1"
    assert parsed["raw_str"] == "not-json-inner"


# ── _find_duration ──────────────────────────────────────────────────────────


def test_find_duration_bounds_and_depth():
    record = ["id", [["nested", [None, None, [8]]]]]
    assert _find_duration(record) == 8

    # Out of range or non-int ignored
    assert _find_duration([None, None, [0]]) is None
    assert _find_duration([None, None, [121]]) is None
    assert _find_duration([None, None, [8.5]]) is None
    assert _find_duration([None, None, ["8"]]) is None

    # Boundary 120s allowed
    assert _find_duration([None, None, [120]]) == 120

    # Depth limit > 8 stops recursion
    deep = [None, None, [10]]
    for _ in range(9):
        deep = [deep]
    assert _find_duration(deep) is None


# ── Credits & Tier ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_credits_and_tier_3():
    rpc = _make_rpc_with_call([24860, 2, 3, 3, None, 24860, [1763424000, 0]])
    creds = await rpc.get_credits()
    assert creds["credits"] == 24860
    assert creds["userPaygateTier"] == 2
    assert creds["priceTier"] == 3
    assert creds["reset_ts"] == 1763424000
    assert await rpc.get_tier() == 3


@pytest.mark.asyncio
async def test_get_credits_fallback_and_errors():
    # Missing priceTier falls back to userPaygateTier
    rpc = _make_rpc_with_call([500, 2])
    assert await rpc.get_tier() == 2

    # Unexpected shape raises FlowError
    bad_rpc = _make_rpc_with_call({})
    with pytest.raises(FlowError):
        await bad_rpc.get_credits()


# ── HTrJv Model Config (tier 3 + matrix pricing) ────────────────────────────


def _build_htrjv_fixture():
    # Family 1: Veo 3.1 - Fast (tier 2 = 20, tier 3 = 10, duration 8s)
    veo_fast_var = [None] * 17
    veo_fast_var[0] = "veo_3_1_t2v_fast_ultra"
    veo_fast_var[4] = [
        [2, [[1, 20]]],
        [3, [[1, 10]]],
    ]
    veo_fast_var[16] = 8

    # Variant mentioning tier 3 with empty cost list -> should be skipped
    veo_skipped_var = [None] * 17
    veo_skipped_var[0] = "veo_3_1_t2v_fast_unavailable"
    veo_skipped_var[4] = [
        [2, [[1, 20]]],
        [3, []],
    ]
    veo_skipped_var[16] = 8

    # Family 2: Veo 3.1 - Lite (tier 3 = 5, duration 4s)
    veo_lite_var = [None] * 17
    veo_lite_var[0] = "veo_3_1_t2v_lite"
    veo_lite_var[4] = [
        [2, [[1, 10]]],
        [3, [[1, 5]]],
    ]
    veo_lite_var[16] = 4

    # Family 3: Omni 1.2 Flash
    # - 3s 360p edit variant via tier table
    omni_3s = [None] * 17
    omni_3s[0] = "macaron_cookie_i2v_3s"
    omni_3s[4] = [[3, [[1, 3]]]]
    omni_3s[16] = 3

    # - Matrix-priced variant (variant[4] has cost 0, duration None; variant[25][0] holds [tier, dur, res_code])
    omni_matrix = [None] * 26
    omni_matrix[0] = "macaron_cookie_edit"
    omni_matrix[4] = [[3, [[1, 0]]]]
    omni_matrix[16] = None
    omni_matrix[23] = [[2]]  # res_code = 2
    omni_matrix[25] = [
        [
            [[3, 10, 1], [1, 10]],
            [[3, 10, 2], [1, 30]],
            [[2, 10, 2], [1, 60]],
        ]
    ]

    # Family 4: Upscaler & R2V
    upscaler_var = [None] * 17
    upscaler_var[0] = "veo_3_1_upsampler_4k"
    upscaler_var[4] = [[1, [[1, 50]]]]  # tier 3 unmentioned -> falls back to tier 1
    upscaler_var[16] = None

    r2v_var = [None] * 17
    r2v_var[0] = "veo_3_1_r2v_fast"
    r2v_var[4] = [[3, [[1, 10]]]]
    r2v_var[16] = 8

    families = [
        ["Veo 3.1 - Fast", [veo_fast_var, veo_skipped_var]],
        ["Veo 3.1 - Lite", [veo_lite_var]],
        ["Omni 1.2 Flash", [omni_3s, omni_matrix]],
        ["Tools", [upscaler_var, r2v_var]],
    ]
    return [[None, None, None, None, families]]


@pytest.mark.asyncio
async def test_get_model_config_tier3_and_matrix():
    htrjv = _build_htrjv_fixture()

    async def fake_call(rpcid, payload):
        if rpcid == RPC_CREDITS:
            return [24860, 2, 3, 3]
        if rpcid == RPC_MODEL_CONFIG:
            return htrjv
        raise AssertionError(f"Unexpected rpcid {rpcid}")

    rpc = _make_rpc_with_call(fake_call)
    cfg = await rpc.get_model_config()
    by_key = {m["key"]: m for m in cfg["videoModels"]}

    assert "veo_3_1_t2v_fast_unavailable" not in by_key
    assert by_key["veo_3_1_t2v_fast_ultra"] == {
        "key": "veo_3_1_t2v_fast_ultra",
        "displayName": "Veo 3.1 - Fast",
        "creditCost": 10,
        "durationS": 8,
        "supportedFeatures": ["TEXT"],
    }
    assert by_key["veo_3_1_t2v_lite"]["creditCost"] == 5
    assert by_key["veo_3_1_t2v_lite"]["durationS"] == 4
    assert by_key["macaron_cookie_i2v_3s"]["creditCost"] == 3
    assert by_key["macaron_cookie_i2v_3s"]["supportedFeatures"] == ["START_IMAGE"]
    # Matrix lookup matched [tier=3, dur=10, res_code=2] -> 30cr, 10s
    assert by_key["macaron_cookie_edit"]["creditCost"] == 30
    assert by_key["macaron_cookie_edit"]["durationS"] == 10
    assert by_key["macaron_cookie_edit"]["supportedFeatures"] == ["EDIT"]
    # Fallback tier & feature flags
    assert by_key["veo_3_1_upsampler_4k"]["creditCost"] == 50
    assert by_key["veo_3_1_upsampler_4k"]["supportedFeatures"] == ["UPSCALE"]
    assert by_key["veo_3_1_r2v_fast"]["supportedFeatures"] == ["REFERENCES"]


@pytest.mark.asyncio
async def test_get_model_config_malformed_returns_empty():
    rpc = _make_rpc_with_call(None)
    assert await rpc.get_model_config(tier=3) == {"videoModels": []}


# ── list_project_media & get_media_url ──────────────────────────────────────


@pytest.mark.asyncio
async def test_list_project_media_and_get_media_url():
    zzl0ze = [
        None,
        [
            ["wf-vid", None, None, ["Sunset Clip", None, None, None, "sess-1", "turn-1"], "proj-1"],
            ["wf-img", None, None, ["Lotus Art", None, None, None, "sess-2", "turn-2"], "proj-1"],
        ],
        [
            [
                "med-vid-1",
                "proj-1",
                "wf-vid",
                None,
                None,
                [
                    {
                        "poster": "https://lh3.googleusercontent.com/asb/tok_vid",
                        "model": "veo_3_1_t2v_lite",
                    }
                ],
                None,
                [[None, None, [4]]],
            ],
            [
                "med-img-1",
                "proj-1",
                "wf-img",
                None,
                None,
                [
                    {
                        "poster": "https://lh3.googleusercontent.com/asb/tok_img",
                        "model": "GEM_PIX_2",
                    }
                ],
                None,
                [],
            ],
        ],
    ]
    as29s = [
        "med-vid-1",
        "https://flow-content.google/video/med-vid-1?Expires=9999&Signature=abc",
    ]

    async def fake_call(rpcid, payload):
        if rpcid == RPC_PROJECT_MEDIA:
            return zzl0ze
        if rpcid == RPC_MEDIA:
            return as29s if payload == ["med-vid-1"] else []
        raise AssertionError(f"Unexpected rpcid {rpcid}")

    rpc = _make_rpc_with_call(fake_call)
    pm = await rpc.list_project_media("proj-1")
    assert len(pm["workflows"]) == 2
    assert pm["workflows"][0]["display_name"] == "Sunset Clip"

    by_id = {m["media_id"]: m for m in pm["medias"]}
    assert by_id["med-vid-1"]["kind"] == "video"
    assert by_id["med-vid-1"]["duration_s"] == 4
    assert by_id["med-vid-1"]["model_key"] == "veo_3_1_t2v_lite"
    assert by_id["med-img-1"]["kind"] == "image"
    assert by_id["med-img-1"]["duration_s"] is None

    url = await rpc.get_media_url("med-vid-1")
    assert url == "https://flow-content.google/video/med-vid-1?Expires=9999&Signature=abc"
    assert await rpc.get_media_url("med-pending") == ""


@pytest.mark.asyncio
async def test_ensure_page_raises_when_logged_out():
    fake_page = SimpleNamespace(
        url="https://accounts.google.com/v3/signin",
        goto=AsyncMock(),
    )
    bm = SimpleNamespace(page=AsyncMock(return_value=fake_page))
    rpc = FlowRPC(bm)
    with patch("flow._rpc.asyncio.sleep", AsyncMock()):
        with pytest.raises(AuthError):
            await rpc._ensure_page()
    fake_page.goto.assert_awaited_once()
