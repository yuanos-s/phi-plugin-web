"""
TapTap OAuth2 Device Code 登录 + LeanCloud sessionToken 获取
"""
import time, hmac, hashlib, base64, random, string, httpx

# 注意：以下 CN_CLIENT_ID 和 CN_APP_KEY 实际上是 LeanCloud 的凭证
# 如果它们失效，你需要注册自己的 LeanCloud 应用并替换
CN_CLIENT_ID = "rAK3FfdieFob2Nn8Am"
CN_APP_KEY   = "Qr9AEqtuoSVS3zeD6iVbM4ZC0AtkJcQ89tywVyi0"
CN_TAP_AUTH  = "https://accounts.tapapis.cn"
CN_TAP_API   = "https://open.tapapis.cn"
CN_LC_BASE   = "https://rak3ffdi.cloud.tds1.tapapis.cn/1.1"

GB_CLIENT_ID = "kviehleldgxsagpozb"
GB_APP_KEY   = "tG9CTm0LDD736k9HMM9lBZrbeBGRmUkjSfNLDNib"
GB_TAP_AUTH  = "https://accounts.tapapis.com"
GB_TAP_API   = "https://open.tapapis.com"
GB_LC_BASE   = "https://kviehlel.cloud.ap-sg.tapapis.com/1.1"


def _cfg(is_global):
    if is_global:
        return GB_CLIENT_ID, GB_APP_KEY, GB_TAP_AUTH, GB_TAP_API, GB_LC_BASE
    return CN_CLIENT_ID, CN_APP_KEY, CN_TAP_AUTH, CN_TAP_API, CN_LC_BASE


def _rand_dev_id():
    return ''.join(random.choices(string.hexdigits, k=32))


async def request_qrcode(is_global=False):
    cid, _, auth_base, _, _ = _cfg(is_global)
    dev_id = _rand_dev_id()
    files = {
        "client_id": (None, cid), "response_type": (None, "device_code"),
        "scope": (None, "public_profile"), "version": (None, "2.1"),
        "platform": (None, "unity"), "info": (None, f'{{"device_id":"{dev_id}"}}'),
    }
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(f"{auth_base}/oauth2/v1/device/code", files=files)
        r.raise_for_status()
        resp = r.json()
    resp["device_id"] = dev_id
    return resp


async def poll_login(device_code, device_id, is_global=False):
    cid, _, auth_base, _, _ = _cfg(is_global)
    files = {
        "grant_type": (None, "device_token"), "client_id": (None, cid),
        "secret_type": (None, "hmac-sha-1"), "code": (None, device_code),
        "version": (None, "1.0"), "platform": (None, "unity"),
        "info": (None, f'{{"device_id":"{device_id}"}}'),
    }
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(f"{auth_base}/oauth2/v1/token", files=files)
        resp = r.json()

    if "access_token" in resp or resp.get("success") is True:
        token = resp.get("data", resp)
        return {"status": "success", "token": token}

    err = None
    if isinstance(resp.get("data"), dict):
        err = resp.get("data", {}).get("error")
    if not err:
        err = resp.get("error")

    if err in ("authorization_waiting", "authorization_pending"):
        return {"status": "waiting"}
    if err == "authorization_scanned":
        return {"status": "scanned"}
    if err:
        return {"status": "error", "message": err}
    return {"status": "waiting"}


def _mac_auth(url, method, kid, mac_key):
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
    cid, _, _, api_base, _ = _cfg(is_global)
    url = f"{api_base}/account/profile/v1?client_id={cid}"
    auth = _mac_auth(url, "GET", token["kid"], token["mac_key"])
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get(url, headers={"Authorization": auth})
        return r.json()


async def get_session_token(profile, token, is_global=False):
    cid, app_key, _, _, lc_base = _cfg(is_global)
    ts = str(int(time.time()))
    sign = hashlib.md5(f"{ts}{app_key}".encode()).hexdigest()
    headers = {
        "X-LC-Id": cid,
        "Content-Type": "application/json",
        "X-LC-Sign": f"{sign},{ts}",
    }
    # 从 profile 中提取 openid（TapTap 用户唯一标识）
    openid = profile.get("openid") or profile.get("id") or profile.get("uid")
    if not openid:
        raise ValueError("无法从 TapTap profile 中获取 openid")
    auth_data = {
        "openid": openid,
        "access_token": token.get("access_token"),
        "expires_in": token.get("expires_in", 86400),
    }
    body = {"authData": {"taptap": auth_data}}
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(f"{lc_base}/users", json=body, headers=headers)
        resp = r.json()
    # 检查 LeanCloud 是否返回错误
    if "error" in resp or "code" in resp:
        raise RuntimeError(f"LeanCloud 返回错误: {resp}")
    return resp
