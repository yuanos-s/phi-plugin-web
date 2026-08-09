"""
Supabase REST API 客户端 (彻底迁移版)

变更:
  - 移除 LeanCloud 相关
  - 新增 archives 表操作 (存档上传后存储)
  - 用户 upsert 返回 session_token (UUID)
  - 支持 SERVICE_KEY (admin 操作)
"""
import os
import json
import uuid
import httpx

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")


def _is_configured() -> bool:
    return bool(SUPABASE_URL and SUPABASE_ANON_KEY)


def _get_key() -> str:
    """优先用 service_key, 否则用 anon_key"""
    return SUPABASE_SERVICE_KEY or SUPABASE_ANON_KEY


def _get_headers() -> dict:
    key = _get_key()
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


async def _request(method, table, params=None, body=None):
    if not _is_configured():
        raise RuntimeError("SUPABASE_URL / SUPABASE_ANON_KEY 未配置")
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    headers = _get_headers()
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.request(method, url, headers=headers, params=params, json=body)
        if r.status_code >= 400:
            raise RuntimeError(f"Supabase {r.status_code}: {r.text[:300]}")
        if not r.text.strip():
            return []
        return r.json()


# ===== 用户操作 =====

async def upsert_user(taptap_openid: str, player_name: str,
                      avatar_url: str = "", is_global: bool = False) -> dict:
    """创建或更新用户，返回 {id, session_token}"""
    # 先查是否已存在
    existing = await get_user_by_openid(taptap_openid)
    if existing:
        # 更新名字/头像
        await _request("PATCH", "users",
            params={"taptap_openid": f"eq.{taptap_openid}"},
            body={"player_name": player_name, "avatar_url": avatar_url,
                  "is_global": is_global})
        return existing

    # 新建：生成 session_token (UUID)
    session_token = str(uuid.uuid4())
    body = {
        "taptap_openid": taptap_openid,
        "player_name": player_name,
        "avatar_url": avatar_url,
        "session_token": session_token,
        "is_global": is_global,
    }
    result = await _request("POST", "users", body=body)
    return result[0] if isinstance(result, list) and result else {
        "id": None, "session_token": session_token
    }


async def get_user_by_openid(taptap_openid: str) -> dict | None:
    result = await _request("GET", "users",
        params={"taptap_openid": f"eq.{taptap_openid}", "limit": "1"})
    return result[0] if isinstance(result, list) and result else None


async def get_user_by_token(session_token: str) -> dict | None:
    result = await _request("GET", "users",
        params={"session_token": f"eq.{session_token}", "limit": "1"})
    return result[0] if isinstance(result, list) and result else None


# ===== 存档操作 =====

async def save_archive(user_id: str, game_record: dict, summary: dict,
                       game_user: dict, b30_data: list,
                       save_rks: float, computed_rks: float,
                       total_songs: int) -> str:
    """保存存档解析结果，返回 archive id"""
    body = {
        "user_id": user_id,
        "game_record": json.dumps(game_record),
        "summary": json.dumps(summary),
        "game_user": json.dumps(game_user),
        "b30_data": json.dumps(b30_data),
        "save_rks": save_rks,
        "computed_rks": computed_rks,
        "total_songs": total_songs,
    }
    result = await _request("POST", "archives", body=body)
    return result[0].get("id") if isinstance(result, list) and result else None


async def get_latest_archive(user_id: str) -> dict | None:
    """获取用户最新存档"""
    result = await _request("GET", "archives",
        params={"user_id": f"eq.{user_id}",
                "order": "created_at.desc",
                "limit": "1"})
    return result[0] if isinstance(result, list) and result else None


async def get_all_archives(user_id: str, limit: int = 50) -> list:
    """获取用户所有存档"""
    result = await _request("GET", "archives",
        params={"user_id": f"eq.{user_id}",
                "order": "created_at.desc",
                "limit": str(limit)})
    return result if isinstance(result, list) else []


# ===== B30 历史快照 =====

async def save_history(user_id: str, save_rks: float, computed_rks: float, b30_data: list):
    body = {
        "user_id": user_id,
        "save_rks": save_rks,
        "computed_rks": computed_rks,
        "b30_data": json.dumps(b30_data),
    }
    await _request("POST", "b30_history", body=body)


async def get_history(user_id: str, limit: int = 50) -> list:
    result = await _request("GET", "b30_history",
        params={"user_id": f"eq.{user_id}",
                "order": "created_at.desc",
                "limit": str(limit)})
    return result if isinstance(result, list) else []


# ===== 排行榜 =====

async def get_leaderboard(limit: int = 100) -> list:
    if not _is_configured():
        return []
    result = await _request("GET", "leaderboard",
        params={"order": "save_rks.desc", "limit": str(limit)})
    return result if isinstance(result, list) else []
