"""配置单一真源。

问题：同一份「参数」有四个读取点，其中三个读的是硬编码常量或错误路径，
所以用户在参数页改完，策略树根本没吃进去。

原则：
  1. 只有这里能读写 adjustments.json，其他模块一律 config.get()
  2. 每次 save 递增 version，所有缓存键带上它 → 改完立刻失效
  3. 读不到就用 DEFAULT，绝不让常量冒充配置
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from .paths import data_path

_LOCK = threading.RLock()
_STATE = {"data": None, "version": 0, "mtime": 0.0, "path": None}

# 内置默认值：配置文件缺项时用它，但**允许被覆盖**
DEFAULT = {
    "freq": {},
    "width": {},
    "tendency": {
        "过度诈唬型": {"bluff_catch": 0.20, "value_thin": 0.10, "bluff": -0.30,
                     "note": "他诈唬过多 → 多抓、少诈唬"},
        "下注不足型": {"bluff_catch": -0.25, "value_thin": -0.10, "bluff": 0.15,
                     "note": "他不下注 → 他一下注就该弃"},
    },
    "simplify": {
        "levels_pre": [100, 75, 50, 25, 0],
        "levels_post": [100, 80, 60, 40, 20, 0],
        "threshold_pre": 2,
        "threshold_post": 8,
        "force_mixed_if_multi_sizing": True,
    },
}


def _cfg_path() -> Path:
    return data_path("tree", "adjustments.json")


def _deep_merge(base: dict, over: dict) -> dict:
    out = dict(base or {})
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load() -> dict:
    """读配置（带 mtime 缓存）。"""
    p = _cfg_path()
    with _LOCK:
        try:
            mt = p.stat().st_mtime if p.exists() else 0.0
        except Exception:
            mt = 0.0
        if _STATE["data"] is not None and _STATE["mtime"] == mt and _STATE["path"] == str(p):
            return _STATE["data"]
        data = {}
        try:
            if p.exists():
                data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            data = {}
        merged = _deep_merge(DEFAULT, data)
        _STATE.update(data=merged, mtime=mt, path=str(p))
        return merged


def get(section: str, key: str = None, default=None):
    d = load().get(section) or {}
    if key is None:
        return d or default
    return d.get(key, default)


def version() -> int:
    """配置版本号：save 时 +1。所有缓存键都要带它。"""
    return _STATE["version"]


def bump():
    with _LOCK:
        _STATE["version"] += 1
        _STATE["data"] = None


def save(patch: dict) -> dict:
    """深合并写回，并让所有缓存失效。"""
    p = _cfg_path()
    with _LOCK:
        cur = {}
        try:
            if p.exists():
                cur = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            cur = {}
        merged = _deep_merge(cur, patch or {})
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
        _STATE.update(data=None, version=_STATE["version"] + 1)
        return merged


def effective_report() -> dict:
    """每个参数的生效值 + 来源文件 + mtime，用来排查「改了没反应」。"""
    p = _cfg_path()
    try:
        mt = p.stat().st_mtime if p.exists() else 0
    except Exception:
        mt = 0
    d = load()
    return {
        "path": str(p),
        "exists": p.exists(),
        "mtime": mt,
        "version": version(),
        "sections": {k: (list(v.keys()) if isinstance(v, dict) else v) for k, v in d.items()},
        "simplify": d.get("simplify"),
        "tendency_types": list((d.get("tendency") or {}).keys()),
    }
