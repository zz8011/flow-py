"""Agent UI automation for Google Flow AI (flow.google.com).

The current Flow app has no direct generation API: the project page's
right-hand panel is a chat agent that plans the generation and asks for
approval on a confirmation card before spending credits. This driver
implements the flow verified live on 2026-11-18:

  * open panel / new conversation via the edit_square button
  * type into the ProseMirror editor, send with the arrow_forward button
  * a bare prompt makes the agent generate IMAGES; a video must be
    requested explicitly ("生成一段视频：…")
  * if the turn fails ("出了点问题" / "Something went wrong"), click its retry control once
  * the confirmation card quotes model + duration + credit cost; the
    caller verifies the quote against the official model-config price
    and only then approves
  * approval MUST be a real input click — synthetic DOM clicks are
    silently ignored, and cards from dead turns carry a `dimmed` class

Completion is detected by the caller through the RPC media list
(flow._rpc.FlowRPC.list_project_media), not by scraping this panel.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Optional, Sequence

from ._exceptions import GenerationError, NotFoundError

log = logging.getLogger(__name__)

# ── Bilingual UI labels (Chinese primary, English fallback) ──────────────────

APPROVE_LABELS = ("批准", "Approve")
RETRY_LABELS = ("重试", "Retry", "Try again")
SAVE_LABELS = ("保存", "Save")
ADD_TO_PROMPT_LABELS = ("添加到提示", "Add to prompt")
UPLOAD_MEDIA_LABELS = ("上传媒体", "Upload media", "Upload")
SETTINGS_ARIA_LABELS = ("设置", "Settings")
BACK_ARIA_LABELS = ("返回", "Back")
CLEAR_PROMPT_ARIA_LABELS = ("清除提示", "Clear prompt")
ADD_MEDIA_ARIA_LABELS = (
    "在提示框中添加素材",
    "Add media to prompt",
    "Add media",
    "Add ingredients",
)
SEARCH_ASSET_ARIA_LABELS = (
    "搜索资源",
    "Search assets",
    "Search media",
    "Search",
)
STOP_ARIA_LABELS = ("停止", "Stop", "Stop generating")
DOWNLOAD_MEDIA_ARIA_LABELS = ("下载媒体内容", "Download media", "Download")
CONFIRM_ALWAYS_LABELS = ("始终", "Always")
UPSCALE_LABELS = ("高清重塑", "Upscaled", "Upscale")
ERROR_TEXTS = ("出了点问题", "Something went wrong")


def build_aria_selector(
    tag: str,
    labels: Sequence[str],
    *,
    prefix: str = "",
    suffix: str = "",
) -> str:
    """Build a comma-separated CSS selector matching any aria-label in *labels*."""
    parts = []
    for label in labels:
        escaped = label.replace("\\", "\\\\").replace("'", "\\'")
        ci_flag = " i" if any(c.isascii() and c.isalpha() for c in label) else ""
        parts.append(f"{prefix}{tag}[aria-label='{escaped}'{ci_flag}]{suffix}")
    return ", ".join(parts)


def matches_any_label(text: str, labels: Sequence[str], *, exact: bool = True) -> bool:
    """Return True if *text* matches any label in *labels* (case-insensitive for ASCII)."""
    cleaned = (text or "").strip()
    if not cleaned:
        return False
    lowered = cleaned.lower()
    for label in labels:
        target = label.strip().lower()
        if exact and lowered == target:
            return True
        if not exact and target in lowered:
            return True
    return False


def parse_credit_cost(text: str) -> Optional[int]:
    """Extract the quoted credit cost — the points that will be charged — from CN/EN UI text."""
    if not text:
        return None
    m = re.search(r"消耗\s*(\d+)\s*个?点数", text)
    if m:
        return int(m.group(1))
    # A balance is not a quote: drop "Balance[:]? N credits" first, otherwise
    # "Balance: 0 credits. 50 credits will be charged" would parse as 0.
    text = re.sub(r"\bbalance\b\s*:?\s*\d[\d,]*\s*credits?\b", " ", text, flags=re.I)
    # "50 credits will be charged" is the most explicit form, so it wins over verb forms
    m = re.search(r"\b(\d+)\s*credits?\s+will\s+be\s+charged\b", text, re.I)
    if not m:
        m = re.search(
            r"\b(?:use|uses|using|spend|spends|spending|cost|costs|costing|for|requires?)"
            r"\s*:?\s+(\d+)\s*credits?\b",
            text,
            re.I,
        )
    if m:
        return int(m.group(1))
    m = re.search(r"\b(\d+)\s*credits?\b", text, re.I)
    if m:
        return int(m.group(1))
    return None


def has_nonzero_credit_quote(text: str) -> bool:
    """Return True if *text* quotes a non-zero or unparseable credit charge."""
    if not text:
        return False
    cost = parse_credit_cost(text)
    if cost is not None:
        return cost > 0
    # Bare 免费 / free never clears a charge word ("Try free! Additional credits apply" must
    # abort). Only an explicit negation, or an explicit zero quote, clears the points it
    # mentions, so a charge word left outside one — 消耗 / credits / 点数 / 积分 — fails closed.
    rest = re.sub(
        r"no\s+credits?\s+(?:will\s+be\s+)?charged"
        r"|(?:不|无需|无须|不用|不会|不必)(?:消耗|扣除?|使用|花(?:费)?)?\s*(?:点数|积分)"
        r"|(?<![\d.])0\s*个?\s*(?:点数|积分)",
        " ",
        text,
        flags=re.I,
    )
    return bool(re.search(r"消耗|点数|积分|\bcredits?\b", rest, re.I))


def parse_duration_s(text: str) -> Optional[int]:
    """Extract a video duration in seconds from Chinese or English text.

    A decimal second ("0.5s fade-out", "10.5 秒") is a timing cue, not a duration: it
    returns None so callers fall back to their default instead of the fractional digits.
    """
    if not text:
        return None
    m = re.search(r"(?<![\d.])(\d+)\s*秒", text)
    if m:
        return int(m.group(1))
    m = re.search(r"(?<![\d.])(\d+)\s*-?\s*(?:seconds?|secs?)\b", text, re.I)
    if m:
        return int(m.group(1))
    m = re.search(r"(?<![\d.])(\d{1,2})s\b", text, re.I)
    if m:
        return int(m.group(1))
    return None


async def _locate_first_by_text(page, labels: Sequence[str], *, exact: bool = True):
    """Return the first Playwright locator matching any label in *labels*, or None."""
    for label in labels:
        loc = page.get_by_text(label, exact=exact)
        if await loc.count() > 0:
            return loc
    return None


_APPROVE_LABELS_JS = json.dumps([s.lower() for s in APPROVE_LABELS], ensure_ascii=False)
_ERROR_TEXTS_JS = json.dumps([s.lower() for s in ERROR_TEXTS], ensure_ascii=False)

_FIND_LIVE_APPROVE = f"""() => {{
  const labels = {_APPROVE_LABELS_JS};
  const els = Array.from(document.querySelectorAll('span, div, button'));
  const hits = els.filter(e => labels.includes((e.innerText || '').trim().toLowerCase())
    && !(e.className || '').toString().includes('dimmed'));
  return hits.length;
}}"""

_CARD_TEXT = f"""() => {{
  const labels = {_APPROVE_LABELS_JS};
  const hasCost = t => t.includes('点数') || /\\bcredits?\\b/i.test(t);
  const hasDur = t => t.includes('秒') || /\\b\\d+\\s*(?:-?\\s*(?:seconds?|secs?)|s)\\b/i.test(t);
  const els = Array.from(document.querySelectorAll('span, div, button'));
  const hits = els.filter(e => labels.includes((e.innerText || '').trim().toLowerCase())
    && !(e.className || '').toString().includes('dimmed'));
  if (!hits.length) return '';
  const hit = hits[hits.length - 1];
  const row = hit.closest('.agent-row, flow-chat-bubble, .agent-bubble, .agent-message-content');
  if (row && hasCost(row.innerText || '')) return row.innerText;
  let e = hit;
  let best = '';
  let bestFull = '';
  for (let i = 0; i < 8 && e; i++) {{
    if (e.classList && e.classList.contains('messages-list')) break;
    const t = (e.innerText || '');
    if (hasCost(t)) {{
      if (t.length > best.length) best = t;
      if (hasDur(t) && t.length > bestFull.length) bestFull = t;
    }}
    e = e.parentElement;
  }}
  return bestFull || best;
}}"""

_HAS_ERROR = (
    "() => { const body = (document.body.innerText || '').toLowerCase(); "
    f"return {_ERROR_TEXTS_JS}.some(t => body.includes(t)); }}"
)
_CONFIRMED_PROJECTS: set[str] = set()


class AgentUI:
    """Drive the creation-agent panel on a flow.google.com project page."""

    def __init__(self, browser_manager, project_id: str):
        self._bm = browser_manager
        self.project_id = project_id
        self.project_url = f"https://flow.google.com/project/{project_id}"

    async def _close_overlays(self, page) -> None:
        for _ in range(3):
            if not await page.locator(".cdk-overlay-backdrop").count():
                break
            try:
                await page.locator(".cdk-overlay-backdrop").last.click(
                    force=True, position={"x": 5, "y": 5}, timeout=3000
                )
            except Exception:
                await page.keyboard.press("Escape")
            await asyncio.sleep(0.8)

    async def _find_box(self, page):
        for sel in ("textarea", "[contenteditable='true']", "[role='textbox']"):
            loc = page.locator(sel)
            for i in range(await loc.count()):
                el = loc.nth(i)
                try:
                    if await el.is_visible():
                        return el
                except Exception:
                    continue
        return None

    async def _ensure_confirm_always(self, page) -> None:
        """Verify once per project that agent confirmation before generation is ON."""
        if self.project_id in _CONFIRMED_PROJECTS:
            return
        try:
            tune = page.locator(
                build_aria_selector("button", SETTINGS_ARIA_LABELS, suffix=":has-text('tune')")
            ).last
            if await tune.count() == 0:
                tune = page.locator("button:has-text('tune')").last
            if await tune.count() == 0:
                return
            await tune.click(timeout=5000)
            await asyncio.sleep(1.5)
            radios = page.locator("input.mdc-radio__native-control")
            radio_count = await radios.count()
            if radio_count >= 1:
                target_radio = radios.first
                for i in range(radio_count):
                    cand = radios.nth(i)
                    try:
                        label_text = await cand.evaluate(
                            "el => (el.closest('mat-radio-button, .mdc-form-field, label')?.innerText || '')"
                        )
                    except Exception:
                        label_text = ""
                    if any(lbl.lower() in label_text.lower() for lbl in CONFIRM_ALWAYS_LABELS):
                        target_radio = cand
                        break
                first_checked = await target_radio.is_checked()
                if not first_checked:
                    await target_radio.click(force=True)
                    await asyncio.sleep(0.8)
                    save_btn = await _locate_first_by_text(page, SAVE_LABELS, exact=True)
                    if save_btn is not None:
                        await save_btn.last.click(timeout=5000)
                        await asyncio.sleep(1.5)
                        _CONFIRMED_PROJECTS.add(self.project_id)
                        return
            back = page.locator(build_aria_selector("button", BACK_ARIA_LABELS)).last
            if await back.count() == 0:
                back = page.locator("button:has-text('arrow_back')").last
            if await back.count() > 0:
                await back.click(timeout=5000)
                await asyncio.sleep(1.0)
            _CONFIRMED_PROJECTS.add(self.project_id)
        except Exception:
            await self._close_overlays(page)

    async def open_session(self, page):
        """Open the project page, open the agent panel, start a new chat."""
        await self._close_overlays(page)
        await page.goto(self.project_url, wait_until="domcontentloaded", timeout=30_000)
        await asyncio.sleep(6)
        box = await self._find_box(page)
        if box is None:
            comp = page.locator("button:has-text('edit_square')").first
            if await comp.count() > 0:
                await comp.click()
                await asyncio.sleep(3)
                box = await self._find_box(page)
        if box is None:
            raise GenerationError("Agent panel editor not found on project page")
        await self._ensure_confirm_always(page)
        # Fresh conversation (edit_square = new-session in this panel).
        try:
            await page.locator("button:has-text('edit_square')").last.click(timeout=5000)
            await asyncio.sleep(3)
        except Exception:
            pass  # already in a fresh session
        if await page.locator("flow-ingredient-chip").count() > 0:
            clear_btn = page.locator(build_aria_selector("button", CLEAR_PROMPT_ARIA_LABELS))
            if await clear_btn.count() > 0:
                try:
                    await clear_btn.last.click(timeout=3000)
                    await asyncio.sleep(1)
                except Exception:
                    pass
        box = await self._find_box(page)
        if box is None:
            raise GenerationError("Agent editor lost after starting new session")
        return box

    async def _chip_matches(self, page, valid_ids: list[str], valid_toks: list[str]) -> bool:
        for i in valid_ids:
            if i and await page.locator(f"flow-ingredient-chip img[src*='{i}']").count() > 0:
                return True
        for t in valid_toks:
            if t and await page.locator(f"flow-ingredient-chip img[src*='{t}']").count() > 0:
                return True
        return False

    async def _open_asset_picker(self, page) -> None:
        await self._close_overlays(page)
        await page.locator(build_aria_selector("button", ADD_MEDIA_ARIA_LABELS)).last.click(
            timeout=8000
        )
        await asyncio.sleep(2.0)

    async def _select_and_add_row(self, page, row) -> None:
        cls = await row.get_attribute("class") or ""
        if "asset-item-active" not in cls:
            await row.click(timeout=5000)
            await asyncio.sleep(1.0)
        add_btn = page.locator(
            ".cdk-overlay-container button.detail-add-to-prompt-btn"
        )
        if await add_btn.count() == 0:
            add_btn = await _locate_first_by_text(page, ADD_TO_PROMPT_LABELS, exact=True)
        if add_btn is not None and await add_btn.count() > 0:
            await add_btn.last.click(timeout=5000)
            await asyncio.sleep(1.5)
        await self._close_overlays(page)

    async def attach_media(self, page, pm: dict, media_id: str) -> dict:
        """Attach a project media item to the prompt box and verify its chip."""
        target = next(
            (m for m in pm.get("medias", [])
             if m["media_id"] == media_id or m["media_id"].startswith(media_id)),
            None,
        )
        if target is None:
            raise NotFoundError(f"Media {media_id} not found in project {self.project_id}")
        mid = target["media_id"]
        wf_id = target.get("workflow_id") or ""
        wf_medias = [
            m for m in pm.get("medias", [])
            if m["media_id"] == mid or (wf_id and m.get("workflow_id") == wf_id)
        ]
        valid_ids = [m["media_id"].replace("_upsampled", "") for m in wf_medias]
        valid_toks = [
            m["poster_url"].split("/asb/")[-1][:60]
            for m in wf_medias
            if "/asb/" in (m.get("poster_url") or "")
        ]
        if await self._chip_matches(page, valid_ids, valid_toks):
            return target

        await self._open_asset_picker(page)

        # Strategy 1: direct match by media_id or workflow poster token(s)
        direct_selectors = [
            f".cdk-overlay-container button.asset-item:has([src*='{i}'])"
            for i in dict.fromkeys(valid_ids) if i
        ] + [
            f".cdk-overlay-container button.asset-item:has([src*='{t}'])"
            for t in dict.fromkeys(valid_toks) if t
        ]
        for sel in direct_selectors:
            loc = page.locator(sel)
            if await loc.count() == 1:
                await self._select_and_add_row(page, loc.first)
                if await self._chip_matches(page, valid_ids, valid_toks):
                    return target

        # Strategy 2: search by workflow display_name and verify chip per candidate row
        title = (target.get("display_name") or "").strip()
        for idx in range(6):
            if await page.locator(".cdk-overlay-container button.asset-item").count() == 0:
                await self._open_asset_picker(page)
            if title:
                search = page.locator(
                    build_aria_selector(
                        "input", SEARCH_ASSET_ARIA_LABELS, prefix=".cdk-overlay-container "
                    )
                ).first
                if await search.count() > 0:
                    await search.fill(title[:40])
                    await asyncio.sleep(1.8)
            rows = page.locator(".cdk-overlay-container button.asset-item")
            if idx >= await rows.count():
                break
            await self._select_and_add_row(page, rows.nth(idx))
            if await self._chip_matches(page, valid_ids, valid_toks):
                return target
            # Wrong duplicate media attached; reset session before next row
            await self.open_session(page)

        await self._close_overlays(page)
        raise GenerationError(f"Could not attach media {mid} in agent asset picker")

    async def upload_media(self, page, rpc, file_path: str) -> dict:
        """Upload a local media file into the project and attach its chip."""
        p = Path(file_path).expanduser().resolve()
        if not p.is_file():
            raise NotFoundError(f"Local media file not found: {file_path}")
        before = {
            m["media_id"]
            for m in (await rpc.list_project_media(self.project_id))["medias"]
        }
        await self._open_asset_picker(page)
        upload_btn = await _locate_first_by_text(page, UPLOAD_MEDIA_LABELS, exact=True)
        if upload_btn is None:
            await self._close_overlays(page)
            raise GenerationError("Upload media trigger not found in asset picker")
        async with page.expect_file_chooser(timeout=15_000) as fc:
            await upload_btn.last.click(timeout=8000)
        chooser = await fc.value
        await chooser.set_files(str(p))

        new_id = None
        for _ in range(20):
            await asyncio.sleep(2.5)
            pm = await rpc.list_project_media(self.project_id)
            for m in pm["medias"]:
                if m["media_id"] not in before:
                    new_id = m["media_id"]
                    break
            if new_id:
                await self._close_overlays(page)
                return await self.attach_media(page, pm, new_id)
        await self._close_overlays(page)
        raise GenerationError(f"Uploaded file {p.name} did not appear in project media list")

    async def attach_or_upload(self, page, rpc, pm: dict, media_or_path: str) -> dict:
        """Attach either a local file path or an existing project media_id."""
        if Path(media_or_path).expanduser().is_file():
            return await self.upload_media(page, rpc, media_or_path)
        return await self.attach_media(page, pm, media_or_path)

    async def _submit(self, page, box, text: str):
        try:
            await box.click(timeout=8000)
        except Exception:
            await box.evaluate("e => e.focus()")
        await asyncio.sleep(0.5)
        await page.keyboard.type(text, delay=25)
        await asyncio.sleep(0.5)
        await page.locator("button:has-text('arrow_forward')").last.click(timeout=15_000)

    async def _click_retry_once(self, page) -> bool:
        for label in RETRY_LABELS:
            retry = page.get_by_text(label, exact=True)
            for i in range(await retry.count()):
                el = retry.nth(i)
                try:
                    if await el.is_visible():
                        await el.click(timeout=8000)
                        return True
                except Exception:
                    continue
        return False

    async def _wait_card(self, page, timeout_s: float) -> Optional[str]:
        """Wait for a live confirmation card; retry a failed turn once."""
        deadline = asyncio.get_event_loop().time() + timeout_s
        retried = False
        idle_ticks = 0
        stop_sel = (
            build_aria_selector("button", STOP_ARIA_LABELS, prefix="flow-base-prompt-box ")
            + ", flow-base-prompt-box button:has-text('stop')"
        )
        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(4)
            try:
                if await page.evaluate(_FIND_LIVE_APPROVE):
                    await asyncio.sleep(1.5)
                    return await page.evaluate(_CARD_TEXT)
                if not retried and await page.evaluate(_HAS_ERROR):
                    if await self._click_retry_once(page):
                        retried = True
                        idle_ticks = 0
                        continue
                busy = await page.locator(stop_sel).count()
                if not busy:
                    idle_ticks += 1
                    if idle_ticks >= 3:
                        return None
                else:
                    idle_ticks = 0
            except Exception:
                continue
        return None

    async def _approve(self, page) -> bool:
        """Real-input click on the live card's approve label (never DOM click)."""
        for label in APPROVE_LABELS:
            loc = page.get_by_text(label, exact=True)
            for i in range(await loc.count()):
                el = loc.nth(i)
                try:
                    cls = await el.evaluate("e => (e.className || '').toString()")
                    if "dimmed" in cls:
                        continue
                    if await el.is_visible():
                        await el.click(timeout=8000)
                        return True
                except Exception:
                    continue
        return False

    @staticmethod
    def parse_card(card_text: str) -> dict:
        """Extract {cost, duration_s, raw} from a confirmation card's text."""
        return {
            "cost": parse_credit_cost(card_text or ""),
            "duration_s": parse_duration_s(card_text or ""),
            "raw": card_text or "",
        }

    async def run_turn(self, page, text: str, *, card_timeout_s: float = 150,
                       verify_cost=None, require_card: bool = False) -> dict:
        """Submit one agent turn and approve its confirmation card.

        ``verify_cost`` is an optional callable(parsed_card) -> bool; when
        it returns False the card is NOT approved and GenerationError is
        raised — the tool never approves a quote it could not verify.
        Turns that produce no card at all (e.g. free image generations)
        return {"cost": None, "no_card": True} unless ``require_card`` is True.
        """
        box = await self._find_box(page)
        if box is None:
            raise GenerationError("Agent editor not available for new turn")
        await self._submit(page, box, text)
        card_text = await self._wait_card(page, card_timeout_s)
        if card_text is None:
            if require_card:
                raise GenerationError(
                    "Agent turn finished without presenting a confirmation card"
                )
            return {"cost": None, "duration_s": None, "no_card": True, "raw": ""}
        parsed = self.parse_card(card_text)
        if verify_cost is not None and not verify_cost(parsed):
            raise GenerationError(
                "Confirmation card quote could not be verified against the "
                f"official price — NOT approving. Card: {parsed}"
            )
        if not await self._approve(page):
            raise GenerationError("Approval click failed on confirmation card")
        parsed["no_card"] = False
        return parsed
