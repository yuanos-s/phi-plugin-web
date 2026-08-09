"""
历史成绩记录 — Supabase 版本
优先使用 Supabase，未配置时回退到本地 JSON

修复:
  #5  db 导入失败不再崩溃整个模块，_sb_ready 安全回退
"""
import json
from pathlib import Path
from datetime import datetime

HISTORY_DIR = Path(__file__).parent / "history"

# 安全导入 Supabase 客户端
_sb_ready = False
try:
    from db import _is_configured as _sb_check
    _sb_ready = True
except Exception:
    _sb_check = None


def _sb_is_ready() -> bool:
    if not _sb_ready or _sb_check is None:
        return False
    try:
        return _sb_check()
    except Exception:
        return False


def _local_save(session_token: str, player_name: str, b30: list, rks: float, computed_rks: float):
    HISTORY_DIR.mkdir(exist_ok=True)
    safe_key = session_token[:8] if len(session_token) >= 8 else "unknown"
    filepath = HISTORY_DIR / f"{safe_key}.json"
    snapshot = {
        "ts": datetime.now().isoformat(),
        "player_name": player_name,
        "save_rks": rks, "computed_rks": computed_rks,
        "b30": [{"song": s["song"], "song_id": s.get("song_id",""),
                 "level": s["level"], "score": s["score"],
                 "acc": s["acc"], "rks": s["rks"],
                 "fc": s["fc"], "difficulty": s["difficulty"]}
                for s in b30],
    }
    history = []
    if filepath.exists():
        try:
            with open(filepath, encoding="utf-8") as f:
                history = json.load(f)
        except Exception:
            history = []
    history.append(snapshot)
    if len(history) > 100:
        history = history[-100:]
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def _local_get(session_token: str) -> list:
    safe_key = session_token[:8] if len(session_token) >= 8 else "unknown"
    filepath = HISTORY_DIR / f"{safe_key}.json"
    if not filepath.exists():
        return []
    try:
        with open(filepath, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _local_trend(session_token: str) -> list:
    history = _local_get(session_token)
    return [{"ts": h["ts"], "save_rks": h["save_rks"],
             "computed_rks": h["computed_rks"], "player_name": h["player_name"]}
            for h in history]


# ===== 统一接口 =====

async def save_snapshot(session_token: str, player_name: str, b30: list,
                        rks: float, computed_rks: float, user_id: str = None):
    if _sb_is_ready() and user_id:
        try:
            import db
            b30_data = [{"song": s["song"], "song_id": s.get("song_id",""),
                         "level": s["level"], "score": s["score"],
                         "acc": s["acc"], "rks": s["rks"],
                         "fc": s["fc"], "difficulty": s["difficulty"]}
                        for s in b30]
            await db.save_history(user_id, rks, computed_rks, b30_data)
            return
        except Exception:
            pass
    _local_save(session_token, player_name, b30, rks, computed_rks)


async def get_history_async(session_token: str, user_id: str = None) -> list:
    if _sb_is_ready() and user_id:
        try:
            import db
            return await db.get_history(user_id)
        except Exception:
            pass
    return _local_get(session_token)


def get_rks_trend(session_token: str, user_id: str = None) -> list:
    history = _local_get(session_token)
    return [{"ts": h["ts"], "save_rks": h["save_rks"],
             "computed_rks": h["computed_rks"], "player_name": h["player_name"]}
            for h in history]
