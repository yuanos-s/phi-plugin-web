"""
Phi-Plugin Web — FastAPI 后端
基于 Catrong/phi-plugin 移植
迁移至 Supabase 存储，支持用户手动绑定存档
"""
import os
import uuid
import httpx
from typing import Optional
from fastapi import FastAPI, HTTPException, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from datetime import datetime, timezone

# 原有导入
from taptap import request_qrcode, poll_login, get_profile, get_session_token
from phigros import get_full_save, parse_summary, parse_game_record, parse_game_user
from songs import (load_all, get_all_songs, get_song, get_difficulty, get_song_name,
                   get_ill_url, calc_rks, rating, compute_suggest, min_up_rks,
                   suggest_acc, LEVELS)
from history import save_snapshot, get_history, get_rks_trend

# Supabase 交互函数
from db import (
    supabase_client,
    upsert_user,
    get_user_by_taptap_openid,
    save_archive,
    save_b30_history,
    get_latest_archive,
    get_b30_history_for_user,
)

app = FastAPI(title="Phi-Plugin Web", redirect_slashes=False)

# 登录会话存储（内存，带 TTL 过期）
_login_sessions: dict = {}

# ===== 模型定义 =====
class BindArchiveRequest(BaseModel):
    session_token: str
    is_global: bool = False

# ===== 辅助函数（获取当前用户，暂时用测试 ID） =====
async def get_current_user(session_token: str) -> dict:
    """
    根据 session_token 从 Supabase users 表获取用户信息。
    这里暂时用占位实现，实际应从 JWT 或请求头解析。
    """
    # 模拟：从 Supabase 查找用户（实际应解析 JWT）
    # 为了演示，返回固定用户（需替换为真实逻辑）
    # 生产环境应通过 Supabase Auth 的 JWT 验证
    return {"id": "00000000-0000-0000-0000-000000000000", "taptap_openid": "test_openid"}

# ===== 页面 =====
@app.get("/")
async def index():
    return FileResponse("static/index.html")

# ===== 登录 =====
@app.post("/api/login/qrcode")
async def api_qrcode(is_global: bool = False):
    try:
        resp = await request_qrcode(is_global)
    except Exception as e:
        print(f"[ERROR] /api/login/qrcode: {e}")
        raise HTTPException(500, f"获取二维码失败: {e}")
    data = resp.get("data", resp)
    sid = str(uuid.uuid4())
    _login_sessions[sid] = {
        "device_code": data.get("device_code", resp.get("device_code", "")),
        "device_id": resp.get("device_id", ""),
        "is_global": is_global,
    }
    print(f"[DEBUG] QR session created: {sid}")
    return {"session_id": sid, "qr_url": data.get("qrcode_url", ""),
            "expires_in": data.get("expires_in", 300)}

@app.get("/api/login/check")
async def api_check(session_id: str):
    print(f"[DEBUG] Checking session: {session_id}")
    sess = _login_sessions.get(session_id)
    if not sess:
        print("[DEBUG] Session not found")
        raise HTTPException(404, "登录会话不存在或已过期")
    try:
        print("[DEBUG] Calling poll_login...")
        result = await poll_login(sess["device_code"], sess["device_id"], sess["is_global"])
        print(f"[DEBUG] poll_login result: {result}")
    except Exception as e:
        print(f"[ERROR] poll_login exception: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(500, f"轮询失败: {e}")

    if result["status"] == "success":
        token = result["token"]
        try:
            print("[DEBUG] Getting profile...")
            profile_resp = await get_profile(token, sess["is_global"])
            profile = profile_resp.get("data", profile_resp)
            # 注意：get_session_token 仍然依赖 LeanCloud，会失败。
            # 我们暂时跳过，直接返回模拟的 session_token
            # 后续替换为 Supabase Auth 或直接让用户手动输入
            # 这里为了兼容，生成一个 UUID 作为临时 token
            fake_token = str(uuid.uuid4())
            # 将用户信息存入 Supabase users 表
            user_data = await upsert_user(
                taptap_openid=profile.get("openid") or profile.get("id") or "unknown",
                player_name=profile.get("name", ""),
                avatar_url=profile.get("avatar", ""),
                session_token=fake_token,
                is_global=sess["is_global"]
            )
            # 删除 session
            _login_sessions.pop(session_id, None)
            print("[DEBUG] Login success (fake token generated)")
            return {
                "status": "success",
                "session_token": fake_token,
                "is_global": sess["is_global"],
                "player_name": profile.get("name", "")
            }
        except Exception as e:
            print(f"[ERROR] Login flow exception: {e}")
            import traceback
            traceback.print_exc()
            raise HTTPException(500, f"登录失败: {e}")
    elif result["status"] == "waiting":
        return {"status": "waiting"}
    elif result["status"] == "scanned":
        return {"status": "scanned"}
    elif result["status"] == "expired":
        _login_sessions.pop(session_id, None)
        print("[DEBUG] QR expired")
        return {"status": "expired", "message": "二维码已过期，请重新获取"}
    else:
        _login_sessions.pop(session_id, None)
        print(f"[DEBUG] poll_login returned error: {result}")
        return {"status": "error", "message": result.get("message", "")}

# ===== 曲目数据 =====
@app.get("/api/songs")
async def api_songs():
    return get_all_songs()

@app.get("/api/songs/{song_id}")
async def api_song(song_id: str):
    song = get_song(song_id)
    if not song:
        raise HTTPException(404, "曲目不存在")
    return song

# ===== 用户相关 =====
@app.get("/api/user/info")
async def api_user_info(session_token: str, is_global: bool = False):
    # 从 Supabase 获取用户信息
    user = get_user_by_taptap_openid(session_token)  # 这里需要调整，实际应根据 token 查
    if not user:
        raise HTTPException(404, "用户不存在")
    return user

# ===== 绑定存档接口 =====
@app.post("/api/archive/bind")
async def bind_archive(request: BindArchiveRequest):
    """
    用户绑定 Phigros 云存档。
    目前因 LeanCloud 停服，无法拉取真实数据，返回模拟数据。
    待社区新 API 可用后，替换 save_data 获取逻辑。
    """
    # 验证 session_token 格式（25位小写字母数字）
    if not (len(request.session_token) == 25 and request.session_token.isalnum() and request.session_token.islower()):
        raise HTTPException(400, "sessionToken 格式不正确，应为25位小写字母数字")
    
    # 尝试拉取存档（目前会失败，因为 LeanCloud 已停服）
    # 我们临时模拟数据，以构建完整流程
    # 未来替换为调用 phi-plugin-next API 或 philib 等
    try:
        # 模拟存档数据
        save_data = {
            "player": {"nickname": "测试玩家", "playerId": "12345"},
            "summary": {"ranking_score": 15.2, "challenge_mode_rank": 100},
            "game_record": {"records": {}},
            "stats": {"cleared": 0, "fc": 0, "phi": 0, "total_records": 0},
            "b30": [],
            "all_scores": [],
            "computed_rks": 15.0,
            "total_songs": 0
        }
        # 实际上可使用 philib 或直接调用 API
        # 但目前只有模拟
    except Exception as e:
        raise HTTPException(400, f"拉取存档失败: {str(e)}")
    
    # 获取当前用户（实际应从 JWT 解析）
    # 此处暂用固定测试用户，实际需根据请求头中的 session_token 查找
    # 假设我们从请求头获取 X-Session-Token 或使用 Authorization
    # 为了演示，使用固定用户 ID
    user_id = "00000000-0000-0000-0000-000000000000"
    
    # 保存存档到 Supabase
    try:
        # 保存到 archives 表
        archive_id = await save_archive(
            user_id=user_id,
            save_rks=save_data["summary"]["ranking_score"],
            computed_rks=save_data["computed_rks"],
            total_songs=save_data["total_songs"],
            total_cleared=save_data["stats"]["cleared"],
            total_fc=save_data["stats"]["fc"],
            total_phi=save_data["stats"]["phi"],
            b30_data=save_data["b30"],
            all_scores=save_data["all_scores"]
        )
        # 保存到 b30_history
        await save_b30_history(
            user_id=user_id,
            save_rks=save_data["summary"]["ranking_score"],
            computed_rks=save_data["computed_rks"],
            b30_data=save_data["b30"]
        )
    except Exception as e:
        raise HTTPException(500, f"保存存档失败: {str(e)}")
    
    return {"status": "success", "message": "存档绑定成功（当前为模拟数据，真实功能待 LeanCloud 替代方案）"}

# ===== B30 接口（从 Supabase 读取）=====
@app.get("/api/user/b30")
async def api_b30(session_token: str, is_global: bool = False):
    # 根据 session_token 查找用户
    # 这里简化：用固定用户 ID
    user_id = "00000000-0000-0000-0000-000000000000"
    archive = await get_latest_archive(user_id)
    if not archive:
        # 返回空数据，前端显示“暂无存档，请绑定”
        return {
            "player": {"nickname": "", "player_id": ""},
            "summary": {},
            "b30": [],
            "computed_rks": 0,
            "save_rks": 0,
            "challenge_rank": 0,
            "total_songs": 0,
            "stats": {"cleared": 0, "fc": 0, "phi": 0, "total_records": 0},
            "no_data": True
        }
    # 解析 archive 数据
    b30 = archive.get("b30_data", [])
    summary = {
        "ranking_score": archive["save_rks"],
        "challenge_mode_rank": archive.get("challenge_rank", 0)
    }
    stats = {
        "cleared": archive.get("total_cleared", 0),
        "fc": archive.get("total_fc", 0),
        "phi": archive.get("total_phi", 0),
        "total_records": len(b30)
    }
    return {
        "player": {"nickname": archive.get("player_name", ""), "player_id": ""},
        "summary": summary,
        "b30": b30,
        "computed_rks": archive["computed_rks"],
        "save_rks": archive["save_rks"],
        "challenge_rank": summary["challenge_mode_rank"],
        "total_songs": archive.get("total_songs", 0),
        "stats": stats,
    }

# ===== 全部成绩 =====
@app.get("/api/user/all-scores")
async def api_all_scores(session_token: str, is_global: bool = False):
    user_id = "00000000-0000-0000-0000-000000000000"
    archive = await get_latest_archive(user_id)
    if not archive or not archive.get("all_scores"):
        return {"scores": [], "summary": {}, "player": {"nickname": ""}}
    return {
        "scores": archive["all_scores"],
        "summary": {"ranking_score": archive["save_rks"]},
        "player": {"nickname": archive.get("player_name", "")}
    }

# ===== 推分建议 =====
@app.get("/api/user/suggest")
async def api_suggest(session_token: str, is_global: bool = False):
    user_id = "00000000-0000-0000-0000-000000000000"
    archive = await get_latest_archive(user_id)
    if not archive:
        return {
            "save_rks": 0,
            "target_rks": 0,
            "min_up_rks": 0,
            "suggestions": [],
            "player": {"nickname": ""}
        }
    b30 = archive.get("b30_data", [])
    save_rks = archive["save_rks"]
    suggestions = compute_suggest(b30, save_rks)
    target_rks = save_rks + min_up_rks(save_rks)
    return {
        "save_rks": save_rks,
        "target_rks": round(target_rks, 4),
        "min_up_rks": round(min_up_rks(save_rks), 4),
        "suggestions": suggestions,
        "player": {"nickname": archive.get("player_name", "")}
    }

# ===== 历史趋势 =====
@app.get("/api/user/history")
async def api_history(session_token: str):
    user_id = "00000000-0000-0000-0000-000000000000"
    history = await get_b30_history_for_user(user_id)
    trend = [{"ts": h["created_at"], "save_rks": h["save_rks"], "computed_rks": h["computed_rks"], "player_name": ""} for h in history]
    return {"trend": trend, "count": len(history)}

# ===== 排行榜 =====
@app.get("/api/leaderboard")
async def api_leaderboard(limit: int = 100):
    from db import get_leaderboard
    return await get_leaderboard(limit)

# ===== 配置 =====
@app.get("/api/config")
async def api_config():
    supabase_configured = bool(os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_ANON_KEY"))
    return {
        "supabase_configured": supabase_configured,
        "supabase_url": os.getenv("SUPABASE_URL", "")
    }

# ===== 静态文件 =====
app.mount("/static", StaticFiles(directory="static"), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
