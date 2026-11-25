"""Offline unit tests for bilingual AgentUI selectors, price verification, and safety gates."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from flow._client import FlowClient, _make_cost_verifier, verify_upscale_menu_cost
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


def test_parse_credit_cost_quotes_charge_not_balance():
    """The quote is the points that will be charged; a balance figure is never the quote."""
    assert parse_credit_cost("Balance: 0 credits. 50 credits will be charged") == 50
    assert parse_credit_cost("Balance 24860 credits. Cost: 20 credits") == 20
    # Balance only, no quote -> None; bare numbers still parse once the balance is dropped
    assert parse_credit_cost("Balance: 24860 credits") is None
    assert parse_credit_cost("Balance: 0 credits\n20 credits") == 20
    assert has_nonzero_credit_quote("Balance: 0 credits. 50 credits will be charged") is True
    # A 4K menu item that shows the balance is verified against the 50-credit quote
    verify_upscale_menu_cost(
        "4K Upscaled\nBalance 24860 credits. Cost: 50 credits", is_4k=True, official_4k_cost=50
    )


def test_has_nonzero_credit_quote_explicit_free():
    for free in (
        "1080p Upscaled — no credits charged",
        "1080p Upscaled — no credits will be charged",
        "1080p Upscaled — No Credits Will Be Charged",
        "1080p 免费高清重塑",
        "1080p 高清重塑（免费，不消耗点数）",
        "1080p 高清重塑（免费，不会消耗点数）",
        "1080p 高清重塑（无需消耗积分）",
        "1080p Upscaled (Free)",
    ):
        assert has_nonzero_credit_quote(free) is False, free
    # A free word never overrides an explicit positive quote (fail-closed)
    assert has_nonzero_credit_quote("1080p Upscaled (Free) — 20 credits") is True


@pytest.mark.parametrize(
    "text",
    [
        # Round-3 review bypass samples: no quoted number, a free word, and a charge word
        "Hands-free mode — credits required",
        "Try free! Additional credits apply",
        "1080p 免费试用（超出消耗点数）",
        # The same shape in both languages
        "1080p Upscaled (Free trial) — credits apply",
        "1080p Upscaled — FREE preview, credits used for the final render",
        "1080p Upscaled 免费 — credits apply",
        "1080p 免费版（消耗积分）",
        "1080p 高清重塑（免费试用，消耗点数）",
        # A negation clears only the charge word inside it
        "1080p Upscaled — no credits charged for 1080p; credits apply to 4K",
        "1080p 高清重塑（不消耗点数）；4K 需消耗点数",
    ],
)
def test_has_nonzero_credit_quote_free_word_does_not_clear_charge_word(text):
    """免费 / free beside a charge word is an unparseable quote: the 1080p gate must abort."""
    assert has_nonzero_credit_quote(text) is True
    with pytest.raises(GenerationError, match="unexpectedly quotes"):
        verify_upscale_menu_cost(text, is_4k=False)


def test_parse_duration_s_two_digit_short_form():
    assert parse_duration_s("90s synthwave video") == 90
    assert parse_duration_s("15s clip") == 15
    # Integral seconds keep parsing, with or without a space and next to CJK text
    assert parse_duration_s("城市天际线，3 秒") == 3
    assert parse_duration_s("生成3秒视频") == 3


@pytest.mark.parametrize(
    "text", ["0.3s", "0.13秒", "3.5s", "10.5 秒", "2.5 seconds", "0.5s fade-out"]
)
def test_parse_duration_s_fractional_seconds_fail_closed(text):
    """A decimal second is a timing cue ("0.5s fade-out"), never a video duration."""
    assert parse_duration_s(text) is None


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


# ── generate_video prompt assembly (aspect directive / Omni routing) ────────


def _client_capturing_turns(monkeypatch, *, medias=(), cfg=None) -> tuple[FlowClient, AsyncMock]:
    """Offline FlowClient: every agent turn is captured instead of submitted."""
    rpc = SimpleNamespace(
        get_model_config=AsyncMock(return_value=cfg or {}),
        list_project_media=AsyncMock(return_value={"medias": list(medias)}),
        get_media_url=AsyncMock(return_value="https://lh3.googleusercontent.com/x"),
    )
    bm = SimpleNamespace(page=AsyncMock(return_value=object()))
    client = FlowClient(SimpleNamespace(_rpc_client=lambda: rpc), bm, "proj-1")
    monkeypatch.setattr(
        client,
        "_wait_new_media",
        AsyncMock(return_value={"media_id": "media-1", "workflow_id": ""}),
    )
    run_turn = AsyncMock()
    monkeypatch.setattr(
        "flow._client.AgentUI",
        lambda bm, project_id: SimpleNamespace(
            open_session=AsyncMock(),
            attach_media=AsyncMock(),
            attach_or_upload=AsyncMock(),
            run_turn=run_turn,
        ),
    )
    return client, run_turn


_OMNI_PRICES = {
    "videoModels": [
        {"displayName": "Omni 1.2 Flash", "durationS": 3, "creditCost": 3},
        {"displayName": "Omni 1.2 Flash", "durationS": 10, "creditCost": 30},
    ]
}


@pytest.mark.asyncio
async def test_generate_video_aspect_word_in_prompt_keeps_explicit_aspect(monkeypatch):
    client, run_turn = _client_capturing_turns(monkeypatch)

    await client.generate_video("A sweeping mountain landscape at dawn", aspect="portrait")
    sent = run_turn.await_args.args[1]
    assert "9:16 竖屏" in sent and "16:9" not in sent

    # And the other way round: "portrait" in the prompt must not eat an explicit landscape
    await client.generate_video("portrait painting of a merchant", aspect="landscape")
    assert "16:9 横屏" in run_turn.await_args.args[1]


@pytest.mark.asyncio
async def test_generate_video_decimal_seconds_do_not_route_to_omni(monkeypatch):
    client, run_turn = _client_capturing_turns(monkeypatch)

    for prompt in ("0.3s fade-in from black, city skyline", "0.3秒 淡入，城市天际线"):
        await client.generate_video(prompt)
        sent = run_turn.await_args.args[1]
        assert "Veo 3.1 - Fast" in sent and "Omni" not in sent, prompt

    # An integral 3s (either unit) still routes to Omni 1.2 Flash
    for prompt in ("city skyline in 3s", "城市天际线，3 秒"):
        await client.generate_video(prompt)
        assert "Omni 1.2 Flash" in run_turn.await_args.args[1], prompt


@pytest.mark.asyncio
@pytest.mark.parametrize("prompt", ["0.13秒", "13秒", "23 秒", "13s clip", "23 seconds"])
async def test_generate_video_only_exactly_three_seconds_routes_to_omni(monkeypatch, prompt):
    """Neither branch may read the trailing 3 of a longer or fractional number as 3s."""
    client, run_turn = _client_capturing_turns(monkeypatch)
    await client.generate_video(prompt)
    sent = run_turn.await_args.args[1]
    assert "Omni" not in sent and "Veo 3.1 - Fast" in sent


@pytest.mark.asyncio
async def test_generate_video_fractional_seconds_keep_default_duration_clause(monkeypatch):
    client, run_turn = _client_capturing_turns(monkeypatch)

    # Default I2V (Omni): "0.3s fade-in" is a cue, so the 3s directive must still be written
    await client.generate_video("0.3s fade-in from black, city skyline", start_image="media-img")
    sent = run_turn.await_args.args[1]
    assert "Omni 1.2 Flash" in sent and "时长 3 秒" in sent

    # Veo 3.1 - Lite likewise pins its 4s default when the prompt carries "10.5 秒"
    await client.generate_video("10.5 秒 的长镜头", model="Veo 3.1 - Lite")
    assert "时长 4 秒" in run_turn.await_args.args[1]


@pytest.mark.asyncio
async def test_extend_video_fractional_seconds_fall_back_to_default_3s(monkeypatch):
    """A "0.5s fade-out" cue used to parse as 5s, so the turn was requested at the 5s tier."""
    client, run_turn = _client_capturing_turns(
        monkeypatch, medias=({"media_id": "media-src", "workflow_id": ""},), cfg=_OMNI_PRICES
    )
    await client.extend_video("media-src", prompt="0.5s fade-out")
    args, kwargs = run_turn.await_args
    assert "延长 3 秒" in args[1] and "5 秒" not in args[1]
    # A card that states no duration is pinned to the 3s tier
    assert kwargs["verify_cost"]({"cost": 3, "duration_s": None}) is True
    assert kwargs["verify_cost"]({"cost": 30, "duration_s": None}) is False


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
