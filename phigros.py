"""
Phigros 存档获取、AES 解密、二进制解析
"""
import struct
import base64
import zipfile
import io
import json
import httpx
from Crypto.Cipher import AES

# ===== 常量 =====
CN_CLIENT_ID = "rAK3FfdieFob2Nn8Am"
CN_APP_KEY = "Qr9AEqtuoSVS3zeD6iVbM4ZC0AtkJcQ89tywVyi0"
CN_LC_BASE = "https://rak3ffdi.cloud.tds1.tapapis.cn/1.1"

GB_CLIENT_ID = "kviehleldgxsagpozb"
GB_APP_KEY = "tG9CTm0LDD736k9HMM9lBZrbeBGRmUkjSfNLDNib"
GB_LC_BASE = "https://kviehlel.cloud.ap-sg.tapapis.com/1.1"

AES_KEY = base64.b64decode("6Jaa0qVAJZuXkZCLiOa/Ax5tIZVu+taKUN1V1nqwkks=")
AES_IV = base64.b64decode("Kk/wisgNYwcAV8WVGMgyUw==")

LEVELS = ["EZ", "HD", "IN", "AT", "LEGACY"]


def _cfg(is_global):
    if is_global:
        return GB_CLIENT_ID, GB_APP_KEY, GB_LC_BASE
    return CN_CLIENT_ID, CN_APP_KEY, CN_LC_BASE


# ===== Binary Reader =====
class BinaryReader:
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    def remaining(self):
        return len(self.data) - self.pos

    def get_byte(self):
        b = self.data[self.pos]; self.pos += 1; return b

    def get_short(self):
        self.pos += 2
        return self.data[self.pos-2] | (self.data[self.pos-1] << 8)

    def get_int(self):
        self.pos += 4
        return struct.unpack_from("<i", self.data, self.pos-4)[0]

    def get_float(self):
        self.pos += 4
        return struct.unpack_from("<f", self.data, self.pos-4)[0]

    def get_varint(self):
        if self.data[self.pos] > 127:
            self.pos += 2
            return (0x7F & self.data[self.pos-2]) | (self.data[self.pos-1] << 7)
        self.pos += 1
        return self.data[self.pos-1]

    def get_string(self):
        length = self.get_varint()
        self.pos += length
        return self.data[self.pos-length:self.pos].decode("utf-8")


def decrypt_save(ciphertext: bytes) -> bytes:
    cipher = AES.new(AES_KEY, AES.MODE_CBC, AES_IV)
    plain = cipher.decrypt(ciphertext)
    pad = plain[-1]
    if 0 < pad <= 16:
        plain = plain[:-pad]
    return plain


def parse_summary(summary_b64: str) -> dict:
    raw = base64.b64decode(summary_b64)
    r = BinaryReader(raw)
    sv = r.get_byte()
    cr = r.get_short()
    rks = r.get_float()
    gv = r.get_varint()
    av = r.get_string()
    cleared = [r.get_short() for _ in range(4)]
    fc = [r.get_short() for _ in range(4)]
    phi = [r.get_short() for _ in range(4)]
    return {"save_version": sv, "challenge_mode_rank": cr, "ranking_score": round(rks, 4),
            "game_version": gv, "avatar": av,
            "cleared": cleared, "full_combo": fc, "phi": phi}


def parse_game_record(data: bytes) -> dict:
    r = BinaryReader(data)
    count = r.get_varint()
    records = {}
    while r.remaining() > 0:
        sid = r.get_string()
        r.get_varint()  # skip
        lvl_mask = r.get_byte()
        fc_mask = r.get_byte()
        levels = []
        for lv in range(5):
            if lvl_mask & (1 << lv):
                score = r.get_int()
                acc = r.get_float()
                fc = (score == 1000000 and acc == 100) or bool(fc_mask & (1 << lv))
                levels.append({"score": score, "acc": round(acc, 4), "fc": fc})
            else:
                levels.append(None)
        records[sid] = levels
    return {"song_count": count, "records": records}


def parse_game_user(data: bytes) -> dict:
    r = BinaryReader(data)
    flags = r.get_byte()
    return {"show_player_id": bool(flags & 1), "self_intro": r.get_string(),
            "avatar": r.get_string(), "background": r.get_string()}


def parse_game_progress(data: bytes) -> dict:
    r = BinaryReader(data)
    tem = r.get_byte()
    return {"is_first_run": bool(tem & 1), "legacy_chapter_finished": bool(tem & 2),
            "completed": r.get_string(), "challenge_mode_rank": r.get_short(),
            "money": [r.get_varint() for _ in range(5)]}


# ===== LeanCloud API =====
async def lc_get_player_info(session_token, is_global=False):
    cid, akey, base = _cfg(is_global)
    headers = {"X-LC-Id": cid, "X-LC-Key": akey, "X-LC-Session": session_token,
               "User-Agent": "LeanCloud-CSharp-SDK/1.0.3", "Accept": "application/json"}
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(f"{base}/users/me", headers=headers)
        r.raise_for_status()
        return r.json()


async def lc_get_saves(session_token, object_id, is_global=False):
    cid, akey, base = _cfg(is_global)
    headers = {"X-LC-Id": cid, "X-LC-Key": akey, "X-LC-Session": session_token,
               "User-Agent": "LeanCloud-CSharp-SDK/1.0.3", "Accept": "application/json"}
    where = json.dumps({"user": {"__type": "Pointer", "className": "_User", "objectId": object_id}})
    params = {"skip": "0", "limit": "100", "where": where, "include": "cover,gameFile"}
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(f"{base}/gamesaves/", headers=headers, params=params)
        r.raise_for_status()
        return r.json().get("results", [])


async def fetch_zip(url: str) -> bytes:
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.get(url)
        r.raise_for_status()
        return r.content


# ===== 完整存档 =====
async def get_full_save(session_token, is_global=False):
    player = await lc_get_player_info(session_token, is_global)
    saves = await lc_get_saves(session_token, player["objectId"], is_global)
    if not saves:
        raise ValueError("未找到存档，请确认已在游戏中同步存档")
    saves.sort(key=lambda s: s.get("modifiedAt", {}).get("iso", ""), reverse=True)
    save_info = saves[0]
    if not save_info.get("gameFile"):
        raise ValueError("存档中没有 gameFile")
    save_url = save_info["gameFile"]["url"]
    summary = {}
    if save_info.get("summary"):
        try:
            summary = parse_summary(save_info["summary"])
        except Exception:
            pass
    zip_data = await fetch_zip(save_url)
    zf = zipfile.ZipFile(io.BytesIO(zip_data))
    game_record, game_user, game_progress = {}, {}, {}
    for name, parser in [("gameRecord", parse_game_record), ("user", parse_game_user),
                         ("gameProgress", parse_game_progress)]:
        if name in zf.namelist():
            raw = zf.read(name)
            if len(raw) > 1:
                try:
                    plain = decrypt_save(raw[1:])
                    result = parser(plain)
                    if name == "gameRecord":
                        game_record = result
                    elif name == "user":
                        game_user = result
                    elif name == "gameProgress":
                        game_progress = result
                except Exception:
                    pass
    return {"player": player, "save_info": {"modified_at": save_info.get("modifiedAt", {}),
                                            "created_at": save_info.get("createdAt", "")},
            "summary": summary, "game_record": game_record,
            "game_user": game_user, "game_progress": game_progress}
