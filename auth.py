"""
Telegram WebApp initData HMAC validation.
Docs: https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
"""
import hmac
import hashlib
import json
from urllib.parse import parse_qsl


def verify_init_data(init_data: str, bot_token: str, max_age_seconds: int = 86400) -> dict | None:
    """
    Validate initData from Telegram.WebApp.initData.
    Returns the parsed user dict if valid, None otherwise.
    """
    if not init_data:
        return None

    try:
        parsed = dict(parse_qsl(init_data, keep_blank_values=True))
    except Exception:
        return None

    received_hash = parsed.pop("hash", None)
    if not received_hash:
        return None

    # data_check_string: all fields sorted alphabetically, key=value joined by \n
    data_check = "\n".join(f"{k}={parsed[k]}" for k in sorted(parsed.keys()))

    # secret_key = HMAC_SHA256(key="WebAppData", msg=bot_token)
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    computed_hash = hmac.new(secret_key, data_check.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(computed_hash, received_hash):
        return None

    # Optional: check auth_date freshness
    import time
    auth_date = int(parsed.get("auth_date", 0))
    if max_age_seconds > 0 and (time.time() - auth_date) > max_age_seconds:
        return None

    user_json = parsed.get("user")
    if not user_json:
        return None
    try:
        return json.loads(user_json)
    except json.JSONDecodeError:
        return None
