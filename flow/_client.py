"""
flow._client — High-level FlowClient combining FlowRPC, AgentUI, and FlowAPI.

Architecture:
    FlowRPC        → flow.google.com batchexecute RPC (credits, models, media, as29s URLs)
    AgentUI        → Playwright creation-agent automation with price verification gate
    FlowAPI        → read-only RPC + download compatibility layer
    FlowClient     → unified async SDK for flow.google.com video/image + flowmusic.app (.music)

Usage:
    async with await FlowClient.create("project-uuid") as client:
        jobs = await client.generate_video("golden lotus at dawn")
        status = await client.wait_for_video(jobs[0])
        path = await client.download(status.fife_url, "./output/video.mp4")
"""
from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from typing import Optional

from ._api import FlowAPI, VideoJob, VideoStatus, GeneratedImage, Credits, Workflow
from ._browser import BrowserManager
from ._exceptions import (
    GenerationError, InvalidArgumentError, NotFoundError,
)
from ._flow_ui import (
    AgentUI,
    DOWNLOAD_MEDIA_ARIA_LABELS,
    UPSCALE_LABELS,
    build_aria_selector,
    has_nonzero_credit_quote,
    parse_credit_cost,
    parse_duration_s,
)
from ._storage import get_active_project

log = logging.getLogger(__name__)


def _safe_filename(text: str, max_len: int = 60) -> str:
    """Convert prompt text into a safe lowercase filename slug."""
    slug = re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")
    return slug[:max_len].rstrip("_") or "output"


# ── Camera motion / position mappings ─────────────────────────────────────────
CAMERA_MOTIONS = {
    "dolly_in":          "Dolly in",
    "dolly-in":          "Dolly in",
    "dolly_out":         "Dolly out",
    "dolly-out":         "Dolly out",
    "orbit_left":        "Orbit left",
    "orbit-left":        "Orbit left",
    "orbit_right":       "Orbit right",
    "orbit-right":       "Orbit right",
    "orbit_up":          "Orbit up",
    "orbit-up":          "Orbit up",
    "orbit_low":         "Orbit low",
    "orbit-low":         "Orbit low",
    "dolly_zoom_in":     "Dolly in zoom out",
    "dolly-zoom-in":     "Dolly in zoom out",
    "dolly_zoom_out":    "Dolly out zoom in",
    "dolly-zoom-out":    "Dolly out zoom in",
}

CAMERA_POSITIONS = {
    "center":  "Center",
    "left":    "Left",
    "right":   "Right",
    "high":    "High",
    "low":     "Low",
    "closer":  "Closer",
    "further": "Further",
}

_CAMERA_MOTION_CN = {
    "Dolly in":          "镜头缓慢向前推近（Dolly in）",
    "Dolly out":         "镜头缓慢向后拉远（Dolly out）",
    "Orbit left":        "镜头向左环绕移动（Orbit left）",
    "Orbit right":       "镜头向右环绕移动（Orbit right）",
    "Orbit up":          "镜头向上环绕移动（Orbit up）",
    "Orbit low":         "镜头向下低角度环绕（Orbit low）",
    "Dolly in zoom out": "镜头向前推进同时变焦拉远（Dolly in zoom out）",
    "Dolly out zoom in": "镜头向后拉远同时变焦推近（Dolly out zoom in）",
}

_CAMERA_POS_CN = {
    "Center":  "居中机位（Center）",
    "Left":    "左侧机位（Left）",
    "Right":   "右侧机位（Right）",
    "High":    "高机位俯拍（High）",
    "Low":     "低机位仰拍（Low）",
    "Closer":  "近景拉近机位（Closer）",
    "Further": "远景拉远机位（Further）",
}

_VIDEO_MODEL_ALIASES = {
    "veo 3.1 - fast":    "Veo 3.1 - Fast",
    "veo_3_1_t2v_fast":  "Veo 3.1 - Fast",
    "veo-fast":          "Veo 3.1 - Fast",
    "fast":              "Veo 3.1 - Fast",
    "veo 3.1 - lite":    "Veo 3.1 - Lite",
    "veo_3_1_t2v_lite":  "Veo 3.1 - Lite",
    "veo-lite":          "Veo 3.1 - Lite",
    "lite":              "Veo 3.1 - Lite",
    "veo 3.1 - quality": "Veo 3.1 - Quality",
    "veo_3_1_t2v":       "Veo 3.1 - Quality",
    "quality":           "Veo 3.1 - Quality",
    "omni 1.2 flash":    "Omni 1.2 Flash",
    "omni-1.2":          "Omni 1.2 Flash",
    "omni":              "Omni 1.2 Flash",
    "macaron":           "Omni 1.2 Flash",
    "omni 1.1 flash":    "Omni 1.1 Flash",
    "omni-1.1":          "Omni 1.1 Flash",
    "abra":              "Omni 1.1 Flash",
}

_ASPECT_CN = {
    "landscape": "16:9 横屏",
    "16:9":      "16:9 横屏",
    "portrait":  "9:16 竖屏",
    "9:16":      "9:16 竖屏",
    "square":    "1:1 方形",
    "1:1":       "1:1 方形",
}


def _make_cost_verifier(
    cfg: dict,
    *,
    expected_duration_s: Optional[int | set[int]] = None,
    default_family: Optional[str] = None,
):
    """Build a strict confirmation-card price verifier against HTrJv config."""
    def verify(parsed: dict) -> bool:
        cost = parsed.get("cost")
        card_dur = parsed.get("duration_s")
        if cost is None or cost <= 0:
            return False
        raw = parsed.get("raw", "")
        models = cfg.get("videoModels", [])
        family = [
            m for m in models
            if m.get("displayName") and m["displayName"] in raw
        ]
        if not family and default_family:
            family = [
                m for m in models
                if m.get("displayName") == default_family
            ]
        if not family:
            return False
        if card_dur is not None:
            return any(
                m.get("durationS") == card_dur and m.get("creditCost") == cost
                for m in family
            )
        if isinstance(expected_duration_s, set) and expected_duration_s:
            return any(
                m.get("durationS") in expected_duration_s and m.get("creditCost") == cost
                for m in family
            )
        if isinstance(expected_duration_s, int):
            return any(
                m.get("durationS") == expected_duration_s and m.get("creditCost") == cost
                for m in family
            )
        return any(m.get("creditCost") == cost for m in family)
    return verify


def verify_upscale_menu_cost(
    item_text: str,
    *,
    is_4k: bool,
    official_4k_cost: Optional[int] = None,
) -> None:
    """Verify upscale download menu item cost before clicking (fail-closed)."""
    if not is_4k:
        if has_nonzero_credit_quote(item_text):
            raise GenerationError(
                f"1080p upscale unexpectedly quotes a credit cost: {item_text!r} — aborting"
            )
        return
    quoted = parse_credit_cost(item_text)
    if quoted is None or official_4k_cost is None or quoted != official_4k_cost:
        raise GenerationError(
            f"4K upscale menu cost {quoted} does not match official {official_4k_cost} — aborting"
        )


class FlowClient:
    """
    High-level async client for Google Flow AI (flow.google.com).

    Generation and edit operations run via the in-page creation agent
    (``AgentUI``) and edit-page download menu with strict price verification
    against ``HTrJv``. Read-only queries run over ``FlowRPC`` / ``FlowAPI``.
    """

    def __init__(
        self,
        api: FlowAPI,
        bm: BrowserManager,
        project_id: str,
        workflow_id: Optional[str] = None,
    ):
        self._api        = api
        self._bm         = bm
        self.project_id  = project_id
        self.workflow_id = workflow_id
        self._music      = None
        self._project_url = f"https://flow.google.com/project/{project_id}"

    @property
    def music(self):
        """Access FlowMusicClient sharing this client's browser profile."""
        if self._music is None:
            from ._music import FlowMusicClient
            from ._music_rpc import FlowMusicRPC
            self._music = FlowMusicClient(FlowMusicRPC(self._bm))
        return self._music

    # ── Factory ────────────────────────────────────────────────────────────────

    @classmethod
    async def create(
        cls,
        project_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        *,
        headless: bool = True,
        cdp_url: Optional[str] = None,
        timeout_s: int = 300,
    ) -> "FlowClient":
        """
        Create and initialize a FlowClient.

        Args:
            project_id:  Flow project UUID. Defaults to the saved active project.
            workflow_id: Flow workflow UUID (used for edit-page operations).
            headless:    Launch browser in headless mode (default True).
            cdp_url:     Connect to an existing Chrome CDP port, e.g. "http://127.0.0.1:9222".
            timeout_s:   Default generation timeout (seconds).
        """
        pid = project_id or get_active_project()[0] or ""

        if cdp_url:
            bm = BrowserManager.from_cdp(cdp_url)
        else:
            bm = BrowserManager(headless=headless)
        await bm.start()

        api = FlowAPI(bm, project_id=pid, default_timeout_s=timeout_s)

        # Navigate to project page to load session + reCAPTCHA
        page = await bm.page()
        if "flow.google.com" not in page.url:
            proj_url = f"https://flow.google.com/project/{pid}"
            await page.goto(proj_url, wait_until="domcontentloaded", timeout=20_000)
            await asyncio.sleep(2)

        return cls(api, bm, pid, workflow_id)

    # ── Context manager ────────────────────────────────────────────────────────

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        await self.close()

    async def close(self):
        if self._music is not None:
            await self._music.close()
        await self._bm.stop()

    # ══════════════════════════════════════════════════════════════════════════
    # GENERATION (UI automation + interceptor)
    # ══════════════════════════════════════════════════════════════════════════

    async def generate_video(
        self,
        prompt: str,
        *,
        model: str = "Veo 3.1 - Fast",
        aspect: str = "landscape",
        count: int = 1,
        start_image: Optional[str] = None,
        reference_images: Optional[list[str]] = None,
        workflow_id: Optional[str] = None,
        timeout_s: int = 120,
    ) -> list[VideoJob]:
        """
        Generate video(s) via the flow.google.com creation agent (T2V / I2V / R2V).

        Supports:
          * Text-to-Video (T2V) with explicit model & aspect ratio directives;
          * Image-to-Video (I2V) via ``start_image`` (project media_id or local file);
          * Multi-reference Video (R2V) via ``reference_images``;
          * Strict confirmation-card price verification against HTrJv before approval.
        """
        rpc = self._api._rpc_client()
        agent = AgentUI(self._bm, self.project_id)
        page = await self._bm.page()

        cfg = await rpc.get_model_config()
        verify = _make_cost_verifier(cfg)

        aspect_label = _ASPECT_CN.get((aspect or "landscape").lower(), "16:9 横屏")
        model_display = _VIDEO_MODEL_ALIASES.get(
            (model or "").strip().lower(), (model or "Veo 3.1 - Fast").strip()
        )
        # Omni-only parameters (360p / 3s) or default I2V use Omni 1.2 Flash. The lookbehinds keep
        # fractional seconds ("0.3s fade-in", "0.3秒") from reading as a 3s request.
        if (
            re.search(
                r"360p|(?<!\.)3\s*秒|(?<![\d.])3\s*(?:s|sec|secs|seconds?)\b", prompt or "", re.I
            )
            or (start_image and model_display == "Veo 3.1 - Fast" and "veo" not in (prompt or "").lower())
        ):
            model_display = "Omni 1.2 Flash"

        base = (prompt or "").strip()
        if start_image:
            if not base.startswith("用这张图片"):
                base = f"用这张图片作为首帧生成一段视频：{base}"
        elif reference_images:
            if "视频" not in base and "video" not in base.lower():
                base = f"参考所附图片生成一段视频：{base}"
        else:
            if "视频" not in base and "video" not in base.lower():
                base = f"生成一段视频：{base}"

        clauses: list[str] = []
        if not re.search(r"Omni|Veo", base, re.I) and model_display:
            clauses.append(f"使用 {model_display} 模型")
        # landscape/portrait in the prompt is scene content, not an aspect directive: only an
        # explicit ratio suppresses the clause, so the `aspect` argument always lands.
        if not re.search(r"16:9|9:16|横屏|竖屏", base, re.I):
            clauses.append(aspect_label)
        if start_image and model_display == "Omni 1.2 Flash":
            if parse_duration_s(base) is None:
                clauses.append("时长 3 秒")
            if not re.search(r"360p|720p|1080p", base, re.I):
                clauses.append("分辨率 360p")
        elif model_display == "Veo 3.1 - Lite" and parse_duration_s(base) is None:
            clauses.append("时长 4 秒")

        text = base.rstrip("。.") + ("。" + "，".join(clauses) if clauses else "")

        jobs: list[VideoJob] = []
        for _ in range(max(1, count)):
            await agent.open_session(page)
            pm = await rpc.list_project_media(self.project_id)
            if start_image:
                await agent.attach_or_upload(page, rpc, pm, start_image)
                pm = await rpc.list_project_media(self.project_id)
            for ref in reference_images or []:
                await agent.attach_or_upload(page, rpc, pm, ref)
                pm = await rpc.list_project_media(self.project_id)

            before = {m["media_id"] for m in pm["medias"]}
            await agent.run_turn(page, text, verify_cost=verify, require_card=True)
            media = await self._wait_new_media(
                rpc, before, kind="video", timeout_s=max(timeout_s, 600)
            )
            if media is None:
                raise GenerationError(
                    "Agent approved the generation but no video appeared "
                    "in the project media list within the timeout"
                )
            job = VideoJob.__new__(VideoJob)
            job.media_name = media["media_id"]
            job.status = "COMPLETE"
            job.project_id = self.project_id
            job.workflow_id = media.get("workflow_id", "")
            job.fife_url = await rpc.get_media_url(media["media_id"])
            job.operation_name = ""
            job.remaining_credits = 0
            job.file_path = None
            job.elapsed_s = 0.0
            jobs.append(job)
        log.info("Agent video generation complete: %d job(s)", len(jobs))
        return jobs

    async def _wait_new_media(self, rpc, before_ids: set, *, kind: str,
                              timeout_s: int = 600):
        """Poll the RPC media list until a new media of *kind* has a signed URL."""
        deadline = asyncio.get_event_loop().time() + timeout_s
        while asyncio.get_event_loop().time() < deadline:
            pm = await rpc.list_project_media(self.project_id)
            for m in pm["medias"]:
                if m["media_id"] not in before_ids and m["kind"] == kind:
                    url = await rpc.get_media_url(m["media_id"])
                    if not url and kind == "image":
                        url = m.get("poster_url", "")
                    if url:
                        m["signed_url"] = url
                        return m
            await asyncio.sleep(6)
        return None

    async def generate_image(
        self,
        prompt: str,
        *,
        aspect: str = "landscape",
        count: int = 1,
        model: Optional[str] = None,
        reference_images: Optional[list[str]] = None,
        timeout_s: int = 120,
    ) -> list[GeneratedImage]:
        """
        Generate images via the flow.google.com creation agent.

        Supports aspect ratio, count, model name, and reference images.
        Image generation is free on the current tier; if a confirmation
        card ever quotes a cost above 0 the turn is aborted immediately.
        """
        rpc = self._api._rpc_client()
        agent = AgentUI(self._bm, self.project_id)
        page = await self._bm.page()

        def verify_free(parsed: dict) -> bool:
            return parsed.get("cost") == 0

        await agent.open_session(page)
        pm = await rpc.list_project_media(self.project_id)
        for ref in reference_images or []:
            await agent.attach_or_upload(page, rpc, pm, ref)
            pm = await rpc.list_project_media(self.project_id)

        before = {m["media_id"] for m in pm["medias"]}
        aspect_label = _ASPECT_CN.get((aspect or "landscape").lower(), "16:9 横屏")
        prefix = "参考所附图片，" if reference_images else ""
        model_clause = f"，使用 {model} 模型" if model else ""
        text = f"{prefix}生成 {max(1, count)} 张 {aspect_label} 图片：{prompt}{model_clause}"

        await agent.run_turn(page, text, card_timeout_s=60,
                             verify_cost=verify_free)
        images: list[GeneratedImage] = []
        deadline = asyncio.get_event_loop().time() + max(timeout_s, 300)
        while asyncio.get_event_loop().time() < deadline:
            pm = await rpc.list_project_media(self.project_id)
            new = [m for m in pm["medias"]
                   if m["media_id"] not in before and m["kind"] == "image"]
            ready = []
            for m in new:
                url = await rpc.get_media_url(m["media_id"]) or m.get("poster_url", "")
                if url:
                    ready.append((m, url))
            if ready and len(ready) == len(new):
                for m, url in ready:
                    img = GeneratedImage.__new__(GeneratedImage)
                    img._raw = {}
                    img.media_name = m["media_id"]
                    img.project_id = self.project_id
                    img.workflow_id = m.get("workflow_id", "")
                    img.fife_url = url
                    img.seed = 0
                    img.model = m.get("model_key", "")
                    img.file_path = None
                    img.prompt = prompt
                    img.dimensions = {}
                    images.append(img)
                break
            await asyncio.sleep(6)
        if not images:
            raise GenerationError(
                "Agent finished the turn but no image appeared in the "
                "project media list within the timeout"
            )
        log.info("Agent T2I complete: %d image(s)", len(images))
        return images

    # ── Video edit operations (agent panel + edit page upscale) ───────────────

    async def _run_video_edit_turn(
        self,
        media_id: str,
        instruction: str,
        *,
        use_source_duration: bool = True,
        expected_duration_s: Optional[int] = None,
        timeout_s: int = 120,
    ) -> VideoJob:
        """Attach *media_id* in a fresh agent session, verify card price, and wait."""
        rpc = self._api._rpc_client()
        agent = AgentUI(self._bm, self.project_id)
        page = await self._bm.page()

        pm = await rpc.list_project_media(self.project_id)
        target = next(
            (m for m in pm["medias"]
             if m["media_id"] == media_id or m["media_id"].startswith(media_id)),
            None,
        )
        if target is None:
            raise NotFoundError(
                f"Media {media_id} not found in project {self.project_id}"
            )

        cfg = await rpc.get_model_config()
        dur_hint = expected_duration_s
        if dur_hint is None and use_source_duration:
            wf_id = target.get("workflow_id") or ""
            wf_durs = {
                m.get("duration_s")
                for m in pm["medias"]
                if (m["media_id"] == target["media_id"] or (wf_id and m.get("workflow_id") == wf_id))
                and m.get("duration_s")
            }
            dur_hint = wf_durs or target.get("duration_s")
        verify = _make_cost_verifier(
            cfg,
            expected_duration_s=dur_hint,
            default_family="Omni 1.2 Flash",
        )

        before = {m["media_id"] for m in pm["medias"]}
        await agent.open_session(page)
        await agent.attach_media(page, pm, target["media_id"])
        await agent.run_turn(
            page, instruction, verify_cost=verify, require_card=True
        )
        media = await self._wait_new_media(
            rpc, before, kind="video", timeout_s=max(timeout_s, 600)
        )
        if media is None:
            raise GenerationError(
                "Agent approved the video edit but no new video appeared "
                "in the project media list within the timeout"
            )
        job = VideoJob.__new__(VideoJob)
        job.media_name = media["media_id"]
        job.status = "COMPLETE"
        job.project_id = self.project_id
        job.workflow_id = media.get("workflow_id", "")
        job.fife_url = await rpc.get_media_url(media["media_id"])
        job.operation_name = ""
        job.remaining_credits = 0
        job.file_path = None
        job.elapsed_s = 0.0
        return job

    async def extend_video(
        self,
        media_id: str,
        workflow_id: Optional[str] = None,
        prompt: str = "",
        *,
        timeout_s: int = 120,
    ) -> VideoJob:
        """
        Extend a video via the flow.google.com creation agent.

        Attaches the source video chip and asks Omni 1.2 Flash to extend it
        (default: 3s at 360p = 3 credits unless duration/resolution is in prompt).
        """
        parsed_dur = parse_duration_s(prompt or "")
        ext_dur = parsed_dur if parsed_dur else 3
        res_clause = "" if re.search(r"360p|720p|1080p", prompt or "", re.I) else "，分辨率 360p"
        body = (prompt or "自然延续画面动作与场景").strip().rstrip("。.")
        if parsed_dur:
            text = f"使用 Omni 1.2 Flash 模型把这个视频延长：{body}{res_clause}。"
        else:
            text = f"使用 Omni 1.2 Flash 模型把这个视频延长 {ext_dur} 秒：{body}{res_clause}。"
        job = await self._run_video_edit_turn(
            media_id, text, use_source_duration=False,
            expected_duration_s=ext_dur, timeout_s=timeout_s,
        )
        log.info("Agent extend complete → %s", job.media_name[:16])
        return job

    async def extend_loop(
        self,
        media_id: str,
        workflow_id: Optional[str] = None,
        iterations: int = 5,
        prompt: str = "",
        output_dir: Optional[str] = None,
        *,
        wait: bool = True,
        poll_s: float = 5.0,
        timeout_s: int = 300,
    ) -> list[VideoJob]:
        """Extend a video *iterations* times in sequence via the agent."""
        jobs: list[VideoJob] = []
        current_id = media_id
        out = Path(output_dir) if output_dir else None
        if out:
            out.mkdir(parents=True, exist_ok=True)

        for i in range(iterations):
            log.info("Extend loop %d/%d, media=%s", i + 1, iterations, current_id[:12])
            job = await self.extend_video(current_id, workflow_id, prompt, timeout_s=timeout_s)
            jobs.append(job)

            if wait:
                status = await self.wait_for_video(job, poll_s=poll_s, timeout_s=timeout_s)
                current_id = job.media_name or current_id
                if out and status.fife_url:
                    dest = out / f"extend_{i+1:03d}.mp4"
                    await self.download(status.fife_url, dest)
                    log.info("  → saved %s", dest)
            else:
                current_id = job.media_name or current_id

        return jobs

    async def camera_motion(
        self,
        media_id: str,
        motion: str,
        workflow_id: Optional[str] = None,
        *,
        timeout_s: int = 120,
    ) -> VideoJob:
        """Apply a camera motion to a video via the creation agent (Omni 1.2 Flash)."""
        motion_label = CAMERA_MOTIONS.get(motion.lower())
        if not motion_label:
            raise InvalidArgumentError(
                f"Unknown camera motion '{motion}'. Valid: {list(CAMERA_MOTIONS)}"
            )
        desc = _CAMERA_MOTION_CN.get(motion_label, motion_label)
        text = f"使用 Omni 1.2 Flash 模型给这个视频重新运镜：{desc}，画面主体内容保持不变，分辨率 360p。"
        job = await self._run_video_edit_turn(
            media_id, text, use_source_duration=True, timeout_s=timeout_s
        )
        log.info("Agent camera motion '%s' complete → %s", motion, job.media_name[:16])
        return job

    async def camera_position(
        self,
        media_id: str,
        position: str,
        workflow_id: Optional[str] = None,
        *,
        timeout_s: int = 120,
    ) -> VideoJob:
        """Apply a camera position change to a video via the creation agent."""
        pos_label = CAMERA_POSITIONS.get(position.lower())
        if not pos_label:
            raise InvalidArgumentError(
                f"Unknown camera position '{position}'. Valid: {list(CAMERA_POSITIONS)}"
            )
        desc = _CAMERA_POS_CN.get(pos_label, pos_label)
        text = f"使用 Omni 1.2 Flash 模型调整这个视频的机位：把摄像机位置调整为{desc}，画面主体内容保持不变，分辨率 360p。"
        job = await self._run_video_edit_turn(
            media_id, text, use_source_duration=True, timeout_s=timeout_s
        )
        log.info("Agent camera position '%s' complete → %s", position, job.media_name[:16])
        return job

    async def insert_object(
        self,
        media_id: str,
        prompt: str,
        workflow_id: Optional[str] = None,
        *,
        timeout_s: int = 120,
    ) -> VideoJob:
        """Insert an object into a video using a text prompt via the creation agent."""
        body = (prompt or "").strip().rstrip("。.")
        if not body:
            raise InvalidArgumentError("insert_object requires a non-empty prompt")
        text = f"使用 Omni 1.2 Flash 模型对这个视频进行编辑，在画面中加入：{body}，其余内容保持不变，分辨率 360p。"
        job = await self._run_video_edit_turn(
            media_id, text, use_source_duration=True, timeout_s=timeout_s
        )
        log.info("Agent insert complete → %s", job.media_name[:16])
        return job

    async def remove_object(
        self,
        media_id: str,
        workflow_id: Optional[str] = None,
        *,
        mask_x: float = 0.5,
        mask_y: float = 0.5,
        brush_size: int = 40,
        prompt: str = "",
        timeout_s: int = 120,
    ) -> VideoJob:
        """
        Remove an object from a video via the creation agent (Omni 1.2 Flash).

        Note: The old labs.google pixel brush mask canvas is gone in the
        flow.google.com SPA. Object removal now runs through Omni 1.2 Flash
        video editing using either an explicit object description (``prompt``)
        or a natural-language region description derived from ``(mask_x, mask_y)``.
        """
        body = (prompt or "").strip().rstrip("。.")
        if body:
            target_desc = body
        else:
            horiz = "左侧" if mask_x < 0.35 else ("右侧" if mask_x > 0.65 else "中央")
            vert = "上方" if mask_y < 0.35 else ("下方" if mask_y > 0.65 else "中部")
            target_desc = f"画面{vert}{horiz}区域的前景物体或杂物"
        text = (
            f"使用 Omni 1.2 Flash 模型对这个视频进行编辑，"
            f"将{target_desc}移除并自然补全背景，其余画面内容保持不变，分辨率 360p。"
        )
        job = await self._run_video_edit_turn(
            media_id, text, use_source_duration=True, timeout_s=timeout_s
        )
        log.info("Agent remove complete → %s", job.media_name[:16])
        return job

    async def upscale_video(
        self,
        media_id: str,
        workflow_id: Optional[str] = None,
        resolution: str = "1080p",
        *,
        timeout_s: int = 120,
    ) -> VideoJob:
        """
        Upscale a video via the edit-page download menu (1080p = 0 credits FREE).

        Navigates to ``/project/<id>/edit/<workflow_id>``, opens the download
        menu, verifies the credit cost on the menu item against HTrJv, clicks
        the target resolution, and polls ``as29s`` until ``<media_id>_upsampled``
        has a freshly signed download URL.
        """
        rpc = self._api._rpc_client()
        pm = await rpc.list_project_media(self.project_id)
        target = next(
            (m for m in pm["medias"]
             if m["media_id"] == media_id or m["media_id"].startswith(media_id)),
            None,
        )
        if target is not None:
            media_id = target["media_id"]
            wid = target.get("workflow_id") or workflow_id or self.workflow_id or ""
        else:
            wid = workflow_id or self.workflow_id or ""
        if not wid:
            raise NotFoundError(
                f"Workflow ID for media {media_id} not found in project {self.project_id}"
            )

        is_4k = resolution.lower() in ("4k", "4096")
        upsampled_id = f"{media_id}_upsampled"

        page = await self._bm.page()
        edit_url = f"https://flow.google.com/project/{self.project_id}/edit/{wid}"
        await page.goto(edit_url, wait_until="domcontentloaded", timeout=30_000)
        await asyncio.sleep(6)

        dl_btn = page.locator(build_aria_selector("button", DOWNLOAD_MEDIA_ARIA_LABELS)).first
        await dl_btn.click(timeout=15_000)
        await asyncio.sleep(1.5)

        label_key = "4K" if is_4k else "1080p"
        candidates = page.locator(".cdk-overlay-container [role=menuitem]").filter(
            has_text=label_key
        )
        cand_count = await candidates.count()
        if cand_count == 0:
            raise GenerationError(f"Upscale option '{label_key}' not found in download menu")
        item = candidates.first
        if cand_count > 1:
            for idx in range(cand_count):
                cand = candidates.nth(idx)
                try:
                    txt = await cand.inner_text()
                except Exception:
                    continue
                if any(lbl.lower() in txt.lower() for lbl in UPSCALE_LABELS):
                    item = cand
                    break
        item_text = await item.inner_text()
        official_4k_cost = None
        if is_4k:
            cfg = await rpc.get_model_config()
            official_4k_cost = next(
                (
                    m.get("creditCost")
                    for m in cfg.get("videoModels", [])
                    if m.get("key") == "veo_3_1_upsampler_4k"
                ),
                None,
            )
        verify_upscale_menu_cost(item_text, is_4k=is_4k, official_4k_cost=official_4k_cost)

        # Capture direct browser download if triggered, and poll as29s for _upsampled
        dl_events = []

        def on_dl(d):
            dl_events.append(d)

        page.on("download", on_dl)
        try:
            await item.click(timeout=8000)
            deadline = asyncio.get_event_loop().time() + max(timeout_s, 180)
            url = ""
            while asyncio.get_event_loop().time() < deadline:
                await asyncio.sleep(5)
                url = await rpc.get_media_url(upsampled_id)
                if url:
                    break
        finally:
            try:
                page.remove_listener("download", on_dl)
            except Exception:
                pass

        if not url:
            raise GenerationError(
                f"Upscale timed out waiting for signed URL of {upsampled_id}"
            )
        job = VideoJob.__new__(VideoJob)
        job.media_name = upsampled_id
        job.status = "COMPLETE"
        job.project_id = self.project_id
        job.workflow_id = wid
        job.fife_url = url
        job.operation_name = ""
        job.remaining_credits = 0
        job.file_path = None
        job.elapsed_s = 0.0
        log.info("Upscale complete → %s", upsampled_id)
        return job

    # ══════════════════════════════════════════════════════════════════════════
    # READ-ONLY OPERATIONS (direct API, no UI)
    # ══════════════════════════════════════════════════════════════════════════

    async def get_credits(self) -> Credits:
        """Get remaining credits. Direct API, no reCAPTCHA needed."""
        return await self._api.get_credits()

    async def poll_video(self, media_id: str) -> VideoStatus:
        """Poll video generation status. Direct API, no reCAPTCHA needed."""
        return await self._api.poll_video(media_id)

    async def wait_for_video(
        self,
        job: VideoJob,
        *,
        poll_s: float = 5.0,
        timeout_s: int = 300,
        on_poll: Optional[callable] = None,
    ) -> VideoStatus:
        """
        Poll until the video is complete.

        Args:
            job:       VideoJob returned by a generation method
            poll_s:    Seconds between polls
            timeout_s: Maximum wait time
            on_poll:   Optional callback(status, elapsed_s) for progress display

        Returns:
            VideoStatus with .complete=True and .fife_url populated
        """
        return await self._api.wait_for_video(job, poll_s=poll_s, timeout_s=timeout_s, on_poll=on_poll)

    async def get_model_config(self) -> dict:
        """Get all video models with costs and capabilities."""
        return await self._api.get_video_model_config()

    async def get_flow_config(self) -> dict:
        """Get Flow app feature flags."""
        return await self._api.get_flow_app_config()

    async def get_workflows(self) -> list[Workflow]:
        """List workflows in the active project."""
        return await self._api.list_workflows()

    # ══════════════════════════════════════════════════════════════════════════
    # DOWNLOAD
    # ══════════════════════════════════════════════════════════════════════════

    async def download(
        self,
        media_name_or_url: str,
        output_path: str | Path,
    ) -> Path:
        """
        Download a generated video or image.

        Args:
            media_name_or_url: FIFE URL (starts with https://lh3.google...) or media UUID
            output_path:       Local file path to save to

        Returns:
            Path object of the saved file
        """
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        if media_name_or_url.startswith("https://"):
            url = media_name_or_url
        else:
            # It's a media name → poll to get the fife_url
            status = await self.poll_video(media_name_or_url)
            url = status.fife_url
            if not url:
                raise ValueError(f"No download URL for media {media_name_or_url}")

        return await self._api.download(url, str(out))

    async def download_all(
        self,
        workflow_id: Optional[str] = None,
        output_dir: str | Path = "./flow_output",
        *,
        file_prefix: str = "video",
    ) -> list[Path]:
        """
        Download all completed videos in a workflow.

        Returns list of downloaded paths.
        """
        # Get workflow media list
        wid = workflow_id or self.workflow_id or ""
        data = await self._api.get_project_data()
        workflows = data.get("workflows", [])
        media_names = []
        for wf in workflows:
            if wf.get("id") == wid or not wid:
                for clip in wf.get("clips", []):
                    name = clip.get("mediaId") or clip.get("mediaName")
                    if name:
                        media_names.append(name)

        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        paths = []
        for i, name in enumerate(media_names):
            try:
                status = await self.poll_video(name)
                if status.fife_url:
                    p = out / f"{file_prefix}_{i+1:03d}.mp4"
                    await self.download(status.fife_url, p)
                    paths.append(p)
            except Exception as e:
                log.warning("Could not download %s: %s", name[:16], e)

        return paths

    # ══════════════════════════════════════════════════════════════════════════
    # CONVENIENCE
    # ══════════════════════════════════════════════════════════════════════════

    async def generate_video_and_wait(
        self,
        prompt: str,
        output_path: Optional[str] = None,
        **kwargs,
    ) -> VideoStatus:
        """
        Generate a video and wait for completion. Optionally download.

        Returns VideoStatus with .fife_url and .complete=True.
        """
        jobs = await self.generate_video(prompt, **kwargs)
        if not jobs:
            raise GenerationError("No jobs returned from generate_video")
        status = await self.wait_for_video(jobs[0])
        if output_path and status.fife_url:
            await self.download(status.fife_url, output_path)
        return status

    async def generate_image_and_save(
        self,
        prompt: str,
        output_dir: str = "./flow_images",
        **kwargs,
    ) -> list[Path]:
        """
        Generate images and save them locally.

        Returns list of saved file paths.
        """
        images = await self.generate_image(prompt, **kwargs)
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        paths = []
        for i, img in enumerate(images):
            if img.fife_url:
                p = out / f"image_{i+1:03d}.jpg"
                await self.download(img.fife_url, p)
                paths.append(p)
        return paths

    # ── Private helpers ────────────────────────────────────────────────────────

    async def _ensure_project_page(self, page=None) -> None:
        """Navigate to the project page if not already there."""
        if page is None:
            page = await self._bm.page()
        if self.project_id not in page.url:
            await page.goto(
                self._project_url, wait_until="domcontentloaded", timeout=20_000
            )
            await asyncio.sleep(2)

    def __repr__(self):
        return (
            f"<FlowClient project={self.project_id[:8]}... "
            f"workflow={self.workflow_id and self.workflow_id[:8]}...>"
        )
