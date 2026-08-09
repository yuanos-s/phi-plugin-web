"""
TapTap OAuth2 Device Code 登录 (无 LeanCloud)

迁移变更:
  - 移除 get_session_token (LeanCloud 登录) — LeanCloud 已停服
  - 只保留 TapTap OAuth: 扫码 → 获取 token → 获取 profile
  - profile 中的 openid/name/avatar 交给 Supabase 处理
"""
import os
import time
import hmac
import hashlib
import base64
import random
import string
import json
import httpx

# ===== 环境变量 =====
TAP_CLIENT_ID = os.getenv("TAP_CLIENT_ID", "rAK3FfdieFob2Nn8Am")

CN_TAP_AUTH = "https://accounts.tapapis.cn"
CN_TAP_API  = "https://open.tapapis.cn"
GB_TAP_AUTH = "https://accounts.tapapis.com"
GB_TAP_API  = "https://open.tapapis.com"

_TAP_ERROR_MAP = {
    "authorization_waiting": "waiting",
    "authorization_pending": "waiting",
    "slow_down": "waiting",
    "authorization_scanned": "scanned",
    "invalid_grant_code": "expired",
    "invalid_grant": "expired",
    "invalid_device_code": "expired",
    "expired_token": "expired",
    "device_code_expired": "expired",
    "access_denied": "error",
    "unauthorized": "error",
}


def _cfg(is_global):
    if is_global:
        return GB_TAP_AUTH, GB_TAP_API
    return CN_TAP_AUTH, CN_TAP_API


def _rand_dev_id():
    return ''.join(random.choices(string.hexdigits, k=32))


async def request_qrcode(is_global=False):
    auth_base, _ = _cfg(is_global)
    cid = TAP_CLIENT_ID
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
    auth_base, _ = _cfg(is_global)
    cid = TAP_CLIENT_ID
    files = {
        "grant_type": (None, "device_token"),
        "client_id": (None, cid),
        "secret_type": (None, "hmac-sha-1"),
        "code": (None, device_code),
        "version": (None, "1.0"),
        "platform": (None, "unity"),
        "info": (None, json.dumps({"device_id": device_id})),
    }
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.post(f"{auth_base}/oauth2/v1/token", files=files)
            if r.status_code >= 400:
                try:
                    resp = r.json()
                except Exception:
                    if r.status_code in (400, 410):
                        return {"status": "expired"}
                    return {"status": "error", "message": f"TapTap HTTP {r.status_code}"}
            else:
                resp = r.json()
    except httpx.RequestError as e:
        return {"status": "error", "message": f"网络错误: {e}"}
    except Exception as e:
        return {"status": "error", "message": f"轮询异常: {e}"}

    if "access_token" in resp or resp.get("success") is True:
        token = resp.get("data", resp)
        if "kid" not in token or "mac_key" not in token:
            return {"status": "error",
                    "message": f"token 缺少必要字段: {list(token.keys())}"}
        return {"status": "success", "token": token}

    err = None
    if isinstance(resp.get("data"), dict):
        err = resp["data"].get("error")
    if not err:
        err = resp.get("error")

    if err:
        mapped = _TAP_ERROR_MAP.get(err)
        if mapped == "waiting":
            return {"status": "waiting"}
        if mapped == "scanned":
            return {"status": "scanned"}
        if mapped == "expired":
            return {"status": "expired"}
        if mapped == "error":
            return {"status": "error", "message": err}
        return {"status": "error", "message": f"TapTap 未知错误: {err}"}

    return {"status": "waiting"}


def _mac_auth(url, method, kid, mac_key):
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
    """获取 TapTap 用户 profile (openid, name, avatar)"""
    _, api_base = _cfg(is_global)
    cid = TAP_CLIENT_ID
    url = f"{api_base}/account/profile/v1?client_id={cid}"
    auth = _mac_auth(url, "GET", token["kid"], token["mac_key"])
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.get(url, headers={"Authorization": auth})
            if r.status_code >= 400:
                raise RuntimeError(f"TapTap profile HTTP {r.status_code}: {r.text[:200]}")
            return r.json()
    except httpx.RequestError as e:
        raise RuntimeError(f"TapTap profile 网络错误: {e}")
