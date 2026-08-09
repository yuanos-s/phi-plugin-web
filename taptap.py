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

    # 将 slow_down 也视为等待状态
    if err in ("authorization_waiting", "authorization_pending", "slow_down"):
        return {"status": "waiting"}
    if err == "authorization_scanned":
        return {"status": "scanned"}
    if err:
        return {"status": "error", "message": err}
    return {"status": "waiting"}
