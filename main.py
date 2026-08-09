"""
Phi-Plugin Web — FastAPI 后端 (Supabase 彻底迁移版)

变更:
  - 移除所有 LeanCloud 调用
  - 登录: TapTap → profile → Supabase upsert → 返回 session_token (UUID)
  - 新增 /api/user/upload-archive: 上传存档 ZIP, 解析后存入 Supabase
  - B30/全部成绩/推分: 从 Supabase archives 表读取
  - 自动登录: 验证 Supabase session_token
"""
import uuid
import time
import logging
import httpx
from fastapi import FastAPI, HTTPException, Query, UploadFile, File, Form
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

from taptap import request_qrcode, poll_login, get_profile
from phigros import parse_uploaded_save
from songs import (get_all_songs, get_song, get_difficulty, get_song_name,
                   get_ill_url, calc_rks, rating, compute_suggest, min_up_rks,
                   suggest_acc, LEVELS)

# Supabase
try:
    import db as supabase
    SB_OK = supabase._is_configured()
except Exception:
    SB_OK = False

logger = logging.getLogger("phi-web")
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Phi-Plugin Web", redirect_slashes=False)
_login_sessions: dict = {}
_SESSION_TTL = 300


@app.middleware("http")
async def strip_trailing_slash(request, call_next):
    path = request.url.path
    if path != '/' and path.endswith('/'):
        request.scope['path'] = path.rstrip('/')
    return await call_next(request)


def _cleanup_sessions():
    now = time.time()
    for k in [k for k, v in _login_sessions.items()
              if now - v.get("_ts", 0) > _SESSION_TTL]:
        _login_sessions.pop(k, None)


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


def _compute_b30_and_stats(game_record: dict, summary: dict) -> dict:
    """从 game_record 计算 B30 + 统计数据"""
    all_scores = _build_score_list(game_record)
    b30 = all_scores[:30]
    phi_scores = [s for s in all_scores if s["acc"] >= 100][:3]
    phi_rks = sum(s["rks"] for s in phi_scores)
    com_rks = (sum(s["rks"] for s in b30[:27]) + phi_rks) / 30 if b30 else 0
    total_cleared = sum(summary.get("cleared", [0]*4))
    total_fc = sum(summary.get("full_combo", [0]*4))
    total_phi = sum(summary.get("phi", [0]*4))
    return {
        "b30": b30, "all_scores": all_scores,
        "computed_rks": round(com_rks, 4),
        "total_cleared": total_cleared, "total_fc": total_fc,
        "total_phi": total_phi, "total_records": len(all_scores),
    }


# ===== 页面 =====
@app.get("/")
async def index():
    return FileResponse("static/index.html")


# ===== 登录 =====
@app.post("/api/login/qrcode")
async def api_qrcode(is_global: bool = False):
    _cleanup_sessions()
    try:
        resp = await request_qrcode(is_global)
    except Exception as e:
        logger.exception("request_qrcode failed")
        raise HTTPException(500, f"获取二维码失败: {e}")
    data = resp.get("data", resp)
    sid = str(uuid.uuid4())
    _login_sessions[sid] = {
        "device_code": data.get("device_code", resp.get("device_code", "")),
        "device_id": resp.get("device_id", ""),
        "is_global": is_global,
        "_ts": time.time(),
    }
    return {"session_id": sid, "qr_url": data.get("qrcode_url", ""),
            "expires_in": data.get("expires_in", 300)}


@app.get("/api/login/check")
async def api_check(session_id: str):
    _cleanup_sessions()
    sess = _login_sessions.get(session_id)
    if not sess:
        raise HTTPException(404, "登录会话不存在或已过期")

    try:
        result = await poll_login(sess["device_code"], sess["device_id"], sess["is_global"])
    except Exception as e:
        return {"status": "error", "message": f"轮询异常: {e}"}

    if result["status"] == "waiting":
        return {"status": "waiting"}
    if result["status"] == "scanned":
        return {"status": "scanned"}
    if result["status"] == "expired":
        _login_sessions.pop(session_id, None)
        return {"status": "expired", "message": "二维码已过期"}
    if result["status"] == "error":
        return {"status": "error", "message": result.get("message", "")}

    if result["status"] == "success":
        token = result["token"]
        # 获取 TapTap profile
        try:
            profile = await get_profile(token, sess["is_global"])
        except Exception as e:
            return {"status": "error", "message": f"获取 TapTap 用户信息失败: {e}"}

        profile_data = profile.get("data", profile) if isinstance(profile, dict) else {}
        taptap_openid = (profile_data.get("openid") or profile_data.get("id")
                         or profile_data.get("uid") or "")
        player_name = profile_data.get("name", "")
        avatar_url = profile_data.get("avatar", "")

        if not taptap_openid:
            return {"status": "error", "message": "无法获取 TapTap openid"}

        # Supabase: 创建/更新用户
        session_token = None
        user_id = None
        if SB_OK:
            try:
                user_rec = await supabase.upsert_user(
                    taptap_openid=taptap_openid,
                    player_name=player_name,
                    avatar_url=avatar_url,
                    is_global=sess["is_global"],
                )
                session_token = user_rec.get("session_token")
                user_id = user_rec.get("id")
            except Exception as e:
                logger.warning(f"Supabase upsert failed: {e}")

        if not session_token:
            # 回退: 生成临时 token
            session_token = str(uuid.uuid4())

        _login_sessions.pop(session_id, None)
        return {
            "status": "success",
            "session_token": session_token,
            "is_global": sess["is_global"],
            "player_name": player_name,
            "taptap_openid": taptap_openid,
            "user_id": user_id,
        }

    return {"status": "waiting"}


# ===== 自动登录 =====
@app.get("/api/auth/restore")
async def api_restore(session_token: str):
    if not SB_OK:
        return {"status": "ok", "session_token": session_token,
                "is_global": False, "player_name": ""}

    try:
        user = await supabase.get_user_by_token(session_token)
        if not user:
            return {"status": "not_found", "message": "Token 未找到，请重新扫码"}
        return {
            "status": "ok",
            "session_token": session_token,
            "is_global": user.get("is_global", False),
            "player_name": user.get("player_name", ""),
            "taptap_openid": user.get("taptap_openid", ""),
            "user_id": user.get("id"),
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ===== 上传存档 =====
@app.post("/api/user/upload-archive")
async def api_upload_archive(session_token: str, file: UploadFile = File(...)):
    """接收用户上传的 Phigros 存档 ZIP, 解析后存入 Supabase"""
    if not SB_OK:
        raise HTTPException(500, "Supabase 未配置，无法存储存档")

    # 验证用户
    try:
        user = await supabase.get_user_by_token(session_token)
        if not user:
            raise HTTPException(401, "用户未找到，请重新登录")
        user_id = user["id"]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"用户验证失败: {e}")

    # 读取文件
    zip_data = await file.read()
    if not zip_data:
        raise HTTPException(400, "文件为空")

    # 解析存档
    try:
        parsed = parse_uploaded_save(zip_data)
    except ValueError as e:
        raise HTTPException(400, f"存档解析失败: {e}")
    except Exception as e:
        raise HTTPException(500, f"存档解析异常: {e}")

    game_record = parsed["game_record"]
    summary = parsed["summary"]
    game_user = parsed["game_user"]

    # 计算 B30
    stats = _compute_b30_and_stats(game_record, summary)
    b30 = stats["b30"]
    com_rks = stats["computed_rks"]
    save_rks = summary.get("ranking_score", 0)

    # 存入 Supabase
    try:
        archive_id = await supabase.save_archive(
            user_id=user_id,
            game_record=game_record,
            summary=summary,
            game_user=game_user,
            b30_data=b30,
            save_rks=save_rks,
            computed_rks=com_rks,
            total_songs=len(game_record.get("records", {})),
        )
    except Exception as e:
        raise HTTPException(500, f"存储失败: {e}")

    # 同时存入 b30_history (趋势追踪)
    try:
        await supabase.save_history(user_id, save_rks, com_rks, b30)
    except Exception as e:
        logger.warning(f"历史快照存储失败 (非致命): {e}")

    return {
        "status": "ok",
        "archive_id": archive_id,
        "player": {"nickname": game_user.get("self_intro", "") or user.get("player_name", "")},
        "summary": summary,
        "b30_count": len(b30),
        "save_rks": save_rks,
        "computed_rks": com_rks,
        "total_songs": len(game_record.get("records", {})),
    }


# ===== B30 =====
@app.get("/api/user/b30")
async def api_b30(session_token: str, user_id: str = Query(None)):
    if not SB_OK:
        raise HTTPException(500, "Supabase 未配置")

    try:
        if not user_id:
            user = await supabase.get_user_by_token(session_token)
            if not user:
                raise HTTPException(401, "用户未找到")
            user_id = user["id"]

        archive = await supabase.get_latest_archive(user_id)
        if not archive:
            return {
                "player": {"nickname": "", "player_id": ""},
                "summary": {},
                "b30": [],
                "computed_rks": 0,
                "save_rks": 0,
                "challenge_rank": 0,
                "total_songs": 0,
                "stats": {"cleared": 0, "fc": 0, "phi": 0, "total_records": 0},
                "no_data": True,
                "message": "暂无存档数据，请上传 Phigros 存档文件",
            }

        b30_data = archive.get("b30_data", [])
        summary = archive.get("summary", {})
        if isinstance(summary, str):
            summary = json.loads(summary)

        b30 = b30_data if isinstance(b30_data, list) else []
        save_rks = archive.get("save_rks", 0)
        com_rks = archive.get("computed_rks", 0)

        total_cleared = sum(summary.get("cleared", [0]*4))
        total_fc = sum(summary.get("full_combo", [0]*4))
        total_phi = sum(summary.get("phi", [0]*4))

        return {
            "player": {"nickname": "", "player_id": ""},
            "summary": summary,
            "b30": b30,
            "computed_rks": com_rks,
            "save_rks": save_rks,
            "challenge_rank": summary.get("challenge_mode_rank", 0),
            "total_songs": archive.get("total_songs", 0),
            "stats": {"cleared": total_cleared, "fc": total_fc,
                       "phi": total_phi, "total_records": len(b30)},
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


# ===== 全部成绩 =====
@app.get("/api/user/all-scores")
async def api_all_scores(session_token: str, user_id: str = Query(None)):
    if not SB_OK:
        raise HTTPException(500, "Supabase 未配置")

    try:
        if not user_id:
            user = await supabase.get_user_by_token(session_token)
            if not user:
                raise HTTPException(401, "用户未找到")
            user_id = user["id"]

        archive = await supabase.get_latest_archive(user_id)
        if not archive:
            return {"scores": [], "summary": {},
                    "player": {"nickname": ""}, "no_data": True}

        game_record = archive.get("game_record", {})
        if isinstance(game_record, str):
            game_record = json.loads(game_record)
        summary = archive.get("summary", {})
        if isinstance(summary, str):
            summary = json.loads(summary)

        all_scores = _build_score_list(game_record)
        return {"scores": all_scores, "summary": summary,
                "player": {"nickname": ""}}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


# ===== 推分建议 =====
@app.get("/api/user/suggest")
async def api_suggest(session_token: str, user_id: str = Query(None)):
    if not SB_OK:
        raise HTTPException(500, "Supabase 未配置")

    try:
        if not user_id:
            user = await supabase.get_user_by_token(session_token)
            if not user:
                raise HTTPException(401, "用户未找到")
            user_id = user["id"]

        archive = await supabase.get_latest_archive(user_id)
        if not archive:
            return {"save_rks": 0, "target_rks": 0, "min_up_rks": 0,
                    "suggestions": [], "player": {"nickname": ""}, "no_data": True}

        game_record = archive.get("game_record", {})
        if isinstance(game_record, str):
            game_record = json.loads(game_record)
        summary = archive.get("summary", {})
        if isinstance(summary, str):
            summary = json.loads(summary)

        all_scores = _build_score_list(game_record)
        b30 = all_scores[:30]
        save_rks = summary.get("ranking_score", 0)

        suggestions = compute_suggest(b30, save_rks)
        target_rks = save_rks + min_up_rks(save_rks)

        return {
            "save_rks": save_rks,
            "target_rks": round(target_rks, 4),
            "min_up_rks": round(min_up_rks(save_rks), 4),
            "suggestions": suggestions,
            "player": {"nickname": ""},
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


# ===== 历史 =====
@app.get("/api/user/history")
async def api_history(session_token: str, user_id: str = Query(None)):
    if not SB_OK:
        return {"trend": [], "count": 0}

    try:
        if not user_id:
            user = await supabase.get_user_by_token(session_token)
            if not user:
                return {"trend": [], "count": 0}
            user_id = user["id"]

        history = await supabase.get_history(user_id)
        trend = [{"ts": h.get("created_at", ""),
                  "save_rks": h.get("save_rks", 0),
                  "computed_rks": h.get("computed_rks", 0)}
                 for h in history]
        return {"trend": trend, "count": len(trend)}
    except Exception:
        return {"trend": [], "count": 0}


# ===== 排行榜 =====
@app.get("/api/leaderboard")
async def api_leaderboard(limit: int = 100):
    if not SB_OK:
        return JSONResponse({"leaderboard": [], "note": "Supabase 未配置"})
    try:
        lb = await supabase.get_leaderboard(limit)
        return {"leaderboard": lb}
    except Exception as e:
        return JSONResponse({"leaderboard": [], "error": str(e)})


# ===== 曲目 =====
@app.get("/api/songs")
async def api_songs():
    return get_all_songs()

@app.get("/api/songs/{song_id}")
async def api_song(song_id: str):
    song = get_song(song_id)
    if not song:
        raise HTTPException(404, "曲目不存在")
    return song


# ===== 配置 =====
@app.get("/api/config")
async def api_config():
    return {"supabase_enabled": SB_OK, "leaderboard_available": SB_OK}

app.mount("/static", StaticFiles(directory="static"), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
