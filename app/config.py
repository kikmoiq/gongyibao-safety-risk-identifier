# -*- coding: utf-8 -*-
"""应用配置读写：config.json（运行时可改，界面可配 LLM）"""
import json
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # 项目根目录
CONFIG_PATH = ROOT / "config.json"
EXAMPLE_PATH = ROOT / "config.example.json"

DEFAULT = {
    "llm": {
        "enabled": False,
        "base_url": "https://api.deepseek.com/v1",
        "api_key": "",
        "model": "deepseek-chat",
        "temperature": 0.2,
        "max_tokens": 4096,
        "max_excerpt_chars": 12000,
    },
    "demo_package_path": "",
}

_lock = threading.Lock()


def _read_file(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load() -> dict:
    """读配置；config.json 不存在则用 example 生成一份。"""
    cfg = json.loads(json.dumps(DEFAULT, ensure_ascii=False))
    src = None
    if CONFIG_PATH.exists():
        src = CONFIG_PATH
    elif EXAMPLE_PATH.exists():
        src = EXAMPLE_PATH
    if src:
        try:
            data = _read_file(src)
            cfg = _deep_merge(cfg, data)
        except Exception:
            pass
    return cfg


def save(data: dict) -> dict:
    with _lock:
        cur = load()
        merged = _deep_merge(cur, data)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(merged, f, ensure_ascii=False, indent=2)
    return merged


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in override.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def public_view(cfg: dict) -> dict:
    """给前端的配置视图（key 打码）。"""
    view = json.loads(json.dumps(cfg, ensure_ascii=False))
    key = view.get("llm", {}).get("api_key", "")
    if key:
        view["llm"]["api_key"] = key[:4] + "****" + ("（已设置，留空则不改）" if False else "")
    return view
