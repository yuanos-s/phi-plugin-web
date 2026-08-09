"""
TapTap OAuth2 Device Code 登录 + LeanCloud sessionToken 获取

关键修复：
1. Client ID 必须使用 Phigros 的 LeanCloud App ID (rAK3FfdieFob2Nn8Am)
   它同时是 TapTap OAuth client_id 和 LeanCloud X-LC-Id
2. LeanCloud TapTap authData 必须包含完整的 profile + token 数据
   不能只传 openid/access_token，LeanCloud 需要完整 MAC 签名凭证来验证
3. 错误处理：所有异常都捕获并返回明确信息，不删 session（除非成功/过期）
"""
import os
import time
import hmac
import hashlib
import base64
import random
import string
import json
import traceback
import httpx

# ===== 环境变量 =====
# TapTap OAuth client_id = LeanCloud App ID = rAK3FfdieFob2Nn8Am (国服)
# 如果设置了 TAP_CLIENT_ID 环境变量，优先使用；否则用默认值
# ⚠️ 注意：这个值必须与 LeanCloud 的 X-LC-Id 一致，不能随意改
TAP_CLIENT_ID = os.getenv("TAP_CLIENT_ID", "rAK3FfdieFob2Nn8Am")

# LeanCloud 凭证
CN_LC_ID    = os.getenv("CN_LC_ID", TAP_CLIENT_ID)
CN_LC_KEY   = os.getenv("CN_LC_KEY", "Qr9AEqtuoSVS3zeD6iVbM4ZC0AtkJcQ89tywVyi0")
CN_TAP_AUTH  = "https://accounts.tapapis.cn"
CN_TAP_API   = "https://open.tapapis.cn"
CN_LC_BASE   = "https://rak3ffdi.cloud.tds1.tapapis.cn/1.1"

GB_LC_ID    = os.getenv("GB_LC_ID", "kviehleldgxsagpozb")
GB_LC_KEY   = os.getenv("GB_LC_KEY", "tG9CTm0LDD736k9HMM9lBZrbeBGRmUkjSfNLDNib")
GB_TAP_AUTH  = "https://accounts.tapapis.com"
GB_TAP_API   = "https://open.tapapis.com"
GB_LC_BASE   = "https://kviehlel.cloud.ap-sg.tapapis.com/1.1"


def _cfg(is_global):
    """返回 (lc_id, lc_key, tap_auth, tap_api, lc_base)"""
    if is_global:
        return GB_LC_ID, GB_LC_KEY, GB_TAP_AUTH, GB_TAP_API, GB_LC_BASE
    return CN_LC_ID, CN_LC_KEY, CN_TAP_AUTH, CN_TAP_API, CN_LC_BASE


def _rand_dev_id():
    return ''.join(random.choices(string.hexdigits, k=32))


async def request_qrcode(is_global=False):
    """
    请求 TapTap 登录二维码
    返回: {device_code, qrcode_url, expires_in, interval, device_id}
    """
    _, _, auth_base, _, _ = _cfg(is_global)
    # TapTap OAuth 的 client_id 必须与 LeanCloud App ID 一致
    cid = TAP_CLIENT_ID if not is_global else GB_LC_ID
    dev_id = _rand_dev_id()

    files = {
        "client_id": (None, cid),
        "response_type": (None, "device_code"),
        "scope": (None, "public_profile"),
        "version": (None, "2.1"),
        "platform": (None, "unity"),
        "info": (None, json.dumps({"device_id": dev_id})),
    }
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(f"{auth_base}/oauth2/v1/device/code", files=files)
        r.raise_for_status()
        resp = r.json()

    resp["device_id"] = dev_id
    return resp


async def poll_login(device_code, device_id, is_global=False):
    """
    轮询扫码登录状态
    返回:
      {"status": "waiting"} — 等待扫码
      {"status": "scanned"} — 已扫描等待确认
      {"status": "success", "token": {...}} — 登录成功，token 含 kid/mac_key/access_token 等
      {"status": "expired"} — 二维码过期
      {"status": "error", "message": "..."} — 其他错误
    """
    _, _, auth_base, _, _ = _cfg(is_global)
    cid = TAP_CLIENT_ID if not is_global else GB_LC_ID

    files = {
        "grant_type": (None, "device_token"),
        "client_id": (None, cid),
        "secret_type": (None, "hmac-sha-1"),
        "code": (None, device_code),
        "version": (None, "1.0"),
        "platform": (None, "unity"),
        "info": (None, json.dumps({"device_id": device_id})),
    }
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(f"{auth_base}/oauth2/v1/token", files=files)
        resp = r.json()

    # 成功：TapTap 返回 token 数据
    if "access_token" in resp or resp.get("success") is True:
        token = resp.get("data", resp)
        # 确保 token 包含必要字段
        if "kid" not in token or "mac_key" not in token:
            return {"status": "error",
                    "message": f"TapTap 返回的 token 缺少必要字段: {list(token.keys())}"}
        return {"status": "success", "token": token}

    # 错误判断
    err = None
    if isinstance(resp.get("data"), dict):
        err = resp["data"].get("error")
    if not err:
        err = resp.get("error")

    if err in ("authorization_waiting", "authorization_pending", "slow_down"):
        return {"status": "waiting"}
    if err == "authorization_scanned":
        return {"status": "scanned"}
    if err in ("invalid_grant_code", "expired_token"):
        return {"status": "expired"}
    if err:
        return {"status": "error", "message": err}

    return {"status": "waiting"}


def _mac_auth(url, method, kid, mac_key):
    """构建 TapTap MAC Authorization 头 (HMAC-SHA1)"""
    from urllib.parse import urlparse
    p = urlparse(url)
    ts = str(int(time.time())).zfill(10)
    nonce = base64.b64encode(random.randbytes(16)).decode()
    host = p.hostname
    uri = p.path + (f"?{p.query}" if p.query else "")
    port = str(p.port or (443 if p.scheme == "https" else 80))
    base_str = f"{ts}\n{nonce}\n{method}\n{uri}\n{host}\n{port}\n\n"
    mac = base64.b64encode(
        hmac.new(mac_key.encode(), base_str.encode(), hashlib.sha1).digest()
    ).decode()
    return f'MAC id="{kid}", ts="{ts}", nonce="{nonce}", mac="{mac}"'


async def get_profile(token, is_global=False):
    """
    用 TapTap token 获取用户 profile
    token 必须包含: kid, mac_key, access_token, scope
    """
    _, _, _, api_base, _ = _cfg(is_global)
    cid = TAP_CLIENT_ID if not is_global else GB_LC_ID
    url = f"{api_base}/account/profile/v1?client_id={cid}"

    auth = _mac_auth(url, "GET", token["kid"], token["mac_key"])
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get(url, headers={"Authorization": auth})
        resp = r.json()

    # 返回完整响应，让调用方决定如何提取 data
    return resp


async def get_session_token(profile, token, is_global=False):
    """
    用 TapTap profile + token 登录 LeanCloud，获取 Phigros sessionToken

    关键：LeanCloud 的 TapTap auth adapter 需要完整的 token 数据
    (kid, access_token, mac_key, mac_algorithm, scope, token_type, expires_in)
    以及 profile 数据 (name, avatar, openid 等)
    不能只传部分字段，否则 LeanCloud 无法验证 MAC 签名
    """
    lc_id, lc_key, _, _, lc_base = _cfg(is_global)

    ts = str(int(time.time()))
    sign = hashlib.md5(f"{ts}{lc_key}".encode()).hexdigest()
    headers = {
        "X-LC-Id": lc_id,
        "Content-Type": "application/json",
        "X-LC-Sign": f"{sign},{ts}",
    }

    # 合并完整的 profile + token 数据（与 phi-plugin 原版一致）
    # profile 通常是 {data: {name, avatar, openid, ...}} 或直接 {name, avatar, ...}
    profile_data = profile.get("data", profile) if isinstance(profile, dict) else {}
    # token 包含 kid, access_token, mac_key, mac_algorithm, scope, token_type, expires_in
    merged = {**profile_data, **token}
    body = {"authData": {"taptap": merged}}

    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(f"{lc_base}/users", json=body, headers=headers)
        resp = r.json()

    if "error" in resp or resp.get("code"):
        raise RuntimeError(f"LeanCloud 错误 (code={resp.get('code','?')}): "
                           f"{resp.get('error', resp)}")

    if not resp.get("sessionToken"):
        raise RuntimeError(f"LeanCloud 未返回 sessionToken: {resp}")

    return resp
