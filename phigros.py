"""
Phigros 存档解析模块（仅保留解析功能，不再依赖 LeanCloud）
"""
import struct
import base64
import zipfile
import io
import json
import os
from Crypto.Cipher import AES

# ===== 常量（仅用于解析，不再用于网络请求） =====
LEVELS = ["EZ", "HD", "IN", "AT", "LEGACY"]
AES_KEY = base64.b64decode("6Jaa0qVAJZuXkZCLiOa/Ax5tIZVu+taKUN1V1nqwkks=")
AES_IV = base64.b64decode("Kk/wisgNYwcAV8WVGMgyUw==")


# ===== 异常类 =====
class LeanCloudDeprecatedError(Exception):
    """LeanCloud 已停服，该功能不再可用"""
    pass


# ===== Binary Reader =====
class BinaryReader:
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    def remaining(self):
        return len(self.data) - self.pos

    def _need(self, n: int):
        if self.pos + n > len(self.data):
            raise ValueError(f"数据越界：需要 {n} 字节，剩余 {self.remaining()} 字节")

    def get_byte(self):
        self._need(1)
        b = self.data[self.pos]
        self.pos += 1
        return b

    def get_short(self):
        self._need(2)
        val = self.data[self.pos] | (self.data[self.pos + 1] << 8)
        self.pos += 2
        return val

    def get_int(self):
        self._need(4)
        val = struct.unpack_from("<i", self.data, self.pos)[0]
        self.pos += 4
        return val

    def get_float(self):
        self._need(4)
        val = struct.unpack_from("<f", self.data, self.pos)[0]
        self.pos += 4
        return val

    def get_varint(self):
        self._need(1)
        if self.data[self.pos] > 127:
            self._need(2)
            val = (0x7F & self.data[self.pos]) | (self.data[self.pos + 1] << 7)
            self.pos += 2
            return val
        val = self.data[self.pos]
        self.pos += 1
        return val

    def get_string(self):
        length = self.get_varint()
        self._need(length)
        val = self.data[self.pos:self.pos + length].decode("utf-8")
        self.pos += length
        return val


def decrypt_save(ciphertext: bytes) -> bytes:
    """解密存档数据（PKCS7 填充校验）"""
    if not ciphertext or len(ciphertext) < 16:
        raise ValueError("存档数据为空或过短")
    cipher = AES.new(AES_KEY, AES.MODE_CBC, AES_IV)
    plain = cipher.decrypt(ciphertext)
    pad = plain[-1]
    if 0 < pad <= 16:
        # 验证填充是否有效
        if all(p == pad for p in plain[-pad:]):
            plain = plain[:-pad]
        else:
            raise ValueError("PKCS7 填充校验失败")
    return plain


def parse_summary(summary_b64: str) -> dict:
    """解析存档摘要"""
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
    return {
        "save_version": sv,
        "challenge_mode_rank": cr,
        "ranking_score": round(rks, 4),
        "game_version": gv,
        "avatar": av,
        "cleared": cleared,
        "full_combo": fc,
        "phi": phi,
    }


def parse_game_record(data: bytes) -> dict:
    """解析游戏记录"""
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
    """解析用户信息"""
    r = BinaryReader(data)
    flags = r.get_byte()
    return {
        "show_player_id": bool(flags & 1),
        "self_intro": r.get_string(),
        "avatar": r.get_string(),
        "background": r.get_string(),
    }


def parse_game_progress(data: bytes) -> dict:
    """解析游戏进度"""
    r = BinaryReader(data)
    tem = r.get_byte()
    return {
        "is_first_run": bool(tem & 1),
        "legacy_chapter_finished": bool(tem & 2),
        "completed": r.get_string(),
        "challenge_mode_rank": r.get_short(),
        "money": [r.get_varint() for _ in range(5)],
    }


def parse_archive_zip(zip_data: bytes) -> dict:
    """
    解析 Phigros 存档 ZIP 文件，返回结构化数据
    用于用户上传存档时的解析
    """
    result = {"game_record": {}, "game_user": {}, "game_progress": {}, "summary": {}}
    zf = zipfile.ZipFile(io.BytesIO(zip_data))
    for name, parser in [
        ("gameRecord", parse_game_record),
        ("user", parse_game_user),
        ("gameProgress", parse_game_progress),
    ]:
        if name in zf.namelist():
            raw = zf.read(name)
            if len(raw) > 1:
                try:
                    plain = decrypt_save(raw[1:])
                    parsed = parser(plain)
                    if name == "gameRecord":
                        result["game_record"] = parsed
                    elif name == "user":
                        result["game_user"] = parsed
                    elif name == "gameProgress":
                        result["game_progress"] = parsed
                except Exception as e:
                    print(f"[WARN] 解析 {name} 失败: {e}")
    return result


# ===== 以下函数因 LeanCloud 停服已废弃 =====

async def lc_get_player_info(session_token, is_global=False):
    """已废弃：LeanCloud 已停服"""
    raise LeanCloudDeprecatedError("LeanCloud 已停服，该函数不再可用")


async def lc_get_saves(session_token, object_id, is_global=False):
    """已废弃：LeanCloud 已停服"""
    raise LeanCloudDeprecatedError("LeanCloud 已停服，该函数不再可用")


async def get_full_save(session_token, is_global=False):
    """已废弃：LeanCloud 已停服，请使用上传存档功能"""
    raise LeanCloudDeprecatedError(
        "LeanCloud 已停服，无法自动拉取存档。请使用「上传存档」功能手动上传 ZIP 文件。"
    )
