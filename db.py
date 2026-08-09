"""
Supabase 数据库交互模块
"""
import os
import json
from typing import Optional, List, Dict, Any
from supabase import create_client, Client

# 初始化 Supabase 客户端
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")  # 用于管理操作

# 优先使用 service_key，否则使用 anon_key
SUPABASE_KEY = SUPABASE_SERVICE_KEY or SUPABASE_ANON_KEY

_sb: Optional[Client] = None

def get_supabase_client() -> Client:
    global _sb
    if _sb is None:
        if not SUPABASE_URL or not SUPABASE_KEY:
            raise ValueError("Supabase URL and key must be set in environment")
        _sb = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _sb

def supabase_client():
    """便捷函数"""
    return get_supabase_client()

# ===== 用户操作 =====

async def upsert_user(
    taptap_openid: str,
    player_name: str = "",
    avatar_url: str = "",
    session_token: str = "",
    is_global: bool = False
) -> Dict[str, Any]:
    """
    插入或更新用户（基于 taptap_openid）
    返回用户记录
    """
    sb = get_supabase_client()
    data = {
        "taptap_openid": taptap_openid,
        "player_name": player_name,
        "avatar_url": avatar_url,
        "last_session_token": session_token,
        "is_global": is_global,
        "updated_at": "NOW()"  # 会在触发器自动更新
    }
    # 使用 upsert（PostgreSQL 的 ON CONFLICT）
    res = sb.table("users").upsert(data, on_conflict="taptap_openid").execute()
    if res.data:
        return res.data[0]
    else:
        raise Exception("Upsert user failed")

async def get_user_by_taptap_openid(openid: str) -> Optional[Dict[str, Any]]:
    sb = get_supabase_client()
    res = sb.table("users").select("*").eq("taptap_openid", openid).limit(1).execute()
    if res.data:
        return res.data[0]
    return None

async def get_user_by_session_token(session_token: str) -> Optional[Dict[str, Any]]:
    sb = get_supabase_client()
    res = sb.table("users").select("*").eq("last_session_token", session_token).limit(1).execute()
    if res.data:
        return res.data[0]
    return None

# ===== 存档操作 =====

async def save_archive(
    user_id: str,
    save_rks: float,
    computed_rks: float,
    total_songs: int,
    total_cleared: int,
    total_fc: int,
    total_phi: int,
    b30_data: List[dict],
    all_scores: List[dict]
) -> str:
    """
    保存一份存档到 archives 表
    返回 archive_id
    """
    sb = get_supabase_client()
    data = {
        "user_id": user_id,
        "save_rks": save_rks,
        "computed_rks": computed_rks,
        "total_songs": total_songs,
        "total_cleared": total_cleared,
        "total_fc": total_fc,
        "total_phi": total_phi,
        "b30_data": json.dumps(b30_data),
        "all_scores": json.dumps(all_scores)
    }
    res = sb.table("archives").insert(data).execute()
    if res.data:
        return res.data[0]["id"]
    else:
        raise Exception("Save archive failed")

async def get_latest_archive(user_id: str) -> Optional[Dict[str, Any]]:
    """
    获取用户最新的一条存档记录
    """
    sb = get_supabase_client()
    res = sb.table("archives")\
        .select("*")\
        .eq("user_id", user_id)\
        .order("created_at", desc=True)\
        .limit(1)\
        .execute()
    if res.data:
        return res.data[0]
    return None

async def get_all_archives(user_id: str, limit: int = 100) -> List[Dict[str, Any]]:
    sb = get_supabase_client()
    res = sb.table("archives")\
        .select("*")\
        .eq("user_id", user_id)\
        .order("created_at", desc=True)\
        .limit(limit)\
        .execute()
    return res.data

# ===== B30 历史 =====

async def save_b30_history(
    user_id: str,
    save_rks: float,
    computed_rks: float,
    b30_data: List[dict]
) -> str:
    sb = get_supabase_client()
    data = {
        "user_id": user_id,
        "save_rks": save_rks,
        "computed_rks": computed_rks,
        "b30_data": json.dumps(b30_data)
    }
    res = sb.table("b30_history").insert(data).execute()
    if res.data:
        return res.data[0]["id"]
    else:
        raise Exception("Save b30 history failed")

async def get_b30_history_for_user(user_id: str, limit: int = 100) -> List[Dict[str, Any]]:
    sb = get_supabase_client()
    res = sb.table("b30_history")\
        .select("*")\
        .eq("user_id", user_id)\
        .order("created_at", desc=True)\
        .limit(limit)\
        .execute()
    return res.data

# ===== 排行榜 =====

async def get_leaderboard(limit: int = 100) -> List[Dict[str, Any]]:
    sb = get_supabase_client()
    res = sb.table("leaderboard")\
        .select("*")\
        .order("save_rks", desc=True)\
        .limit(limit)\
        .execute()
    return res.data
