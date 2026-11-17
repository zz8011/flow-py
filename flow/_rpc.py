"""batchexecute RPC transport for the current flow.google.com app.

History: flow-py 0.1.0 targeted the old labs.google/fx Next.js app and
authenticated by scraping an OAuth Bearer token out of the page session.
Google retired that app in late 2026; labs.google/fx now redirects to
flow.google.com, an Angular SPA whose backend traffic is Google's
``batchexecute`` RPC protocol served from the app origin itself and
authenticated purely by session cookies.

This module implements that protocol on top of the existing
BrowserManager (the persistent profile carries the session):

* bootstrap tokens (``at`` / ``f.sid`` / ``bl``) come from the page's
  ``WIZ_global_data`` — the same values the app itself uses;
* requests are ``POST /_/AiSandboxAngularFrontend/data/batchexecute``
  with a form body of ``f.req`` + ``at``;
* responses are the usual ``)]}'``-prefixed line stream containing
  ``["wrb.fr", <rpcid>, <json-string>, ...]`` entries.

RPC ids used here (observed live, 2026-11-18):

* ``nzlxg``  — credits: ``[]`` -> ``[balance, tier, ..., [reset_ts]]``
* ``UpteDb`` — project list: ``["projects/*", 21, ...]``
* ``HTrJv``  — model config (families, variants, per-tier credit costs)
* ``Zzl0ze`` — project workflows + media: ``["projects/<id>", ...]``
* ``jHPbke`` — create project: ``["projects/*", [null, [name]], [null, 22]]``
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any, Optional
from urllib.parse import urlencode

from ._exceptions import AuthError, FlowError

log = logging.getLogger(__name__)

FLOW_ORIGIN = "https://flow.google.com"
BATCH_PATH = "/_/AiSandboxAngularFrontend/data/batchexecute"

RPC_CREDITS = "nzlxg"
RPC_PROJECTS = "UpteDb"
RPC_MODEL_CONFIG = "HTrJv"
RPC_PROJECT_MEDIA = "Zzl0ze"
RPC_CREATE_PROJECT = "jHPbke"
RPC_MEDIA = "as29s"


def _parse_batch_response(text: str) -> dict[str, Any]:
    """Parse a batchexecute response body into {rpcid: payload}."""
    out: dict[str, Any] = {}
    if not text:
        return out
    body = text
    if body.startswith(")]}'"):
        body = body.split("\n", 1)[1] if "\n" in body else ""
    for line in body.splitlines():
        line = line.strip()
        if not line or line.isdigit():
            continue
        try:
            arr = json.loads(line)
        except Exception:
            continue
        if not isinstance(arr, list):
            continue
        for item in arr:
            if (
                isinstance(item, list)
                and len(item) >= 3
                and item[0] == "wrb.fr"
                and isinstance(item[1], str)
            ):
                payload = item[2]
                if isinstance(payload, str):
                    try:
                        payload = json.loads(payload)
                    except Exception:
                        pass
                out[item[1]] = payload
    return out


def _find_duration(node, depth: int = 0):
    """Find the [null, null, [seconds]] duration marker in a media record."""
    if depth > 8:
        return None
    if isinstance(node, list):
        if (
            len(node) == 3
            and node[0] is None
            and node[1] is None
            and isinstance(node[2], list)
            and len(node[2]) == 1
            and isinstance(node[2][0], int)
            and 0 < node[2][0] <= 120
        ):
            return node[2][0]
        for child in node:
            found = _find_duration(child, depth + 1)
            if found is not None:
                return found
    return None


class FlowRPC:
    """Minimal batchexecute client bound to a BrowserManager session."""

    def __init__(self, browser_manager):
        self._bm = browser_manager
        self._wiz: Optional[dict] = None
        self._reqid = 100000

    # ── bootstrap ──────────────────────────────────────────────────────

    async def _ensure_page(self):
        page = await self._bm.page()
        if "flow.google.com" not in page.url:
            await page.goto(FLOW_ORIGIN + "/", wait_until="domcontentloaded", timeout=30_000)
            await asyncio.sleep(3)
        if "accounts.google.com" in page.url:
            raise AuthError("Not logged in. Run `flow login` to authenticate interactively.")
        return page

    async def _bootstrap(self) -> dict:
        if self._wiz:
            return self._wiz
        page = await self._ensure_page()
        wiz = await page.evaluate(
            "() => { const w = window.WIZ_global_data || {};"
            " return {at: w.SNlM0e || '', sid: w.FdrFJe || '', bl: w.cfb2h || ''}; }"
        )
        if not wiz or not wiz.get("at"):
            # Page may still be booting; give it one more beat and retry.
            await asyncio.sleep(3)
            wiz = await page.evaluate(
                "() => { const w = window.WIZ_global_data || {};"
                " return {at: w.SNlM0e || '', sid: w.FdrFJe || '', bl: w.cfb2h || ''}; }"
            )
        if not wiz or not wiz.get("at"):
            raise AuthError(
                "Could not read Flow session bootstrap (WIZ_global_data). "
                "The session may be logged out — run `flow login`."
            )
        self._wiz = wiz
        return wiz

    # ── core call ──────────────────────────────────────────────────────

    async def call(self, rpcid: str, payload: Any) -> Any:
        """Invoke one RPC and return its decoded payload (or None)."""
        wiz = await self._bootstrap()
        page = await self._bm.page()
        self._reqid += 17
        query = urlencode(
            {
                "rpcids": rpcid,
                "f.sid": wiz["sid"],
                "bl": wiz["bl"],
                "hl": "en",
                "rt": "c",
                "_reqid": str(self._reqid),
                "source-path": "/",
            }
        )
        freq = json.dumps([[[rpcid, json.dumps(payload), None, "generic"]]])
        resp = await self._bm.context.request.post(
            FLOW_ORIGIN + BATCH_PATH + "?" + query,
            form={"f.req": freq, "at": wiz["at"]},
            headers={"x-same-domain": "1"},
        )
        if resp.status != 200:
            raise FlowError(f"batchexecute {rpcid} failed: HTTP {resp.status}")
        results = _parse_batch_response(await resp.text())
        if rpcid not in results:
            raise FlowError(f"batchexecute {rpcid}: no payload in response")
        return results[rpcid]

    # ── typed helpers ──────────────────────────────────────────────────

    async def get_credits(self) -> dict:
        """Return {credits, userPaygateTier, sku, serviceTier, reset_ts}."""
        data = await self.call(RPC_CREDITS, [])
        # Observed shape: [balance, tier, 3, 3, null, balance, [reset_ts, nanos]]
        if not isinstance(data, list) or not data:
            raise FlowError(f"Unexpected credits payload: {data!r}")
        reset_ts = None
        if len(data) > 6 and isinstance(data[6], list) and data[6]:
            reset_ts = data[6][0]
        return {
            "credits": int(data[0]),
            "userPaygateTier": data[1] if len(data) > 1 else "",
            "priceTier": data[2] if len(data) > 2 and isinstance(data[2], int) else (data[1] if len(data) > 1 else 1),
            "sku": "",
            "serviceTier": "",
            "reset_ts": reset_ts,
        }

    async def get_tier(self) -> int:
        raw = await self.get_credits()
        try:
            return int(raw.get("priceTier") or raw.get("userPaygateTier") or 1)
        except (TypeError, ValueError):
            return 1

    async def list_projects(self) -> list[dict]:
        """Return [{id, name, thumbnail_url}] for the account's projects."""
        data = await self.call(RPC_PROJECTS, ["projects/*", 21, None, None, None, None, [1]])
        projects: list[dict] = []
        entries = []
        if isinstance(data, list) and data and isinstance(data[0], list):
            entries = data[0]
        for e in entries:
            if not isinstance(e, list) or not e:
                continue
            meta = e[1] if len(e) > 1 and isinstance(e[1], list) else []
            projects.append(
                {
                    "id": e[0],
                    "name": meta[0] if meta else "",
                    "thumbnail_url": meta[3] if len(meta) > 3 else "",
                }
            )
        return projects

    async def create_project(self, name: Optional[str] = None) -> str:
        """Create a project and return its UUID."""
        if not name:
            name = time.strftime("%b %d - %H:%M")
        data = await self.call(
            RPC_CREATE_PROJECT, ["projects/*", [None, [name]], [None, 22]]
        )
        # Response carries the created resource; fall back to a fresh list.
        text = json.dumps(data or "")
        m = re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", text)
        if m:
            return m.group(0)
        for p in await self.list_projects():
            if p["name"] == name:
                return p["id"]
        raise FlowError("Project creation returned no project id")

    async def get_model_config(self, tier: Optional[int] = None) -> dict:
        """Return {"videoModels": [...]} in the shape the CLI expects.

        Decoded from the HTrJv payload: section [0][4] holds model
        families; each variant is [model_key, ..., [[tier, [[_, cost]]], ...], ...]
        and the variant's duration (seconds) sits at index 16.
        """
        if tier is None:
            tier = await self.get_tier()
        data = await self.call(RPC_MODEL_CONFIG, [])
        models: list[dict] = []
        try:
            families = data[0][4]
        except (TypeError, IndexError, KeyError):
            return {"videoModels": []}
        for family in families or []:
            if not isinstance(family, list) or len(family) < 2:
                continue
            display = family[0]
            for variant in family[1] or []:
                if not isinstance(variant, list) or not variant:
                    continue
                key = variant[0]
                cost = None
                tiers = variant[4] if len(variant) > 4 else None
                tier_mentioned = False
                if isinstance(tiers, list):
                    by_tier = {}
                    for t in tiers:
                        if isinstance(t, list) and len(t) == 2:
                            if t[0] == tier:
                                tier_mentioned = True
                            if isinstance(t[1], list):
                                for c in t[1]:
                                    if isinstance(c, list) and len(c) == 2 and isinstance(c[1], (int, float)):
                                        by_tier[t[0]] = c[1]
                    if tier in by_tier:
                        cost = by_tier[tier]
                    elif tier_mentioned:
                        continue
                    elif by_tier:
                        cost = next(iter(by_tier.values()))
                duration = variant[16] if len(variant) > 16 else None
                if (
                    cost == 0
                    and duration is None
                    and len(variant) > 25
                    and isinstance(variant[25], list)
                    and variant[25]
                ):
                    res_code = (
                        variant[23][0][0]
                        if len(variant) > 23
                        and isinstance(variant[23], list)
                        and variant[23]
                        and variant[23][0]
                        else 1
                    )
                    for row in variant[25][0]:
                        if (
                            isinstance(row, list)
                            and len(row) == 2
                            and row[0] == [tier, 10, res_code]
                            and isinstance(row[1], list)
                            and len(row[1]) == 2
                        ):
                            cost = row[1][1]
                            duration = 10
                            break
                feats = []
                lk = str(key).lower()
                if "_t2v" in lk or "t2v" in lk:
                    feats.append("TEXT")
                if "_i2v" in lk or "i2v" in lk:
                    feats.append("START_IMAGE")
                if "_r2v" in lk or "r2v" in lk:
                    feats.append("REFERENCES")
                if "_edit" in lk:
                    feats.append("EDIT")
                if "extend" in lk or "extension" in lk:
                    feats.append("EXTEND")
                if "upsampl" in lk:
                    feats.append("UPSCALE")
                models.append(
                    {
                        "key": key,
                        "displayName": display,
                        "creditCost": cost,
                        "durationS": duration,
                        "supportedFeatures": feats,
                    }
                )
        return {"videoModels": models}

    async def list_project_media(self, project_id: str) -> dict:
        """Return {workflows: [...], medias: [...]} parsed from Zzl0ze.

        Media group shape: [media_id, project_id, workflow_id, null, null,
        [<media record>], null, [<detail>]] — the record carries the
        poster URL, byte size, prompt and model key; the detail carries
        the duration as [null, null, [seconds]]. NOTE: this listing does
        NOT include signed download URLs; resolve those per media with
        get_media_url() (RPC as29s).
        """
        data = await self.call(
            RPC_PROJECT_MEDIA, [f"projects/{project_id}", None, None, None, [1]]
        )
        workflows: list[dict] = []
        medias: list[dict] = []
        if not isinstance(data, list) or len(data) < 2:
            return {"workflows": workflows, "medias": medias}
        for w in data[1] if isinstance(data[1], list) else []:
            if not isinstance(w, list) or len(w) < 4:
                continue
            meta = w[3] if isinstance(w[3], list) else []
            workflows.append(
                {
                    "id": w[0],
                    "display_name": meta[0] if meta else "",
                    "session_id": meta[4] if len(meta) > 4 else "",
                    "turn_id": meta[5] if len(meta) > 5 else "",
                    "project_id": w[4] if len(w) > 4 else project_id,
                }
            )
        wf_names = {w["id"]: w["display_name"] for w in workflows}
        media_section = data[2] if len(data) > 2 and isinstance(data[2], list) else []
        for group in media_section:
            if not isinstance(group, list) or len(group) < 3:
                continue
            text = json.dumps(group, ensure_ascii=False)
            posters = re.findall(r"https://lh3\.googleusercontent\.com/asb/[^\"\\]+", text)
            models = re.findall(r"(?:macaron|abra|veo|GEM_PIX)[A-Za-z0-9_]*", text)
            model_key = models[0] if models else ""
            duration = _find_duration(group)
            is_video = (
                any(t in model_key for t in ("_t2v", "_i2v", "_r2v", "_fl_", "_edit", "veo_"))
                or duration is not None
            )
            signed = re.findall(r"https://flow-content\.google/video/[^\"\\]+", text)
            wf_id = group[2] if isinstance(group[2], str) else ""
            medias.append(
                {
                    "media_id": group[0],
                    "kind": "video" if is_video else "image",
                    "signed_url": signed[0] if signed else "",
                    "poster_url": posters[0] if posters else "",
                    "model_key": model_key,
                    "duration_s": duration,
                    "workflow_id": wf_id,
                    "display_name": wf_names.get(wf_id, ""),
                }
            )
        return {"workflows": workflows, "medias": medias}

    async def get_media_url(self, media_id: str) -> str:
        """Resolve a media's signed flow-content download URL (RPC as29s)."""
        data = await self.call(RPC_MEDIA, [media_id])
        text = json.dumps(data, ensure_ascii=False)
        m = re.search(
            r"https://flow-content\.google/(?:video|image)/" + re.escape(media_id) + r"[^\"\\ ]*",
            text,
        )
        return m.group(0) if m else ""
