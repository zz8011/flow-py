"""
flow._api — Model constants, response types, mask helpers, and read-only FlowAPI.

All active flow.google.com RPC calls (credits, model config, project workflows,
media status polling, and fresh download URL signing) are delegated to
``flow._rpc.FlowRPC``. Content generation and editing run via ``FlowClient``
(``flow._client``) using the in-page creation agent (``flow._flow_ui.AgentUI``).
"""
from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Callable, Optional

from ._exceptions import GenerationError, GenerationTimeout

log = logging.getLogger(__name__)

# ── Base URL ─────────────────────────────────────────────────────────────────
FLOW_BASE = "https://flow.google.com"

# ── Image models ─────────────────────────────────────────────────────────────
IMAGE_MODEL_NARWHAL  = "NARWHAL"      # Nano Banana 2 / Imagen 3.5 (default)
IMAGE_MODEL_IMAGEN3  = "IMAGEN_3"     # Imagen 3

# ── Image aspect ratios ──────────────────────────────────────────────────────
IMAGE_AR_PORTRAIT  = "IMAGE_ASPECT_RATIO_PORTRAIT"    # 9:16
IMAGE_AR_LANDSCAPE = "IMAGE_ASPECT_RATIO_LANDSCAPE"   # 16:9
IMAGE_AR_SQUARE    = "IMAGE_ASPECT_RATIO_SQUARE"      # 1:1

# ── Video models (videoModelKey field) ───────────────────────────────────────

# ── Veo 3.1 Text-to-Video (with audio, 20cr fast / 100cr quality) ────────────
VIDEO_MODEL_VEO31_FAST     = "veo_3_1_t2v_fast"           # Veo 3.1 Fast, landscape, 20cr
VIDEO_MODEL_VEO31_FAST_P   = "veo_3_1_t2v_fast_portrait"  # Veo 3.1 Fast, portrait, 20cr
VIDEO_MODEL_VEO31_STD      = "veo_3_1_t2v"                # Veo 3.1 Quality, landscape, 100cr
VIDEO_MODEL_VEO31_STD_P    = "veo_3_1_t2v_portrait"       # Veo 3.1 Quality, portrait, 100cr

# ── Veo 2.1 Text-to-Video (no audio, 10cr) ───────────────────────────────────
VIDEO_MODEL_VEO21_T2V      = "veo_2_1_fast_d_15_t2v"      # Veo 2.1 Fast T2V, landscape, 10cr
VIDEO_MODEL_VEO20_STD      = "veo_2_0_t2v"                # Veo 2.0 Quality, landscape, 100cr

# ── Veo 3.1 Image-to-Video (with audio) ──────────────────────────────────────
VIDEO_MODEL_VEO31_I2V      = "veo_3_1_i2v_s_fast"         # Veo 3.1 Fast I2V, landscape, 20cr
VIDEO_MODEL_VEO31_I2V_P    = "veo_3_1_i2v_s_fast_portrait"# Veo 3.1 Fast I2V, portrait, 20cr
VIDEO_MODEL_VEO31_I2V_STD  = "veo_3_1_i2v_s"              # Veo 3.1 Quality I2V, landscape, 100cr
VIDEO_MODEL_VEO31_I2V_STD_P= "veo_3_1_i2v_s_portrait"     # Veo 3.1 Quality I2V, portrait, 100cr

# ── Veo 2.1 Image-to-Video ───────────────────────────────────────────────────
VIDEO_MODEL_VEO21_I2V      = "veo_2_1_fast_d_15_i2v"      # Veo 2.1 Fast I2V, landscape, 10cr
VIDEO_MODEL_VEO20_I2V_STD  = "veo_2_0_i2v"                # Veo 2.0 Quality I2V, landscape, 100cr

# ── Start+End Frame (Interpolation) ──────────────────────────────────────────
VIDEO_MODEL_VEO31_SE       = "veo_3_1_i2v_s_fast_fl"          # Veo 3.1 Fast, landscape, 20cr
VIDEO_MODEL_VEO31_SE_P     = "veo_3_1_i2v_s_fast_portrait_fl" # Veo 3.1 Fast, portrait, 20cr
VIDEO_MODEL_VEO31_SE_STD   = "veo_3_1_i2v_s_fl"               # Veo 3.1 Quality, landscape, 100cr
VIDEO_MODEL_VEO31_SE_STD_P = "veo_3_1_i2v_s_portrait_fl"      # Veo 3.1 Quality, portrait, 100cr
VIDEO_MODEL_VEO21_SE       = "veo_2_1_fast_d_15_with_start_image_and_end_image_interpolation"  # 10cr

# ── Multi-Reference Video (MULTI_REFERENCE_NO_STYLE capability) ──────────────
VIDEO_MODEL_VEO31_R2V      = "veo_3_1_r2v_fast_landscape"  # Veo 3.1 Fast R2V, landscape, 20cr
VIDEO_MODEL_VEO31_R2V_P    = "veo_3_1_r2v_fast_portrait"   # Veo 3.1 Fast R2V, portrait, 20cr

# ── Extend ───────────────────────────────────────────────────────────────────
VIDEO_MODEL_EXTEND_L       = "veo_3_1_extend_fast_landscape"   # Veo 3.1 Fast, landscape, 20cr
VIDEO_MODEL_EXTEND_P       = "veo_3_1_extend_fast_portrait"    # Veo 3.1 Fast, portrait, 20cr
VIDEO_MODEL_EXTEND_L_STD   = "veo_3_1_extend_landscape"        # Veo 3.1 Quality, landscape, 100cr
VIDEO_MODEL_EXTEND_P_STD   = "veo_3_1_extend_portrait"         # Veo 3.1 Quality, portrait, 100cr
VIDEO_MODEL_VEO21_EXTEND   = "veo_2_1_fast_d_15_with_video_extension"  # Veo 2.1, 10cr

# ── Camera Motion / Reshoot ──────────────────────────────────────────────────
VIDEO_MODEL_RESHOOT_L      = "veo_3_0_reshoot_landscape"   # Reshoot landscape, 20cr
VIDEO_MODEL_RESHOOT_P      = "veo_3_0_reshoot_portrait"    # Reshoot portrait, 20cr

# ── Object Editing ───────────────────────────────────────────────────────────
VIDEO_MODEL_INSERT_L       = "veo_2_0_object_insertion_landscape"  # Insert, landscape, 20cr
VIDEO_MODEL_INSERT_P       = "veo_2_0_object_insertion_portrait"   # Insert, portrait, 20cr
VIDEO_MODEL_REMOVE_L       = "veo_2_0_object_removal_landscape"    # Remove, landscape, 20cr
VIDEO_MODEL_REMOVE_P       = "veo_2_0_object_removal_portrait"     # Remove, portrait, 20cr

# Aliases for backwards compat
VIDEO_MODEL_INSERT         = VIDEO_MODEL_INSERT_L
VIDEO_MODEL_REMOVE         = VIDEO_MODEL_REMOVE_L

# ── Upscaling (cost=0 FREE!) ─────────────────────────────────────────────────
VIDEO_MODEL_UPSCALER_1080P = "veo_3_1_upsampler_1080p"     # Upscale to 1080p, FREE (0cr)

# ── Video resolutions (for upscale) ──────────────────────────────────────────
VIDEO_RES_1080P = "VIDEO_RESOLUTION_1080P"
VIDEO_RES_720P  = "VIDEO_RESOLUTION_720P"

# ── Video aspect ratios ──────────────────────────────────────────────────────
VIDEO_AR_LANDSCAPE = "VIDEO_ASPECT_RATIO_LANDSCAPE"
VIDEO_AR_PORTRAIT  = "VIDEO_ASPECT_RATIO_PORTRAIT"

# ── Image input roles ────────────────────────────────────────────────────────
IMAGE_ROLE_START     = "START_IMAGE"
IMAGE_ROLE_END       = "END_IMAGE"
IMAGE_ROLE_REFERENCE = "REFERENCE_IMAGE"    # for multi-reference (r2v) models

# ── Camera Motion presets (reshootMotionType values) ─────────────────────────
RESHOOT_FORWARD          = "RESHOOT_MOTION_TYPE_FORWARD"          # Dolly in
RESHOOT_BACKWARD         = "RESHOOT_MOTION_TYPE_BACKWARD"         # Dolly out
RESHOOT_LEFT             = "RESHOOT_MOTION_TYPE_LEFT"             # Orbit left
RESHOOT_RIGHT            = "RESHOOT_MOTION_TYPE_RIGHT"            # Orbit right
RESHOOT_UP               = "RESHOOT_MOTION_TYPE_UP"               # Orbit up
RESHOOT_DOWN             = "RESHOOT_MOTION_TYPE_DOWN"             # Orbit low
RESHOOT_DOLLY_ZOOM_IN    = "RESHOOT_MOTION_TYPE_DOLLY_IN_ZOOM_OUT"   # Dolly in + zoom out
RESHOOT_DOLLY_ZOOM_OUT   = "RESHOOT_MOTION_TYPE_DOLLY_OUT_ZOOM_IN"   # Dolly out + zoom in

# ── Camera Position presets (reshootMotionType stationary values) ────────────
RESHOOT_POS_CENTER  = "RESHOOT_MOTION_TYPE_STATIONARY"
RESHOOT_POS_LEFT    = "RESHOOT_MOTION_TYPE_STATIONARY_LEFT"
RESHOOT_POS_RIGHT   = "RESHOOT_MOTION_TYPE_STATIONARY_RIGHT"
RESHOOT_POS_HIGH    = "RESHOOT_MOTION_TYPE_STATIONARY_HIGHER"
RESHOOT_POS_LOW     = "RESHOOT_MOTION_TYPE_STATIONARY_LOWER"
RESHOOT_POS_CLOSER  = "RESHOOT_MOTION_TYPE_STATIONARY_CLOSER"
RESHOOT_POS_FURTHER = "RESHOOT_MOTION_TYPE_STATIONARY_FURTHER"

# ── Additional reshoot types ─────────────────────────────────────────────────
RESHOOT_ORBIT_LEFT      = "RESHOOT_MOTION_TYPE_ORBIT_LEFT"
RESHOOT_ORBIT_RIGHT     = "RESHOOT_MOTION_TYPE_ORBIT_RIGHT"
RESHOOT_ORBIT_UP        = "RESHOOT_MOTION_TYPE_ORBIT_UP"
RESHOOT_ORBIT_DOWN      = "RESHOOT_MOTION_TYPE_ORBIT_DOWN"
RESHOOT_LEFT_TO_RIGHT   = "RESHOOT_MOTION_TYPE_LEFT_TO_RIGHT"
RESHOOT_RIGHT_TO_LEFT   = "RESHOOT_MOTION_TYPE_RIGHT_TO_LEFT"
RESHOOT_SPIN            = "RESHOOT_MOTION_TYPE_SPIN"
RESHOOT_WIDER_SHOT      = "RESHOOT_MOTION_TYPE_WIDER_SHOT"
RESHOOT_CLOSER_SHOT     = "RESHOOT_MOTION_TYPE_CLOSER_SHOT"
RESHOOT_HIGHER_ANGLE    = "RESHOOT_MOTION_TYPE_HIGHER_ANGLE"
RESHOOT_FORWARD_L       = "RESHOOT_MOTION_TYPE_STATIONARY_FORWARD"
RESHOOT_BACKWARD_L      = "RESHOOT_MOTION_TYPE_STATIONARY_BACKWARD"

# ── Mask usage types ─────────────────────────────────────────────────────────
MASK_USAGE_TYPE = "IMAGE_USAGE_TYPE_MASK"

# ── Complete human-readable CAMERA_PRESETS dict ──────────────────────────────
CAMERA_PRESETS = {
    # Camera Motion
    "dolly_in":          RESHOOT_FORWARD,
    "dolly_out":         RESHOOT_BACKWARD,
    "orbit_left":        RESHOOT_LEFT,
    "orbit_right":       RESHOOT_RIGHT,
    "orbit_up":          RESHOOT_UP,
    "orbit_down":        RESHOOT_DOWN,
    "dolly_zoom_in":     RESHOOT_DOLLY_ZOOM_IN,
    "dolly_zoom_out":    RESHOOT_DOLLY_ZOOM_OUT,
    # Camera Position
    "pos_center":   RESHOOT_POS_CENTER,
    "pos_left":     RESHOOT_POS_LEFT,
    "pos_right":    RESHOOT_POS_RIGHT,
    "pos_high":     RESHOOT_POS_HIGH,
    "pos_low":      RESHOOT_POS_LOW,
    "pos_closer":   RESHOOT_POS_CLOSER,
    "pos_further":  RESHOOT_POS_FURTHER,
    # Extra presets
    "spin":          RESHOOT_SPIN,
    "wider":         RESHOOT_WIDER_SHOT,
    "closer_shot":   RESHOOT_CLOSER_SHOT,
    "higher_angle":  RESHOOT_HIGHER_ANGLE,
}


# ── Response objects ─────────────────────────────────────────────────────────

class GeneratedImage:
    def __init__(self, raw: dict):
        self._raw          = raw
        self.media_name: str  = raw.get("name", "")
        self.project_id: str  = raw.get("projectId", "")
        self.workflow_id: str = raw.get("workflowId", "")
        img = raw.get("image", {}).get("generatedImage", {})
        self.fife_url: str    = img.get("fifeUrl", "")
        self.seed: int        = img.get("seed", 0)
        self.model: str       = img.get("modelNameType", "")
        self.file_path: Optional[Path] = None

    def __repr__(self):
        return f"<GeneratedImage name={self.media_name[:8]}... model={self.model}>"


class VideoJob:
    """Represents a submitted or completed video generation job."""

    def __init__(self, raw: dict):
        self._raw = raw
        media_list = raw.get("media", [])
        if media_list:
            m = media_list[0]
            self.media_name: str  = m.get("name", "")
            self.project_id: str  = m.get("projectId", "")
            self.workflow_id: str = m.get("workflowId", "")
        else:
            wf   = raw.get("workflows", [{}])[0]
            meta = wf.get("metadata", {})
            self.media_name  = meta.get("primaryMediaId", "")
            self.project_id  = wf.get("projectId", "")
            self.workflow_id = wf.get("name", "")

        ops = raw.get("operations", [{}])
        self.operation_name: str     = ops[0].get("operation", {}).get("name", "") if ops else ""
        self.remaining_credits: int  = raw.get("remainingCredits", 0)
        self.status: str             = "PENDING"
        self.fife_url: str           = ""
        self.file_path: Optional[Path] = None
        self.elapsed_s: float        = 0.0

    def __repr__(self):
        return f"<VideoJob media={self.media_name[:8]}... status={self.status}>"


class VideoStatus:
    def __init__(self, raw: dict):
        self._raw        = raw
        media_list       = raw.get("media", [{}])
        m                = media_list[0] if media_list else {}
        self.media_name: str = m.get("name", "")
        meta             = m.get("mediaMetadata", {})
        ms               = meta.get("mediaStatus", {})
        self.status: str = ms.get("mediaGenerationStatus", "UNKNOWN")
        self.complete: bool = self.status in (
            "MEDIA_GENERATION_STATUS_COMPLETE",
            "MEDIA_GENERATION_STATUS_SUCCESS",
            "MEDIA_GENERATION_STATUS_SUCCESSFUL",
        )
        self.failed: bool = self.status in (
            "MEDIA_GENERATION_STATUS_FAILED",
            "MEDIA_GENERATION_STATUS_REJECTED",
        )
        vid = m.get("video", {}).get("generatedVideo", {})
        self.fife_url: str = vid.get("fifeUrl", "")
        self.seed: int     = vid.get("seed", 0)
        self.model: str    = vid.get("model", "")

    def __repr__(self):
        return f"<VideoStatus {self.status} fife={'✓' if self.fife_url else '✗'}>"


class Credits:
    def __init__(self, raw: dict):
        self.credits: int      = raw.get("credits", 0)
        self.tier: str         = raw.get("userPaygateTier", "")
        self.sku: str          = raw.get("sku", "")
        self.service_tier: str = raw.get("serviceTier", "")

    def __repr__(self):
        return f"<Credits {self.credits} ({self.tier})>"


class Workflow:
    def __init__(self, raw: dict):
        self.name: str             = raw.get("name", "")
        meta                       = raw.get("metadata", {})
        self.display_name: str     = meta.get("displayName", "")
        self.create_time: str      = meta.get("createTime", "")
        self.primary_media_id: str = meta.get("primaryMediaId", "")
        self.batch_id: str         = meta.get("batchId", "")
        self.project_id: str       = raw.get("projectId", "")
        self.medias: list          = raw.get("medias", [])

    def __repr__(self):
        return f"<Workflow {self.name[:8]}... '{self.display_name[:30]}'>"


# ── Core API client ──────────────────────────────────────────────────────────

# v0.1.0 FlowAPI direct-generation/editing methods -> their FlowClient replacement. The
# labs.google direct API they called is retired, so the names only survive to guide old code.
_RETIRED_API_METHODS: dict[str, str] = {
    "generate_image":            "FlowClient.generate_image()",
    "generate_video":            "FlowClient.generate_video()",
    "generate_video_from_image": "FlowClient.generate_video(start_image=...)",
    "generate_video_multi_ref":  "FlowClient.generate_video(reference_images=[...])",
    "extend_video":              "FlowClient.extend_video()",
    "reshoot_video":             "FlowClient.camera_motion() / FlowClient.camera_position()",
    "insert_object":             "FlowClient.insert_object()",
    "remove_object":             "FlowClient.remove_object()",
    "upscale_video":             "FlowClient.upscale_video()",
    "extend_loop":               "FlowClient.extend_loop()",
    "generate_video_and_wait":   "FlowClient.generate_video_and_wait()",
    "upscale_and_wait":          "FlowClient.upscale_video()",
    "extend_and_wait":           "FlowClient.extend_video() + FlowClient.wait_for_video()",
    "reshoot_and_wait":          "FlowClient.camera_motion()/camera_position() + wait_for_video()",
    "insert_and_wait":           "FlowClient.insert_object() + FlowClient.wait_for_video()",
    "remove_and_wait":           "FlowClient.remove_object() + FlowClient.wait_for_video()",
    "upload_image":              "FlowClient.generate_video(start_image=<local path>)",
    "batch_generate_images":     "FlowClient.generate_image(count=...)",
    "batch_generate_videos":     "a loop over FlowClient.generate_video()",
    "rename_workflow":           "the flow.google.com web UI (no RPC for it; not ported)",
}


class FlowAPI:
    """
    Read-only RPC & media download client for Google Flow AI (flow.google.com).

    Backed by ``flow._rpc.FlowRPC`` (batchexecute with browser session cookies).
    For video/image generation and editing, use ``FlowClient`` — it drives the
    in-page creation agent (the "agent UI path"). The retired v0.1.0 direct-API
    method names are kept as stubs that raise ``GenerationError`` saying so.
    """

    def __init__(
        self,
        browser_manager,
        project_id: str       = "",
        user_tier: str        = "PAYGATE_TIER_ONE",
        poll_interval_s: float = 5.0,
        default_timeout_s: int = 300,
    ):
        self._bm              = browser_manager
        self.project_id       = project_id
        self._user_tier       = user_tier
        self._poll_interval   = poll_interval_s
        self._timeout_s       = default_timeout_s
        self._rpc = None  # FlowRPC, lazily built
        self._project_page_url = (
            f"{FLOW_BASE}/project/{project_id}" if project_id else ""
        )

    def __getattr__(self, name: str):
        """Turn retired v0.1.0 direct-generation calls into a pointer at FlowClient."""
        target = _RETIRED_API_METHODS.get(name)
        if target is None:
            raise AttributeError(f"{type(self).__name__!r} object has no attribute {name!r}")

        def _retired(*_args, **_kwargs):
            raise GenerationError(
                f"FlowAPI.{name}() is unavailable on flow.google.com (the labs.google "
                f"direct API was retired); use {target} instead."
            )

        return _retired

    def _rpc_client(self):
        """Lazily build the batchexecute RPC client (flow.google.com)."""
        if self._rpc is None:
            from ._rpc import FlowRPC
            self._rpc = FlowRPC(self._bm)
        return self._rpc

    # ── Credits & Config ──────────────────────────────────────────────────────

    async def get_credits(self) -> Credits:
        """Fetch remaining credits via the flow.google.com RPC ``nzlxg``."""
        return Credits(await self._rpc_client().get_credits())

    async def get_video_model_config(self) -> dict:
        """Fetch full video model configuration decoded from RPC ``HTrJv``."""
        cfg = await self._rpc_client().get_model_config()
        return {"result": cfg}

    async def get_flow_app_config(self) -> dict:
        """Return empty app config (no batchexecute equivalent on flow.google.com)."""
        log.debug("get_flow_app_config: not available on flow.google.com backend")
        return {}

    async def get_user_settings(self) -> dict:
        """Return empty user settings (no batchexecute equivalent on flow.google.com)."""
        return {}

    # ── Project data ──────────────────────────────────────────────────────────

    async def get_project_data(self) -> dict:
        """Fetch workflows + media from RPC ``Zzl0ze``, shaped into projectContents."""
        pm = await self._rpc_client().list_project_media(self.project_id)
        media_by_wf: dict = {}
        for m in pm["medias"]:
            media_by_wf.setdefault(m.get("workflow_id", ""), []).append(m)
        workflows = []
        for w in pm["workflows"]:
            medias = media_by_wf.get(w["id"], [])
            workflows.append({
                "name": w["id"],
                "metadata": {
                    "displayName": w["display_name"],
                    "primaryMediaId": medias[0]["media_id"] if medias else "",
                },
                "projectId": self.project_id,
                "medias": [
                    {
                        "name": m["media_id"],
                        "mediaMetadata": {"mediaStatus": {
                            "mediaGenerationStatus": "MEDIA_GENERATION_STATUS_SUCCESSFUL"}},
                        "video": {"generatedVideo": {"fifeUrl": m["signed_url"]}},
                        "image": {"generatedImage": {"fifeUrl": m["poster_url"]}},
                    }
                    for m in medias
                ],
            })
        return {"projectContents": {"workflows": workflows}}

    async def list_workflows(self) -> list[Workflow]:
        data = await self.get_project_data()
        wfs  = data.get("projectContents", {}).get("workflows", [])
        return [Workflow(w) for w in wfs]

    # ── Poll status ───────────────────────────────────────────────────────────

    async def poll_video(
        self,
        media_name: str,
        project_id: Optional[str] = None,
    ) -> VideoStatus:
        """Check the status of a video/image generation job via ``Zzl0ze`` + ``as29s``."""
        pid = project_id or self.project_id
        rpc = self._rpc_client()
        pm = await rpc.list_project_media(pid)
        for m in pm["medias"]:
            if m["media_id"] == media_name:
                # Always sign freshly via as29s; for videos, empty URL means still rendering.
                url = await rpc.get_media_url(media_name)
                if not url and m.get("kind") == "image":
                    url = m.get("poster_url", "")
                if not url:
                    break
                return VideoStatus({
                    "media": [{
                        "name": media_name,
                        "mediaMetadata": {"mediaStatus": {
                            "mediaGenerationStatus": "MEDIA_GENERATION_STATUS_SUCCESSFUL"}},
                        "video": {"generatedVideo": {"fifeUrl": url}},
                        "image": {"generatedImage": {"fifeUrl": url}},
                    }],
                })
        # Upscaled media (<id>_upsampled) is resolved directly via as29s.
        if media_name.endswith("_upsampled"):
            url = await rpc.get_media_url(media_name)
            if url:
                return VideoStatus({
                    "media": [{
                        "name": media_name,
                        "mediaMetadata": {"mediaStatus": {
                            "mediaGenerationStatus": "MEDIA_GENERATION_STATUS_SUCCESSFUL"}},
                        "video": {"generatedVideo": {"fifeUrl": url}},
                        "image": {"generatedImage": {"fifeUrl": url}},
                    }],
                })
        return VideoStatus({
            "media": [{
                "name": media_name,
                "mediaMetadata": {"mediaStatus": {
                    "mediaGenerationStatus": "MEDIA_GENERATION_STATUS_PENDING"}},
            }],
        })

    async def wait_for_video(
        self,
        job: VideoJob,
        *,
        timeout_s: int   = 0,
        poll_s:    float = 5.0,
        on_poll: Optional[Callable] = None,
    ) -> VideoStatus:
        """Wait for a VideoJob to complete, polling every ``poll_s`` seconds."""
        if not job.media_name:
            raise GenerationError("VideoJob has no media_name — cannot poll")

        limit = timeout_s or self._timeout_s
        t0    = time.monotonic()

        while True:
            elapsed = time.monotonic() - t0
            if elapsed > limit:
                raise GenerationTimeout(limit)

            status = await self.poll_video(job.media_name)
            log.debug("poll %s → %s (%.0fs)", job.media_name[:8], status.status, elapsed)

            if on_poll:
                on_poll(status, elapsed)

            if status.complete:
                job.status    = "COMPLETE"
                job.fife_url  = status.fife_url
                job.elapsed_s = elapsed
                return status

            if status.failed:
                raise GenerationError(f"Generation failed: {status.status}")

            await asyncio.sleep(poll_s)

    # ── Media download ────────────────────────────────────────────────────────

    async def download(self, fife_url: str, output_path: str | Path) -> Path:
        """Download a generated image or video using Playwright browser context."""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        resp = await self._bm.context.request.get(fife_url)
        if resp.status != 200:
            raise GenerationError(f"Download failed HTTP {resp.status}")

        body = await resp.body()
        output_path.write_bytes(body)
        log.info("Downloaded %dKB → %s", len(body) // 1024, output_path)
        return output_path

    async def download_image(self, img: GeneratedImage, output_dir: str | Path = ".") -> Path:
        """Download a GeneratedImage to a directory."""
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        path = out / f"{img.media_name[:8]}.jpg"
        await self.download(img.fife_url, path)
        img.file_path = path
        return path

    async def download_video(self, job: VideoJob, output_dir: str | Path = ".") -> Path:
        """Download a completed VideoJob to a directory."""
        if not job.fife_url:
            raise GenerationError("VideoJob has no fife_url")
        out  = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        path = out / f"{job.media_name[:8]}.mp4"
        await self.download(job.fife_url, path)
        job.file_path = path
        return path


# ── Module-level utilities ────────────────────────────────────────────────────

def create_removal_mask(
    width: int,
    height: int,
    regions: list[tuple[int, int, int, int]],
    *,
    quality: int = 85,
) -> bytes:
    """
    Generate a JPEG mask image (white = REMOVE, black = KEEP).

    Args:
        width:    Width in pixels.
        height:   Height in pixels.
        regions:  List of (x, y, w, h) rectangles to mark for removal.
        quality:  JPEG quality (1-95, default 85).

    Returns:
        JPEG bytes ready for base64 encoding.
    """
    try:
        from PIL import Image, ImageDraw
    except ImportError as exc:
        raise ImportError(
            "Pillow is required for create_removal_mask(). "
            "Install with: pip install pillow"
        ) from exc
    import io

    img  = Image.new("RGB", (width, height), (0, 0, 0))   # black = keep
    draw = ImageDraw.Draw(img)
    for x, y, w, h in regions:
        draw.rectangle([x, y, x + w, y + h], fill=(255, 255, 255))   # white = remove

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def encode_mask_b64(mask_bytes: bytes) -> str:
    """Base64-encode a mask JPEG for use in imageMask.imageBytes."""
    import base64
    return base64.b64encode(mask_bytes).decode()


# ── MODEL_REGISTRY ────────────────────────────────────────────────────────────
MODEL_REGISTRY: dict[str, dict] = {
    "veo_3_1_t2v_fast":           {"display": "Veo 3.1 Fast",         "cost": 20,  "caps": ["TEXT","AUDIO"],                   "ratios": ["LANDSCAPE"]},
    "veo_3_1_t2v_fast_portrait":  {"display": "Veo 3.1 Fast Portrait","cost": 20,  "caps": ["TEXT","AUDIO"],                   "ratios": ["PORTRAIT"]},
    "veo_3_1_t2v":                {"display": "Veo 3.1 Quality",      "cost": 100, "caps": ["TEXT","AUDIO"],                   "ratios": ["LANDSCAPE"]},
    "veo_3_1_t2v_portrait":       {"display": "Veo 3.1 Quality P",    "cost": 100, "caps": ["TEXT","AUDIO"],                   "ratios": ["PORTRAIT"]},
    "veo_2_1_fast_d_15_t2v":      {"display": "Veo 2.1 Fast",         "cost": 10,  "caps": ["TEXT"],                           "ratios": ["LANDSCAPE"]},
    "veo_2_0_t2v":                {"display": "Veo 2.0 Quality",      "cost": 100, "caps": ["TEXT"],                           "ratios": ["LANDSCAPE"]},
    "veo_3_1_r2v_fast_landscape": {"display": "Veo 3.1 R2V Fast",     "cost": 20,  "caps": ["MULTI_REFERENCE_NO_STYLE","AUDIO"],"ratios": ["LANDSCAPE"]},
    "veo_3_1_r2v_fast_portrait":  {"display": "Veo 3.1 R2V Fast P",   "cost": 20,  "caps": ["MULTI_REFERENCE_NO_STYLE","AUDIO"],"ratios": ["PORTRAIT"]},
    "veo_3_1_i2v_s_fast":         {"display": "Veo 3.1 Fast I2V",     "cost": 20,  "caps": ["START_IMAGE","AUDIO"],            "ratios": ["LANDSCAPE"]},
    "veo_3_1_i2v_s_fast_portrait":{"display": "Veo 3.1 Fast I2V P",   "cost": 20,  "caps": ["START_IMAGE","AUDIO"],            "ratios": ["PORTRAIT"]},
    "veo_3_1_i2v_s":              {"display": "Veo 3.1 Quality I2V",  "cost": 100, "caps": ["START_IMAGE","AUDIO"],            "ratios": ["LANDSCAPE"]},
    "veo_3_1_i2v_s_portrait":     {"display": "Veo 3.1 Quality I2V P","cost": 100, "caps": ["START_IMAGE","AUDIO"],            "ratios": ["PORTRAIT"]},
    "veo_2_1_fast_d_15_i2v":      {"display": "Veo 2.1 Fast I2V",     "cost": 10,  "caps": ["START_IMAGE"],                   "ratios": ["LANDSCAPE"]},
    "veo_2_0_i2v":                {"display": "Veo 2.0 Quality I2V",  "cost": 100, "caps": ["START_IMAGE"],                   "ratios": ["LANDSCAPE"]},
    "veo_3_1_i2v_s_fast_fl":      {"display": "Veo 3.1 Fast SE",      "cost": 20,  "caps": ["START_IMAGE_AND_END_IMAGE","AUDIO"],"ratios":["LANDSCAPE"]},
    "veo_3_1_i2v_s_fast_portrait_fl":{"display":"Veo 3.1 Fast SE P",  "cost": 20,  "caps": ["START_IMAGE_AND_END_IMAGE","AUDIO"],"ratios":["PORTRAIT"]},
    "veo_3_1_i2v_s_fl":           {"display": "Veo 3.1 Quality SE",   "cost": 100, "caps": ["START_IMAGE_AND_END_IMAGE","AUDIO"],"ratios":["LANDSCAPE"]},
    "veo_3_1_i2v_s_portrait_fl":  {"display": "Veo 3.1 Quality SE P", "cost": 100, "caps": ["START_IMAGE_AND_END_IMAGE","AUDIO"],"ratios":["PORTRAIT"]},
    "veo_2_1_fast_d_15_with_start_image_and_end_image_interpolation":
                                  {"display": "Veo 2.1 SE",           "cost": 10,  "caps": ["START_IMAGE_AND_END_IMAGE"],      "ratios": ["LANDSCAPE"]},
    "veo_3_1_extend_fast_landscape":{"display":"Veo 3.1 Fast Extend", "cost": 20,  "caps": ["VIDEO_EXTENSION"],                "ratios": ["LANDSCAPE"]},
    "veo_3_1_extend_fast_portrait": {"display":"Veo 3.1 Fast Ext P",  "cost": 20,  "caps": ["VIDEO_EXTENSION"],                "ratios": ["PORTRAIT"]},
    "veo_3_1_extend_landscape":   {"display": "Veo 3.1 Quality Ext",  "cost": 100, "caps": ["VIDEO_EXTENSION"],                "ratios": ["LANDSCAPE"]},
    "veo_3_1_extend_portrait":    {"display": "Veo 3.1 Quality Ext P","cost": 100, "caps": ["VIDEO_EXTENSION"],                "ratios": ["PORTRAIT"]},
    "veo_2_1_fast_d_15_with_video_extension":
                                  {"display": "Veo 2.1 Extend",       "cost": 10,  "caps": ["VIDEO_EXTENSION"],                "ratios": ["LANDSCAPE"]},
    "veo_3_0_reshoot_landscape":  {"display": "Camera Motion",        "cost": 20,  "caps": ["RESHOOT"],                        "ratios": ["LANDSCAPE"]},
    "veo_3_0_reshoot_portrait":   {"display": "Camera Motion P",      "cost": 20,  "caps": ["RESHOOT"],                        "ratios": ["PORTRAIT"]},
    "veo_2_0_object_insertion_landscape":{"display":"Insert Object",   "cost": 20,  "caps": ["OBJECT_INSERTION"],               "ratios": ["LANDSCAPE"]},
    "veo_2_0_object_insertion_portrait": {"display":"Insert Object P", "cost": 20,  "caps": ["OBJECT_INSERTION"],               "ratios": ["PORTRAIT"]},
    "veo_2_0_object_removal_landscape":  {"display":"Remove Object",   "cost": 20,  "caps": ["OBJECT_REMOVAL"],                 "ratios": ["LANDSCAPE"]},
    "veo_2_0_object_removal_portrait":   {"display":"Remove Object P", "cost": 20,  "caps": ["OBJECT_REMOVAL"],                 "ratios": ["PORTRAIT"]},
    "veo_3_1_upsampler_1080p":    {"display": "Upscale 1080p",        "cost": 0,   "caps": ["UPSCALING"],                      "ratios": ["LANDSCAPE","PORTRAIT"]},
}
