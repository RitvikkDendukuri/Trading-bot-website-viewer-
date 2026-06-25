# bot registry — add new bots by appending to _BOT_MODULES
from __future__ import annotations

from importlib import import_module
from types import ModuleType
from typing import Dict, List

_BOT_MODULES = [
    "app.bots.sector_rotation.strategy",
]

_loaded: Dict[str, ModuleType] = {}


def _load() -> None:
    if _loaded:
        return
    for path in _BOT_MODULES:
        mod = import_module(path)
        bot_id = mod.METADATA["id"]
        _loaded[bot_id] = mod


def all_bots() -> List[dict]:
    _load()
    return [dict(mod.METADATA) for mod in _loaded.values()]


def bot_ids() -> List[str]:
    _load()
    return list(_loaded.keys())


def get_metadata(bot_id: str) -> dict:
    _load()
    return dict(_loaded[bot_id].METADATA)


def get_strategy(bot_id: str) -> ModuleType:
    _load()
    if bot_id not in _loaded:
        raise KeyError(f"Unknown bot: {bot_id}")
    return _loaded[bot_id]
