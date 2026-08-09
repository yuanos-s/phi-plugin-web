"""
Supabase REST API 客户端 (基于 httpx)

修复:
  #6  _headers 改为函数调用，不再在模块加载时固定
  #7  updated_at 不再发 "NOW()" 字符串，省略让 DB 默认值处理
"""
import os
import json
import httpx

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_ANON_KEY", "")


def _is_configured() -> bool:
    return bool(SUPABASE_URL and SUPABASE_KEY)


def _get_headers() -> dict:
    """动态构建 headers，确保环境变量生效"""
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


async def _request(method: str, table: str, params: dict = None, body: dict = None) -> list | dict:
    if not _is_configured():
        raise RuntimeError("SUPABASE_URL / SUPABASE_ANON_KEY 未配置")
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    headers = _get_headers()
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.request(method, url, headers=headers, params=params, json=body)
        if r.status_code >= 400:
            raise RuntimeError(f"Supabase {r.status_code}: {r.text[:300]}")
        # 空响应体处理
        if not r.text.strip():
            return []
        return r.json()


# ===== 用户操作 =====

async def upsert_user(taptap_openid: str, player_name: str,
                      session_token: str, is_global: bool) -> dict:
    body = {
        "taptap_openid": taptap_openid,
        "player_name": player_name,
        "session_token": session_token,
        "is_global": is_global,
        # BUG #7: 不发 "NOW()"，让 DB 的 DEFAULT NOW() 处理
    }
    result = await _request("POST", "users",
        params={"on_conflict": "taptap_openid"},
        body=body)
    return result[0] if isinstance(result, list) and result else {}


async def get_user_by_openid(taptap_openid: str) -> dict | None:
    result = await _request("GET", "users",
        params={"taptap_openid": f"eq.{taptap_openid}", "limit": "1"})
    return result[0] if isinstance(result, list) and result else None


async def get_user_by_token(session_token: str) -> dict | None:
    result = await _request("GET", "users",
        params={"session_token": f"eq.{session_token}", "limit": "1"})
    return result[0] if isinstance(result, list) and result else None


async def update_session_token(taptap_openid: str, session_token: str):
    await _request("PATCH", "users",
        params={"taptap_openid": f"eq.{taptap_openid}"},
        body={"session_token": session_token})


# ===== 历史快照 =====

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
