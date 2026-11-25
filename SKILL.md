---
name: flow
description: Google Flow AI (flow.google.com) & Flow Music (flowmusic.app / Lyria 3.5) CLI and Python SDK for generating and editing videos, images, and music. Covers flow video, image, frames, extend, extend-loop, camera, camera-pos, insert, remove, upscale, poll, download, batch-images, batch-videos, and the full flow music suite (generate, score, chat, lyrics, extend, cover, replace, trim, stems, download, status, credits, models, songs, sessions).
---

# Flow AI & Flow Music Skill

Automate Google Flow AI (`flow.google.com`) for video/image creation & editing, and Google Flow Music (`flowmusic.app` / Lyria 3.5 & Producer) for music composition, scoring, editing, and stem splitting.

## Installation

Requirements: Python 3.10+ (and `ffmpeg`/`ffprobe` if using `flow music score`).

```bash
git clone https://github.com/zz8011/flow-py.git
cd flow-py
pip install -e ".[dev]"
playwright install chromium
```

Or use the repository's portable installer (creates an isolated venv at `~/.flow-py/venv` and a `~/.local/bin/flow` wrapper when `--venv` is passed):

```bash
bash install.sh --venv
```

## Quick Start

```bash
# Authenticate once (shared Google session for flow.google.com and flowmusic.app)
flow login
flow projects
flow use <project_id>
flow status

# Video & Image (flow.google.com)
flow credits                                      # Check video/image balance
flow video "golden sunset over temple"            # Text to Video
flow video "lotus blooms" --start ./frame.jpg     # Image to Video (I2V)
flow image "serene lotus pond" -n 4               # Text to Image (x4)
flow upscale <media_id> -r 1080p -o out.mp4       # Free 1080p upscale

# Music (flowmusic.app / Lyria 3.5)
flow music status                                 # Check music auth & credits
flow music generate "warm folk guitar" -i -f wav  # Generate instrumental WAV
flow music score ./video.mp4 -p "piano" --mux     # Score a video & mux audio
```

## All Commands

### Auth, Status & Projects

```bash
flow login                      # Open browser for Google auth (syncs Flow & Flow Music)
flow logout                     # Clear saved browser session & music JWT cache
flow status [--json]            # Show auth, active project, credits & recent workflows
flow config                     # Show current configuration
flow projects                   # List projects (live from flow.google.com)
flow use <project_id>           # Set active project
flow workflows [-n 20]          # List workflows in active project
flow credits                    # Show video/image credits remaining
flow models [--json]            # List video models and official credit costs
```

### Video & Image Generation (`flow.google.com`)

```bash
# Text to Video / Image-to-Video / Multi-Reference Video
flow video "prompt" [options]
  -p, --project <id>            # Override active project
  -m, --model "Veo 3.1 - Fast"  # Veo 3.1 - Lite/Fast/Quality, Omni 1.2/1.1 Flash
  -a, --aspect landscape|portrait
  -n, --count 1-4
  --start <path_or_media_id>    # Image-to-Video mode
  -r, --reference <path_or_id>  # Reference image(s) (repeatable)
  --wait / --no-wait
  -o, --output <dir>
  --headless / --headed
  --cdp                         # Connect to existing Chrome CDP (port 9222)

# Text to Image / Reference Image
flow image "prompt" [options]
  -m, --model <name>            # Optional image model display name
  -a, --aspect landscape|portrait|square
  -n, --count 1-4
  -r, --reference <path_or_id>  # Reference image(s) (repeatable)
  -o, --output <dir>

# Image to Video (Frames mode)
flow frames <image_path> [options]
  -p, --prompt "motion description"
  -a, --aspect landscape|portrait
  -o, --output <dir>
```

### Video Editing & Upscaling

All `media_id` arguments accept an unambiguous prefix (e.g., first 8-16 characters).

```bash
# Extend video (single or loop)
flow extend <media_id> [-w <workflow_id>] [-p "what happens next"] [-o out.mp4]
flow extend-loop <media_id> [-w <wid>] -n 5 [-p "steady push forward"] [-o ./out]

# Camera motion & position
flow camera <media_id> --motion <type>
  # dolly_in, dolly_out, orbit_left, orbit_right,
  # orbit_up, orbit_low, dolly_zoom_in, dolly_zoom_out
flow camera-pos <media_id> --position <pos>
  # center, left, right, high, low, closer, further

# Object insert / remove (via Omni 1.2 Flash editing)
flow insert <media_id> -t "golden lotus flower"
flow remove <media_id> [-t "object description"] [--x 0.5 --y 0.5 --brush 40]

# Upscale (1080p is 0 credits FREE; 4k verifies official price)
flow upscale <media_id> [-w <wid>] [-r 1080p|4k] [-o out.mp4]
```

### Status, Download & Batch

```bash
flow poll <media_id> [--wait] [--timeout 300]
flow download <media_id> -o ./flow_output
flow download-all [-w <wid>] -o ./flow_downloads
flow batch-images prompts.txt -n 2 -a landscape -o ./batch_images
flow batch-videos prompts.txt -m "Veo 3.1 - Fast" -c 1 -o ./batch_videos
```

### Music Generation & Editing (`flow music` / `flowmusic.app`)

All `clip_id` arguments accept an unambiguous UUID prefix.

```bash
# Status, library & models
flow music status [--json]            # Auth, subscription tier, credits, recent songs
flow music credits [--json]           # Remaining music credits & tokens
flow music models [--json]            # Available models (Lyria 3.5, etc.)
flow music songs [-n 20] [--json]     # List songs in Flow Music library
flow music sessions [-n 20] [--json]  # List Producer chat sessions

# Generate, lyrics, Producer chat & video scoring
flow music generate "style prompt" [-l "lyrics"|@lyrics.txt] [-i] [-t "Title"] \
  [--bpm 120] [-d 60] [--seed 42] [-m "Lyria 3.5"] [-f mp3|wav|m4a] [-o ./flow_music]
flow music lyrics "theme or style" [--json]
flow music chat "instruction" [-s <session_id>] [--audio ref.mp3] [-f mp3|wav|m4a] [-o ./out]
flow music score <video.mp4> [-p "style hint"] [-f mp3|wav|m4a] [-o .] [--mux]

# Edit, stem split & download
flow music extend <clip_id> [-s 30.0] [--from-sec 20.0] [-p "outro"] [-f mp3|wav|m4a] [-o ./out]
flow music cover <clip_id> -p "bossa nova jazz" [--strength 0.5] [-f mp3|wav|m4a] [-o ./out]
flow music replace <clip_id> --start 30 --end 60 [-p "guitar solo"] [-f mp3|wav|m4a] [-o ./out]
flow music trim <clip_id> [--start 0] --end 30 [--fade-in 0] [--fade-out 1.5] [-f wav] [-o ./out]
flow music stems <clip_id> [-f wav|mp3|m4a] [-o ./flow_stems]
flow music download <clip_id> [-f mp3|wav|m4a] [-o ./flow_music]
```

## Architecture

- **Flow (`flow.google.com`)**: Uses `WIZ_global_data`-bootstrapped `batchexecute` RPC (`_rpc.py`) for read-only queries and fresh signed media URLs (`as29s`), paired with Playwright `AgentUI` (`_flow_ui.py`) for creation/editing and strict confirmation-card price verification against `HTrJv` before clicking approve.
- **Flow Music (`flowmusic.app`)**: Uses Google SSO once to cache a short-lived Supabase JWT in `~/.flow-py/music_token.json` (`0600`), then executes `/__api/*` REST and SSE streams directly via `aiohttp` (`_music_rpc.py` + `_music.py`).

| File | Purpose |
|---|---|
| `flow/_rpc.py` | `flow.google.com` `batchexecute` RPC client (credits, projects, `HTrJv` models, `Zzl0ze` media, `as29s` URLs) |
| `flow/_flow_ui.py` | `AgentUI` Playwright automation + bilingual (ZH/EN) selectors & confirmation card parser |
| `flow/_client.py` | High-level `FlowClient` SDK (video/image generation, edits, upscale, downloads, `.music` property) |
| `flow/_music_rpc.py` | `flowmusic.app` REST + SSE transport, Google SSO bootstrap, JWT token cache |
| `flow/_music.py` | High-level `FlowMusicClient` SDK and `SongClip` / `StemClip` / `ProducerTurn` / `MusicCredits` models |
| `flow/_browser.py` | Playwright persistent profile & CDP browser lifecycle (`BrowserManager`) |
| `flow/_api.py` | Model/camera/mask constants, `MODEL_REGISTRY`, response models, and `FlowAPI` read/poll wrapper |
| `flow/_models.py` | High-level enums, dataclasses, and `parse_prompt_file` |
| `flow/_exceptions.py` | Exception hierarchy |
| `flow/_storage.py` | Config and project persistence (`~/.flow-py/`) |
| `flow/cli/main.py` | Click CLI root and Flow video/image commands |
| `flow/cli/_music.py` | Click `flow music` subcommand group |

## Python SDK

```python
import asyncio
from flow import FlowClient, FlowMusicClient

async def main():
    # 1. Flow Video & Image (flow.google.com)
    async with await FlowClient.create(project_id="4f3c93f5-...") as client:
        credits = await client.get_credits()
        print(f"Credits: {credits.credits}")

        jobs = await client.generate_video(
            "golden lotus at dawn",
            model="Veo 3.1 - Lite",
            aspect="landscape",
        )
        status = await client.wait_for_video(jobs[0])
        await client.download(status.fife_url, "output.mp4")

        # Also access music via the shared browser profile:
        music_credits = await client.music.get_credits()
        print(f"Music credits: {music_credits.credits_remaining}")

    # 2. Standalone Flow Music (flowmusic.app / Lyria 3.5)
    async with await FlowMusicClient.create() as music:
        song = await music.generate_song(
            "uplifting indie synth-pop, shimmering arpeggios",
            instrumental=True,
            bpm=120,
            title="Dawn Horizon",
        )
        trimmed = await music.trim_song(song.id, start_s=0.0, end_s=30.0, fade_out_s=1.5)
        await music.download_song(trimmed, "./dawn_30s.wav", audio_format="wav")

asyncio.run(main())
```
