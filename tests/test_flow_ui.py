"""Offline unit tests for bilingual AgentUI selectors, price verification, and safety gates."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from flow._client import _make_cost_verifier, verify_upscale_menu_cost
from flow._exceptions import GenerationError
from flow._flow_ui import (
    _CARD_TEXT,
    _FIND_LIVE_APPROVE,
    _HAS_ERROR,
    ADD_MEDIA_ARIA_LABELS,
    ADD_TO_PROMPT_LABELS,
    APPROVE_LABELS,
    CONFIRM_ALWAYS_LABELS,
    DOWNLOAD_MEDIA_ARIA_LABELS,
    UPSCALE_LABELS,
    UPLOAD_MEDIA_LABELS,
    AgentUI,
    build_aria_selector,
    has_nonzero_credit_quote,
    matches_any_label,
    parse_credit_cost,
    parse_duration_s,
)


# ── Bilingual selector & label helpers ──────────────────────────────────────


def test_bilingual_label_constants_and_aria_selector():
    assert APPROVE_LABELS[0] == "批准" and "Approve" in APPROVE_LABELS
    assert "在提示框中添加素材" in ADD_MEDIA_ARIA_LABELS
    assert any("Add media" in lbl for lbl in ADD_MEDIA_ARIA_LABELS)
    assert "下载媒体内容" in DOWNLOAD_MEDIA_ARIA_LABELS
    assert any("Download" in lbl for lbl in DOWNLOAD_MEDIA_ARIA_LABELS)
    assert "添加到提示" in ADD_TO_PROMPT_LABELS and "Add to prompt" in ADD_TO_PROMPT_LABELS
    assert "高清重塑" in UPSCALE_LABELS and "Upscaled" in UPSCALE_LABELS
    assert "始终" in CONFIRM_ALWAYS_LABELS and "Always" in CONFIRM_ALWAYS_LABELS
    assert "上传媒体" in UPLOAD_MEDIA_LABELS and "Upload media" in UPLOAD_MEDIA_LABELS

    sel = build_aria_selector("button", ADD_MEDIA_ARIA_LABELS)
    assert "button[aria-label='在提示框中添加素材']" in sel
    assert "button[aria-label='Add media to prompt' i]" in sel

    prefixed = build_aria_selector("input", ("搜索资源", "Search assets"), prefix=".cdk-overlay-container ")
    assert ".cdk-overlay-container input[aria-label='搜索资源']" in prefixed
    assert ".cdk-overlay-container input[aria-label='Search assets' i]" in prefixed

    assert matches_any_label("  批准 ", APPROVE_LABELS) is True
    assert matches_any_label("APPROVE", APPROVE_LABELS) is True
    assert matches_any_label("Approved", APPROVE_LABELS, exact=True) is False
    assert matches_any_label("1080p Upscaled", UPSCALE_LABELS, exact=False) is True


# ── Bilingual card & cost parsing ───────────────────────────────────────────


def test_parse_credit_cost_and_duration_bilingual():
    # Chinese confirmation card
    cn = "我将使用 Veo 3.1 - Lite 生成 4 秒视频。\n要消耗 5 个点数，开始生成这 1 个视频吗？"
    assert parse_credit_cost(cn) == 5
    assert parse_duration_s(cn) == 4
    assert AgentUI.parse_card(cn) == {"cost": 5, "duration_s": 4, "raw": cn}

    # English confirmation card
    en = "I'll generate an 8-second video using Veo 3.1 - Fast.\nUse 10 credits to start generating?"
    assert parse_credit_cost(en) == 10
    assert parse_duration_s(en) == 8
    assert AgentUI.parse_card(en) == {"cost": 10, "duration_s": 8, "raw": en}

    # Balance mention before action-qualified cost must pick the action cost
    en_bal = "Balance: 24860 credits. Spend 3 credits to generate a 3s clip?"
    assert parse_credit_cost(en_bal) == 3
    assert parse_duration_s(en_bal) == 3

    # Decade like 1980s must not be mistaken for a video duration
    assert parse_duration_s("1980s retro neon city") is None
    assert parse_duration_s("10 seconds") == 10
    assert parse_duration_s("5 sec") == 5


def test_has_nonzero_credit_quote_fail_closed():
    assert has_nonzero_credit_quote("1080p 已高清重塑") is False
    assert has_nonzero_credit_quote("1080p Upscaled (Free)") is False
    assert has_nonzero_credit_quote("1080p Upscaled (0 credits)") is False
    assert has_nonzero_credit_quote("1080p 消耗 20 个点数") is True
    assert has_nonzero_credit_quote("1080p (20 credits)") is True
    assert has_nonzero_credit_quote("1080p (uses credits)") is True
    assert has_nonzero_credit_quote("1080p 消耗 点数") is True


def test_bilingual_cost_verifier_and_upscale_gate():
    cfg = {
        "videoModels": [
            {"displayName": "Veo 3.1 - Lite", "durationS": 4, "creditCost": 5},
            {"displayName": "Omni 1.2 Flash", "durationS": 3, "creditCost": 3},
            {"displayName": "Omni 1.2 Flash", "durationS": 10, "creditCost": 30},
        ]
    }
    verifier = _make_cost_verifier(cfg)

    en_card = AgentUI.parse_card("Generating 4 seconds with Veo 3.1 - Lite. Costs 5 credits.")
    assert verifier(en_card) is True

    bad_en_card = AgentUI.parse_card("Generating 4 seconds with Veo 3.1 - Lite. Costs 50 credits.")
    assert verifier(bad_en_card) is False

    # Upscale 1080p free vs unexpected charge (CN & EN)
    verify_upscale_menu_cost("1080p 已高清重塑", is_4k=False)
    verify_upscale_menu_cost("1080p Upscaled", is_4k=False)
    with pytest.raises(GenerationError):
        verify_upscale_menu_cost("1080p 已高清重塑（消耗 10 个点数）", is_4k=False)
    with pytest.raises(GenerationError):
        verify_upscale_menu_cost("1080p Upscaled (10 credits)", is_4k=False)

    # Upscale 4K must match official cost
    verify_upscale_menu_cost("4K 已高清重塑（消耗 50 个点数）", is_4k=True, official_4k_cost=50)
    verify_upscale_menu_cost("4K Upscaled (50 credits)", is_4k=True, official_4k_cost=50)
    with pytest.raises(GenerationError):
        verify_upscale_menu_cost("4K Upscaled (99 credits)", is_4k=True, official_4k_cost=50)
    with pytest.raises(GenerationError):
        verify_upscale_menu_cost("4K Upscaled", is_4k=True, official_4k_cost=50)


# ── JS probes & AgentUI gating ──────────────────────────────────────────────


def test_js_probes_include_bilingual_tokens_and_card_boundaries():
    assert "批准" in _FIND_LIVE_APPROVE and "approve" in _FIND_LIVE_APPROVE
    assert "dimmed" in _FIND_LIVE_APPROVE
    assert "messages-list" in _CARD_TEXT
    assert "点数" in _CARD_TEXT and "credits?" in _CARD_TEXT
    assert "出了点问题" in _HAS_ERROR and "something went wrong" in _HAS_ERROR


class _FakeElement:
    def __init__(self, text: str, cls: str = "", visible: bool = True):
        self.text = text
        self.cls = cls
        self.visible = visible
        self.clicked = False

    async def evaluate(self, _script: str):
        return self.cls

    async def is_visible(self) -> bool:
        return self.visible

    async def click(self, timeout: int = 8000):
        self.clicked = True


class _FakeLocator:
    def __init__(self, items: list[_FakeElement]):
        self._items = items

    async def count(self) -> int:
        return len(self._items)

    def nth(self, i: int) -> _FakeElement:
        return self._items[i]


class _FakePage:
    def __init__(self, by_text: dict[str, list[_FakeElement]]):
        self._by_text = by_text

    def get_by_text(self, text: str, exact: bool = True):
        return _FakeLocator(self._by_text.get(text, []))


@pytest.mark.asyncio
async def test_approve_skips_dimmed_and_supports_english_fallback():
    dimmed_cn = _FakeElement("批准", cls="btn dimmed")
    live_en = _FakeElement("Approve", cls="btn primary")
    page = _FakePage({"批准": [dimmed_cn], "Approve": [live_en]})

    ui = AgentUI(browser_manager=None, project_id="proj-1")
    ok = await ui._approve(page)
    assert ok is True
    assert dimmed_cn.clicked is False
    assert live_en.clicked is True


@pytest.mark.asyncio
async def test_run_turn_refuses_unverified_card_and_approves_verified():
    ui = AgentUI(browser_manager=None, project_id="proj-1")
    ui._find_box = AsyncMock(return_value=object())
    ui._submit = AsyncMock()
    ui._approve = AsyncMock(return_value=True)

    # 1. Unverified quote must NOT call _approve
    ui._wait_card = AsyncMock(return_value="Use 999 credits to generate 8s video?")
    with pytest.raises(GenerationError, match="NOT approving"):
        await ui.run_turn(object(), "gen video", verify_cost=lambda p: p["cost"] == 10, require_card=True)
    ui._approve.assert_not_awaited()

    # 2. Missing card raises when require_card=True, succeeds when require_card=False
    ui._wait_card = AsyncMock(return_value=None)
    with pytest.raises(GenerationError, match="without presenting a confirmation card"):
        await ui.run_turn(object(), "gen video", require_card=True)
    no_card_res = await ui.run_turn(object(), "gen image", require_card=False)
    assert no_card_res["no_card"] is True
    ui._approve.assert_not_awaited()

    # 3. Verified English card approves
    ui._wait_card = AsyncMock(return_value="Use 5 credits to generate 4 seconds video?")
    ok_res = await ui.run_turn(
        object(),
        "gen video",
        verify_cost=lambda p: p["cost"] == 5 and p["duration_s"] == 4,
        require_card=True,
    )
    assert ok_res["cost"] == 5
    assert ok_res["duration_s"] == 4
    assert ok_res["no_card"] is False
    ui._approve.assert_awaited_once()
