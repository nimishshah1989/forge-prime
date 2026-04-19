"""Inner Claude Code session wrapper for forge-runner (FR-011, FR-037, FR-038).

Wraps ``claude_agent_sdk.query()`` with:
  - ``asyncio.wait_for`` for wall-clock timeout enforcement
  - Exponential backoff retry on transient rate-limit / overload errors
  - ``AuthFailure`` raised on unrecoverable authentication errors
  - Synthetic ``session_start`` / ``session_end`` events around the SDK loop
  - Runner event dict conversion from SDK message types

Public API:
    AuthFailure            — custom exception: caller must halt, not mark FAILED
    run_session(chunk, ctx) -> AsyncIterator[dict]
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, AsyncIterator

import httpx
import structlog

import claude_agent_sdk
from claude_agent_sdk import ClaudeAgentOptions, ProcessError

from ._time import now_ist, to_iso
from .router import ModelProvider, resolve
from .state import ChunkRow
from .tools import load_bearing

if TYPE_CHECKING:
    pass  # keep for future type-only imports

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Transient vs auth error detection via stderr substring matching
# ---------------------------------------------------------------------------

_TRANSIENT_MARKERS = ("529", "rate limit", "overloaded")
_AUTH_MARKERS = ("authentication", "401", "invalid api key", "invalid_api_key")

_MAX_BACKOFF_RETRIES = 5
_BACKOFF_CAP_SEC = 60


class AuthFailure(Exception):
    """Raised when the SDK session fails due to an unrecoverable auth error.

    The caller MUST reset the chunk to PENDING and exit with code 1, NOT mark
    it FAILED — this is an environment-level failure, not a chunk failure.
    """


def _is_transient(exc: ProcessError) -> bool:
    """Return True if the error is transient (rate-limit / overload)."""
    stderr = (exc.stderr or "").lower()
    return any(m in stderr for m in _TRANSIENT_MARKERS)


def _is_auth_error(exc: ProcessError) -> bool:
    """Return True if the error is an unrecoverable authentication failure."""
    stderr = (exc.stderr or "").lower()
    return any(m in stderr for m in _AUTH_MARKERS)


def _make_event(chunk_id: str, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Build a runner event dict with the standard envelope."""
    return {
        "t": to_iso(now_ist()),
        "chunk_id": chunk_id,
        "kind": kind,
        "payload": payload,
    }


async def run_session(
    chunk: ChunkRow,
    ctx: Any,  # RunContext — typed Any to avoid circular imports at stub time
) -> AsyncIterator[dict[str, Any]]:
    """Async generator yielding runner event dicts for one chunk session.

    Emits:
      - ``session_start``  — before the first SDK message
      - ``tool_use``       — for each ToolUseBlock in AssistantMessages
      - ``tool_result``    — for each ToolResultBlock in UserMessages
      - ``text``           — for each TextBlock in AssistantMessages
      - ``session_end``    — after the SDK iterator is exhausted
      - ``error``          — if a non-retried exception occurs

    Raises:
      - ``AuthFailure``          — on auth/401 errors (caller handles halt)
      - ``asyncio.TimeoutError`` — when wall-clock timeout is exceeded

    The backoff wrapper transparently retries transient 529/rate-limit errors
    up to ``_MAX_BACKOFF_RETRIES`` times without counting them against max_turns.
    """
    # Resolve model alias to (model_id, provider)
    model_alias = getattr(chunk, "model_alias", None)
    model_id, provider = resolve(model_alias)
    # Store resolved model_id on ctx for cost_tracker
    ctx.model_id = model_id  # type: ignore[attr-defined]

    conductor_path = Path(ctx.repo) / ".forge" / "CONDUCTOR.md"
    try:
        conductor_text = conductor_path.read_text(encoding="utf-8")
    except OSError:
        logger.warning("conductor_md_not_found", path=str(conductor_path))
        conductor_text = ""

    conductor_with_chunk = conductor_text + f"\n\nCURRENT CHUNK: {chunk.id}"

    # Route to OpenRouter for non-Anthropic models
    if provider == ModelProvider.OPENROUTER:
        async for event in _run_openrouter_session(chunk, ctx, model_id, conductor_with_chunk):
            yield event
        return

    options = ClaudeAgentOptions(
        cwd=str(ctx.repo),
        allowed_tools=load_bearing(),
        max_turns=ctx.max_turns,
        system_prompt={"type": "preset", "preset": "claude_code", "append": conductor_with_chunk},
    )

    session_id = f"forge-{chunk.id}-{int(time.time())}"

    yield _make_event(
        chunk.id,
        "session_start",
        {
            "session_id": session_id,
            "cwd": str(ctx.repo),
            "allowed_tools_count": len(load_bearing()),
            "max_turns": ctx.max_turns,
        },
    )

    turns = 0
    stop_reason = "unknown"
    usage: dict[str, Any] = {}

    attempt = 0

    async def _query_with_backoff() -> AsyncIterator[Any]:
        """Inner generator: retries on transient errors with exponential backoff."""
        nonlocal attempt
        while True:
            try:
                async for msg in claude_agent_sdk.query(
                    prompt=f"Implement chunk {chunk.id} per the spec.",
                    options=options,
                ):
                    yield msg
                return
            except ProcessError as exc:
                if _is_auth_error(exc):
                    raise AuthFailure(
                        f"Authentication failed for chunk {chunk.id}: {exc.stderr}"
                    ) from exc
                if _is_transient(exc) and attempt < _MAX_BACKOFF_RETRIES:
                    delay = min(2**attempt, _BACKOFF_CAP_SEC)
                    logger.warning(
                        "session_transient_retry",
                        chunk_id=chunk.id,
                        attempt=attempt + 1,
                        delay_sec=delay,
                    )
                    await asyncio.sleep(delay)
                    attempt += 1
                    continue
                raise

    # Wrap the whole iteration in a wall-clock timeout via queue + producer task.
    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

    async def _produce() -> None:
        nonlocal turns, stop_reason, usage
        try:
            async for msg in _query_with_backoff():
                if hasattr(msg, "content") and isinstance(msg.content, list):
                    for block in msg.content:
                        block_type = getattr(block, "type", None)
                        if block_type == "tool_use":
                            turns += 1
                            await queue.put(
                                _make_event(
                                    chunk.id,
                                    "tool_use",
                                    {
                                        "tool": getattr(block, "name", "unknown"),
                                        "input": getattr(block, "input", {}),
                                    },
                                )
                            )
                        elif block_type == "text":
                            await queue.put(
                                _make_event(
                                    chunk.id,
                                    "text",
                                    {"content": getattr(block, "text", "")[:2000]},
                                )
                            )
                elif hasattr(msg, "tool_use_id"):
                    content = getattr(msg, "content", "")
                    summary = (
                        str(content)[:200] if not isinstance(content, list) else str(content)[:200]
                    )
                    await queue.put(
                        _make_event(
                            chunk.id,
                            "tool_result",
                            {
                                "tool_use_id": getattr(msg, "tool_use_id", ""),
                                "is_error": False,
                                "summary": summary,
                            },
                        )
                    )

                if hasattr(msg, "stop_reason"):
                    stop_reason = getattr(msg, "stop_reason", "end_turn") or "end_turn"
                    raw_usage = getattr(msg, "usage", None)
                    if raw_usage is not None and hasattr(raw_usage, "__dict__"):
                        usage = vars(raw_usage)
                    elif isinstance(raw_usage, dict):
                        usage = raw_usage
        finally:
            await queue.put(None)  # sentinel

    try:
        producer_task = asyncio.create_task(_produce())
        timeout_sec: float = float(ctx.timeout_sec)

        deadline = asyncio.get_event_loop().time() + timeout_sec

        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                producer_task.cancel()
                raise asyncio.TimeoutError(
                    f"Session for {chunk.id} exceeded {ctx.timeout_sec}s timeout"
                )
            try:
                event = await asyncio.wait_for(queue.get(), timeout=remaining)
            except asyncio.TimeoutError:
                producer_task.cancel()
                raise asyncio.TimeoutError(
                    f"Session for {chunk.id} exceeded {ctx.timeout_sec}s timeout"
                ) from None

            if event is None:
                break
            yield event

        # Ensure producer finished cleanly (propagates exceptions from _produce)
        await producer_task

    except AuthFailure:
        yield _make_event(
            chunk.id,
            "error",
            {"error_type": "AuthFailure", "message": "Authentication failed"},
        )
        raise

    except asyncio.TimeoutError:
        yield _make_event(
            chunk.id,
            "error",
            {
                "error_type": "TimeoutError",
                "message": f"Wall-clock timeout ({ctx.timeout_sec}s) exceeded",
            },
        )
        raise

    yield _make_event(
        chunk.id,
        "session_end",
        {
            "session_id": session_id,
            "stop_reason": stop_reason,
            "turns": turns,
            "usage": usage,
        },
    )


async def _run_openrouter_session(
    chunk: ChunkRow,
    ctx: Any,
    model_id: str,
    system_prompt: str,
) -> AsyncIterator[dict[str, Any]]:
    """Simple single-turn OpenRouter call for deepseek/gemini models.

    Streams SSE, yields session_start / text / session_end events.
    OpenRouter models don't have tool-use in the same way as claude_agent_sdk,
    so this path is for cheap scaffold/planning tasks only.
    """
    import os
    import json as _json

    key = os.getenv("OPENROUTER_API_KEY", "")
    session_id = f"forge-or-{chunk.id}-{int(time.time())}"

    yield _make_event(chunk.id, "session_start", {
        "session_id": session_id,
        "model": model_id,
        "provider": "openrouter",
    })

    prompt = (
        f"System: {system_prompt}\n\n"
        f"Implement chunk {chunk.id} per the spec."
    )

    in_tok = out_tok = 0
    collected: list[str] = []

    try:
        async with httpx.AsyncClient(timeout=float(ctx.timeout_sec)) as client:
            async with client.stream(
                "POST",
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json={
                    "model": model_id,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": True,
                },
            ) as resp:
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = line[6:]
                    if data.strip() == "[DONE]":
                        break
                    try:
                        chunk_data = _json.loads(data)
                        delta = chunk_data["choices"][0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            collected.append(content)
                            yield _make_event(chunk.id, "text", {"content": content[:2000]})
                        usage = chunk_data.get("usage") or {}
                        in_tok = usage.get("prompt_tokens", in_tok)
                        out_tok = usage.get("completion_tokens", out_tok)
                    except Exception:
                        continue
    except Exception as exc:
        yield _make_event(chunk.id, "error", {"error_type": type(exc).__name__, "message": str(exc)})

    yield _make_event(chunk.id, "session_end", {
        "session_id": session_id,
        "stop_reason": "end_turn",
        "turns": 1,
        "usage": {"input_tokens": in_tok, "output_tokens": out_tok},
    })
