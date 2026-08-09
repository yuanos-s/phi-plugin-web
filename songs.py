"""
曲目信息加载 + 曲绘 URL + 推分建议
"""
import csv
import json
import os
from pathlib import Path
from typing import Optional

LEVELS = ["EZ", "HD", "IN", "AT", "LEGACY"]
DATA_DIR = Path(__file__).parent / "data"
ILL_BASE = "https://raw.githubusercontent.com/Catrong/phi-plugin-ill/main/ill"
ILL_PROXY = "https://gh-proxy.com"

_song_info: dict = {}
_chapters: dict = {}
_sp_info: dict = {}
_loaded = False


def load_all():
    global _song_info, _chapters, _sp_info, _loaded
    if _loaded:
        return

    # info.csv
    with open(DATA_DIR / "info.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            sid = (row.get("id") or "").strip()
            if not sid:
                continue
            entry = {
                "id": sid,
                "song": row.get("song", ""),
                "composer": row.get("composer", ""),
                "illustrator": row.get("illustrator", ""),
                "chapter": "",
                "bpm": "",
                "length": "",
                "difficulty": {},
            }
            for lv in LEVELS[:4]:
                d = (row.get(lv) or "").strip()
                if d:
                    try:
                        entry["difficulty"][lv] = float(d)
                    except ValueError:
                        pass
            _song_info[sid] = entry

    # infolist.json — 补充 bpm/length/chapter
    jpath = DATA_DIR / "infolist.json"
    if jpath.exists():
        with open(jpath, encoding="utf-8") as f:
            for sid, info in json.load(f).items():
                if sid in _song_info:
                    for k in ("bpm", "length", "chapter", "isOriginal"):
                        if k in info:
                            _song_info[sid][k] = info[k]
                else:
                    _song_info[sid] = {"id": sid, "song": sid, "difficulty": {}, **info}

    # spinfo.json
    spath = DATA_DIR / "spinfo.json"
    if spath.exists():
        with open(spath, encoding="utf-8") as f:
            _sp_info = json.load(f)
        for sid, info in _sp_info.items():
            if sid not in _song_info:
                _song_info[sid] = {"id": sid, "song": info.get("song", sid),
                                   "difficulty": {}, "chapter": "SP", **info}
            else:
                _song_info[sid].update(info)

    # chaplist.yaml
    cpath = DATA_DIR / "chaplist.yaml"
    if cpath.exists():
        import yaml
        with open(cpath, encoding="utf-8") as f:
            _chapters = yaml.safe_load(f) or {}

    _loaded = True


def get_ill_url(song_id: str) -> str:
    """获取曲绘在线 URL (通过 GitHub 代理)"""
    name = song_id.replace(".0", "")
    raw = f"{ILL_BASE}/{name}.png"
    return f"{ILL_PROXY}/{raw}"


def get_all_songs() -> list:
    load_all()
    result = []
    for sid, info in _song_info.items():
        result.append({
            "id": sid,
            "song": info.get("song", sid),
            "composer": info.get("composer", ""),
            "chapter": info.get("chapter", ""),
            "bpm": info.get("bpm", ""),
            "length": info.get("length", ""),
            "difficulty": info.get("difficulty", {}),
            "illustration": get_ill_url(sid),
        })
    return result


def get_song(song_id: str) -> Optional[dict]:
    load_all()
    info = _song_info.get(song_id)
    if not info:
        return None
    return {
        "id": song_id,
        "song": info.get("song", song_id),
        "composer": info.get("composer", ""),
        "chapter": info.get("chapter", ""),
        "bpm": info.get("bpm", ""),
        "length": info.get("length", ""),
        "difficulty": info.get("difficulty", {}),
        "illustration": get_ill_url(song_id),
    }


def get_difficulty(song_id: str, level: int) -> float:
    load_all()
    info = _song_info.get(song_id)
    if not info:
        return 0.0
    return info.get("difficulty", {}).get(LEVELS[level], 0.0)


def get_song_name(song_id: str) -> str:
    load_all()
    info = _song_info.get(song_id)
    return info.get("song", song_id) if info else song_id


def get_chapters() -> dict:
    load_all()
    return _chapters


# ===== 推分建议 =====
def calc_rks(acc: float, difficulty: float) -> float:
    if acc >= 100:
        return difficulty
    if acc < 70:
        return 0.0
    return difficulty * ((acc - 55) / 45) ** 2


def suggest_acc(target_rks: float, difficulty: float) -> float:
    """
    计算达到目标 RKS 所需的最低 ACC
    公式: acc = 45 * sqrt(rks / difficulty) + 55
    返回 -1 表示无法推分（需要 100%+）
    """
    if difficulty <= 0:
        return -1
    import math
    ans = 45 * math.sqrt(target_rks / difficulty) + 55
    if ans >= 100:
        return -1
    return round(ans, 2)


def min_up_rks(current_rks: float) -> float:
    """
    计算让 RKS 上升 0.01 所需的最小 RKS 增量
    考虑 Phigros 四舍五入到两位小数
    """
    import math
    base = math.floor(current_rks * 100) / 100 + 0.005 - current_rks
    if base < 0:
        base += 0.01
    return round(base, 4)


def rating(score: int, fc: bool) -> str:
    if score >= 1000000:
        return "PHI"
    if fc:
        return "FC"
    if score == 0:
        return "NEW"
    if score < 700000:
        return "F"
    if score < 820000:
        return "C"
    if score < 880000:
        return "B"
    if score < 920000:
        return "A"
    if score < 960000:
        return "S"
    return "V"


def compute_suggest(b30: list, save_rks: float) -> list:
    """
    生成推分建议列表
    b30: 按 RKS 降序排列的成绩列表
    返回: 每首可推分的曲目 + 所需 ACC + 建议等级
    """
    target = save_rks + min_up_rks(save_rks)
    # B30 的门槛是第 26 首的 RKS（0-indexed: b30[26]）
    threshold = b30[26]["rks"] if len(b30) > 26 else (b30[-1]["rks"] if b30 else 0)

    result = []
    for s in b30:
        if s["acc"] >= 100:
            continue
        acc_needed = suggest_acc(target, s["difficulty"])
        if acc_needed < 0:
            continue
        if acc_needed <= s["acc"]:
            continue

        # 只推荐能进 B30 或者提升 B30 的
        if s["rks"] < threshold and s not in b30[:27]:
            continue

        # 建议等级
        if acc_needed < 98.5:
            grade = 0
        elif acc_needed < 99:
            grade = 1
        elif acc_needed < 99.5:
            grade = 2
        elif acc_needed < 99.7:
            grade = 3
        elif acc_needed < 99.85:
            grade = 4
        else:
            grade = 5

        result.append({
            **s,
            "acc_needed": acc_needed,
            "acc_diff": round(acc_needed - s["acc"], 2),
            "suggest_grade": grade,
            "rks_gain": round(suggest_acc(target, s["difficulty"]) and
                             calc_rks(acc_needed, s["difficulty"]) - s["rks"], 4),
        })

    result.sort(key=lambda x: x["acc_diff"])
    return result
