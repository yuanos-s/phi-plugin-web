"""
历史成绩记录 — 已迁移至 Supabase
此文件为兼容层，实际调用 db.py 中的函数
"""
import json
from typing import List, Dict, Any

# 导入 Supabase 函数
from db import save_b30_history, get_b30_history_for_user, get_user_by_session_token


def save_snapshot(session_token: str, player_name: str, b30: list, rks: float, computed_rks: float):
    """
    保存 B30 快照到 Supabase
    """
    import asyncio

    # 获取 user_id
    user = asyncio.run(get_user_by_session_token(session_token))
    if not user:
        print(f"[WARN] 用户不存在，无法保存快照: {session_token[:8]}")
        return

    # 调用 Supabase 保存
    try:
        asyncio.run(save_b30_history(
            user_id=user["id"],
            save_rks=rks,
            computed_rks=computed_rks,
            b30_data=b30
        ))
    except Exception as e:
        print(f"[ERROR] 保存历史快照失败: {e}")


def get_history(session_token: str) -> List[Dict[str, Any]]:
    """
    获取历史记录（从 Supabase）
    """
    import asyncio

    user = asyncio.run(get_user_by_session_token(session_token))
    if not user:
        return []

    history = asyncio.run(get_b30_history_for_user(user["id"]))
    # 转换为旧格式兼容
    result = []
    for h in history:
        result.append({
            "ts": h["created_at"],
            "player_name": "",
            "save_rks": h["save_rks"],
            "computed_rks": h["computed_rks"],
            "b30": h.get("b30_data", [])
        })
    return result


def get_rks_trend(session_token: str) -> List[Dict[str, Any]]:
    """
    获取 RKS 变化趋势
    """
    history = get_history(session_token)
    return [
        {
            "ts": h["ts"],
            "save_rks": h["save_rks"],
            "computed_rks": h["computed_rks"],
            "player_name": h.get("player_name", "")
        }
        for h in history
    ]
