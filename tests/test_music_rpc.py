"""Offline unit tests for flow._music_rpc (lyrics UUID, token cache, JSON & SSE parsing)."""
from __future__ import annotations

import json
import os
import stat
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import aiohttp
import pytest

from flow._exceptions import FlowError, GenerationError
from flow._music_rpc import (
    INSTRUMENTAL_MARKER,
    FlowMusicRPC,
    clear_cached_music_token,
    lyrics_id_for_text,
)


@pytest.fixture
def isolated_token_file(tmp_path: Path):
    storage_root = tmp_path / ".flow-py"
    token_file = storage_root / "music_token.json"

    def _ensure_dirs():
        storage_root.mkdir(parents=True, exist_ok=True)

    with patch("flow._music_rpc.MUSIC_TOKEN_FILE", token_file), patch(
        "flow._music_rpc.ensure_dirs", _ensure_dirs
    ):
        yield token_file


# ── lyrics_id_for_text ──────────────────────────────────────────────────────


def test_lyrics_id_for_text_edge_cases():
    assert lyrics_id_for_text("") == ""
    assert lyrics_id_for_text(" \n\t ") == ""
    assert lyrics_id_for_text(INSTRUMENTAL_MARKER) == ""

    id_a1 = lyrics_id_for_text("[Chorus]\nShine bright")
    id_a2 = lyrics_id_for_text("[Chorus]\nShine bright")
    id_b = lyrics_id_for_text("[Chorus]\nShine brighter")
    assert id_a1 == id_a2
    assert id_a1 != id_b
    assert len(id_a1) == 36


# ── Token cache & expiry ────────────────────────────────────────────────────


def test_token_cache_save_load_expiry_and_clear(isolated_token_file: Path):
    rpc = FlowMusicRPC()
    assert rpc._load_cached_token() is None

    future_exp = time.time() + 3600
    rpc._save_cached_token("jwt-fresh-1", future_exp)
    assert isolated_token_file.exists()
    mode = stat.S_IMODE(os.stat(isolated_token_file).st_mode)
    assert mode == 0o600
    assert rpc._load_cached_token() == "jwt-fresh-1"

    # Fresh instance loads from disk
    rpc2 = FlowMusicRPC()
    assert rpc2._load_cached_token() == "jwt-fresh-1"

    # Within 90s expiry buffer must be treated as expired
    isolated_token_file.write_text(
        json.dumps({"access_token": "jwt-soon-expiring", "expires_at": time.time() + 60})
    )
    rpc3 = FlowMusicRPC()
    assert rpc3._load_cached_token() is None

    # Corrupted JSON fails gracefully
    isolated_token_file.write_text("{corrupt")
    assert rpc3._load_cached_token() is None

    # Clear deletes the cached token file
    rpc._save_cached_token("jwt-to-clear", future_exp)
    assert isolated_token_file.exists()
    clear_cached_music_token()
    assert not isolated_token_file.exists()


# ── HTTP JSON wrapper ───────────────────────────────────────────────────────


class _FakeResponse:
    def __init__(self, status: int, body: str = "", lines: list[bytes] | None = None):
        self.status = status
        self._body = body
        self.content = _FakeStreamContent(lines or [])

    async def text(self) -> str:
        return self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False


class _FakeStreamContent:
    def __init__(self, lines: list[bytes]):
        self._lines = lines

    def __aiter__(self):
        return self._iter()

    async def _iter(self):
        for line in self._lines:
            yield line


class _FakeHTTP:
    def __init__(self, responses: list[_FakeResponse]):
        self._responses = list(responses)
        self.calls: list[dict] = []

    def request(self, method, url, params=None, json=None, headers=None):
        self.calls.append(
            {"method": method, "url": url, "params": params, "json": json, "headers": headers}
        )
        return self._responses.pop(0)

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append({"method": "GET", "url": url, "params": params, "headers": headers})
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.mark.asyncio
async def test_request_json_success_params_and_401_retry():
    rpc = FlowMusicRPC()
    rpc._bootstrap = AsyncMock(side_effect=["tok-old", "tok-new", "tok-new"])
    fake_http = _FakeHTTP(
        [
            _FakeResponse(401, "expired"),
            _FakeResponse(200, json.dumps({"ok": True, "count": 2})),
        ]
    )
    rpc._get_http = AsyncMock(return_value=fake_http)

    res = await rpc.request_json(
        "get",
        "/models",
        params={"active": True, "empty": None, "limit": 10},
    )
    assert res == {"ok": True, "count": 2}
    assert len(fake_http.calls) == 2
    assert fake_http.calls[0]["headers"]["Authorization"] == "Bearer tok-old"
    assert fake_http.calls[1]["headers"]["Authorization"] == "Bearer tok-new"
    assert fake_http.calls[0]["params"] == {"active": "true", "limit": 10}
    rpc._bootstrap.assert_any_await(force_refresh=True)


@pytest.mark.asyncio
async def test_request_json_empty_and_http_error():
    rpc = FlowMusicRPC()
    rpc._bootstrap = AsyncMock(return_value="tok-1")
    fake_http = _FakeHTTP(
        [
            _FakeResponse(204, ""),
            _FakeResponse(400, json.dumps({"detail": "bad prompt"})),
        ]
    )
    rpc._get_http = AsyncMock(return_value=fake_http)

    assert await rpc.request_json("POST", "/noop") is None
    with pytest.raises(FlowError, match="bad prompt"):
        await rpc.request_json("POST", "/bad")


# ── SSE streaming & reconnect ───────────────────────────────────────────────


def _sse_block(event: str, payload: dict) -> list[bytes]:
    return [
        f"event: {event}\n".encode(),
        f"data: {json.dumps(payload)}\n".encode(),
        b"\n",
    ]


@pytest.mark.asyncio
async def test_stream_job_once_chat_part_events():
    lines: list[bytes] = [b": heartbeat\n", b"\n"]
    lines += _sse_block("conversation_id", {"id": "conv-99"})
    lines += _sse_block("generated-title", {"title": "Morning Dew"})
    lines += _sse_block("tool_progress", {"message": "Composing melody..."})
    lines += _sse_block("part", {"index": 0, "status": "start", "part": {"part_kind": "text", "content": "Hello"}})
    lines += _sse_block("part", {"index": 0, "status": "delta", "delta": " world!"})
    lines += _sse_block(
        "part",
        {
            "index": 1,
            "status": "final",
            "part": {
                "part_kind": "tool-return",
                "tool_call_id": "tc-1",
                "tool_name": "audio__create_song",
                "content": json.dumps({"clip_id": "clip-abc"}),
            },
        },
    )
    lines += _sse_block(
        "part",
        {
            "index": 2,
            "status": "final",
            "part": {
                "part_kind": "tool-call",
                "tool_name": "synthetic__suggest_actions",
                "args": json.dumps({"a": "Make it faster", "b": "Add strings"}),
            },
        },
    )
    lines += _sse_block("complete", {})

    progress_msgs: list[str] = []
    rpc = FlowMusicRPC()
    rpc._bootstrap = AsyncMock(return_value="tok-1")
    rpc._get_http = AsyncMock(return_value=_FakeHTTP([_FakeResponse(200, lines=lines)]))

    res = await rpc._stream_job_once("job-1", tool_progress=True, on_progress=progress_msgs.append)
    assert res["conversation_id"] == "conv-99"
    assert res["title"] == "Morning Dew"
    assert res["text"] == "Hello world!"
    assert progress_msgs == ["Composing melody..."]
    assert res["tool_returns"][0]["content"] == {"clip_id": "clip-abc"}
    assert res["suggestions"] == ["Make it faster", "Add strings"]


@pytest.mark.asyncio
async def test_stream_job_once_tool_message_and_error():
    ok_lines = _sse_block(
        "message",
        {
            "parts": [
                {"part_kind": "text", "content": "Done."},
                {
                    "part_kind": "tool-return",
                    "tool_call_id": "tc-2",
                    "tool_name": "lyrics__create",
                    "content": {"title": "Dawn", "lyrics": "[Verse]\nLight"},
                },
            ]
        },
    ) + _sse_block("final", {})

    rpc = FlowMusicRPC()
    rpc._bootstrap = AsyncMock(return_value="tok-1")
    rpc._get_http = AsyncMock(return_value=_FakeHTTP([_FakeResponse(200, lines=ok_lines)]))
    res = await rpc._stream_job_once("job-2")
    assert res["text"] == "Done."
    assert res["tool_returns"][0]["content"]["title"] == "Dawn"

    err_lines = _sse_block("error", {"message": "Quota exceeded"})
    rpc._get_http = AsyncMock(return_value=_FakeHTTP([_FakeResponse(200, lines=err_lines)]))
    with pytest.raises(GenerationError, match="Quota exceeded"):
        await rpc._stream_job_once("job-3")


@pytest.mark.asyncio
async def test_stream_job_reconnects_and_fails_after_three_drops():
    rpc = FlowMusicRPC()
    rpc._stream_job_once = AsyncMock(
        side_effect=[
            aiohttp.ServerDisconnectedError("drop 1"),
            {"conversation_id": "c1", "text": "ok", "tool_calls": [], "tool_returns": [], "suggestions": [], "title": None},
        ]
    )
    with patch("flow._music_rpc.asyncio.sleep", AsyncMock()):
        out = await rpc.stream_job("job-ok")
    assert out["text"] == "ok"
    assert rpc._stream_job_once.await_count == 2

    rpc._stream_job_once = AsyncMock(
        side_effect=aiohttp.ClientPayloadError("truncated")
    )
    with patch("flow._music_rpc.asyncio.sleep", AsyncMock()):
        with pytest.raises(GenerationError, match="kept dropping"):
            await rpc.stream_job("job-drop")
    assert rpc._stream_job_once.await_count == 3
