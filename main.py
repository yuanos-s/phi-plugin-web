"""
Phi-Plugin Web — FastAPI 后端
基于 Catrong/phi-plugin 移植 + Supabase 持久化

新增 Supabase 集成:
  - 登录成功后自动持久化 sessionToken 到 Supabase
  - 前端可通过缓存的 sessionToken 自动登录（免重新扫码）
  - B30 历快照存入 Supabase 数据库
  - 排行榜 API
  - 未配置 Supabase 时自动回退到本地存储
"""
import uuid
import logging
import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from typing import Optional

from taptap import request_qrcode, poll_login, get_profile, get_session_token
from phigros import get_full_save, parse_summary, parse_game_record, parse_game_user
from songs import (load_all, get_all_songs, get_song, get_difficulty, get_song_name,
                   get_ill_url, calc_rks, rating, compute_suggest, min_up_rks,
                   suggest_acc, LEVELS)
from history import save_snapshot, get_history_async, get_rks_trend

# Supabase 客户端（可选）
try:
    import db as supabase
    SB_OK = supabase._is_configured()
except Exception:
    SB_OK = False

logger = logging.getLogger("phi-web")
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Phi-Plugin Web")
_login_sessions: dict = {}

# ===== 页面 =====
@app.get("/")
async def index():
    return FileResponse("static/index.html")


# ===== 登录 =====
@app.post("/api/login/qrcode")
async def api_qrcode(is_global: bool = False):
    try:
        resp = await request_qrcode(is_global)
    except httpx.HTTPStatusError as e:
        raise HTTPException(502, f"TapTap API 错误: {e.response.status_code}")
    except Exception as e:
        logger.exception("request_qrcode failed")
        raise HTTPException(500, f"获取二维码失败: {e}")
    data = resp.get("data", resp)
    sid = str(uuid.uuid4())
    _login_sessions[sid] = {
        "device_code": data.get("device_code", resp.get("device_code", "")),
        "device_id": resp.get("device_id", ""),
        "is_global": is_global,
    }
    return {"session_id": sid, "qr_url": data.get("qrcode_url", ""),
            "expires_in": data.get("expires_in", 300)}


@app.get("/api/login/check")
async def api_check(session_id: str):
    sess = _login_sessions.get(session_id)
    if not sess:
        raise HTTPException(404, "登录会话不存在或已过期，请重新获取二维码")

    try:
        result = await poll_login(sess["device_code"], sess["device_id"], sess["is_global"])
    except httpx.HTTPStatusError as e:
        return {"status": "error", "message": f"TapTap HTTP {e.response.status_code}"}
    except httpx.RequestError:
        return {"status": "waiting", "message": "网络超时，正在重试..."}
    except Exception as e:
        logger.exception("poll_login error")
        return {"status": "error", "message": f"轮询异常: {e}"}

    if result["status"] == "waiting":
        return {"status": "waiting"}
    if result["status"] == "scanned":
        return {"status": "scanned"}
    if result["status"] == "expired":
        del _login_sessions[session_id]
        return {"status": "expired", "message": "二维码已过期"}
    if result["status"] == "error":
        return {"status": "error", "message": result.get("message", "")}

    # 成功 → 获取 profile + sessionToken
    if result["status"] == "success":
        token = result["token"]
        # 3a: TapTap profile
        try:
            profile = await get_profile(token, sess["is_global"])
        except Exception as e:
            logger.exception("get_profile failed")
            return {"status": "error", "message": f"获取 TapTap 用户信息失败: {e}"}

        # 3b: LeanCloud sessionToken
        try:
            lc_resp = await get_session_token(profile, token, sess["is_global"])
        except RuntimeError as e:
            return {"status": "error", "message": f"LeanCloud 登录失败: {e}"}
        except Exception as e:
            logger.exception("get_session_token failed")
            return {"status": "error", "message": f"获取 sessionToken 异常: {e}"}

        st = lc_resp.get("sessionToken", "")
        if not st:
            return {"status": "error", "message": f"LeanCloud 未返回 sessionToken: {lc_resp}"}

        del _login_sessions[session_id]
        profile_data = profile.get("data", profile) if isinstance(profile, dict) else {}

        # 3c: 持久化到 Supabase（如果已配置）
        user_id = None
        taptap_openid = profile_data.get("openid") or profile_data.get("id") or profile_data.get("uid") or ""
        if SB_OK and taptap_openid:
            try:
                user_rec = await supabase.upsert_user(
                    taptap_openid=taptap_openid,
                    player_name=profile_data.get("name", ""),
                    session_token=st,
                    is_global=sess["is_global"],
                )
                user_id = user_rec.get("id")
            except Exception as e:
                logger.warning(f"Supabase upsert failed (非致命): {e}")

        return {
            "status": "success",
            "session_token": st,
            "is_global": sess["is_global"],
            "player_name": profile_data.get("name", ""),
            "taptap_openid": taptap_openid,
            "user_id": user_id,
        }

    return {"status": "waiting"}


# ===== 自动登录（检查已保存的 sessionToken）=====
@app.get("/api/auth/restore")
async def api_restore(session_token: str):
    """
    前端用缓存的 sessionToken 尝试自动登录
    如果 Supabase 已配置且 token 有效，返回用户信息
    """
    if not SB_OK:
        # 未配置 Supabase，直接返回 token 让前端用
        return {"status": "ok", "session_token": session_token,
                "is_global": False, "player_name": ""}

    try:
        user = await supabase.get_user_by_token(session_token)
        if not user:
            return {"status": "not_found", "message": "Token 未找到，请重新扫码"}

        # 尝试验证 token 是否仍然有效
        from phigros import lc_get_player_info
        try:
            player = await lc_get_player_info(session_token, user.get("is_global", False))
            return {
                "status": "ok",
                "session_token": session_token,
                "is_global": user.get("is_global", False),
                "player_name": player.get("nickname", user.get("player_name", "")),
                "taptap_openid": user.get("taptap_openid", ""),
                "user_id": user.get("id"),
            }
        except httpx.HTTPStatusError:
            # Token 已失效
            return {"status": "expired", "message": "Token 已失效，请重新扫码"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ===== 排行榜 =====
@app.get("/api/leaderboard")
async def api_leaderboard(limit: int = 100):
    if not SB_OK:
        return JSONResponse({"leaderboard": [], "note": "Supabase 未配置，排行榜不可用"})
    try:
        lb = await supabase.get_leaderboard(limit)
        return {"leaderboard": lb}
    except Exception as e:
        return JSONResponse({"leaderboard": [], "error": str(e)})


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


# ===== 玩家数据 =====
@app.get("/api/user/info")
async def api_user_info(session_token: str, is_global: bool = False):
    from phigros import lc_get_player_info
    try:
        return await lc_get_player_info(session_token, is_global)
    except httpx.HTTPStatusError as e:
        raise HTTPException(e.response.status_code, e.response.text)
    except Exception as e:
        raise HTTPException(500, str(e))


def _build_score_list(game_record: dict) -> list:
    all_scores = []
    for song_id, levels in game_record.get("records", {}).items():
        for lv_idx, rec in enumerate(levels):
            if lv_idx >= 4 or rec is None:
                continue
            diff = get_difficulty(song_id, lv_idx)
            rks = calc_rks(rec["acc"], diff)
            all_scores.append({
                "song_id": song_id, "song": get_song_name(song_id),
                "level": LEVELS[lv_idx], "level_idx": lv_idx,
                "score": rec["score"], "acc": rec["acc"], "fc": rec["fc"],
                "difficulty": diff, "rks": round(rks, 4),
                "rating": rating(rec["score"], rec["fc"]),
                "illustration": get_ill_url(song_id),
            })
    all_scores.sort(key=lambda x: x["rks"], reverse=True)
    return all_scores


# 提取 user_id 的辅助函数
def _get_user_id(session_token: str, is_global: bool = False) -> str | None:
    if not SB_OK:
        return None
    # user_id 从前端传入或在 B30 流程中获取
    return None


@app.get("/api/user/b30")
async def api_b30(session_token: str, is_global: bool = False,
                  user_id: str = Query(None)):
    try:
        save = await get_full_save(session_token, is_global)
    except httpx.HTTPStatusError as e:
        raise HTTPException(e.response.status_code, e.response.text)
    except Exception as e:
        raise HTTPException(500, str(e))

    all_scores = _build_score_list(save["game_record"])
    b30 = all_scores[:30]
    summary = save.get("summary", {})
    player = save.get("player", {})

    phi_scores = [s for s in all_scores if s["acc"] >= 100][:3]
    phi_rks = sum(s["rks"] for s in phi_scores)
    com_rks = (sum(s["rks"] for s in b30[:27]) + phi_rks) / 30 if b30 else 0

    # 保存历史快照（优先 Supabase）
    try:
        await save_snapshot(
            session_token, player.get("nickname", ""), b30,
            summary.get("ranking_score", 0), round(com_rks, 4),
            user_id=user_id,
        )
    except Exception as e:
        logger.warning(f"保存历史失败 (非致命): {e}")

    total_cleared = sum(summary.get("cleared", [0]*4))
    total_fc = sum(summary.get("full_combo", [0]*4))
    total_phi = sum(summary.get("phi", [0]*4))

    return {
        "player": {"nickname": player.get("nickname", ""),
                    "player_id": player.get("playerId", "")},
        "summary": summary,
        "b30": b30,
        "computed_rks": round(com_rks, 4),
        "save_rks": summary.get("ranking_score", 0),
        "challenge_rank": summary.get("challenge_mode_rank", 0),
        "total_songs": len(save.get("game_record", {}).get("records", {})),
        "stats": {"cleared": total_cleared, "fc": total_fc, "phi": total_phi,
                   "total_records": len(all_scores)},
    }


@app.get("/api/user/all-scores")
async def api_all_scores(session_token: str, is_global: bool = False):
    try:
        save = await get_full_save(session_token, is_global)
    except httpx.HTTPStatusError as e:
        raise HTTPException(e.response.status_code, e.response.text)
    except Exception as e:
        raise HTTPException(500, str(e))

    all_scores = _build_score_list(save["game_record"])
    summary = save.get("summary", {})
    return {"scores": all_scores, "summary": summary,
            "player": {"nickname": save.get("player", {}).get("nickname", "")}}


@app.get("/api/user/suggest")
async def api_suggest(session_token: str, is_global: bool = False):
    try:
        save = await get_full_save(session_token, is_global)
    except httpx.HTTPStatusError as e:
        raise HTTPException(e.response.status_code, e.response.text)
    except Exception as e:
        raise HTTPException(500, str(e))

    all_scores = _build_score_list(save["game_record"])
    b30 = all_scores[:30]
    save_rks = save.get("summary", {}).get("ranking_score", 0)

    suggestions = compute_suggest(b30, save_rks)
    target_rks = save_rks + min_up_rks(save_rks)

    return {
        "save_rks": save_rks,
        "target_rks": round(target_rks, 4),
        "min_up_rks": round(min_up_rks(save_rks), 4),
        "suggestions": suggestions,
        "player": {"nickname": save.get("player", {}).get("nickname", "")},
    }


@app.get("/api/user/history")
async def api_history(session_token: str, user_id: str = Query(None)):
    # 优先 Supabase
    if SB_OK and user_id:
        try:
            history = await get_history_async(session_token, user_id)
            if history:
                trend = [{"ts": h.get("created_at",""), "save_rks": h.get("save_rks",0),
                          "computed_rks": h.get("computed_rks",0)}
                         for h in history]
                return {"trend": trend, "count": len(history)}
        except Exception as e:
            logger.warning(f"Supabase history failed: {e}")

    # 回退本地
    trend = get_rks_trend(session_token)
    return {"trend": trend, "count": len(trend)}


# ===== 配置信息 =====
@app.get("/api/config")
async def api_config():
    """返回前端需要的配置信息"""
    return {
        "supabase_enabled": SB_OK,
        "leaderboard_available": SB_OK,
    }


# 静态文件
app.mount("/static", StaticFiles(directory="static"), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
