# -*- coding: utf-8 -*-
"""
Attention Radar — 新聞注意力 / KL 散度 95 分位 / 轉移熵 指標管線
數據源（全部免費、免 API key）:
  - GDELT DOC 2.0 API : 新聞量 (timelinevol) + 語調 (timelinetone) + 頭條 (artlist)
  - Yahoo Finance     : 日線價格
輸出: ui/data.js  (window.RADAR_DATA = {...})

GDELT 限流嚴格（約 5 秒 1 次，且大型查詢常被拒）:
  - 成功回應快取到 cache/，重跑只抓缺的
  - 429 指數退避重試；若整輪被中斷，直接重跑即可從快取續傳
"""
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

import numpy as np
import pandas as pd

# ---------- 資產設定 ----------

XAU = {
    "id": "XAU", "name": "黃金 XAU",
    "query": '("gold price" OR "gold prices" OR "spot gold")',
    "yahoo": "GC=F",
    "note": "注意力來源：總經/地緣新聞（建議疊加 EPU、GPR 指數）",
}
BTC = {
    "id": "BTC", "name": "比特幣 BTC",
    "query": "bitcoin", "yahoo": "BTC-USD",
    "note": "幣圈可換 CryptoPanic / LunarCrush 取得社媒層數據",
}
# 美股候選池：掃描全部，按近 7 天新聞聲量取前三名做完整分析
# 查詢一律用「<公司名> stock」雙詞 AND：高頻單詞（apple/amazon）會被 GDELT
# 當成大型查詢拒絕，且五支用相同格式聲量才可比
US_CANDIDATES = [
    {"id": "NVDA", "name": "輝達 NVDA", "query": "nvidia stock", "yahoo": "NVDA"},
    {"id": "TSLA", "name": "特斯拉 TSLA", "query": "tesla stock", "yahoo": "TSLA"},
    {"id": "AAPL", "name": "蘋果 AAPL", "query": "apple stock", "yahoo": "AAPL"},
    {"id": "MSFT", "name": "微軟 MSFT", "query": "microsoft stock", "yahoo": "MSFT"},
    {"id": "AMZN", "name": "亞馬遜 AMZN", "query": "amazon stock", "yahoo": "AMZN"},
]
US_TOP_N = 3
US_NOTE = "美股可疊加 Alpha Vantage NEWS_SENTIMENT 的逐篇情緒分"

END = pd.Timestamp.now()
START = END - pd.Timedelta(days=365)
PAUSE = 20  # GDELT 請求間隔秒數
UA = {"User-Agent": "Mozilla/5.0 (attention-radar research script)"}


# ---------- HTTP / 快取 ----------

def http_get(url: str, retries: int = 14, backoff: float = 20.0, expect_json: bool = False) -> str:
    req = urllib.request.Request(url, headers=UA)
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read().decode("utf-8", errors="replace")
            # GDELT 有時用 HTTP 200 回傳限流純文字
            if expect_json and not raw.lstrip().startswith(("{", "[")):
                raise urllib.error.HTTPError(url, 429, raw[:80], None, None)
            return raw
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < retries - 1:
                wait = min(backoff * (1.5 ** attempt), 180)
                print(f"  限流(429)，等待 {wait:.0f}s 後重試...")
                time.sleep(wait)
                continue
            raise
    raise RuntimeError("unreachable")


def cached_gdelt(cache_name: str, url: str) -> str:
    os.makedirs("cache", exist_ok=True)
    path = f"cache/{cache_name}.json"
    if os.path.exists(path):
        print(f"  使用快取 {path}")
        with open(path, encoding="utf-8") as f:
            return f.read()
    raw = http_get(url, expect_json=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(raw)
    time.sleep(PAUSE)
    return raw


def gdelt_timeline(query: str, mode: str, cache_key: str) -> pd.Series:
    """date-indexed series。mode: timelinevol(新聞量%) / timelinetone(平均語調)"""
    sig = hashlib.md5(f"{query}|{mode}|{START:%Y%m%d}|{END:%Y%m%d}".encode()).hexdigest()[:10]
    url = (
        "https://api.gdeltproject.org/api/v2/doc/doc?query="
        + urllib.parse.quote(query)
        + f"&mode={mode}"
        + f"&startdatetime={START:%Y%m%d}000000&enddatetime={END:%Y%m%d}000000"
        + "&format=json"
    )
    raw = cached_gdelt(f"{cache_key}_{mode}_{sig}", url)
    pts = json.loads(raw)["timeline"][0]["data"]
    s = pd.Series(
        [p["value"] for p in pts],
        index=pd.to_datetime([p["date"] for p in pts]).date,
    )
    s.index = pd.to_datetime(s.index)
    return s.groupby(level=0).mean()


def gdelt_articles(query: str, cache_key: str, maxrecords: int = 75) -> list:
    """近 7 天英文頭條（ArtList 模式）"""
    sig = hashlib.md5(f"{query}|artlist|{END:%Y%m%d}".encode()).hexdigest()[:10]
    url = (
        "https://api.gdeltproject.org/api/v2/doc/doc?query="
        + urllib.parse.quote(query + " sourcelang:english")
        + f"&mode=artlist&maxrecords={maxrecords}&sort=datedesc"
        + f"&startdatetime={(END - pd.Timedelta(days=7)):%Y%m%d}000000"
        + f"&enddatetime={END:%Y%m%d}000000&format=json"
    )
    raw = cached_gdelt(f"{cache_key}_artlist_{sig}", url)
    arts = json.loads(raw).get("articles", [])
    seen, out = set(), []
    for a in arts:
        t = a.get("title", "").strip()
        if t and t.lower() not in seen:
            seen.add(t.lower())
            out.append({"title": t, "url": a.get("url", ""),
                        "domain": a.get("domain", ""), "date": a.get("seendate", "")[:8]})
    return out


def yahoo_close(symbol: str) -> pd.Series:
    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/"
        + urllib.parse.quote(symbol)
        + "?range=1y&interval=1d"
    )
    data = json.loads(http_get(url, expect_json=True))
    res = data["chart"]["result"][0]
    s = pd.Series(
        res["indicators"]["quote"][0]["close"],
        index=pd.to_datetime(res["timestamp"], unit="s").normalize(),
        dtype=float,
    )
    return s.dropna()


# ---------- 語料分類（金融情緒詞典；可換 FinBERT，見 README） ----------

POS_WORDS = {
    "surge", "surges", "surged", "rally", "rallies", "gain", "gains", "rise",
    "rises", "soar", "soars", "soared", "record", "beat", "beats", "bullish",
    "profit", "profits", "growth", "jump", "jumps", "boost", "boosts",
    "upgrade", "upgraded", "strong", "win", "wins", "recovery", "rebound",
    "optimism", "breakout", "outperform", "high", "highs", "milestone",
    "breakthrough", "top", "best", "buy", "adoption", "approval", "approve",
}
NEG_WORDS = {
    "crash", "crashes", "plunge", "plunges", "plunged", "fall", "falls",
    "drop", "drops", "slump", "slumps", "fear", "fears", "loss", "losses",
    "bearish", "decline", "declines", "selloff", "sell-off", "downgrade",
    "weak", "risk", "risks", "warning", "warns", "fraud", "lawsuit",
    "tumble", "tumbles", "dump", "panic", "recession", "manipulation",
    "probe", "fine", "fined", "crackdown", "ban", "bans", "hack", "hacked",
    "scam", "bubble", "liquidation", "default", "sink", "sinks", "worst",
}


def classify_headline(title: str):
    """回傳 (label, score)。score = (pos命中-neg命中)/詞數，純詞典法。"""
    words = re.findall(r"[a-z']+", title.lower())
    p = sum(w in POS_WORDS for w in words)
    n = sum(w in NEG_WORDS for w in words)
    if p > n:
        return "pos", round((p - n) / max(len(words), 1), 3)
    if n > p:
        return "neg", round((p - n) / max(len(words), 1), 3)
    return "neu", 0.0


# ---------- 指標 ----------

def attention_z(vol: pd.Series, win: int = 90) -> pd.Series:
    """新聞量相對自身 90 天基線的 z-score（注意力激增指標）"""
    mu = vol.rolling(win, min_periods=30).mean().shift(1)
    sd = vol.rolling(win, min_periods=30).std().shift(1)
    return ((vol - mu) / sd).replace([np.inf, -np.inf], np.nan)


def kl_series(tone: pd.Series, recent: int = 7, base: int = 90, bins: int = 5) -> pd.Series:
    """每日 KL 散度：近 7 天語調分佈 vs 之前 90 天基線分佈。"""
    edges = np.unique(np.quantile(tone.dropna(), np.linspace(0, 1, bins + 1)))
    if len(edges) < 3:
        return pd.Series(dtype=float)
    eps = 1e-6
    vals, idx, out = tone.values, tone.index, {}
    for t in range(recent + base, len(vals)):
        rec = vals[t - recent + 1: t + 1]
        bas = vals[t - recent - base + 1: t - recent + 1]
        p, _ = np.histogram(rec, bins=edges)
        q, _ = np.histogram(bas, bins=edges)
        p = (p + eps) / (p + eps).sum()
        q = (q + eps) / (q + eps).sum()
        out[idx[t]] = float(np.sum(p * np.log(p / q)))
    return pd.Series(out)


def rolling_q95(s: pd.Series, win: int = 180) -> pd.Series:
    return s.rolling(win, min_periods=60).quantile(0.95).shift(1)


def discretize(x: np.ndarray, k: int = 3) -> np.ndarray:
    qs = np.quantile(x, np.linspace(0, 1, k + 1)[1:-1])
    return np.digitize(x, qs)


def transfer_entropy(x: np.ndarray, y: np.ndarray, k: int = 3) -> float:
    """TE(X→Y) = I(Y_t ; X_{t-1} | Y_{t-1})，X/Y 已離散化"""
    yt, yp, xp = y[1:], y[:-1], x[:-1]
    joint = np.zeros((k, k, k))
    for a, b, c in zip(yt, yp, xp):
        joint[a, b, c] += 1
    joint /= len(yt)
    p_yp_xp = joint.sum(axis=0)
    p_yt_yp = joint.sum(axis=2)
    p_yp = joint.sum(axis=(0, 2))
    te = 0.0
    for a in range(k):
        for b in range(k):
            for c in range(k):
                pj = joint[a, b, c]
                if pj > 0 and p_yp_xp[b, c] > 0 and p_yt_yp[a, b] > 0 and p_yp[b] > 0:
                    te += pj * np.log((pj * p_yp[b]) / (p_yp_xp[b, c] * p_yt_yp[a, b]))
    return float(te)


def te_with_pvalue(x: np.ndarray, y: np.ndarray, k: int = 3, n_perm: int = 200, seed: int = 42):
    xd, yd = discretize(x, k), discretize(y, k)
    te = transfer_entropy(xd, yd, k)
    rng = np.random.default_rng(seed)
    null = [transfer_entropy(rng.permutation(xd), yd, k) for _ in range(n_perm)]
    p = float((np.sum(np.array(null) >= te) + 1) / (n_perm + 1))
    return te, p


# ---------- 組裝 ----------

def jlist(s: pd.Series):
    return [None if pd.isna(v) else round(float(v), 4) for v in s.values]


def analyze(meta: dict, vol: pd.Series, tone: pd.Series) -> dict:
    """指標計算 + 頭條分類 + 價格 + 轉移熵，回傳單一資產的完整 dict"""
    aid = meta["id"]

    print(f"[{aid}] 抓取近 7 天頭條語料...")
    try:
        articles = gdelt_articles(meta["query"], cache_key=aid)
        for art in articles:
            art["label"], art["score"] = classify_headline(art["title"])
    except Exception as e:
        print(f"  頭條抓取失敗: {e}")
        articles = []
    corpus_dist = {
        "pos": sum(x["label"] == "pos" for x in articles),
        "neu": sum(x["label"] == "neu" for x in articles),
        "neg": sum(x["label"] == "neg" for x in articles),
        "total": len(articles),
    }

    print(f"[{aid}] 抓取 Yahoo 價格...")
    try:
        close = yahoo_close(meta["yahoo"])
    except Exception as e:
        print(f"  價格抓取失敗: {e}，跳過轉移熵")
        close = None

    df = pd.DataFrame({"vol": vol, "tone": tone}).dropna()
    df["attn_z"] = attention_z(df["vol"])
    kl = kl_series(df["tone"])
    df["kl"] = kl
    df["kl_q95"] = rolling_q95(df["kl"].dropna()) if kl.notna().sum() > 60 else np.nan

    te_info = None
    if close is not None:
        ret = close.pct_change()
        pair = pd.DataFrame({"tone": df["tone"], "ret": ret}).dropna()
        if len(pair) > 120:
            te_sr, p_sr = te_with_pvalue(pair["tone"].values, pair["ret"].values)
            te_rs, p_rs = te_with_pvalue(pair["ret"].values, pair["tone"].values)
            te_info = {
                "news_to_price": round(te_sr, 4), "p_news_to_price": round(p_sr, 3),
                "price_to_news": round(te_rs, 4), "p_price_to_news": round(p_rs, 3),
                "n": len(pair),
            }
        df = df.join(close.rename("close"))

    last = df.dropna(subset=["kl"]).iloc[-1] if df["kl"].notna().any() else df.iloc[-1]
    alert_kl = bool(df["kl"].notna().any() and pd.notna(last.get("kl_q95"))
                    and last["kl"] > last["kl_q95"])
    alert_attn = bool(pd.notna(df["attn_z"].iloc[-1]) and df["attn_z"].iloc[-1] > 2.0)

    asset = {
        "id": aid, "name": meta["name"], "note": meta.get("note", ""),
        "dates": [d.strftime("%Y-%m-%d") for d in df.index],
        "vol": jlist(df["vol"]), "tone": jlist(df["tone"]),
        "attn_z": jlist(df["attn_z"]), "kl": jlist(df["kl"]),
        "kl_q95": jlist(df["kl_q95"]) if "kl_q95" in df else [],
        "close": jlist(df["close"]) if "close" in df else [],
        "te": te_info,
        "articles": articles[:40],
        "corpus_dist": corpus_dist,
        "alerts": {"kl_breach": alert_kl, "attention_spike": alert_attn},
        "latest": {
            "attn_z": None if pd.isna(df["attn_z"].iloc[-1]) else round(float(df["attn_z"].iloc[-1]), 2),
            "kl": None if pd.isna(last.get("kl", np.nan)) else round(float(last["kl"]), 4),
            "kl_q95": None if pd.isna(last.get("kl_q95", np.nan)) else round(float(last["kl_q95"]), 4),
            "tone": None if pd.isna(df["tone"].iloc[-1]) else round(float(df["tone"].iloc[-1]), 2),
        },
    }
    print(f"[{aid}] 完成: {len(df)} 天, KL警報={alert_kl}, 注意力警報={alert_attn}, 頭條={len(articles)} 篇")
    return asset


def fetch_pair(meta: dict):
    print(f"[{meta['id']}] 抓取 GDELT 新聞量...")
    vol = gdelt_timeline(meta["query"], "timelinevol", cache_key=meta["id"])
    print(f"[{meta['id']}] 抓取 GDELT 語調...")
    tone = gdelt_timeline(meta["query"], "timelinetone", cache_key=meta["id"])
    return vol, tone


# ---------- Telegram 警報 ----------

ALERT_CONFIG = "alert_config.json"
ATTN_THRESHOLD = 2.0


def flatten_assets(result: dict) -> list:
    out = []
    for a in result["assets"]:
        out.extend(a["members"] if a.get("is_group") else [a])
    return out


def prior_breach_date(dates, values, thresholds):
    """跳過最近的連續觸發段後，往回找上一次突破的日期（不含本次）"""
    n = len(values)

    def exceed(i):
        v = values[i]
        t = thresholds[i] if isinstance(thresholds, list) else thresholds
        if i >= len(dates):
            return False
        return v is not None and t is not None and v > t

    i = n - 1
    while i >= 0 and exceed(i):
        i -= 1
    while i >= 0 and not exceed(i):
        i -= 1
    return dates[i] if i >= 0 else None


def days_ago_str(date_str):
    if not date_str:
        return "近一年內首次"
    d = (pd.Timestamp.now().normalize() - pd.Timestamp(date_str)).days
    return f"{date_str}（{d} 天前）"


def build_alert_text(result: dict, prev: dict | None = None) -> str:
    prev = prev or {}
    blocks = []
    for a in flatten_assets(result):
        lines = []
        dates, latest = a["dates"], a["latest"]
        was = prev.get(a["id"], {})
        if a["alerts"].get("attention_spike") and not was.get("attention_spike"):
            prior = prior_breach_date(dates, a["attn_z"], ATTN_THRESHOLD)
            lines.append(
                "• 觸發：新聞注意力激增\n"
                f"  目前注意力指數：{latest['attn_z']}（警戒值 {ATTN_THRESHOLD:.2f}，平時約 0）\n"
                f"  上次同級激增：{days_ago_str(prior)}"
            )
        if a["alerts"].get("kl_breach") and not was.get("kl_breach"):
            prior = prior_breach_date(dates, a["kl"], a.get("kl_q95") or [])
            lines.append(
                "• 觸發：散度突破警戒線（媒體敘事異常轉變）\n"
                f"  目前散度：{latest['kl']}（警戒線 {latest['kl_q95']}）\n"
                f"  上次突破：{days_ago_str(prior)}"
            )
        if lines:
            lines.append(f"• 媒體語調：{latest['tone']}（正偏多／負偏空）")
            blocks.append(f"【{a['name']}】\n" + "\n".join(lines))
    if not blocks:
        return ""
    head = f"⚠️ Ashdata 注意力雷達 警報\n數據時間：{result['generated']}\n"
    return head + "\n\n" + "\n\n".join(blocks)


def send_telegram(text: str) -> bool:
    if not os.path.exists(ALERT_CONFIG):
        print("（未設定 alert_config.json，略過 Telegram 警報）")
        return False
    with open(ALERT_CONFIG, encoding="utf-8") as f:
        cfg = json.load(f)
    url = f"https://api.telegram.org/bot{cfg['telegram_bot_token']}/sendMessage"
    data = urllib.parse.urlencode(
        {"chat_id": cfg["telegram_chat_id"], "text": text}
    ).encode()
    req = urllib.request.Request(url, data=data, headers=UA)
    resp = json.loads(urllib.request.urlopen(req, timeout=30).read())
    return bool(resp.get("ok"))


def run_alerts(result: dict, prev: dict | None = None):
    text = build_alert_text(result, prev)
    if not text:
        print("無新警報觸發，不發送 Telegram")
        return
    ok = send_telegram(text)
    print("Telegram 警報已發送" if ok else "Telegram 發送失敗")


def load_prev_data() -> dict | None:
    """讀取上一輪 docs/data.js（用於失敗時保留舊資產）"""
    try:
        with open("docs/data.js", encoding="utf-8") as f:
            raw = f.read()
        return json.loads(raw[raw.index("=") + 1:].rstrip().rstrip(";"))
    except Exception:
        return None


def prev_asset(prev: dict | None, aid: str) -> dict | None:
    if not prev:
        return None
    for a in prev.get("assets", []):
        if a.get("id") == aid:
            return a
    return None


def main():
    prev = load_prev_data()
    result = {
        "generated": END.strftime("%Y-%m-%d %H:%M"),
        "generated_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "assets": [],
    }
    fresh_count = 0  # 本輪實際刷新的資產數

    def try_simple(meta: dict, aid: str):
        nonlocal fresh_count
        try:
            vol, tone = fetch_pair(meta)
            result["assets"].append(analyze(meta, vol, tone))
            fresh_count += 1
        except Exception as e:
            print(f"[{aid}] 本輪抓取失敗（{e}），沿用上次數據")
            old = prev_asset(prev, aid)
            if old:
                result["assets"].append(old)
            else:
                print(f"[{aid}] 也沒有上次數據可沿用，跳過")

    # --- 黃金 ---
    try_simple(XAU, "XAU")

    # --- 美股：掃描候選池 → 近 7 天聲量前三名做完整分析 ---
    print(f"\n[US] 掃描 {len(US_CANDIDATES)} 支候選，按近 7 天新聞聲量排名...")
    scans = []
    for c in US_CANDIDATES:
        print(f"[US:{c['id']}] 抓取新聞量...")
        try:
            v = gdelt_timeline(c["query"], "timelinevol", cache_key=c["id"])
        except Exception as e:
            print(f"  {c['id']} 抓取失敗（{e}），跳過此候選")
            continue
        hot = float(v.tail(7).mean())
        scans.append((hot, c, v))
        print(f"  {c['id']} 近7天平均聲量 = {hot:.4f}")

    if scans:
        scans.sort(key=lambda x: -x[0])
        max_hot = scans[0][0] or 1.0
        members = []
        for rank, (hot, c, v) in enumerate(scans[:US_TOP_N], 1):
            print(f"\n[US] 第 {rank} 名: {c['id']}")
            try:
                print(f"[{c['id']}] 抓取 GDELT 語調...")
                t = gdelt_timeline(c["query"], "timelinetone", cache_key=c["id"])
                a = analyze({**c, "note": US_NOTE}, v, t)
                a["hotness"] = round(hot, 4)
                a["hotness_pct"] = round(hot / max_hot * 100, 1)
                a["rank"] = rank
                members.append(a)
            except Exception as e:
                print(f"  {c['id']} 完整分析失敗（{e}），跳過")
        if members:
            result["assets"].append({
                "id": "US", "name": "美股 US", "is_group": True,
                "members": members,
                "scanned": [{"id": c["id"], "name": c["name"], "hotness": round(h, 4)}
                            for h, c, _ in scans],
                "alerts": {
                    "kl_breach": any(m["alerts"]["kl_breach"] for m in members),
                    "attention_spike": any(m["alerts"]["attention_spike"] for m in members),
                },
            })
            fresh_count += 1
        else:
            print("[US] 本輪美股全部失敗，沿用上次數據")
            old = prev_asset(prev, "US")
            if old:
                result["assets"].append(old)
    else:
        print("[US] 候選掃描全部失敗，沿用上次數據")
        old = prev_asset(prev, "US")
        if old:
            result["assets"].append(old)

    # --- 比特幣 ---
    try_simple(BTC, "BTC")

    if fresh_count == 0:
        raise RuntimeError("本輪所有資產皆失敗，不覆寫 docs/data.js（保留上次正常數據）")

    # 用上一輪的警報狀態做去重（用於 Telegram）
    prev_alerts = {a["id"]: a["alerts"] for a in flatten_assets(prev)} if prev else {}
    os.makedirs("docs", exist_ok=True)
    with open("docs/data.js", "w", encoding="utf-8") as f:
        f.write("window.RADAR_DATA = ")
        json.dump(result, f, ensure_ascii=False)
        f.write(";")
    print(f"\n已輸出 docs/data.js（本輪實際刷新 {fresh_count} 個資產組）")
    run_alerts(result, prev_alerts)


def alert_only():
    """py radar.py --alert-only：不重抓數據，直接用現有 docs/data.js 檢查並發警報"""
    with open("docs/data.js", encoding="utf-8") as f:
        raw = f.read()
    result = json.loads(raw[raw.index("=") + 1:].rstrip().rstrip(";"))
    run_alerts(result)


if __name__ == "__main__":
    import sys
    if "--alert-only" in sys.argv:
        alert_only()
    else:
        main()
