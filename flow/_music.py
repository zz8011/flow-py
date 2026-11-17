"""High-level async client and models for Google Flow Music (flowmusic.app)."""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

import aiofiles

from ._browser import BrowserManager, _USER_AGENT
from ._exceptions import DownloadError, FlowError, GenerationError, GenerationTimeout
from ._music_rpc import (
    INSTRUMENTAL_MARKER,
    FlowMusicRPC,
    lyrics_id_for_text,
)


# ── Data models ────────────────────────────────────────────────────────

@dataclass
class MusicCredits:
    credits_remaining: float
    tokens_remaining: float
    subscription_tier: str = "free"
    subscription_plan: str = ""
    provider: str = ""


@dataclass
class SongClip:
    id: str
    title: str
    op_type: str = ""
    duration_s: float = 0.0
    status: str = "completed"
    lyrics: str = ""
    sound_prompt: str = ""
    audio_url: str = ""
    wav_url: str = ""
    image_url: str = ""
    conversation_id: str = ""
    created_at: str = ""
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def complete(self) -> bool:
        return self.status == "completed" and bool(self.audio_url or self.wav_url)

    @classmethod
    def from_api(cls, d: dict[str, Any]) -> "SongClip":
        dur_obj = d.get("duration") or {}
        dur_status = dur_obj.get("status") if isinstance(dur_obj, dict) else "completed"
        dur_val = 0.0
        if isinstance(dur_obj, dict) and dur_obj.get("value") is not None:
            try:
                dur_val = float(dur_obj["value"])
            except (TypeError, ValueError):
                dur_val = 0.0
        elif isinstance(dur_obj, (int, float)):
            dur_val = float(dur_obj)

        lyr_obj = d.get("lyrics") or {}
        lyr_text = ""
        if isinstance(lyr_obj, dict):
            val = lyr_obj.get("value")
            if isinstance(val, dict):
                lyr_text = val.get("text") or ""
            elif isinstance(val, str):
                lyr_text = val
        elif isinstance(lyr_obj, str):
            lyr_text = lyr_obj

        op = d.get("operation") or {}
        prompt = (
            op.get("sound_prompt")
            or op.get("instruction")
            or op.get("prompt")
            or ""
        )
        return cls(
            id=d.get("id") or d.get("clip_id") or "",
            title=d.get("title") or op.get("title") or op.get("output_title") or "Untitled",
            op_type=d.get("op_type") or op.get("op_type") or "",
            duration_s=dur_val,
            status=dur_status or "pending",
            lyrics=lyr_text,
            sound_prompt=prompt,
            audio_url=d.get("audio_url") or "",
            wav_url=d.get("wav_url") or "",
            image_url=d.get("image_url") or "",
            conversation_id=op.get("conversation_id") or "",
            created_at=d.get("created_at") or "",
            raw=d,
        )


@dataclass
class StemClip:
    stem_type: str
    clip: SongClip


@dataclass
class ProducerTurn:
    conversation_id: str
    text: str
    clips: list[SongClip] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    title: Optional[str] = None


async def _probe_duration(path: str | Path) -> float:
    proc = await asyncio.create_subprocess_exec(
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=nw=1:nk=1", str(path),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    try:
        return float(out.decode().strip())
    except ValueError:
        raise FlowError(f"ffprobe could not read the video duration: {err.decode()[:200]}")


def _extract_clip_ids_from_returns(tool_returns: list[dict[str, Any]]) -> list[str]:
    ids: list[str] = []
    for tr in tool_returns:
        c = tr.get("content")
        if not isinstance(c, dict):
            continue
        for key in ("clip_id", "clip_id_b", "result_clip_id"):
            val = c.get(key)
            if isinstance(val, str) and len(val) == 36 and val not in ids:
                ids.append(val)
        for out in c.get("clip_outputs") or []:
            if isinstance(out, dict):
                val = out.get("clip_id")
                if isinstance(val, str) and len(val) == 36 and val not in ids:
                    ids.append(val)
        for st in c.get("stems") or []:
            if isinstance(st, dict):
                val = st.get("clip_id")
                if isinstance(val, str) and len(val) == 36 and val not in ids:
                    ids.append(val)
    return ids


# ── Client ─────────────────────────────────────────────────────────────

class FlowMusicClient:
    """High-level async client for Google Flow Music (Lyria 3.5 / Producer)."""

    def __init__(
        self,
        rpc: FlowMusicRPC,
        *,
        timeout_s: int = 360,
        poll_interval_s: float = 3.0,
    ):
        self._rpc = rpc
        self.timeout_s = timeout_s
        self.poll_interval_s = poll_interval_s

    @classmethod
    async def create(
        cls,
        *,
        browser_manager: Optional[BrowserManager] = None,
        headless: bool = True,
        cdp_url: Optional[str] = None,
        timeout_s: int = 360,
    ) -> "FlowMusicClient":
        rpc = FlowMusicRPC(browser_manager, headless=headless, cdp_url=cdp_url)
        return cls(rpc, timeout_s=timeout_s)

    async def close(self) -> None:
        await self._rpc.close()

    async def __aenter__(self) -> "FlowMusicClient":
        return self

    async def __aexit__(self, *_) -> None:
        await self.close()

    # ── Read-only operations ───────────────────────────────────────────

    async def get_credits(self) -> MusicCredits:
        info = await self._rpc.get_credits()
        return MusicCredits(
            credits_remaining=info["credits_remaining"],
            tokens_remaining=info["tokens_remaining"],
            subscription_tier=info["subscription_tier"],
            subscription_plan=info["subscription_plan"],
            provider=info["provider"],
        )

    async def get_models(self) -> list[dict[str, Any]]:
        return await self._rpc.get_models()

    async def list_songs(self, limit: int = 20) -> list[SongClip]:
        raw_clips = await self._rpc.list_auth_clips(limit=limit)
        return [SongClip.from_api(c) for c in raw_clips]

    async def get_song(self, clip_id: str) -> SongClip:
        raw = await self._rpc.resolve_clip(clip_id)
        return SongClip.from_api(raw)

    async def list_sessions(self, limit: int = 20) -> list[dict[str, Any]]:
        return await self._rpc.list_conversations(limit=limit)

    async def get_session(self, conversation_id: str) -> dict[str, Any]:
        return await self._rpc.get_conversation(conversation_id)

    async def wait_for_song(
        self,
        clip_id: str,
        *,
        timeout_s: Optional[int] = None,
        on_poll: Optional[Callable[[SongClip, float], None]] = None,
    ) -> SongClip:
        timeout = timeout_s or self.timeout_s
        start = time.monotonic()
        last_clip: Optional[SongClip] = None
        while time.monotonic() - start < timeout:
            clips = await self._rpc.get_clips([clip_id])
            if not clips:
                # Fallback to user clips list
                user_clips = await self._rpc.list_auth_clips(limit=30)
                clips = [c for c in user_clips if c.get("id") == clip_id]
            if clips:
                last_clip = SongClip.from_api(clips[0])
                if on_poll:
                    on_poll(last_clip, time.monotonic() - start)
                if last_clip.complete:
                    return last_clip
                if last_clip.status in ("failed", "error"):
                    raise GenerationError(f"Song generation failed for {clip_id}")
            await asyncio.sleep(self.poll_interval_s)
        raise GenerationTimeout(
            f"Song {clip_id} did not finish within {timeout}s (last={last_clip})"
        )

    # ── Generation & Producer Chat ─────────────────────────────────────

    async def generate_song(
        self,
        prompt: str,
        *,
        lyrics: str = "",
        instrumental: bool = False,
        title: str = "",
        bpm: Optional[int] = None,
        duration_s: Optional[int] = None,
        seed: Optional[int] = None,
        model: str = "Lyria 3.5",
        conversation_id: Optional[str] = None,
        wait: bool = True,
        on_progress: Optional[Callable[[str], None]] = None,
    ) -> SongClip:
        """Generate a song using Flow Music's Compose pipeline."""
        song_title = title.strip() or "Untitled"
        lyrics_body = INSTRUMENTAL_MARKER if instrumental else lyrics.strip()
        if duration_s and duration_s > 0:
            mm, ss = divmod(int(duration_s), 60)
            end_tag = f"[End - {mm}:{ss:02d}]"
            lyrics_body = f"{lyrics_body}\n{end_tag}" if lyrics_body else end_tag

        sound_prompt = f"{prompt.strip()}, {bpm} bpm" if bpm else prompt.strip()

        if model == "Lyria 4":
            # Lyria 4 two-stage song plan + generate flow
            has_custom_lyrics = not instrumental and bool(lyrics.strip())
            intent_parts = [
                prompt.strip(),
                f"{bpm} bpm" if bpm else "",
                f"length {duration_s // 60}:{duration_s % 60:02d}" if duration_s else "",
                "instrumental, no vocals" if instrumental else "",
            ]
            intent = ", ".join(p for p in intent_parts if p) or "A new song"
            plan_args: dict[str, Any] = {
                "user_intent": intent,
                "reference_clip_ids": [],
                "region_edits": [],
            }
            if has_custom_lyrics:
                plan_args["lyrics"] = lyrics.strip()
            if title.strip():
                plan_args["title"] = title.strip()
            cid, plan_res = await self._rpc.execute_tool_call(
                "lyria__write_song_plan",
                plan_args,
                conversation_id=conversation_id,
                selected_model=model,
                on_progress=on_progress,
                timeout_s=self.timeout_s,
            )
            plan_id = (plan_res or {}).get("song_plan_id")
            if not plan_id:
                raise GenerationError(f"lyria__write_song_plan returned no song_plan_id: {plan_res}")
            gen_args: dict[str, Any] = {"song_plan_id": plan_id, "prompt_strength": 1.0}
            if seed is not None:
                gen_args["seed"] = seed
            _, gen_res = await self._rpc.execute_tool_call(
                "lyria__generate_song",
                gen_args,
                conversation_id=cid,
                selected_model=model,
                on_progress=on_progress,
                timeout_s=self.timeout_s,
            )
        else:
            # Lyria 3.5 / Lyria 3 Pro direct create flow
            lyr_id = lyrics_id_for_text(lyrics_body)
            lyr_map = {lyr_id: lyrics_body} if lyr_id and lyrics_body else {}
            create_args: dict[str, Any] = {
                "sound_prompt": sound_prompt,
                "lyrics_id": lyr_id,
                "title": song_title,
                "seed": seed,
                "image_id": None,
            }
            _, gen_res = await self._rpc.execute_tool_call(
                "audio__create_song",
                create_args,
                conversation_id=conversation_id,
                selected_model=model,
                lyrics_map=lyr_map,
                on_progress=on_progress,
                timeout_s=self.timeout_s,
            )

        clip_id = (gen_res or {}).get("clip_id")
        if not clip_id:
            raise GenerationError(f"Song generation returned no clip_id: {gen_res}")
        if wait:
            return await self.wait_for_song(clip_id)
        return SongClip(id=clip_id, title=(gen_res or {}).get("title") or song_title, status="pending")

    async def generate_lyrics(
        self,
        prompt: str,
        *,
        model: str = "Lyria 3.5",
        conversation_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Generate song lyrics from a topic or style description."""
        _, res = await self._rpc.execute_tool_call(
            "lyrics__create",
            {"prompt": prompt},
            conversation_id=conversation_id,
            selected_model=model,
            timeout_s=self.timeout_s,
        )
        if isinstance(res, dict):
            return res
        return {"title": "", "lyrics": str(res or "")}

    async def chat(
        self,
        prompt: str,
        *,
        conversation_id: Optional[str] = None,
        audio_path: Optional[str | Path] = None,
        video_path: Optional[str | Path] = None,
        model: str = "Lyria 3.5",
        wait_clips: bool = True,
        on_progress: Optional[Callable[[str], None]] = None,
    ) -> ProducerTurn:
        """Converse with the Flow Music Producer agent (creates/edits songs interactively)."""
        upload_parts: list[dict[str, Any]] = []
        if audio_path:
            up = await self._rpc.upload_audio(audio_path, selected_model=model)
            if up.get("url"):
                upload_parts.append(
                    {"kind": "audio-url", "url": up["url"], "media_type": "audio/mpeg"}
                )

        if video_path:
            v = await self._rpc.upload_multipart("/video/upload", {}, "video", video_path)
            if not v.get("video_url"):
                raise GenerationError(f"Video upload returned no video_url: {v}")
            upload_parts.append(
                {"kind": "video-url", "url": v["video_url"], "media_type": "video/mp4"}
            )

        res = await self._rpc.send_chat(
            prompt,
            conversation_id=conversation_id,
            selected_model=model,
            upload_parts=upload_parts or None,
            on_progress=on_progress,
            timeout_s=self.timeout_s,
        )
        clip_ids = _extract_clip_ids_from_returns(res["tool_returns"])
        clips: list[SongClip] = []
        if clip_ids:
            if wait_clips:
                for cid in clip_ids:
                    clips.append(await self.wait_for_song(cid))
            else:
                raw_list = await self._rpc.get_clips(clip_ids)
                clips = [SongClip.from_api(c) for c in raw_list]

        return ProducerTurn(
            conversation_id=res.get("conversation_id") or "",
            text=res.get("text") or "",
            clips=clips,
            suggestions=res.get("suggestions") or [],
            title=res.get("title"),
        )

    async def score_video(
        self,
        video_path: str | Path,
        style: str = "",
        *,
        model: str = "Lyria 3.5",
        fade_out_s: float = 1.5,
        on_progress: Optional[Callable[[str], None]] = None,
    ) -> list[SongClip]:
        """Have Producer watch a video and compose matching music, trimmed to the video length (≈5 credits/song)."""
        dur = await _probe_duration(video_path)
        prompt = (
            "请先看这段视频，然后根据画面的内容、情绪和节奏，为它生成一首纯音乐配乐"
            f"（视频时长约 {dur:.0f} 秒）。{style}"
        )
        turn = await self.chat(prompt, video_path=video_path, model=model, on_progress=on_progress)
        out: list[SongClip] = []
        for c in turn.clips:
            if c.duration_s > dur + 0.5:  # trim 免费
                c = await self.trim_song(c.id, 0.0, dur, fade_out_s=min(fade_out_s, dur / 2))
            out.append(c)
        if not out:
            raise GenerationError(f"Producer produced no song for the video: {turn.text[:200]}")
        return out

    # ── Editing, Stems & Post-processing ───────────────────────────────

    async def _run_recipe_edit(
        self,
        recipe: dict[str, Any],
        title: str,
        *,
        model: str = "Lyria 3.5",
        conversation_id: Optional[str] = None,
        wait: bool = True,
        on_progress: Optional[Callable[[str], None]] = None,
    ) -> SongClip:
        recipe_id = await self._rpc.create_recipe(recipe)
        _, res = await self._rpc.execute_tool_call(
            "audio__render_edit",
            {"recipe_id": recipe_id, "title": title, "image_id": None},
            conversation_id=conversation_id,
            selected_model=model,
            on_progress=on_progress,
            timeout_s=self.timeout_s,
        )
        outputs = (res or {}).get("clip_outputs") or []
        if not outputs or not outputs[0].get("clip_id"):
            raise GenerationError(f"audio__render_edit returned no clip_outputs: {res}")
        out_id = outputs[0]["clip_id"]
        if wait:
            return await self.wait_for_song(out_id)
        return SongClip(id=out_id, title=outputs[0].get("title") or title, status="pending")

    async def extend_song(
        self,
        clip_id: str,
        *,
        extend_s: float = 30.0,
        extend_from_s: Optional[float] = None,
        instruction: str = "",
        title: str = "",
        seed: Optional[int] = None,
        model: str = "Lyria 3.5",
        wait: bool = True,
        on_progress: Optional[Callable[[str], None]] = None,
    ) -> SongClip:
        """Extend an existing song by ``extend_s`` seconds."""
        src = await self.get_song(clip_id)
        out_title = title.strip() or f"{src.title} (Extended)"
        recipe = {
            "nodes": [
                {"node_type": "Input", "clip_id": src.id, "input_ids": [], "output_ids": ["input"]},
                {
                    "node_type": "ExtendSection",
                    "input_ids": ["input"],
                    "output_ids": ["processing"],
                    "instruction": instruction,
                    "extend_s": float(extend_s),
                    "extend_from_s": float(extend_from_s) if extend_from_s is not None else None,
                    "seed": seed,
                },
                {
                    "node_type": "Output",
                    "input_ids": ["processing"],
                    "output_ids": ["output"],
                    "title": out_title,
                    "generate_image": True,
                },
            ],
            "instruction": instruction or None,
        }
        return await self._run_recipe_edit(
            recipe, out_title, model=model, wait=wait, on_progress=on_progress
        )

    async def cover_song(
        self,
        clip_id: str,
        instruction: str,
        *,
        strength: float = 0.5,
        title: str = "",
        seed: Optional[int] = None,
        model: str = "Lyria 3.5",
        wait: bool = True,
        on_progress: Optional[Callable[[str], None]] = None,
    ) -> SongClip:
        """Create a style cover / remix of an existing song."""
        src = await self.get_song(clip_id)
        out_title = title.strip() or f"{src.title} (Cover)"
        recipe = {
            "nodes": [
                {"node_type": "Input", "clip_id": src.id, "input_ids": [], "output_ids": ["input"]},
                {
                    "node_type": "CoverSong",
                    "input_ids": ["input"],
                    "output_ids": ["processing"],
                    "instruction": instruction,
                    "strength": float(strength),
                    "seed": seed,
                },
                {
                    "node_type": "Output",
                    "input_ids": ["processing"],
                    "output_ids": ["output"],
                    "title": out_title,
                    "generate_image": True,
                },
            ],
            "instruction": instruction or None,
        }
        return await self._run_recipe_edit(
            recipe, out_title, model=model, wait=wait, on_progress=on_progress
        )

    async def replace_section(
        self,
        clip_id: str,
        start_s: float,
        end_s: float,
        instruction: str = "",
        *,
        title: str = "",
        seed: Optional[int] = None,
        model: str = "Lyria 3.5",
        wait: bool = True,
        on_progress: Optional[Callable[[str], None]] = None,
    ) -> SongClip:
        """Inpaint / replace a time section ``[start_s, end_s]`` in an existing song."""
        if end_s <= start_s:
            raise FlowError(f"end_s ({end_s}) must be greater than start_s ({start_s})")
        src = await self.get_song(clip_id)
        out_title = title.strip() or f"{src.title} (Replaced)"
        recipe = {
            "nodes": [
                {"node_type": "Input", "clip_id": src.id, "input_ids": [], "output_ids": ["input"]},
                {
                    "node_type": "ReplaceSection",
                    "input_ids": ["input"],
                    "output_ids": ["processing"],
                    "instruction": instruction,
                    "masks": [{"start_s": float(start_s), "end_s": float(end_s)}],
                    "seed": seed,
                },
                {
                    "node_type": "Output",
                    "input_ids": ["processing"],
                    "output_ids": ["output"],
                    "title": out_title,
                    "generate_image": True,
                },
            ],
            "instruction": instruction or None,
        }
        return await self._run_recipe_edit(
            recipe, out_title, model=model, wait=wait, on_progress=on_progress
        )

    async def trim_song(
        self,
        clip_id: str,
        start_s: float = 0.0,
        end_s: float = 30.0,
        *,
        fade_in_s: float = 0.0,
        fade_out_s: float = 0.0,
        title: str = "",
        wait: bool = True,
    ) -> SongClip:
        """Deterministically trim a song to ``[start_s, end_s]`` with optional fades."""
        if end_s <= start_s:
            raise FlowError(f"end_s ({end_s}) must be greater than start_s ({start_s})")
        src = await self.get_song(clip_id)
        out_title = title.strip() or f"{src.title} ({end_s - start_s:.0f}s Trim)"
        graph: list[dict[str, Any]] = [
            {"node_type": "Input", "node_id": "input", "track_id": src.id},
            {
                "node_type": "Trim",
                "node_id": "trim",
                "input_ids": ["input"],
                "start_s": float(start_s),
                "end_s": float(end_s),
            },
        ]
        last_node = "trim"
        if fade_in_s > 0 or fade_out_s > 0:
            graph.append(
                {
                    "node_type": "Fade",
                    "node_id": "fade",
                    "input_ids": ["trim"],
                    "fade_in_s": float(fade_in_s),
                    "fade_out_s": float(fade_out_s),
                }
            )
            last_node = "fade"
        graph.append({"node_type": "Output", "input_ids": [last_node]})

        _, res = await self._rpc.execute_tool_call(
            "audio__apply_effect",
            {"graph": graph, "output_title": out_title},
            timeout_s=self.timeout_s,
        )
        out_id = (res or {}).get("result_clip_id")
        if not out_id:
            raise GenerationError(f"audio__apply_effect returned no result_clip_id: {res}")
        if wait:
            return await self.wait_for_song(out_id)
        return SongClip(id=out_id, title=out_title, status="pending")

    async def split_stems(
        self,
        clip_id: str,
        *,
        on_progress: Optional[Callable[[str], None]] = None,
    ) -> list[StemClip]:
        """Extract separated audio stems (vocals, drums, bass, other) from a song."""
        src = await self.get_song(clip_id)
        existing = await self._rpc.get_clip_stems(src.id)
        stem_entries = existing
        if not stem_entries:
            _, res = await self._rpc.execute_tool_call(
                "audio__split_stems",
                {"clip_id": src.id},
                on_progress=on_progress,
                timeout_s=self.timeout_s,
            )
            stem_entries = (res or {}).get("stems") or []
        if not stem_entries:
            raise GenerationError(f"Stem splitting returned no stems for {src.id}")

        out: list[StemClip] = []
        for entry in stem_entries:
            stype = entry.get("stem_type") or entry.get("type") or "stem"
            scid = entry.get("clip_id") or entry.get("id")
            if scid:
                sclip = await self.wait_for_song(scid)
                out.append(StemClip(stem_type=stype, clip=sclip))
        return out

    # ── Download ───────────────────────────────────────────────────────

    async def download_song(
        self,
        clip_or_id: str | SongClip,
        dest: str | Path,
        *,
        audio_format: str = "mp3",
    ) -> Path:
        """Download a song in ``mp3``, ``wav`` (lossless), or ``m4a`` format."""
        fmt = audio_format.lower().lstrip(".")
        if fmt not in ("mp3", "wav", "m4a"):
            raise FlowError(
                f"Unsupported audio format '{audio_format}' (choose 'mp3', 'wav', or 'm4a')"
            )

        clip = clip_or_id if isinstance(clip_or_id, SongClip) else await self.get_song(clip_or_id)
        if not clip.complete:
            clip = await self.wait_for_song(clip.id)

        dest_path = Path(dest)
        if dest_path.is_dir() or not dest_path.suffix:
            dest_path.mkdir(parents=True, exist_ok=True)
            safe_title = "".join(
                c if c.isalnum() or c in ("-", "_", " ") else "_" for c in clip.title
            ).strip().replace(" ", "_")[:40] or "song"
            dest_path = dest_path / f"{safe_title}_{clip.id[:8]}.{fmt}"
        else:
            dest_path.parent.mkdir(parents=True, exist_ok=True)

        token = await self._rpc._bootstrap()
        http = await self._rpc._get_http()
        dl_url = f"https://www.flowmusic.app/__api/download/audio/{clip.id}"
        headers = {"Authorization": f"Bearer {token}", "User-Agent": _USER_AGENT}
        async with http.get(dl_url, params={"format": fmt}, headers=headers) as resp:
            if resp.status != 200:
                # Fallback to direct CDN URL for m4a/wav if available
                fallback = clip.wav_url if fmt == "wav" else (clip.audio_url if fmt == "m4a" else "")
                if not fallback:
                    raise DownloadError(
                        f"Download failed (HTTP {resp.status}) for song {clip.id} ({fmt})"
                    )
                async with http.get(fallback, headers={"User-Agent": _USER_AGENT}) as fb_resp:
                    if fb_resp.status != 200:
                        raise DownloadError(f"Download failed (HTTP {fb_resp.status}) for {fallback}")
                    async with aiofiles.open(dest_path, "wb") as f:
                        async for chunk in fb_resp.content.iter_chunked(65536):
                            await f.write(chunk)
            else:
                async with aiofiles.open(dest_path, "wb") as f:
                    async for chunk in resp.content.iter_chunked(65536):
                        await f.write(chunk)

        if dest_path.stat().st_size == 0:
            raise DownloadError(f"Downloaded empty file: {dest_path}")
        return dest_path
