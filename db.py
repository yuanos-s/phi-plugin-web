"""
Supabase REST API 客户端 (基于 httpx，不依赖 supabase-py)

环境变量:
  SUPABASE_URL       — 如 https://xxx.supabase.co
  SUPABASE_ANON_KEY  — Supabase 公共 anon key

功能:
  - 用户持久化 (存 sessionToken，免重复扫码)
  - B30 历史快照存储
  - 排行榜查询
"""
import os
import json
import httpx

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_ANON_KEY", "")

_headers = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation",
}


def _is_configured() -> bool:
    return bool(SUPABASE_URL and SUPABASE_KEY)


async def _request(method: str, table: str, params: dict = None, body: dict = None) -> list | dict:
    """调用 Supabase PostgREST API"""
    if not _is_configured():
        raise RuntimeError("SUPABASE_URL / SUPABASE_ANON_KEY 未配置")
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.request(method, url, headers=_headers,
                            params=params, json=body)
        if r.status_code >= 400:
            raise RuntimeError(f"Supabase {r.status_code}: {r.text[:300]}")
        data = r.json()
        return data


# ===== 用户操作 =====

async def upsert_user(taptap_openid: str, player_name: str,
                      session_token: str, is_global: bool) -> dict:
    """创建或更新用户，返回用户记录"""
    body = {
        "taptap_openid": taptap_openid,
        "player_name": player_name,
        "session_token": session_token,
        "is_global": is_global,
        "updated_at": "NOW()",
    }
    # upsert: on conflict update
    result = await _request("POST", "users",
        params={"on_conflict": "taptap_openid"},
        body=body)
    return result[0] if isinstance(result, list) and result else (result if isinstance(result, dict) else {})


async def get_user_by_openid(taptap_openid: str) -> dict | None:
    """通过 TapTap openid 查找用户（用于自动登录）"""
    result = await _request("GET", "users",
        params={"taptap_openid": f"eq.{taptap_openid}", "limit": "1"})
    return result[0] if isinstance(result, list) and result else None


async def get_user_by_token(session_token: str) -> dict | None:
    """通过 sessionToken 查找用户（前端自动登录）"""
    result = await _request("GET", "users",
        params={"session_token": f"eq.{session_token}", "limit": "1"})
    return result[0] if isinstance(result, list) and result else None


async def update_session_token(taptap_openid: str, session_token: str):
    """更新 sessionToken（重新扫码后）"""
    await _request("PATCH", "users",
        params={"taptap_openid": f"eq.{taptap_openid}"},
        body={"session_token": session_token, "updated_at": "NOW()"})


# ===== 历史快照 =====

async def save_history(user_id: str, save_rks: float, computed_rks: float, b30_data: list):
    """保存 B30 快照"""
    body = {
        "user_id": user_id,
        "save_rks": save_rks,
        "computed_rks": computed_rks,
        "b30_data": json.dumps(b30_data),  # PostgREST 需要 JSON 字符串
    }
    await _request("POST", "b30_history", body=body)


async def get_history(user_id: str, limit: int = 50) -> list:
    """获取历史列表"""
    result = await _request("GET", "b30_history",
        params={"user_id": f"eq.{user_id}",
                "order": "created_at.desc",
                "limit": str(limit)})
    return result if isinstance(result, list) else []


# ===== 排行榜 =====

async def get_leaderboard(limit: int = 100) -> list:
    """获取 RKS 排行榜"""
    if not _is_configured():
        return []
    result = await _request("GET", "leaderboard",
        params={"order": "save_rks.desc", "limit": str(limit)})
    return result if isinstance(result, list) else []
