"""High-level UI interaction helpers for Google Flow AI.

Covers both the PROJECT page (prompt/settings/submit) and the EDIT page
(extend, camera, insert, remove, upscale, download).

Key insight: Flow has NO mode tabs on the project page. Instead, clicking
the model selector pill opens a settings panel with Image/Video/Aspect/Count.

Edit page layout (from live DOM inspection):
  - Extend / Insert / Remove / Camera buttons across the bottom toolbar
  - Create button submits each operation
  - Download button in top-right corner
  - Model selector dropdown in toolbar
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from ._models import AspectRatio, GenerationMode

log = logging.getLogger(__name__)

# Text found on mode buttons after opening the settings panel
_MODE_BUTTON_TEXT = {
    GenerationMode.IMAGE: ["Image", "imageImage"],
    GenerationMode.VIDEO: ["Video", "videocamVideo"],
    GenerationMode.FRAME_TO_VIDEO: ["Video", "videocamVideo"],
}

# Aspect ratio button texts in the settings panel
_ASPECT_BUTTON_TEXT = {
    AspectRatio.LANDSCAPE: ["Landscape", "crop_16_9Landscape"],
    AspectRatio.PORTRAIT:  ["Portrait",  "crop_9_16Portrait"],
    AspectRatio.SQUARE:    ["Square",    "crop_1_1Square"],
}

# Count button texts
_COUNT_BUTTON_TEXT = {"1": "x1", "2": "x2", "3": "x3", "4": "x4"}

# The settings panel trigger: the model selector pill
# Project page bottom bar shows "Video □ x1" or model name like "Nano Banana 2 … x2"
_SETTINGS_PILL_TEXTS = ["Nano Banana", "Veo", "Imagen", "\U0001f34c", "Video", "Image"]


class FlowUI:
    """Knows the exact selector patterns for labs.google/fx/tools/flow."""

    # ==================================================================
    # PROJECT PAGE — Navigation / Settings / Prompt / Submit
    # ==================================================================

    async def navigate_to_project(self, page, project_url: str) -> None:
        if project_url.rstrip("/") in page.url:
            return
        await page.goto(project_url, wait_until="domcontentloaded", timeout=30_000)
        await asyncio.sleep(2)

    async def navigate_to_edit(self, page, project_id: str, workflow_id: str) -> None:
        """Navigate to the edit view for a specific workflow."""
        url = f"https://labs.google/fx/tools/flow/project/{project_id}/edit/{workflow_id}"
        if url.rstrip("/") in page.url:
            return
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        await asyncio.sleep(2)

    # ------------------------------------------------------------------
    # Settings panel
    # ------------------------------------------------------------------

    async def open_settings_panel(self, page) -> bool:
        """Open the generation settings panel (Image/Video mode, aspect, count).

        The panel is triggered by clicking the mode/count pill at the bottom bar.
        On the project page this pill shows: "Video □ x1" or "Nano Banana 2 … x2".

        Returns True if panel is open (or was already open).
        """
        # Wait for React to hydrate — buttons may not exist on domcontentloaded
        try:
            await page.wait_for_selector('button', timeout=8000)
        except Exception:
            pass
        await asyncio.sleep(0.5)

        already_open = await self._settings_visible(page)
        if already_open:
            return True

        # Strategy 1: click by known pill text fragments
        for text in _SETTINGS_PILL_TEXTS:
            clicked = await page.evaluate(f"""
                () => {{
                    const btns = [...document.querySelectorAll('button')];
                    const b = btns.find(btn => btn.textContent.includes('{text}'));
                    if (b) {{ b.click(); return true; }}
                    return false;
                }}
            """)
            if clicked:
                await asyncio.sleep(0.8)
                if await self._settings_visible(page):
                    log.debug("Settings panel opened via text '%s'", text)
                    return True

        # Strategy 2: click the count selector (always has "x1" or "x2" etc.)
        clicked = await page.evaluate("""
            () => {
                const btns = [...document.querySelectorAll('button')];
                // The count pill has exactly the pattern "x1", "x2", etc. in its text
                const pill = btns.find(b => /x[1-4]/.test(b.textContent.trim()));
                if (pill) { pill.click(); return pill.textContent.trim(); }
                return null;
            }
        """)
        if clicked:
            await asyncio.sleep(0.8)
            if await self._settings_visible(page):
                log.debug("Settings panel opened via count pill '%s'", clicked)
                return True

        log.warning("Could not open settings panel (no pill found)")
        return False

    async def _settings_visible(self, page) -> bool:
        """Check if the mode/aspect/count tabs are visible (settings panel open)."""
        count = await page.evaluate("""
            () => {
                // Settings panel has role=tab elements for Image/Video/aspect/count
                const tabs = document.querySelectorAll('[role=tab]');
                return tabs.length;
            }
        """)
        return int(count or 0) > 0

    # ------------------------------------------------------------------
    # Mode switching
    # ------------------------------------------------------------------

    async def switch_mode(self, page, mode: GenerationMode) -> bool:
        await self.open_settings_panel(page)
        label_map = {
            GenerationMode.IMAGE:          ["Image", "image Image"],
            GenerationMode.VIDEO:          ["Video", "videocam Video"],
            GenerationMode.FRAME_TO_VIDEO: ["Frames", "crop_free Frames", "Video"],
        }
        for label in label_map.get(mode, []):
            tab = page.get_by_role("tab", name=label, exact=True).first
            if await tab.count() > 0:
                await tab.click()
                await asyncio.sleep(0.4)
                return True
            tab = page.locator("[role='tab']").filter(has_text=label.split()[-1]).first
            if await tab.count() > 0:
                await tab.click()
                await asyncio.sleep(0.4)
                return True
        log.warning("Could not find mode tab for %s", mode.value)
        return False

    # ------------------------------------------------------------------
    # Aspect ratio
    # ------------------------------------------------------------------

    async def set_aspect_ratio(self, page, ratio: AspectRatio) -> bool:
        await self.open_settings_panel(page)
        label_map = {
            AspectRatio.LANDSCAPE: ["Landscape", "crop_16_9 Landscape"],
            AspectRatio.PORTRAIT:  ["Portrait",  "crop_9_16 Portrait"],
            AspectRatio.SQUARE:    ["Square",    "crop_1_1 Square"],
        }
        for label in label_map.get(ratio, []):
            tab = page.get_by_role("tab", name=label, exact=True).first
            if await tab.count() > 0:
                await tab.click()
                await asyncio.sleep(0.3)
                return True
            tab = page.locator("[role='tab']").filter(has_text=label.split()[-1]).first
            if await tab.count() > 0:
                await tab.click()
                await asyncio.sleep(0.3)
                return True
        log.warning("Could not find aspect ratio tab for %s", ratio.value)
        return False

    # ------------------------------------------------------------------
    # Count
    # ------------------------------------------------------------------

    async def set_count(self, page, count: int) -> bool:
        await self.open_settings_panel(page)
        count = max(1, min(4, count))
        label = f"x{count}"
        tab = page.get_by_role("tab", name=label, exact=True).first
        if await tab.count() > 0:
            await tab.click()
            await asyncio.sleep(0.3)
            return True
        log.warning("Could not set count to %d", count)
        return False

    # ------------------------------------------------------------------
    # Prompt input
    # ------------------------------------------------------------------

    async def fill_prompt(self, page, prompt: str) -> bool:
        try:
            await page.keyboard.press("Escape")
            await asyncio.sleep(0.3)
            await page.keyboard.press("Escape")
            await asyncio.sleep(0.2)
        except Exception:
            pass

        els = page.locator("div[contenteditable]")
        count = await els.count()
        for i in range(count):
            el = els.nth(i)
            visible = await el.evaluate(
                "el => el.offsetWidth > 0 && el.offsetHeight > 0 && el.getBoundingClientRect().y > 100"
            )
            if not visible:
                continue
            await el.scroll_into_view_if_needed()
            await asyncio.sleep(0.2)
            await el.click()
            await asyncio.sleep(0.3)
            focused_tag = await page.evaluate(
                "() => document.activeElement.tagName + '|' + document.activeElement.contentEditable"
            )
            if "true" not in focused_tag.lower():
                continue
            await page.keyboard.press("Meta+a")
            await page.keyboard.press("Control+a")
            await asyncio.sleep(0.1)
            await page.keyboard.type(prompt, delay=15)
            await asyncio.sleep(0.2)
            content = await el.text_content()
            if prompt[:10] in (content or ""):
                return True
        log.warning("Could not fill prompt input")
        return False

    # ------------------------------------------------------------------
    # Submit (project page Create button)
    # ------------------------------------------------------------------

    async def click_submit(self, page) -> bool:
        clicked = await page.evaluate("""
            () => {
                const btns = [...document.querySelectorAll('button')];
                const creates = btns.filter(b =>
                    b.textContent.trim().includes('Create') && !b.disabled
                );
                if (creates.length > 0) {
                    creates[creates.length - 1].click();
                    return true;
                }
                return false;
            }
        """)
        if clicked:
            return True
        btn = page.locator("button").filter(has_text="arrow_forward").last
        if await btn.count() > 0:
            await btn.click()
            return True
        log.warning("Could not find submit button")
        return False

    # ------------------------------------------------------------------
    # Image upload (for Frame-to-Video)
    # ------------------------------------------------------------------

    async def upload_image(self, page, image_path: str) -> bool:
        add_btn = page.locator("button").filter(has_text="Add Media").first
        if await add_btn.count() == 0:
            add_btn = page.get_by_text("Add Media").first
        if await add_btn.count() > 0:
            await add_btn.click()
            await asyncio.sleep(1)
        file_input = page.locator("input[type='file']").first
        if await file_input.count() > 0:
            await file_input.set_input_files(image_path)
            await asyncio.sleep(2)
            return True
        try:
            async with page.expect_file_chooser(timeout=3000) as fc_info:
                for sel in ["[aria-label*='upload' i]", ".upload-zone", "[class*='upload']"]:
                    el = page.locator(sel).first
                    if await el.count() > 0:
                        await el.click()
                        break
            fc = await fc_info.value
            await fc.set_files(image_path)
            await asyncio.sleep(2)
            return True
        except Exception as e:
            log.warning("File chooser upload failed: %s", e)
        return False

    # ------------------------------------------------------------------
    # Gallery & media extraction (project page)
    # ------------------------------------------------------------------

    async def count_gallery_items(self, page) -> int:
        count = await page.evaluate("""
            () => document.querySelectorAll(
                'img[src*="getMediaUrlRedirect"], video[src*="getMediaUrlRedirect"]'
            ).length
        """)
        return count or 0

    async def check_policy_error(self, page) -> bool:
        policy_strings = [
            "violates our policy", "content policy", "harmful or unsafe",
            "unable to generate", "request was flagged", "couldn't generate",
        ]
        body = await page.evaluate("() => document.body.innerText")
        body_lower = body.lower()
        return any(s in body_lower for s in policy_strings)

    async def get_newest_media_src(self, page) -> Optional[str]:
        src = await page.evaluate("""
            () => {
                const imgs = [...document.querySelectorAll('img[src*="getMediaUrlRedirect"]')];
                const vids = [...document.querySelectorAll('video[src*="getMediaUrlRedirect"]')];
                const all = [...imgs, ...vids];
                if (!all.length) return null;
                return all[all.length - 1].src || all[all.length - 1].currentSrc;
            }
        """)
        return src or None

    async def get_all_media_srcs(self, page) -> list[str]:
        srcs = await page.evaluate("""
            () => {
                const imgs = [...document.querySelectorAll('img[src*="getMediaUrlRedirect"]')];
                const vids = [...document.querySelectorAll('video[src*="getMediaUrlRedirect"]')];
                return [...imgs, ...vids].map(el => el.src || el.currentSrc).filter(Boolean);
            }
        """)
        return srcs or []

    async def wait_for_generation_complete(
        self, page, before_count: int, timeout_s: int = 300, poll_interval: float = 2.0,
    ) -> bool:
        import time as _time
        deadline = _time.monotonic() + timeout_s
        while _time.monotonic() < deadline:
            if await self.check_policy_error(page):
                return False
            count = await self.count_gallery_items(page)
            if count > before_count:
                break
            await asyncio.sleep(poll_interval)
        else:
            return False
        while _time.monotonic() < deadline:
            src = await self.get_newest_media_src(page)
            if src:
                return True
            await asyncio.sleep(poll_interval)
        return False

    # ==================================================================
    # EDIT PAGE — Extend / Camera / Insert / Remove / Upscale / Download
    # ==================================================================

    async def _click_button_with_text(self, page, texts: list[str], timeout: float = 5) -> bool:
        """Try to click a button matching any of the given text patterns."""
        for text in texts:
            btn = page.locator("button").filter(has_text=text).first
            if await btn.count() > 0:
                try:
                    await btn.click(timeout=timeout * 1000)
                    await asyncio.sleep(0.5)
                    return True
                except Exception:
                    continue
        # JS fallback: find button containing text (escape single quotes)
        for text in texts:
            safe_text = text.replace("'", "\\'")
            clicked = await page.evaluate(f"""
                () => {{
                    const btns = [...document.querySelectorAll('button')];
                    const btn = btns.find(b => b.textContent.includes('{safe_text}') && !b.disabled);
                    if (btn) {{ btn.click(); return true; }}
                    return false;
                }}
            """)
            if clicked:
                await asyncio.sleep(0.5)
                return True
        return False

    # ------------------------------------------------------------------
    # Click a video in the project grid to open edit view
    # ------------------------------------------------------------------

    async def click_video_in_grid(self, page, index: int = 0) -> bool:
        """Click a video/image in the project gallery grid.

        After clicking, the page navigates to the edit view.
        """
        clicked = await page.evaluate(f"""
            () => {{
                const items = document.querySelectorAll(
                    'img[src*="getMediaUrlRedirect"], video[src*="getMediaUrlRedirect"]'
                );
                if (items.length > {index}) {{
                    items[{index}].click();
                    return true;
                }}
                return false;
            }}
        """)
        if clicked:
            await asyncio.sleep(2)
            return True
        return False

    # ------------------------------------------------------------------
    # Extend
    # ------------------------------------------------------------------

    async def click_extend(self, page) -> bool:
        """Click the Extend button in the edit view toolbar."""
        return await self._click_button_with_text(page, [
            "Extend", "extension", "extend",
        ])

    async def fill_extend_prompt(self, page, prompt: str) -> bool:
        """Fill the extend prompt input in the extend panel."""
        els = page.locator("div[contenteditable], textarea")
        count = await els.count()
        for i in range(count):
            el = els.nth(i)
            visible = await el.evaluate(
                "el => el.offsetWidth > 0 && el.offsetHeight > 0"
            )
            if not visible:
                continue
            await el.click()
            await asyncio.sleep(0.2)
            await page.keyboard.press("Meta+a")
            await page.keyboard.press("Control+a")
            await page.keyboard.type(prompt, delay=15)
            await asyncio.sleep(0.2)
            return True
        return False

    async def click_create_in_panel(self, page) -> bool:
        """Click the Create button inside any edit panel (Extend/Camera/Insert/Remove).

        Edit page has two Create buttons:
          1. Camera Create [~560, ~242] — initially DISABLED, enables after motion selection
          2. Main Create   [~1558, ~1109] — always enabled, also serves as Extend/Insert trigger

        For camera mode: we specifically want the [560, 242] button (first one).
        For extend/insert/remove: we want the [1558, 1109] button (last enabled one).

        Strategy: click the LAST enabled Create button (bottom-right of screen), since
        that's the main action trigger across all modes.
        """
        clicked = await page.evaluate("""
            () => {
                const btns = [...document.querySelectorAll('button')];
                // Find ALL enabled buttons containing 'Create'
                const creates = btns.filter(b =>
                    !b.disabled &&
                    (b.textContent.trim().endsWith('Create') ||
                     b.textContent.trim() === 'Create')
                );
                if (creates.length === 0) return null;
                // Click the last one (the main Create button at bottom-right)
                creates[creates.length - 1].click();
                return creates.length;
            }
        """)
        if clicked:
            await asyncio.sleep(0.4)
            log.debug("Clicked Create button (%s found)", clicked)
            return True
        log.warning("No enabled Create button found in panel")
        return False

    async def click_camera_create(self, page, wait_for_enable: float = 5.0) -> bool:
        """Click the Camera-specific Create button (top area, not bottom toolbar).

        The camera Create is at approximately [560, 242] and is initially DISABLED.
        It becomes enabled after selecting a camera motion or position.

        Waits up to *wait_for_enable* seconds for it to become enabled.
        """
        deadline = asyncio.get_event_loop().time() + wait_for_enable
        while asyncio.get_event_loop().time() < deadline:
            result = await page.evaluate("""
                () => {
                    const btns = [...document.querySelectorAll('button')];
                    // Camera Create is near the top (y < 400) and contains 'Create'
                    const camCreates = btns.filter(b => {
                        const r = b.getBoundingClientRect();
                        return r.top < 400 && r.top > 0 &&
                               b.textContent.trim().endsWith('Create') &&
                               !b.disabled;
                    });
                    if (camCreates.length > 0) {
                        camCreates[0].click();
                        return camCreates[0].getBoundingClientRect().top;
                    }
                    return null;
                }
            """)
            if result is not None:
                log.debug("Clicked camera Create at y~%.0f", result)
                return True
            await asyncio.sleep(0.3)

        # Fallback: just click any enabled Create
        return await self.click_create_in_panel(page)

    # ------------------------------------------------------------------
    # Camera
    # ------------------------------------------------------------------

    async def click_camera(self, page) -> bool:
        """Click the Camera button in the edit view toolbar."""
        return await self._click_button_with_text(page, [
            "Camera", "videocam", "camera",
        ])

    async def select_camera_motion(self, page, motion_label: str) -> bool:
        """Select a camera motion preset by its display label.

        Labels: "Dolly in", "Dolly out", "Orbit left", "Orbit right",
                "Orbit up", "Orbit low", "Dolly in zoom out", "Dolly out zoom in"
        """
        # Click the "Camera motion" tab first
        motion_tab = page.locator("[role='tab']").filter(has_text="motion").first
        if await motion_tab.count() > 0:
            await motion_tab.click()
            await asyncio.sleep(0.3)
        elif await page.locator("button").filter(has_text="Motion").first.count() > 0:
            await page.locator("button").filter(has_text="Motion").first.click()
            await asyncio.sleep(0.3)

        return await self._click_button_with_text(page, [motion_label])

    async def select_camera_position(self, page, position_label: str) -> bool:
        """Select a camera position preset.

        Labels: "Center", "Left", "Right", "High", "Low", "Closer", "Further"
        """
        pos_tab = page.locator("[role='tab']").filter(has_text="osition").first
        if await pos_tab.count() > 0:
            await pos_tab.click()
            await asyncio.sleep(0.3)
        elif await page.locator("button").filter(has_text="Position").first.count() > 0:
            await page.locator("button").filter(has_text="Position").first.click()
            await asyncio.sleep(0.3)

        return await self._click_button_with_text(page, [position_label])

    # ------------------------------------------------------------------
    # Insert object
    # ------------------------------------------------------------------

    async def click_insert(self, page) -> bool:
        """Click the Insert button in the edit view toolbar."""
        return await self._click_button_with_text(page, [
            "Insert", "add_circle", "insert",
        ])

    async def fill_insert_prompt(self, page, prompt: str) -> bool:
        """Fill the insert object prompt."""
        return await self.fill_extend_prompt(page, prompt)

    # ------------------------------------------------------------------
    # Remove object
    # ------------------------------------------------------------------

    async def click_remove(self, page) -> bool:
        """Click the Remove button in the edit view toolbar."""
        return await self._click_button_with_text(page, [
            "Remove", "remove_circle", "remove",
        ])

    async def draw_removal_mask(self, page, x_pct: float, y_pct: float, radius_pct: float = 0.1) -> bool:
        """Draw a removal mask on the video preview at a percentage position.

        Args:
            x_pct: X position as fraction (0.0 = left, 1.0 = right)
            y_pct: Y position as fraction (0.0 = top, 1.0 = bottom)
            radius_pct: Brush radius as fraction of video width
        """
        drawn = await page.evaluate(f"""
            () => {{
                const canvas = document.querySelector('canvas');
                const video = document.querySelector('video');
                const target = canvas || video;
                if (!target) return false;
                const rect = target.getBoundingClientRect();
                const x = rect.left + rect.width * {x_pct};
                const y = rect.top + rect.height * {y_pct};

                const events = ['pointerdown', 'pointermove', 'pointerup'];
                for (const type of events) {{
                    const evt = new PointerEvent(type, {{
                        clientX: x, clientY: y,
                        bubbles: true, cancelable: true,
                        pointerId: 1, pointerType: 'mouse',
                    }});
                    target.dispatchEvent(evt);
                }}
                return true;
            }}
        """)
        if drawn:
            await asyncio.sleep(0.5)
        return drawn or False

    # ------------------------------------------------------------------
    # Download / Upscale
    # ------------------------------------------------------------------

    async def click_download_button(self, page) -> bool:
        """Click the Download button in the edit view (top-right area)."""
        return await self._click_button_with_text(page, [
            "Download", "download", "file_download",
        ])

    async def click_upscale_1080p(self, page) -> bool:
        """Click '1080p Upscaled' in the download dropdown."""
        return await self._click_button_with_text(page, [
            "1080p", "1080p Upscaled", "Upscaled",
        ])

    async def click_upscale_4k(self, page) -> bool:
        """Click '4K Upscaled' in the download dropdown (if available)."""
        return await self._click_button_with_text(page, [
            "4K", "4K Upscaled",
        ])

    # ------------------------------------------------------------------
    # Model selector (edit page)
    # ------------------------------------------------------------------

    async def get_video_model_selector(self, page) -> str:
        """Return the currently displayed model name from the model selector."""
        text = await page.evaluate("""
            () => {
                const btns = [...document.querySelectorAll('button')];
                const model = btns.find(b =>
                    b.textContent.includes('Veo') ||
                    b.textContent.includes('veo') ||
                    b.textContent.includes('3.1') ||
                    b.textContent.includes('2.1')
                );
                return model ? model.textContent.trim() : '';
            }
        """)
        return text or ""

    async def select_video_model(self, page, model_display_name: str) -> bool:
        """Open model dropdown and select a model by display name."""
        current = await self.get_video_model_selector(page)
        if current:
            model_btn = page.locator("button").filter(has_text=current.split()[0]).first
            if await model_btn.count() > 0:
                await model_btn.click()
                await asyncio.sleep(0.5)
        return await self._click_button_with_text(page, [model_display_name])

    # ------------------------------------------------------------------
    # Screenshot helper
    # ------------------------------------------------------------------

    async def screenshot(self, page, path: str) -> None:
        try:
            await page.screenshot(path=path, full_page=False)
        except Exception as e:
            log.warning("Screenshot failed: %s", e)

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    async def get_project_url_from_page(self, page) -> Optional[str]:
        url = page.url
        if "/project/" in url:
            return url
        return None


# ═══════════════════════════════════════════════════════════════════════════
# Agent UI (flow.google.com, 2026 app) — added by the flow-py patch.
#
# The current Flow app has no direct generation API: the project page's
# right-hand panel is a chat agent that plans the generation and asks for
# approval on a confirmation card before spending credits. This driver
# implements the flow verified live on 2026-11-18:
#
#   * open panel / new conversation via the edit_square button
#   * type into the ProseMirror editor, send with the arrow_forward button
#   * a bare prompt makes the agent generate IMAGES; a video must be
#     requested explicitly ("生成一段视频：…")
#   * if the turn fails ("出了点问题"), click its 重试 control once
#   * the confirmation card quotes model + duration + credit cost; the
#     caller verifies the quote against the official model-config price
#     and only then approves
#   * approval MUST be a real input click — synthetic DOM clicks are
#     silently ignored, and cards from dead turns carry a `dimmed` class
#
# Completion is detected by the caller through the RPC media list
# (flow._rpc.FlowRPC.list_project_media), not by scraping this panel.
# ═══════════════════════════════════════════════════════════════════════════

from pathlib import Path
import re

from ._exceptions import GenerationError, NotFoundError

_FIND_LIVE_APPROVE = """() => {
  const els = Array.from(document.querySelectorAll('span, div, button'));
  const hits = els.filter(e => (e.innerText || '').trim() === '批准'
    && !(e.className || '').toString().includes('dimmed'));
  return hits.length;
}"""

_CARD_TEXT = """() => {
  const els = Array.from(document.querySelectorAll('span, div, button'));
  const hits = els.filter(e => (e.innerText || '').trim() === '批准'
    && !(e.className || '').toString().includes('dimmed'));
  if (!hits.length) return '';
  const hit = hits[hits.length - 1];
  const row = hit.closest('.agent-row, flow-chat-bubble, .agent-bubble, .agent-message-content');
  if (row && (row.innerText || '').includes('点数')) return row.innerText;
  let e = hit;
  let best = '';
  let bestFull = '';
  for (let i = 0; i < 8 && e; i++) {
    if (e.classList && e.classList.contains('messages-list')) break;
    const t = (e.innerText || '');
    if (t.includes('点数')) {
      if (t.length > best.length) best = t;
      if (t.includes('秒') && t.length > bestFull.length) bestFull = t;
    }
    e = e.parentElement;
  }
  return bestFull || best;
}"""

_HAS_ERROR = "() => document.body.innerText.includes('出了点问题')"
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
            tune = page.locator("button[aria-label='设置']:has-text('tune')").last
            if await tune.count() == 0:
                return
            await tune.click(timeout=5000)
            await asyncio.sleep(1.5)
            radios = page.locator("input.mdc-radio__native-control")
            if await radios.count() >= 1:
                first_checked = await radios.first.is_checked()
                if not first_checked:
                    await radios.first.click(force=True)
                    await asyncio.sleep(0.8)
                    save_btn = page.get_by_text("保存", exact=True).last
                    if await save_btn.count() > 0:
                        await save_btn.click(timeout=5000)
                        await asyncio.sleep(1.5)
                        _CONFIRMED_PROJECTS.add(self.project_id)
                        return
            back = page.locator("button[aria-label='返回']").last
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
            clear_btn = page.locator("button[aria-label='清除提示']")
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

    async def _select_and_add_row(self, page, row) -> None:
        cls = await row.get_attribute("class") or ""
        if "asset-item-active" not in cls:
            await row.click(timeout=5000)
            await asyncio.sleep(1.0)
        add_btn = page.locator(
            ".cdk-overlay-container button.detail-add-to-prompt-btn"
        )
        if await add_btn.count() == 0:
            add_btn = page.get_by_text("添加到提示", exact=True)
        if await add_btn.count() > 0:
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

        await self._close_overlays(page)
        await page.locator("button[aria-label='在提示框中添加素材']").last.click(timeout=8000)
        await asyncio.sleep(2.0)

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
                await self._close_overlays(page)
                await page.locator("button[aria-label='在提示框中添加素材']").last.click(timeout=8000)
                await asyncio.sleep(2.0)
            if title:
                search = page.locator(".cdk-overlay-container input[aria-label='搜索资源']").first
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
        await self._close_overlays(page)
        await page.locator("button[aria-label='在提示框中添加素材']").last.click(timeout=8000)
        await asyncio.sleep(2.0)
        async with page.expect_file_chooser(timeout=15_000) as fc:
            await page.get_by_text("上传媒体", exact=True).last.click(timeout=8000)
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
        retry = page.get_by_text("重试", exact=True)
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
                busy = await page.locator(
                    "flow-base-prompt-box button[aria-label='停止'], "
                    "flow-base-prompt-box button:has-text('stop')"
                ).count()
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
        """Real-input click on the live card's 批准 label (never DOM click)."""
        loc = page.get_by_text("批准", exact=True)
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
        cost = None
        m = re.search(r"消耗\s*(\d+)\s*个点数", card_text or "")
        if m:
            cost = int(m.group(1))
        dur = None
        m = re.search(r"(\d+)\s*秒", card_text or "")
        if m:
            dur = int(m.group(1))
        return {"cost": cost, "duration_s": dur, "raw": card_text or ""}

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
