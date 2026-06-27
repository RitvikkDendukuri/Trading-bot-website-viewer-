# WebSocket broadcast hub — push updates to all connected dashboard clients
from __future__ import annotations

import asyncio
import json
import logging
from typing import Set

from fastapi import WebSocket

log = logging.getLogger("ws")

_clients: Set[WebSocket] = set()
_loop: asyncio.AbstractEventLoop | None = None


def set_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _loop
    _loop = loop


async def connect(ws: WebSocket) -> None:
    await ws.accept()
    _clients.add(ws)
    log.debug("WS client connected (%d total)", len(_clients))


def disconnect(ws: WebSocket) -> None:
    _clients.discard(ws)
    log.debug("WS client disconnected (%d total)", len(_clients))


async def _broadcast(message: dict) -> None:
    payload = json.dumps(message)
    dead: list[WebSocket] = []
    for ws in _clients:
        try:
            await ws.send_text(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _clients.discard(ws)


def notify(event: str = "tick") -> None:
    if not _clients or _loop is None:
        return
    try:
        asyncio.run_coroutine_threadsafe(
            _broadcast({"type": event}), _loop
        )
    except Exception:
        pass
