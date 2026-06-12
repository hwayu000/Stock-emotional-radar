# -*- coding: utf-8 -*-
"""一次性腳本：用本機 git 憑證把 Telegram 設定寫入 GitHub repo 加密 Secrets"""
import base64
import json
import subprocess
import urllib.request

from nacl import encoding, public

REPO = "hwayu000/Stock-emotional-radar"

# 從 Git Credential Manager 取得 token（不落地、不列印）
out = subprocess.run(
    ["git", "credential", "fill"],
    input="protocol=https\nhost=github.com\n\n",
    capture_output=True, text=True, check=True,
).stdout
pat = next(l.split("=", 1)[1] for l in out.splitlines() if l.startswith("password="))

HEADERS = {
    "Authorization": f"token {pat}",
    "Accept": "application/vnd.github+json",
    "User-Agent": "ashdata-setup",
}


def api(path, method="GET", body=None):
    req = urllib.request.Request(
        f"https://api.github.com{path}",
        data=json.dumps(body).encode() if body else None,
        headers=HEADERS, method=method,
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read()
        return json.loads(raw) if raw else {}


# 取 repo 公鑰 → libsodium sealed box 加密 → 上傳
key = api(f"/repos/{REPO}/actions/secrets/public-key")
pub = public.PublicKey(key["key"].encode(), encoding.Base64Encoder())
box = public.SealedBox(pub)

with open("alert_config.json", encoding="utf-8") as f:
    cfg = json.load(f)

for name, value in [
    ("TELEGRAM_BOT_TOKEN", cfg["telegram_bot_token"]),
    ("TELEGRAM_CHAT_ID", cfg["telegram_chat_id"]),
]:
    enc = base64.b64encode(box.encrypt(value.encode())).decode()
    api(f"/repos/{REPO}/actions/secrets/{name}", "PUT",
        {"encrypted_value": enc, "key_id": key["key_id"]})
    print(f"Secret {name} 已設定")
