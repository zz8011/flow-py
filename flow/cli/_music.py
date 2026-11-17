"""CLI command group ``flow music`` for Google Flow Music (flowmusic.app)."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Optional

import click

from .._exceptions import AuthError, DownloadError, FlowError, GenerationError, GenerationTimeout
from .._music import FlowMusicClient, SongClip


def _run(coro):
    return asyncio.run(coro)


async def _make_music_client(headless: bool = True, cdp: bool = False) -> FlowMusicClient:
    cdp_url = "http://127.0.0.1:9222" if cdp else None
    return await FlowMusicClient.create(headless=headless, cdp_url=cdp_url)


def _progress_cb(msg: str) -> None:
    click.echo(f"  🎵 {msg}", err=True)


def _print_clip_summary(clip: SongClip) -> None:
    click.echo(f"   clip_id:  {clip.id}")
    click.echo(f"   title:    {clip.title}")
    if clip.duration_s:
        click.echo(f"   duration: {clip.duration_s:.1f}s")


@click.group("music")
def music_cli():
    """🎵 Google Flow Music (flowmusic.app / Lyria 3.5) — music generation & editing"""


# ── Status, Credits, Models, Songs, Sessions ───────────────────────────

@music_cli.command("status")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.option("--cdp", is_flag=True)
def music_status(as_json: bool, cdp: bool):
    """Check Flow Music auth, subscription, credits, and recent songs."""
    async def _go():
        client = await _make_music_client(cdp=cdp)
        try:
            credits = await client.get_credits()
            songs = await client.list_songs(limit=5)
            info = {
                "auth": "authenticated",
                "credits_remaining": credits.credits_remaining,
                "tokens_remaining": credits.tokens_remaining,
                "tier": credits.subscription_tier,
                "plan": credits.subscription_plan,
                "provider": credits.provider,
                "recent_songs": [
                    {
                        "id": s.id,
                        "title": s.title,
                        "duration_s": s.duration_s,
                        "op_type": s.op_type,
                    }
                    for s in songs
                ],
            }
            if as_json:
                click.echo(json.dumps(info, ensure_ascii=False, indent=2))
                return
            click.echo(f"\n{'─' * 54}")
            click.echo("  🎵 Flow Music Status (flowmusic.app)")
            click.echo(f"{'─' * 54}")
            click.echo("  Auth:      ✅ authenticated")
            click.echo(f"  Tier:      {credits.subscription_tier} ({credits.provider or 'standard'})")
            click.echo(f"  Credits:   💳 {credits.credits_remaining:.0f} (tokens: {credits.tokens_remaining:.0f})")
            if songs:
                click.echo(f"\n  🎶 Recent songs ({len(songs)}):")
                for s in songs:
                    click.echo(f"     {s.id[:12]}...  {s.duration_s:5.1f}s  {s.title[:32]}")
            click.echo(f"{'─' * 54}\n")
        except AuthError as e:
            if as_json:
                click.echo(json.dumps({"auth": "not_logged_in", "error": str(e)}, indent=2))
            else:
                click.echo(f"❌ {e}", err=True)
            sys.exit(1)
        finally:
            await client.close()

    _run(_go())


@music_cli.command("credits")
@click.option("--json", "as_json", is_flag=True)
@click.option("--cdp", is_flag=True)
def music_credits(as_json: bool, cdp: bool):
    """Show remaining Flow Music credits and subscription tier."""
    async def _go():
        client = await _make_music_client(cdp=cdp)
        try:
            c = await client.get_credits()
            if as_json:
                click.echo(json.dumps(c.__dict__, ensure_ascii=False, indent=2))
                return
            click.echo(f"\n💳 Music Credits remaining: {c.credits_remaining:.0f}")
            click.echo(f"   Tokens remaining: {c.tokens_remaining:.0f}")
            click.echo(f"   Tier:             {c.subscription_tier} ({c.subscription_plan or c.provider})")
        finally:
            await client.close()

    _run(_go())


@music_cli.command("models")
@click.option("--json", "as_json", is_flag=True)
@click.option("--cdp", is_flag=True)
def music_models(as_json: bool, cdp: bool):
    """List available Flow Music models (Lyria 3.5, etc.)."""
    async def _go():
        client = await _make_music_client(cdp=cdp)
        try:
            models = await client.get_models()
            if as_json:
                click.echo(json.dumps(models, ensure_ascii=False, indent=2))
                return
            click.echo(f"\n{'Model':22} {'Default':9} {'Description'}")
            click.echo("─" * 68)
            for m in models:
                mark = "✓" if m.get("is_default") else ""
                click.echo(
                    f"{m.get('public_name', '?'):22} {mark:9} {m.get('description', '')}"
                )
        finally:
            await client.close()

    _run(_go())


@music_cli.command("songs")
@click.option("-n", "--limit", default=20, show_default=True)
@click.option("--json", "as_json", is_flag=True)
@click.option("--cdp", is_flag=True)
def music_songs(limit: int, as_json: bool, cdp: bool):
    """List songs in your Flow Music library."""
    async def _go():
        client = await _make_music_client(cdp=cdp)
        try:
            songs = await client.list_songs(limit=limit)
            if as_json:
                click.echo(
                    json.dumps(
                        [
                            {
                                "id": s.id,
                                "title": s.title,
                                "duration_s": s.duration_s,
                                "op_type": s.op_type,
                                "audio_url": s.audio_url,
                                "wav_url": s.wav_url,
                            }
                            for s in songs
                        ],
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                return
            if not songs:
                click.echo("No songs found.")
                return
            click.echo(f"\n  {'Clip ID':38} {'Dur':7} {'Type':22} {'Title'}")
            click.echo("  " + "─" * 92)
            for s in songs:
                click.echo(
                    f"  {s.id:38} {s.duration_s:5.1f}s  {s.op_type[:20]:22} {s.title[:34]}"
                )
        finally:
            await client.close()

    _run(_go())


@music_cli.command("sessions")
@click.option("-n", "--limit", default=20, show_default=True)
@click.option("--json", "as_json", is_flag=True)
@click.option("--cdp", is_flag=True)
def music_sessions(limit: int, as_json: bool, cdp: bool):
    """List Producer chat sessions."""
    async def _go():
        client = await _make_music_client(cdp=cdp)
        try:
            convs = await client.list_sessions(limit=limit)
            if as_json:
                click.echo(json.dumps(convs, ensure_ascii=False, indent=2))
                return
            if not convs:
                click.echo("No sessions found.")
                return
            click.echo(f"\n  {'Session ID':38} {'Title'}")
            click.echo("  " + "─" * 70)
            for c in convs:
                click.echo(f"  {c.get('id', ''):38} {(c.get('title') or '(untitled)')[:40]}")
        finally:
            await client.close()

    _run(_go())


# ── Generation & Producer Chat ─────────────────────────────────────────

@music_cli.command("generate")
@click.argument("prompt")
@click.option("--lyrics", "-l", default="", help="Custom lyrics text (or @path/to/lyrics.txt)")
@click.option("--instrumental", "-i", is_flag=True, help="Instrumental only (no vocals)")
@click.option("--title", "-t", default="", help="Song title")
@click.option("--bpm", type=int, default=None, help="Target tempo in BPM")
@click.option("--duration", "-d", type=int, default=None, help="Target duration in seconds")
@click.option("--seed", type=int, default=None, help="Optional generation seed")
@click.option("--model", "-m", default="Lyria 3.5", show_default=True, help="Music model name")
@click.option("--format", "-f", "audio_format", type=click.Choice(["mp3", "wav", "m4a"]), default="mp3", show_default=True)
@click.option("--output", "-o", default="./flow_music", show_default=True, help="Output file or directory")
@click.option("--wait/--no-wait", default=True, show_default=True)
@click.option("--headless/--headed", default=True, show_default=True)
@click.option("--cdp", is_flag=True)
def music_generate(
    prompt: str,
    lyrics: str,
    instrumental: bool,
    title: str,
    bpm: Optional[int],
    duration: Optional[int],
    seed: Optional[int],
    model: str,
    audio_format: str,
    output: str,
    wait: bool,
    headless: bool,
    cdp: bool,
):
    """Generate a song with Lyria 3.5 from style prompt and optional lyrics."""
    async def _go():
        lyr_text = lyrics
        if lyr_text.startswith("@") and Path(lyr_text[1:]).is_file():
            lyr_text = Path(lyr_text[1:]).read_text()
        client = await _make_music_client(headless=headless, cdp=cdp)
        try:
            mode_str = "instrumental" if instrumental else ("custom lyrics" if lyr_text else "vocal/auto")
            click.echo(f"🎵 Generating song [{model} | {mode_str}]: \"{prompt[:60]}\"")
            clip = await client.generate_song(
                prompt,
                lyrics=lyr_text,
                instrumental=instrumental,
                title=title,
                bpm=bpm,
                duration_s=duration,
                seed=seed,
                model=model,
                wait=wait,
                on_progress=_progress_cb,
            )
            click.echo("✅ Song generated")
            _print_clip_summary(clip)
            if wait and clip.complete and output:
                saved = await client.download_song(clip, output, audio_format=audio_format)
                click.echo(f"💾 Saved: {saved}")
        except (FlowError, GenerationError, GenerationTimeout) as e:
            click.echo(f"\n❌ {e}", err=True)
            sys.exit(1)
        finally:
            await client.close()

    _run(_go())


@music_cli.command("chat")
@click.argument("prompt")
@click.option("--session", "-s", default=None, help="Existing conversation ID to continue")
@click.option("--audio", default=None, type=click.Path(exists=True), help="Upload reference audio file")
@click.option("--model", "-m", default="Lyria 3.5", show_default=True)
@click.option("--format", "-f", "audio_format", type=click.Choice(["mp3", "wav", "m4a"]), default="mp3", show_default=True)
@click.option("--output", "-o", default=None, help="Directory to auto-download generated songs")
@click.option("--headless/--headed", default=True, show_default=True)
@click.option("--cdp", is_flag=True)
def music_chat(
    prompt: str,
    session: Optional[str],
    audio: Optional[str],
    model: str,
    audio_format: str,
    output: Optional[str],
    headless: bool,
    cdp: bool,
):
    """Chat with the Flow Music Producer agent to co-create or refine songs."""
    async def _go():
        client = await _make_music_client(headless=headless, cdp=cdp)
        try:
            turn = await client.chat(
                prompt,
                conversation_id=session,
                audio_path=audio,
                model=model,
                on_progress=_progress_cb,
            )
            click.echo(f"\n💬 Session: {turn.conversation_id}")
            if turn.text:
                click.echo(f"\n{turn.text}\n")
            if turn.clips:
                click.echo(f"🎶 Produced {len(turn.clips)} clip(s):")
                for c in turn.clips:
                    click.echo(f"   • {c.id}  [{c.duration_s:.1f}s]  {c.title}")
                    if output:
                        saved = await client.download_song(c, output, audio_format=audio_format)
                        click.echo(f"     💾 {saved}")
            if turn.suggestions:
                click.echo(f"💡 Suggestions: {' | '.join(turn.suggestions)}")
        except (FlowError, GenerationError, GenerationTimeout) as e:
            click.echo(f"\n❌ {e}", err=True)
            sys.exit(1)
        finally:
            await client.close()

    _run(_go())


@music_cli.command("lyrics")
@click.argument("prompt")
@click.option("--json", "as_json", is_flag=True)
@click.option("--cdp", is_flag=True)
def music_lyrics(prompt: str, as_json: bool, cdp: bool):
    """Generate song lyrics from a theme or style prompt."""
    async def _go():
        client = await _make_music_client(cdp=cdp)
        try:
            res = await client.generate_lyrics(prompt)
            if as_json:
                click.echo(json.dumps(res, ensure_ascii=False, indent=2))
                return
            if res.get("title"):
                click.echo(f"\n📝 {res['title']}\n" + "─" * 40)
            click.echo(res.get("lyrics") or json.dumps(res, ensure_ascii=False, indent=2))
        except (FlowError, GenerationError, GenerationTimeout) as e:
            click.echo(f"\n❌ {e}", err=True)
            sys.exit(1)
        finally:
            await client.close()

    _run(_go())


# ── Editing, Stems & Download ──────────────────────────────────────────

@music_cli.command("extend")
@click.argument("clip_id")
@click.option("--seconds", "-s", type=float, default=30.0, show_default=True, help="Seconds to extend")
@click.option("--from-sec", type=float, default=None, help="Timestamp in source song to extend from")
@click.option("--prompt", "-p", default="", help="Continuation style/direction instruction")
@click.option("--title", "-t", default="", help="Output song title")
@click.option("--format", "-f", "audio_format", type=click.Choice(["mp3", "wav", "m4a"]), default="mp3", show_default=True)
@click.option("--output", "-o", default="./flow_music", show_default=True)
@click.option("--cdp", is_flag=True)
def music_extend(
    clip_id: str,
    seconds: float,
    from_sec: Optional[float],
    prompt: str,
    title: str,
    audio_format: str,
    output: str,
    cdp: bool,
):
    """Extend a song by N seconds."""
    async def _go():
        client = await _make_music_client(cdp=cdp)
        try:
            click.echo(f"⏩ Extending song {clip_id[:16]}... (+{seconds:.0f}s)")
            clip = await client.extend_song(
                clip_id,
                extend_s=seconds,
                extend_from_s=from_sec,
                instruction=prompt,
                title=title,
                on_progress=_progress_cb,
            )
            click.echo("✅ Extended song ready")
            _print_clip_summary(clip)
            if output:
                saved = await client.download_song(clip, output, audio_format=audio_format)
                click.echo(f"💾 Saved: {saved}")
        except (FlowError, GenerationError, GenerationTimeout) as e:
            click.echo(f"\n❌ {e}", err=True)
            sys.exit(1)
        finally:
            await client.close()

    _run(_go())


@music_cli.command("cover")
@click.argument("clip_id")
@click.option("--prompt", "-p", required=True, help="Target genre / style / instrumentation")
@click.option("--strength", type=float, default=0.5, show_default=True, help="Style transfer strength (0.01-1.0)")
@click.option("--title", "-t", default="", help="Output song title")
@click.option("--format", "-f", "audio_format", type=click.Choice(["mp3", "wav", "m4a"]), default="mp3", show_default=True)
@click.option("--output", "-o", default="./flow_music", show_default=True)
@click.option("--cdp", is_flag=True)
def music_cover(
    clip_id: str,
    prompt: str,
    strength: float,
    title: str,
    audio_format: str,
    output: str,
    cdp: bool,
):
    """Create a genre/style cover (remix) of an existing song."""
    async def _go():
        client = await _make_music_client(cdp=cdp)
        try:
            click.echo(f"🎛️  Creating cover of {clip_id[:16]}... ({prompt[:50]})")
            clip = await client.cover_song(
                clip_id,
                prompt,
                strength=strength,
                title=title,
                on_progress=_progress_cb,
            )
            click.echo("✅ Cover song ready")
            _print_clip_summary(clip)
            if output:
                saved = await client.download_song(clip, output, audio_format=audio_format)
                click.echo(f"💾 Saved: {saved}")
        except (FlowError, GenerationError, GenerationTimeout) as e:
            click.echo(f"\n❌ {e}", err=True)
            sys.exit(1)
        finally:
            await client.close()

    _run(_go())


@music_cli.command("replace")
@click.argument("clip_id")
@click.option("--start", "start_s", type=float, required=True, help="Section start time in seconds")
@click.option("--end", "end_s", type=float, required=True, help="Section end time in seconds")
@click.option("--prompt", "-p", default="", help="Replacement instruction")
@click.option("--title", "-t", default="", help="Output song title")
@click.option("--format", "-f", "audio_format", type=click.Choice(["mp3", "wav", "m4a"]), default="mp3", show_default=True)
@click.option("--output", "-o", default="./flow_music", show_default=True)
@click.option("--cdp", is_flag=True)
def music_replace(
    clip_id: str,
    start_s: float,
    end_s: float,
    prompt: str,
    title: str,
    audio_format: str,
    output: str,
    cdp: bool,
):
    """Replace / inpaint a time range [start, end] of an existing song."""
    async def _go():
        client = await _make_music_client(cdp=cdp)
        try:
            click.echo(f"🩹 Replacing [{start_s:.1f}s - {end_s:.1f}s] in {clip_id[:16]}...")
            clip = await client.replace_section(
                clip_id,
                start_s,
                end_s,
                prompt,
                title=title,
                on_progress=_progress_cb,
            )
            click.echo("✅ Replaced song ready")
            _print_clip_summary(clip)
            if output:
                saved = await client.download_song(clip, output, audio_format=audio_format)
                click.echo(f"💾 Saved: {saved}")
        except (FlowError, GenerationError, GenerationTimeout) as e:
            click.echo(f"\n❌ {e}", err=True)
            sys.exit(1)
        finally:
            await client.close()

    _run(_go())


@music_cli.command("trim")
@click.argument("clip_id")
@click.option("--start", "start_s", type=float, default=0.0, show_default=True, help="Start time in seconds")
@click.option("--end", "end_s", type=float, required=True, help="End time in seconds")
@click.option("--fade-in", type=float, default=0.0, show_default=True, help="Fade-in duration (seconds)")
@click.option("--fade-out", type=float, default=0.0, show_default=True, help="Fade-out duration (seconds)")
@click.option("--title", "-t", default="", help="Output song title")
@click.option("--format", "-f", "audio_format", type=click.Choice(["mp3", "wav", "m4a"]), default="mp3", show_default=True)
@click.option("--output", "-o", default="./flow_music", show_default=True)
@click.option("--cdp", is_flag=True)
def music_trim(
    clip_id: str,
    start_s: float,
    end_s: float,
    fade_in: float,
    fade_out: float,
    title: str,
    audio_format: str,
    output: str,
    cdp: bool,
):
    """Trim a song to [start, end] seconds with optional fade-in/fade-out."""
    async def _go():
        client = await _make_music_client(cdp=cdp)
        try:
            click.echo(f"✂️  Trimming {clip_id[:16]}... to [{start_s:.1f}s - {end_s:.1f}s]")
            clip = await client.trim_song(
                clip_id,
                start_s,
                end_s,
                fade_in_s=fade_in,
                fade_out_s=fade_out,
                title=title,
            )
            click.echo("✅ Trimmed song ready")
            _print_clip_summary(clip)
            if output:
                saved = await client.download_song(clip, output, audio_format=audio_format)
                click.echo(f"💾 Saved: {saved}")
        except (FlowError, GenerationError, GenerationTimeout) as e:
            click.echo(f"\n❌ {e}", err=True)
            sys.exit(1)
        finally:
            await client.close()

    _run(_go())


@music_cli.command("stems")
@click.argument("clip_id")
@click.option("--format", "-f", "audio_format", type=click.Choice(["wav", "mp3", "m4a"]), default="wav", show_default=True)
@click.option("--output", "-o", default="./flow_stems", show_default=True, help="Directory to save stem tracks")
@click.option("--cdp", is_flag=True)
def music_stems(clip_id: str, audio_format: str, output: str, cdp: bool):
    """Split a song into separated stems (vocals, drums, bass, other) and download."""
    async def _go():
        client = await _make_music_client(cdp=cdp)
        try:
            click.echo(f"🎚️  Splitting stems for {clip_id[:16]}...")
            stems = await client.split_stems(clip_id, on_progress=_progress_cb)
            out_dir = Path(output)
            out_dir.mkdir(parents=True, exist_ok=True)
            click.echo(f"✅ Extracted {len(stems)} stem(s):")
            for st in stems:
                dest = out_dir / f"{st.stem_type}_{st.clip.id[:8]}.{audio_format}"
                saved = await client.download_song(st.clip, dest, audio_format=audio_format)
                click.echo(f"   💾 [{st.stem_type:10}] {saved}")
        except (FlowError, GenerationError, GenerationTimeout) as e:
            click.echo(f"\n❌ {e}", err=True)
            sys.exit(1)
        finally:
            await client.close()

    _run(_go())


@music_cli.command("download")
@click.argument("clip_id")
@click.option("--format", "-f", "audio_format", type=click.Choice(["mp3", "wav", "m4a"]), default="mp3", show_default=True)
@click.option("--output", "-o", default="./flow_music", show_default=True)
@click.option("--cdp", is_flag=True)
def music_download(clip_id: str, audio_format: str, output: str, cdp: bool):
    """Download a song in m4a or lossless wav format."""
    async def _go():
        client = await _make_music_client(cdp=cdp)
        try:
            click.echo(f"⬇️  Downloading {clip_id[:16]} ({audio_format})...")
            saved = await client.download_song(clip_id, output, audio_format=audio_format)
            click.echo(f"✅ Saved: {saved}")
        except (FlowError, DownloadError) as e:
            click.echo(f"\n❌ {e}", err=True)
            sys.exit(1)
        finally:
            await client.close()

    _run(_go())
