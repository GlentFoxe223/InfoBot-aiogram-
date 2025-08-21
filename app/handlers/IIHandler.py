# app/handlers/IIHandler.py
from __future__ import annotations
import re
import html
from collections import deque
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from datetime import datetime, timedelta
from typing import Any, List, Tuple

from g4f.client import Client
from g4f import models as g4f_models
from loguru import logger as _logger

logger = _logger.bind(feature="ii")

_IS_NAME = lambda s: isinstance(s, str) and bool(re.fullmatch(r"[A-Za-z0-9._\-:]+", s))
_TO_STR = lambda x: str(x or "").strip()
_EXTRACT = lambda content: (
    " ".join((part.get("text") if isinstance(part, dict) else str(part)) for part in content).strip()
    if isinstance(content, list) else _TO_STR(content)
)

_PRIORITY: Tuple[str, ...] = (
    "gpt-4o-mini", "gpt-4o", "gpt-4.1-mini", "gpt-3.5-turbo", "claude-3-haiku", "gemini-pro"
)

_BLOCK_RE = re.compile(r"```([a-zA-Z0-9_+\-]*)\s*\n(.*?)```", re.DOTALL)
_INLINE_RE = re.compile(r"`([^`\n]+)`")

async def _collect_model_ids() -> Tuple[str, ...]:
    out: List[str] = []
    for name in dir(g4f_models):
        if name.startswith("_"):
            continue
        obj: Any = getattr(g4f_models, name)
        if isinstance(obj, str) and _IS_NAME(obj):
            out.append(obj)
            continue
        mid = getattr(obj, "name", None) or getattr(obj, "model", None)
        if _IS_NAME(mid):
            out.append(mid)
    seen, result = set(), []
    for pid in _PRIORITY:
        if pid in out and pid not in seen:
            result.append(pid); seen.add(pid)
    for mid in out:
        if mid not in seen:
            result.append(mid); seen.add(mid)
    return tuple(result)

async def _format_for_html(text: str) -> str:
    placeholders: List[str] = []

    async def _put(fragment: str) -> str:
        idx = len(placeholders)
        placeholders.append(fragment)
        return f"@@BLOCK{idx}@@"

    async def repl_block(m: re.Match) -> str:
        code = m.group(2) or ""
        return _put(f"<pre><code>{html.escape(code)}</code></pre>")

    async def repl_inline(m: re.Match) -> str:
        code = m.group(1) or ""
        return _put(f"<code>{html.escape(code)}</code>")

    s = _BLOCK_RE.sub(repl_block, text)
    s = _INLINE_RE.sub(repl_inline, s)
    s = html.escape(s)
    for i, frag in enumerate(placeholders):
        s = s.replace(f"@@BLOCK{i}@@", frag)
    return s

class IIHandler:
    async def __init__(self, limit_per_run: int = 15, blacklist_minutes: int = 10, timeout_seconds: int = 20):
        self.client = Client()
        self._models: Tuple[str, ...] = await _collect_model_ids() or _PRIORITY
        self._last_ok: str | None = None
        self._blacklist: dict[str, datetime] = {}
        self.limit_per_run = int(limit_per_run)
        self.blacklist_minutes = int(blacklist_minutes)
        self.timeout_seconds = int(timeout_seconds)
        self._executor = ThreadPoolExecutor(max_workers=2)
        logger.info(f"[II] models={self._models}")

    async def _is_blacklisted(self, model: str) -> bool:
        until = await self._blacklist.get(model)
        if not until:
            return False
        if datetime.utcnow() >= until:
            await self._blacklist.pop(model, None)
            return False
        return True

    async def _blacklist_model(self, model: str) -> None:
        self._blacklist[model] = datetime.utcnow() + timedelta(minutes=self.blacklist_minutes)

    async def _request(self, model: str, text: str):
        try:
            return self.client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": text}],
                temperature=0.6,
                web_search=False,
            )
        except TypeError:
            return self.client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": text}],
                temperature=0.6,
            )

    async def _try_model_once(self, model: str, text: str) -> str | None:
        try:
            fut = await self._executor.submit(self._request, model, text)
            resp = await fut.result(timeout=self.timeout_seconds)
            msg = resp.choices[0].message
            content = await _EXTRACT(getattr(msg, "content", None))
            if not content:
                raise ValueError("empty")
            self._last_ok = model
            logger.info(f"[II] ok={model}")
            return await _format_for_html(content)
        except TimeoutError:
            logger.warning(f"[II] timeout={model}")
            await self._blacklist_model(model)
            return None
        except Exception as e:
            logger.warning(f"[II] fail={model} err={e}")
            await self._blacklist_model(model)
            return None

    async def answerII(self, text: str, cycles: int = 2) -> str:
        order = deque()
        if self._last_ok and self._last_ok in self._models and not await self._is_blacklisted(self._last_ok):
            await order.append(self._last_ok)
        for m in self._models:
            if m != self._last_ok:
                await order.append(m)
        allowed = [m for m in order if not self._is_blacklisted(m)]
        if not allowed:
            return "Все модели не ответили."
        allowed = allowed[: self.limit_per_run]
        for c in range(1, cycles + 1):
            logger.info(f"[II] cycle {c}/{cycles}")
            for m in allowed:
                ans = await self._try_model_once(m, text)
                if ans:
                    return ans
        return "Все модели не ответили."

    async def get_answer(self, text: str) -> str:
        return await self.answerII(text)