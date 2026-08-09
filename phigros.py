"""
Phigros 存档解析 (无 LeanCloud)

迁移变更:
  - 移除所有 LeanCloud API 调用 (lc_get_player_info, lc_get_saves, fetch_zip, get_full_save)
  - 保留 AES 解密 + 二进制解析 (这些与存储无关)
  - 新增 parse_uploaded_save(): 接收上传的 ZIP bytes, 返回解析后的完整存档
"""
import struct
import base64
import zipfile
import io
import json
from Crypto.Cipher import AES

AES_KEY = base64.b64decode("6Jaa0qVAJZuXkZCLiOa/Ax5tIZVu+taKUN1V1nqwkks=")
AES_IV = base64.b64decode("Kk/wisgNYwcAV8WVGMgyUw==")

LEVELS = ["EZ", "HD", "IN", "AT", "LEGACY"]


class BinaryReader:
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    def remaining(self):
        return len(self.data) - self.pos

    def _need(self, n):
        if self.pos + n > len(self.data):
            raise IndexError(f"读取越界: pos={self.pos} need={n} len={len(self.data)}")

    def get_byte(self):
        self._need(1)
        b = self.data[self.pos]; self.pos += 1; return b

    def get_short(self):
        self._need(2)
        self.pos += 2
        return self.data[self.pos-2] | (self.data[self.pos-1] << 8)

    def get_int(self):
        self._need(4)
        self.pos += 4
        return struct.unpack_from("<i", self.data, self.pos-4)[0]

    def get_float(self):
        self._need(4)
        self.pos += 4
        return struct.unpack_from("<f", self.data, self.pos-4)[0]

    def get_varint(self):
        self._need(1)
        if self.data[self.pos] > 127:
            self._need(2)
            self.pos += 2
            return (0x7F & self.data[self.pos-2]) | (self.data[self.pos-1] << 7)
        self.pos += 1
        return self.data[self.pos-1]

    def get_string(self):
        length = self.get_varint()
        self._need(length)
        self.pos += length
        return self.data[self.pos-length:self.pos].decode("utf-8", errors="replace")


def decrypt_save(ciphertext: bytes) -> bytes:
    if not ciphertext or len(ciphertext) == 0:
        raise ValueError("空密文")
    if len(ciphertext) % 16 != 0:
        raise ValueError(f"密文长度非 16 倍数: {len(ciphertext)}")
    cipher = AES.new(AES_KEY, AES.MODE_CBC, AES_IV)
    plain = cipher.decrypt(ciphertext)
    if len(plain) == 0:
        return plain
    pad = plain[-1]
    if 1 <= pad <= 16:
        if all(b == pad for b in plain[-pad:]):
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
        try:
            sid = r.get_string()
            r.get_varint()
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
        except IndexError:
            break
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


def parse_uploaded_save(zip_data: bytes) -> dict:
    """
    解析用户上传的 Phigros 存档 ZIP

    存档 ZIP 内含:
      - gameRecord: 首字节=版本号, 其余=AES-CBC 密文
      - user: 同上
      - settings: 同上
      - gameProgress: 同上

    返回: {game_record, game_user, game_progress, summary}
    """
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
                except Exception as e:
                    raise ValueError(f"解析 {name} 失败: {e}")

    # summary 不在 ZIP 内，从 gameProgress 推断或留空
    # summary 通常存在于 LeanCloud 的存档元数据中，上传的 ZIP 可能不含
    # 如果有 summary 文件则解析
    if "summary" in zf.namelist():
        try:
            summary_raw = zf.read("summary")
            summary = parse_summary(summary_raw.decode("utf-8").strip())
        except Exception:
            summary = {}
    else:
        summary = {}

    return {
        "game_record": game_record,
        "game_user": game_user,
        "game_progress": game_progress,
        "summary": summary,
    }
