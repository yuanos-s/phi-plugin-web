"""
TapTap OAuth2 Device Code 登录 + LeanCloud sessionToken 获取

修复:
  #2  poll_login: r.json() 加 try/except，400 非 JSON 时返回 expired
  #3  补全 TapTap 错误码: invalid_grant, invalid_device_code, device_code_expired
  #4  get_profile/get_session_token: 加 raise_for_status + 状态码检查
  #13 移除未使用的 traceback 导入
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

# TapTap 错误码 → 状态映射
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
        return GB_LC_ID, GB_LC_KEY, GB_TAP_AUTH, GB_TAP_API, GB_LC_BASE
    return CN_LC_ID, CN_LC_KEY, CN_TAP_AUTH, CN_TAP_API, CN_LC_BASE


def _rand_dev_id():
    return ''.join(random.choices(string.hexdigits, k=32))


async def request_qrcode(is_global=False):
    _, _, auth_base, _, _ = _cfg(is_global)
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
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.post(f"{auth_base}/oauth2/v1/token", files=files)
            # BUG #2: 400 可能返回非 JSON，先检查状态码
            if r.status_code >= 400:
                # 尝试解析 JSON 错误体
                try:
                    resp = r.json()
                except Exception:
                    # 非 JSON 响应，按 HTTP 状态码判断
                    if r.status_code in (400, 410):
                        return {"status": "expired"}
                    return {"status": "error",
                            "message": f"TapTap HTTP {r.status_code}"}
            else:
                resp = r.json()
    except httpx.RequestError as e:
        return {"status": "error", "message": f"网络错误: {e}"}
    except Exception as e:
        return {"status": "error", "message": f"轮询异常: {e}"}

    # 成功：TapTap 返回 token 数据
    if "access_token" in resp or resp.get("success") is True:
        token = resp.get("data", resp)
        if "kid" not in token or "mac_key" not in token:
            return {"status": "error",
                    "message": f"token 缺少必要字段: {list(token.keys())}"}
        return {"status": "success", "token": token}

    # BUG #3: 用映射表处理所有已知错误码
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
        # 未知错误码，返回 error 而非 waiting
        return {"status": "error", "message": f"TapTap 未知错误: {err}"}

    # 无 error 字段也非成功 → 默认 waiting
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
    _, _, _, api_base, _ = _cfg(is_global)
    cid = TAP_CLIENT_ID if not is_global else GB_LC_ID
    url = f"{api_base}/account/profile/v1?client_id={cid}"
    auth = _mac_auth(url, "GET", token["kid"], token["mac_key"])
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.get(url, headers={"Authorization": auth})
            # BUG #4: 检查 HTTP 状态码
            if r.status_code >= 400:
                raise RuntimeError(f"TapTap profile HTTP {r.status_code}: {r.text[:200]}")
            return r.json()
    except httpx.RequestError as e:
        raise RuntimeError(f"TapTap profile 网络错误: {e}")


async def get_session_token(profile, token, is_global=False):
    lc_id, lc_key, _, _, lc_base = _cfg(is_global)
    ts = str(int(time.time()))
    sign = hashlib.md5(f"{ts}{lc_key}".encode()).hexdigest()
    headers = {
        "X-LC-Id": lc_id,
        "Content-Type": "application/json",
        "X-LC-Sign": f"{sign},{ts}",
    }
    profile_data = profile.get("data", profile) if isinstance(profile, dict) else {}
    merged = {**profile_data, **token}
    body = {"authData": {"taptap": merged}}

    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.post(f"{lc_base}/users", json=body, headers=headers)
            # BUG #4: 检查 HTTP 状态码
            if r.status_code >= 400:
                try:
                    resp = r.json()
                    err_msg = resp.get("error", str(resp))
                    err_code = resp.get("code", "?")
                except Exception:
                    err_msg = r.text[:200]
                    err_code = "?"
                raise RuntimeError(f"LeanCloud 错误 (code={err_code}): {err_msg}")
            resp = r.json()
    except httpx.RequestError as e:
        raise RuntimeError(f"LeanCloud 网络错误: {e}")

    if not resp.get("sessionToken"):
        raise RuntimeError(f"LeanCloud 未返回 sessionToken: {resp}")

    return resp
