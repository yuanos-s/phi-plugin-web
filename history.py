"""
历史成绩记录 — Supabase 版本 (无本地回退)

迁移变更:
  - 移除本地 JSON 存储回退
  - 所有操作直接走 Supabase
"""
import json
import os

try:
    from db import _is_configured, save_history, get_history
    _sb_ok = True
except Exception:
    _sb_ok = False
    _is_configured = lambda: False


async def save_snapshot(user_id: str, b30: list, rks: float, computed_rks: float):
    """保存 B30 快照到 Supabase"""
    if not _sb_ok or not _is_configured():
        return
    try:
        b30_data = [{"song": s.get("song",""), "song_id": s.get("song_id",""),
                     "level": s.get("level",""), "score": s.get("score",0),
                     "acc": s.get("acc",0), "rks": s.get("rks",0),
                     "fc": s.get("fc",False), "difficulty": s.get("difficulty",0)}
                    for s in b30]
        await save_history(user_id, rks, computed_rks, b30_data)
    except Exception:
        pass


async def get_history_async(user_id: str) -> list:
    """获取历史列表"""
    if not _sb_ok or not _is_configured():
        return []
    try:
        return await get_history(user_id)
    except Exception:
        return []


def get_rks_trend(user_id: str = None) -> list:
    """本地无数据，返回空列表"""
    return []
