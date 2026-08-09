"""
Phi-Plugin Web — FastAPI 后端
基于 Catrong/phi-plugin 移植

修复：
1. /api/login/check 500 错误：所有异常捕获并返回明确信息
2. session 不在错误时删除（只在成功/过期时删除）
3. 详细错误信息返回前端
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
from history import save_snapshot, get_history, get_rks_trend

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
        raise HTTPException(502, f"TapTap API 错误: {e.response.status_code} {e.response.text[:200]}")
    except Exception as e:
        logger.exception("request_qrcode failed")
        raise HTTPException(500, f"获取二维码失败: {e}")
    data = resp.get("data", resp)
    sid = str(uuid.uuid4())
    _login_sessions[sid] = {
        "device_code": data.get("device_code", resp.get("device_code", "")),
        "device_id": resp.get("device_id", ""),
        "is_global": is_global,
        "created_at": __import__("time").time(),
    }
    return {"session_id": sid, "qr_url": data.get("qrcode_url", ""),
            "expires_in": data.get("expires_in", 300)}


@app.get("/api/login/check")
async def api_check(session_id: str):
    sess = _login_sessions.get(session_id)
    if not sess:
        raise HTTPException(404, "登录会话不存在或已过期，请重新获取二维码")

    # Step 1: 轮询 TapTap 登录状态
    try:
        result = await poll_login(sess["device_code"], sess["device_id"], sess["is_global"])
    except httpx.HTTPStatusError as e:
        # TapTap 返回了 HTTP 错误（非 200）
        return {"status": "error",
                "message": f"TapTap 返回 HTTP {e.response.status_code}"}
    except httpx.RequestError as e:
        # 网络超时等，不删 session，让前端继续重试
        return {"status": "waiting", "message": "网络超时，正在重试..."}
    except Exception as e:
        logger.exception("poll_login unexpected error")
        return {"status": "error", "message": f"轮询异常: {e}"}

    # Step 2: 根据状态处理
    if result["status"] == "waiting":
        return {"status": "waiting"}
    if result["status"] == "scanned":
        return {"status": "scanned"}
    if result["status"] == "expired":
        del _login_sessions[session_id]
        return {"status": "expired", "message": "二维码已过期，请重新获取"}
    if result["status"] == "error":
        # 不删 session，给用户重试机会
        return {"status": "error", "message": result.get("message", "未知错误")}

    # Step 3: 登录成功，获取 profile + sessionToken
    # 关键修复：错误时 NOT 删除 session，返回明确错误让前端可以重试
    if result["status"] == "success":
        token = result["token"]
        errors = []

        # 3a: 获取 TapTap profile
        profile = None
        try:
            profile = await get_profile(token, sess["is_global"])
        except httpx.RequestError as e:
            return {"status": "error",
                    "message": f"获取 TapTap 用户信息失败（网络错误）: {e}"}
        except Exception as e:
            logger.exception("get_profile failed")
            return {"status": "error",
                    "message": f"获取 TapTap 用户信息失败: {e}"}

        # 3b: 用 profile + token 登录 LeanCloud 获取 sessionToken
        try:
            lc_resp = await get_session_token(profile, token, sess["is_global"])
        except RuntimeError as e:
            return {"status": "error",
                    "message": f"LeanCloud 登录失败: {e}"}
        except httpx.RequestError as e:
            return {"status": "error",
                    "message": f"LeanCloud 网络错误: {e}"}
        except Exception as e:
            logger.exception("get_session_token failed")
            return {"status": "error",
                    "message": f"获取 sessionToken 异常: {e}"}

        # 3c: 成功！
        st = lc_resp.get("sessionToken", "")
        if not st:
            return {"status": "error",
                    "message": f"LeanCloud 未返回 sessionToken: {lc_resp}"}

        del _login_sessions[session_id]
        profile_data = profile.get("data", profile) if isinstance(profile, dict) else {}
        return {
            "status": "success",
            "session_token": st,
            "is_global": sess["is_global"],
            "player_name": profile_data.get("name", ""),
        }

    return {"status": "waiting"}


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


@app.get("/api/user/b30")
async def api_b30(session_token: str, is_global: bool = False):
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

    save_snapshot(session_token, player.get("nickname", ""), b30,
                  summary.get("ranking_score", 0), round(com_rks, 4))

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
async def api_history(session_token: str):
    trend = get_rks_trend(session_token)
    history = get_history(session_token)
    return {"trend": trend, "count": len(history)}


# 静态文件
app.mount("/static", StaticFiles(directory="static"), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
