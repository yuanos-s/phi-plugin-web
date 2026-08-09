"""
TapTap OAuth2 Device Code 登录（仅保留扫码和轮询功能）
"""
import os
import time
import hmac
import hashlib
import base64
import random
import string
import httpx

# ===== 从环境变量读取 TapTap Client ID =====
TAP_CLIENT_ID = os.getenv("TAP_CLIENT_ID", "rAK3FfdieFob2Nn8Am")

# ===== LeanCloud 凭证（仅保留作为注释，已停用） =====
# 以下常量不再用于网络请求，仅作历史参考
# CN_CLIENT_ID = "rAK3FfdieFob2Nn8Am"
# CN_APP_KEY = "Qr9AEqtuoSVS3zeD6iVbM4ZC0AtkJcQ89tywVyi0"

# ===== TapTap API 地址 =====
TAP_AUTH_BASE = "https://accounts.tapapis.cn"


def _rand_dev_id():
    return ''.join(random.choices(string.hexdigits, k=32))


async def request_qrcode(is_global=False):
    """
    请求二维码（设备码）
    注意：is_global 参数仅保留接口兼容性，实际固定使用国服
    """
    cid = TAP_CLIENT_ID
    dev_id = _rand_dev_id()
    files = {
        "client_id": (None, cid),
        "response_type": (None, "device_code"),
        "scope": (None, "public_profile"),
        "version": (None, "2.1"),
        "platform": (None, "unity"),
        "info": (None, f'{{"device_id":"{dev_id}"}}'),
    }
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(f"{TAP_AUTH_BASE}/oauth2/v1/device/code", files=files)
        r.raise_for_status()
        resp = r.json()
    resp["device_id"] = dev_id
    return resp


async def poll_login(device_code, device_id, is_global=False):
    """
    轮询登录状态
    """
    cid = TAP_CLIENT_ID
    files = {
        "grant_type": (None, "device_token"),
        "client_id": (None, cid),
        "secret_type": (None, "hmac-sha-1"),
        "code": (None, device_code),
        "version": (None, "1.0"),
        "platform": (None, "unity"),
        "info": (None, f'{{"device_id":"{device_id}"}}'),
    }
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(f"{TAP_AUTH_BASE}/oauth2/v1/token", files=files)
        resp = r.json()

    if "access_token" in resp or resp.get("success") is True:
        token = resp.get("data", resp)
        return {"status": "success", "token": token}

    err = None
    if isinstance(resp.get("data"), dict):
        err = resp.get("data", {}).get("error")
    if not err:
        err = resp.get("error")

    if err in ("authorization_waiting", "authorization_pending", "slow_down"):
        return {"status": "waiting"}
    if err == "authorization_scanned":
        return {"status": "scanned"}
    if err == "invalid_grant_code":
        return {"status": "expired"}
    if err:
        return {"status": "error", "message": err}
    return {"status": "waiting"}


def _mac_auth(url, method, kid, mac_key):
    """生成 MAC 认证头（用于 TapTap 用户信息接口）"""
    from urllib.parse import urlparse
    p = urlparse(url)
    ts = str(int(time.time())).zfill(10)
    nonce = base64.b64encode(random.randbytes(16)).decode()
    host = p.hostname
    uri = p.path + (f"?{p.query}" if p.query else "")
    port = str(p.port or (443 if p.scheme == "https" else 80))
    base = f"{ts}\n{nonce}\n{method}\n{uri}\n{host}\n{port}\n\n"
    mac = base64.b64encode(hmac.new(mac_key.encode(), base.encode(), hashlib.sha1).digest()).decode()
    return f'MAC id="{kid}", ts="{ts}", nonce="{nonce}", mac="{mac}"'


async def get_profile(token, is_global=False):
    """
    获取 TapTap 用户信息
    """
    api_base = "https://open.tapapis.cn"
    cid = TAP_CLIENT_ID
    url = f"{api_base}/account/profile/v1?client_id={cid}"
    auth = _mac_auth(url, "GET", token["kid"], token["mac_key"])
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get(url, headers={"Authorization": auth})
        r.raise_for_status()
        return r.json()


# ===== 以下函数因 LeanCloud 停服已废弃 =====
async def get_session_token(profile, token, is_global=False):
    """已废弃：LeanCloud 已停服，该函数不再可用"""
    raise NotImplementedError(
        "LeanCloud 已停服，无法通过 TapTap 换取 sessionToken。"
        "请使用 Supabase 存储用户信息，或让用户手动输入 sessionToken。"
    )
