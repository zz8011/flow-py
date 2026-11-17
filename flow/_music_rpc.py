"""REST + SSE transport and Google SSO bootstrap for Google Flow Music (flowmusic.app).

Architecture:
* ``flowmusic.app`` is a Next.js app backed by ``/__api/*`` REST + SSE endpoints,
  authenticated via a Supabase OAuth JWT (``Authorization: Bearer <access_token>``).
* When the user has authenticated once via ``flow login`` (Google session stored in
  ``~/.flow-py/browser-profile``), ``FlowMusicRPC`` automatically completes the
  one-click Google OAuth SSO on ``flowmusic.app`` when needed and caches the
  short-lived JWT in ``~/.flow-py/music_token.json`` (mode 0600).
* While the cached JWT is fresh, all API calls and SSE streams run directly over
  ``aiohttp`` without launching Chromium; on expiry or HTTP 401, ``BrowserManager``
  transparently refreshes the session.
"""
from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
import os
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Optional

import aiohttp

from ._browser import BrowserManager, _USER_AGENT
from ._exceptions import AuthError, FlowError, GenerationError, GenerationTimeout
from ._storage import STORAGE_ROOT, ensure_dirs

log = logging.getLogger(__name__)

MUSIC_ORIGIN = "https://www.flowmusic.app"
MUSIC_API_BASE = f"{MUSIC_ORIGIN}/__api"
MUSIC_TOKEN_FILE = STORAGE_ROOT / "music_token.json"

# Deterministic UUIDv5 namespace used by flowmusic.app for lyrics_id_map
LYRICS_UUID_NS = uuid.UUID("b8f9e3a1-7c2d-4f5e-9a8b-1c3d5e7f9a2b")
INSTRUMENTAL_MARKER = "[Instrumental]"


def lyrics_id_for_text(lyrics: str) -> str:
    """Compute the deterministic UUIDv5 lyrics_id used by flowmusic.app."""
    if not lyrics or not lyrics.strip() or lyrics == INSTRUMENTAL_MARKER:
        return ""
    return str(uuid.uuid5(LYRICS_UUID_NS, lyrics))


def clear_cached_music_token() -> None:
    if MUSIC_TOKEN_FILE.exists():
        MUSIC_TOKEN_FILE.unlink()


class FlowMusicRPC:
    """Authenticated REST + SSE client for Google Flow Music (flowmusic.app)."""

    def __init__(
        self,
        browser_manager: Optional[BrowserManager] = None,
        *,
        headless: bool = True,
        cdp_url: Optional[str] = None,
    ):
        self._external_bm = browser_manager
        self._owned_bm: Optional[BrowserManager] = None
        self._headless = headless
        self._cdp_url = cdp_url
        self._http: Optional[aiohttp.ClientSession] = None
        self._token: Optional[str] = None
        self._expires_at: float = 0.0
        self._bootstrap_lock = asyncio.Lock()

    # ── lifecycle ──────────────────────────────────────────────────────

    async def _get_http(self) -> aiohttp.ClientSession:
        if self._http is None or self._http.closed:
            timeout = aiohttp.ClientTimeout(total=600, sock_read=300)
            self._http = aiohttp.ClientSession(
                headers={"User-Agent": _USER_AGENT},
                timeout=timeout,
            )
        return self._http

    async def close(self) -> None:
        if self._http and not self._http.closed:
            await self._http.close()
        self._http = None
        if self._owned_bm is not None:
            await self._owned_bm.stop()
            self._owned_bm = None

    # ── token cache & browser SSO bootstrap ────────────────────────────

    def _load_cached_token(self) -> Optional[str]:
        if self._token and time.time() < self._expires_at - 90:
            return self._token
        if not MUSIC_TOKEN_FILE.exists():
            return None
        try:
            data = json.loads(MUSIC_TOKEN_FILE.read_text())
            tok = data.get("access_token")
            exp = float(data.get("expires_at") or 0)
            if tok and time.time() < exp - 90:
                self._token = tok
                self._expires_at = exp
                return tok
        except Exception:
            pass
        return None

    def _save_cached_token(self, token: str, expires_at: float) -> None:
        ensure_dirs()
        payload = {
            "access_token": token,
            "expires_at": expires_at,
            "updated_at": int(time.time()),
        }
        MUSIC_TOKEN_FILE.write_text(json.dumps(payload, indent=2))
        try:
            os.chmod(MUSIC_TOKEN_FILE, 0o600)
        except OSError:
            pass
        self._token = token
        self._expires_at = expires_at

    async def _get_bm(self) -> BrowserManager:
        if self._external_bm is not None:
            return self._external_bm
        if self._owned_bm is None:
            self._owned_bm = BrowserManager(headless=self._headless, cdp_url=self._cdp_url)
            await self._owned_bm.start()
        return self._owned_bm

    async def _read_page_session(self, page) -> tuple[Optional[str], float]:
        try:
            info = await page.evaluate(
                """async () => {
                    if (!window.bop || !window.bop.supabase) return null;
                    const { data } = await window.bop.supabase.auth.getSession();
                    const s = data && data.session;
                    if (!s || !s.access_token) return null;
                    return { token: s.access_token, expires_at: s.expires_at || 0 };
                }"""
            )
            if info and info.get("token"):
                exp = float(info.get("expires_at") or (time.time() + 3300))
                return info["token"], exp
        except Exception:
            pass
        return None, 0.0

    async def _bootstrap(self, *, force_refresh: bool = False) -> str:
        if not force_refresh:
            cached = self._load_cached_token()
            if cached:
                return cached
        async with self._bootstrap_lock:
            if not force_refresh:
                cached = self._load_cached_token()
                if cached:
                    return cached
            return await self._bootstrap_locked(force_refresh=force_refresh)

    async def _bootstrap_locked(self, *, force_refresh: bool = False) -> str:
        bm = await self._get_bm()
        page = await bm.page()
        try:
            if "flowmusic.app" not in page.url:
                await page.goto(
                    f"{MUSIC_ORIGIN}/?utm_source=flow",
                    wait_until="domcontentloaded",
                    timeout=45_000,
                )
                await asyncio.sleep(3)

            # Wait up to 6s for window.bop to initialize
            for _ in range(6):
                tok, exp = await self._read_page_session(page)
                if tok:
                    self._save_cached_token(tok, exp)
                    return tok
                has_bop = await page.evaluate("() => !!window.bop")
                if has_bop:
                    break
                await asyncio.sleep(1)

            # Attempt automatic Google SSO using the existing Google profile cookies
            sign_in_btn = page.locator(
                "button:has-text('登录'), button:has-text('Sign in'), button:has-text('Log in')"
            )
            if await sign_in_btn.count() > 0:
                await sign_in_btn.first.click(timeout=5000)
                await asyncio.sleep(1.5)
                google_btn = page.locator(
                    "button:has-text('Google'), [role='button']:has-text('Google')"
                )
                if await google_btn.count() > 0:
                    await google_btn.last.click(timeout=5000)
                    # Wait for OAuth redirect back to flowmusic.app
                    deadline = time.monotonic() + 20.0
                    while time.monotonic() < deadline:
                        await asyncio.sleep(1.5)
                        if "accounts.google.com" in page.url:
                            # Check if Google is asking for interactive login
                            needs_creds = await page.locator("input[type='email'], input[type='password']").count()
                            if needs_creds > 0:
                                raise AuthError(
                                    "Google session not signed in. Run `flow login` first."
                                )
                        if "flowmusic.app" in page.url and "/auth" not in page.url:
                            tok, exp = await self._read_page_session(page)
                            if tok:
                                self._save_cached_token(tok, exp)
                                return tok

            tok, exp = await self._read_page_session(page)
            if tok:
                self._save_cached_token(tok, exp)
                return tok

            raise AuthError(
                "Not authenticated on flowmusic.app. Run `flow login` to sign in with Google."
            )
        finally:
            # Close temporary browser if we spawned one solely for token refresh
            if self._owned_bm is not None and self._external_bm is None:
                await self._owned_bm.stop()
                self._owned_bm = None

    # ── core HTTP & multipart calls ────────────────────────────────────

    async def request_json(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict[str, Any]] = None,
        json_body: Any = None,
        retry_auth: bool = True,
    ) -> Any:
        token = await self._bootstrap()
        http = await self._get_http()
        url = f"{MUSIC_API_BASE}{path}"
        clean_params = (
            {k: str(v).lower() if isinstance(v, bool) else v for k, v in params.items() if v is not None}
            if params
            else None
        )
        headers = {"Authorization": f"Bearer {token}"}
        async with http.request(
            method.upper(), url, params=clean_params, json=json_body, headers=headers
        ) as resp:
            if resp.status == 401 and retry_auth:
                await self._bootstrap(force_refresh=True)
                return await self.request_json(
                    method, path, params=params, json_body=json_body, retry_auth=False
                )
            text = await resp.text()
            if resp.status >= 400:
                detail = text[:300]
                try:
                    detail = json.loads(text).get("detail", detail)
                except Exception:
                    pass
                raise FlowError(f"FlowMusic API {method.upper()} {path} failed (HTTP {resp.status}): {detail}")
            if not text:
                return None
            try:
                return json.loads(text)
            except Exception:
                return text

    async def upload_multipart(
        self,
        path: str,
        fields: dict[str, Any],
        file_field: str,
        file_path: str | Path,
    ) -> Any:
        p = Path(file_path)
        if not p.is_file():
            raise FlowError(f"Upload file not found: {p}")
        token = await self._bootstrap()
        http = await self._get_http()
        mime, _ = mimetypes.guess_type(p.name)
        mime = mime or "application/octet-stream"

        form = aiohttp.FormData()
        for k, v in fields.items():
            if v is not None:
                form.add_field(k, str(v))
        form.add_field(
            file_field,
            p.read_bytes(),
            filename=p.name,
            content_type=mime,
        )
        headers = {"Authorization": f"Bearer {token}"}
        async with http.post(f"{MUSIC_API_BASE}{path}", data=form, headers=headers) as resp:
            text = await resp.text()
            if resp.status >= 400:
                raise FlowError(f"FlowMusic upload {path} failed (HTTP {resp.status}): {text[:300]}")
            return json.loads(text)

    # ── SSE job streaming ──────────────────────────────────────────────

    async def stream_job(
        self,
        job_id: str,
        *,
        tool_progress: bool = False,
        on_progress: Optional[Callable[[str], None]] = None,
        timeout_s: int = 360,
    ) -> dict[str, Any]:
        """Consume ``GET /__api/messages/{job_id}/stream`` until completion."""
        token = await self._bootstrap()
        http = await self._get_http()
        params: dict[str, str] = {"last_id": "0"}
        if tool_progress:
            params["tool_progress"] = "true"

        conversation_id: Optional[str] = None
        title: Optional[str] = None
        text_parts: dict[int, str] = {}
        tool_calls: list[dict[str, Any]] = []
        tool_returns: list[dict[str, Any]] = []
        suggestions: list[str] = []

        url = f"{MUSIC_API_BASE}/messages/{job_id}/stream"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "text/event-stream",
        }
        req_timeout = aiohttp.ClientTimeout(total=timeout_s, sock_read=timeout_s)
        async with http.get(url, params=params, headers=headers, timeout=req_timeout) as resp:
            if resp.status >= 400:
                body = await resp.text()
                raise GenerationError(f"FlowMusic stream {job_id} failed (HTTP {resp.status}): {body[:300]}")

            event_type = "message"
            data_lines: list[str] = []

            def _handle_event(ev: str, raw_data: str) -> bool:
                nonlocal conversation_id, title
                if not raw_data:
                    return False
                try:
                    payload = json.loads(raw_data)
                except Exception:
                    return False

                if ev == "conversation_id":
                    conversation_id = payload.get("id") or conversation_id
                elif ev == "generated-title":
                    title = payload.get("title") or title
                elif ev == "tool_progress":
                    msg = payload.get("message") or ""
                    if msg and on_progress:
                        on_progress(msg)
                elif ev == "error":
                    err_msg = payload.get("message") or payload.get("raw_error") or str(payload)
                    raise GenerationError(f"FlowMusic Producer error: {err_msg}")
                elif ev == "message":
                    # Used by /producer/tool-call streams
                    for part in payload.get("parts", []):
                        pk = part.get("part_kind")
                        if pk == "tool-call":
                            tool_calls.append(part)
                        elif pk == "tool-return":
                            content = part.get("content")
                            if isinstance(content, str):
                                try:
                                    content = json.loads(content)
                                except Exception:
                                    pass
                            tool_returns.append({**part, "content": content})
                        elif pk == "text" and part.get("content"):
                            text_parts[len(text_parts)] = part["content"]
                elif ev == "part":
                    # Used by /conversation chat streams
                    idx = payload.get("index", 0)
                    status = payload.get("status")
                    part = payload.get("part") or {}
                    pk = part.get("part_kind")
                    if status == "start" and pk == "text":
                        text_parts[idx] = part.get("content") or ""
                    elif status == "delta" and "delta" in payload:
                        if idx in text_parts:
                            text_parts[idx] += payload.get("delta") or ""
                    elif status == "final":
                        if pk == "text" and part.get("content"):
                            text_parts[idx] = part["content"]
                        elif pk == "tool-call":
                            tool_calls.append(part)
                            if part.get("tool_name") == "synthetic__suggest_actions":
                                args = part.get("args") or {}
                                if isinstance(args, str):
                                    try:
                                        args = json.loads(args)
                                    except Exception:
                                        args = {}
                                if isinstance(args, dict):
                                    suggestions.extend(
                                        v.strip() for v in args.values()
                                        if isinstance(v, str) and v.strip()
                                    )
                        elif pk == "tool-return":
                            content = part.get("content")
                            if isinstance(content, str):
                                try:
                                    content = json.loads(content)
                                except Exception:
                                    pass
                            tool_returns.append({**part, "content": content})
                elif ev in ("complete", "final"):
                    return True
                return False

            async for raw_line in resp.content:
                line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
                if not line:
                    if data_lines:
                        done = _handle_event(event_type, "\n".join(data_lines))
                        data_lines.clear()
                        event_type = "message"
                        if done:
                            break
                    continue
                if line.startswith(":"):
                    continue
                if line.startswith("event:"):
                    event_type = line[6:].strip()
                elif line.startswith("data:"):
                    data_lines.append(line[5:].lstrip())

            if data_lines:
                _handle_event(event_type, "\n".join(data_lines))

        full_text = "\n\n".join(t.strip() for _, t in sorted(text_parts.items()) if t.strip())
        return {
            "conversation_id": conversation_id,
            "title": title,
            "text": full_text,
            "tool_calls": tool_calls,
            "tool_returns": tool_returns,
            "suggestions": suggestions,
        }

    # ── Producer tool-call & chat helpers ──────────────────────────────

    def _build_client_context(
        self,
        *,
        selected_model: str = "Lyria 3.5",
        lyrics_map: Optional[dict[str, str]] = None,
        project_id: Optional[str] = None,
    ) -> dict[str, Any]:
        return {
            "current_song_id": None,
            "song_queue": [],
            "project_id": project_id,
            "selected_model": selected_model,
            "lyrics_id_map": lyrics_map or {},
            "ghostwriter_version": "standard",
            "onboarding_variant": None,
            "client_platform": "web",
            "clarifying_questions": {
                "supports_question_options": True,
                "supports_multi_question_options": True,
            },
        }

    async def execute_tool_call(
        self,
        tool_name: str,
        args: dict[str, Any],
        *,
        conversation_id: Optional[str] = None,
        selected_model: str = "Lyria 3.5",
        lyrics_map: Optional[dict[str, str]] = None,
        on_progress: Optional[Callable[[str], None]] = None,
        timeout_s: int = 360,
    ) -> tuple[str, Any]:
        """Invoke a structured Producer tool and return ``(conversation_id, result_content)``."""
        if not conversation_id:
            created = await self.request_json(
                "POST", "/conversation/create", json_body={"is_headless_space": True}
            )
            conversation_id = created["conversation_id"]

        call_id = str(uuid.uuid4())
        body = {
            "conversation_id": conversation_id,
            "part": {
                "tool_name": tool_name,
                "args": args,
                "part_kind": "tool-call",
                "tool_call_id": call_id,
            },
            "client_context": self._build_client_context(
                selected_model=selected_model,
                lyrics_map=lyrics_map,
            ),
        }
        resp = await self.request_json("POST", "/producer/tool-call", json_body=body)
        job_id = resp.get("job_id")
        if not job_id:
            raise GenerationError(f"Tool call {tool_name} returned no job_id: {resp}")

        stream_res = await self.stream_job(
            job_id, on_progress=on_progress, timeout_s=timeout_s
        )
        cid = stream_res.get("conversation_id") or conversation_id
        for tr in stream_res["tool_returns"]:
            if tr.get("tool_call_id") == call_id or tr.get("tool_name") == tool_name:
                return cid, tr.get("content")
        if stream_res["tool_returns"]:
            return cid, stream_res["tool_returns"][-1].get("content")
        raise GenerationError(f"Tool call {tool_name} finished without a tool-return result")

    async def send_chat(
        self,
        prompt: str,
        *,
        conversation_id: Optional[str] = None,
        selected_model: str = "Lyria 3.5",
        agent: str = "producer:standard",
        mode: str = "standard",
        upload_parts: Optional[list[dict[str, Any]]] = None,
        on_progress: Optional[Callable[[str], None]] = None,
        timeout_s: int = 360,
    ) -> dict[str, Any]:
        """Send a natural-language message to Producer and stream the response."""
        content: Any = [prompt, *upload_parts] if upload_parts else prompt
        body = {
            "conversation_id": conversation_id,
            "parts": [{"content": content, "part_kind": "user-prompt"}],
            "client_context": self._build_client_context(selected_model=selected_model),
            "model_name": agent,
            "mode": mode,
        }
        resp = await self.request_json("POST", "/conversation", json_body=body)
        job_id = resp.get("job_id")
        if not job_id:
            raise GenerationError(f"Producer chat returned no job_id: {resp}")
        res = await self.stream_job(
            job_id, tool_progress=True, on_progress=on_progress, timeout_s=timeout_s
        )
        if not res.get("conversation_id"):
            res["conversation_id"] = conversation_id
        return res

    # ── typed endpoint wrappers ────────────────────────────────────────

    async def get_me(self) -> dict[str, Any]:
        res = await self.request_json("GET", "/users/me")
        if not res:
            raise AuthError("Not logged in on flowmusic.app.")
        return res

    async def get_credits(self) -> dict[str, Any]:
        credits_resp, sub_resp = await asyncio.gather(
            self.request_json("GET", "/billing/credits"),
            self.request_json("GET", "/billing/subscription"),
        )
        c_data = (credits_resp or {}).get("data") or {}
        s_data = (sub_resp or {}).get("data") or {}
        return {
            "credits_remaining": float(c_data.get("credits_remaining") or 0.0),
            "tokens_remaining": float(c_data.get("tokens_remaining") or 0.0),
            "subscription_tier": s_data.get("subscription_tier") or "free",
            "subscription_plan": s_data.get("subscription_plan") or "",
            "provider": s_data.get("provider") or "",
            "transactions": (credits_resp or {}).get("add_token_transactions") or [],
        }

    async def get_models(self) -> list[dict[str, Any]]:
        resp = await self.request_json("GET", "/models")
        return (resp or {}).get("models") or []

    async def list_auth_clips(self, limit: int = 50) -> list[dict[str, Any]]:
        resp = await self.request_json("GET", "/clips/auth-user")
        clips = (resp or {}).get("clips") or []
        return clips[:limit]

    async def get_clips(self, clip_ids: list[str]) -> list[dict[str, Any]]:
        if not clip_ids:
            return []
        resp = await self.request_json("POST", "/clips", json_body={"clip_ids": clip_ids})
        if isinstance(resp, dict):
            inner = resp.get("clips") or resp.get("data")
            if isinstance(inner, list):
                return inner
            if isinstance(inner, dict):
                return [v for v in inner.values() if isinstance(v, dict)]
            # Or resp itself might be {clip_id: clip_dict}
            vals = [v for v in resp.values() if isinstance(v, dict) and "id" in v]
            if vals:
                return vals
        if isinstance(resp, list):
            return resp
        return []

    async def resolve_clip(self, clip_id_or_prefix: str) -> dict[str, Any]:
        """Resolve a full UUID or short prefix to a Clip record."""
        q = clip_id_or_prefix.strip()
        # Try full UUID lookup directly first
        if len(q) == 36 and q.count("-") == 4:
            clips = await self.get_clips([q])
            if clips:
                return clips[0]
        # Fallback to scanning user's library for prefix match
        user_clips = await self.list_auth_clips(limit=200)
        for c in user_clips:
            cid = c.get("id") or ""
            if cid == q or cid.startswith(q):
                return c
        raise FlowError(f"Song clip '{clip_id_or_prefix}' not found in your Flow Music library")

    async def create_recipe(self, recipe: dict[str, Any]) -> str:
        resp = await self.request_json("POST", "/recipes/create", json_body={"recipe": recipe})
        rid = (resp or {}).get("recipe_id")
        if not rid:
            raise GenerationError(f"Failed to create edit recipe: {resp}")
        return rid

    async def get_clip_stems(self, clip_id: str) -> list[dict[str, Any]]:
        """Check if stem clips already exist in the user's library for ``clip_id``."""
        try:
            clips = await self.list_auth_clips(limit=100)
            for c in clips:
                op = c.get("operation") or {}
                if op.get("op_type") == "audio__split_stems" and op.get("source_clip_id") == clip_id:
                    stems = op.get("stems")
                    if isinstance(stems, list) and stems:
                        return stems
        except FlowError:
            pass
        return []

    async def list_conversations(self, limit: int = 20) -> list[dict[str, Any]]:
        resp = await self.request_json("GET", "/conversations")
        convs = resp if isinstance(resp, list) else (resp or {}).get("data") or []
        return convs[:limit]

    async def get_conversation(self, conversation_id: str) -> dict[str, Any]:
        return await self.request_json("GET", f"/conversations/{conversation_id}")

    async def upload_audio(
        self, file_path: str | Path, *, selected_model: str = "Lyria 3.5"
    ) -> dict[str, Any]:
        p = Path(file_path)
        mime, _ = mimetypes.guess_type(p.name)
        mime = mime or "audio/mpeg"
        up = await self.upload_multipart(
            "/producer/upload-audio",
            {"file_type": mime, "filename": p.name, "selected_model": selected_model},
            "file",
            p,
        )
        clip_id = up.get("clip_id")
        op_id = up.get("operation_id")
        if not clip_id:
            raise GenerationError(f"Audio upload returned no clip_id: {up}")
        # Poll upload check status
        deadline = time.monotonic() + 180.0
        while time.monotonic() < deadline:
            await asyncio.sleep(2.0)
            st = await self.request_json(
                "GET",
                f"/producer/upload-audio/{clip_id}/upload-check-status",
                params={"operation_id": op_id} if op_id else None,
            )
            if (st or {}).get("status") != "pending":
                if (st or {}).get("status") != "complete":
                    raise GenerationError(f"Audio upload check failed: {st}")
                decision = (st or {}).get("decision")
                if decision == "requires_vocal_removal":
                    rv = await self.request_json(
                        "POST",
                        f"/producer/upload-audio/{clip_id}/remove-vocals",
                        json_body={"operation_id": op_id},
                    )
                    return rv
                if decision and decision != "allowed":
                    raise GenerationError(
                        f"Audio upload rejected ({decision}): {(st or {}).get('reason') or st}"
                    )
                return up
        raise GenerationTimeout("Timed out waiting for audio upload copyright/vocal check")
