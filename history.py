"""
历史成绩记录 — 基于 JSON 文件存储
每次获取 B30 时自动保存快照
"""
import json
import os
from pathlib import Path
from datetime import datetime

HISTORY_DIR = Path(__file__).parent / "history"


def save_snapshot(session_token: str, player_name: str, b30: list, rks: float, computed_rks: float):
    """保存一次 B30 快照"""
    HISTORY_DIR.mkdir(exist_ok=True)
    # 用 session_token 的前 8 位做文件名前缀
    safe_key = session_token[:8] if len(session_token) >= 8 else "unknown"
    filepath = HISTORY_DIR / f"{safe_key}.json"

    snapshot = {
        "ts": datetime.now().isoformat(),
        "player_name": player_name,
        "save_rks": rks,
        "computed_rks": computed_rks,
        "b30": [{"song": s["song"], "song_id": s["song_id"], "level": s["level"],
                 "score": s["score"], "acc": s["acc"], "rks": s["rks"],
                 "fc": s["fc"], "difficulty": s["difficulty"]}
                for s in b30],
    }

    history = []
    if filepath.exists():
        try:
            with open(filepath, encoding="utf-8") as f:
                history = json.load(f)
        except Exception:
            history = []

    history.append(snapshot)
    # 最多保留 100 条
    if len(history) > 100:
        history = history[-100:]

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def get_history(session_token: str) -> list:
    """获取历史记录"""
    safe_key = session_token[:8] if len(session_token) >= 8 else "unknown"
    filepath = HISTORY_DIR / f"{safe_key}.json"
    if not filepath.exists():
        return []
    try:
        with open(filepath, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def get_rks_trend(session_token: str) -> list:
    """获取 RKS 变化趋势"""
    history = get_history(session_token)
    return [{"ts": h["ts"], "save_rks": h["save_rks"],
             "computed_rks": h["computed_rks"], "player_name": h["player_name"]}
            for h in history]
