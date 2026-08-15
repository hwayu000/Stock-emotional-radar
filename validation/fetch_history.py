# -*- coding: utf-8 -*-
"""抓取 GDELT 長期歷史資料（2017 起），供大樣本回測使用。

為什麼需要：目前回測樣本僅一年（362 天、事件 30~60 次），
散度方向的 5D 訊號（p=0.048）因樣本不足無法定案。

GDELT DOC 2.0 的資料起點實測為 2017 年初：
  2015-06 / 2016-06 -> "Invalid query start date"（拒絕）
  2017-06 / 2018-06 -> 可用
故可用期間約 9.6 年，樣本量提升約 9.6 倍。

限流很嚴（約 5 秒 1 次，長區間大型查詢常被直接拒絕），故：
  - 逐年分段抓取，每段間隔 PAUSE 秒
  - 成功回應寫入 cache_history/，中斷後重跑會從快取續傳
  - 429 指數退避重試

用法：
    py fetch_history.py            # 抓全部資產全部年份
    py fetch_history.py XAU        # 只抓黃金
"""
import hashlib
import json
import os
import sys
import io
import time
import urllib.error
import urllib.parse
import urllib.request

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, 'cache_history')

UA = {"User-Agent": "Mozilla/5.0 (attention-radar research script)"}
PAUSE = 22          # 請求間隔秒數
START_YEAR = 2017   # 實測的 GDELT 資料起點
END_YEAR = 2026

ASSETS = {
    "XAU":  '("gold price" OR "gold prices" OR "spot gold")',
    "NVDA": 'nvidia stock',
    "TSLA": 'tesla stock',
    "AAPL": 'apple stock',
    "MSFT": 'microsoft stock',
    "AMZN": 'amazon stock',
    "BTC":  'bitcoin',
}
MODES = ("timelinevol", "timelinetone")


def http_get(url, retries=10, backoff=20.0):
    req = urllib.request.Request(url, headers=UA)
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                raw = r.read().decode("utf-8", errors="replace")
            if raw.lstrip().startswith(("{", "[")):
                return raw
            if "Invalid query start date" in raw:
                return None          # 早於資料起點，不必重試
            # 其餘視為限流純文字
            wait = min(backoff * (1.4 ** attempt), 180)
            print(f"      限流，等 {wait:.0f}s 重試({attempt+1}/{retries})", flush=True)
            time.sleep(wait)
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < retries - 1:
                wait = min(backoff * (1.4 ** attempt), 180)
                print(f"      429，等 {wait:.0f}s 重試({attempt+1}/{retries})", flush=True)
                time.sleep(wait)
                continue
            raise
        except Exception as e:
            print(f"      錯誤 {e}，等 {backoff:.0f}s 重試", flush=True)
            time.sleep(backoff)
    return None


def fetch_year(aid, query, mode, year):
    """抓單一資產單一 mode 單一年份。回傳 [(date, value), ...]"""
    os.makedirs(CACHE, exist_ok=True)
    sig = hashlib.md5(f"{query}|{mode}|{year}".encode()).hexdigest()[:8]
    path = os.path.join(CACHE, f"{aid}_{mode}_{year}_{sig}.json")
    if os.path.exists(path):
        raw = open(path, encoding='utf-8').read()
    else:
        url = ("https://api.gdeltproject.org/api/v2/doc/doc?query="
               + urllib.parse.quote(query)
               + f"&mode={mode}"
               + f"&startdatetime={year}0101000000"
               + f"&enddatetime={year+1}0101000000&format=json")
        raw = http_get(url)
        if raw is None:
            return None
        open(path, 'w', encoding='utf-8').write(raw)
        time.sleep(PAUSE)
    try:
        pts = json.loads(raw)["timeline"][0]["data"]
        return [(p["date"][:8], p["value"]) for p in pts]
    except Exception:
        return None


def main():
    want = sys.argv[1:] or list(ASSETS)
    for aid in want:
        if aid not in ASSETS:
            print(f"未知資產 {aid}，略過")
            continue
        query = ASSETS[aid]
        for mode in MODES:
            got = {}
            for year in range(START_YEAR, END_YEAR + 1):
                rows = fetch_year(aid, query, mode, year)
                if rows is None:
                    print(f"  [{aid}/{mode}] {year} 無資料", flush=True)
                    continue
                got.update(dict(rows))
                print(f"  [{aid}/{mode}] {year} OK {len(rows)} 筆"
                      f"（累計 {len(got)}）", flush=True)
            if got:
                out = os.path.join(CACHE, f"merged_{aid}_{mode}.json")
                json.dump(got, open(out, 'w', encoding='utf-8'))
                days = sorted(got)
                print(f"  => {aid}/{mode} 合併 {len(got)} 天 "
                      f"({days[0]} ~ {days[-1]})", flush=True)


if __name__ == "__main__":
    main()
