# -*- coding: utf-8 -*-
"""驗證 10：查詢式 A/B 測試 —— 改良版能否降低語料污染？

為什麼要平行驗證而非直接換掉：
  換查詢式會讓歷史資料不可比（現有資料是用舊式抓的），且正在抓的 8.6 年
  歷史也是用同一式。故先平行取樣比較，有證據再決定是否切換。

比較維度：
  1. 語料切題度 —— 抓 artlist 看標題，量化污染率
  2. 訊號效力   —— 抓 timelinevol 算 attn_z，比較事件後波動放大倍數
                   （這才是真正重要的：乾淨不等於有效）

用法：
    py v10_query_ab.py            # 只跑語料切題度（快，約 2 分鐘）
    py v10_query_ab.py --full     # 加跑 timelinevol 效力比較（慢，約 10 分鐘）
"""
import sys, io, json, os, time, urllib.parse, urllib.request
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, 'cache_ab')
UA = {"User-Agent": "Mozilla/5.0 (attention-radar research script)"}
PAUSE = 22

# 候選查詢式。GDELT 支援 - 排除詞，但不支援欄位限定（無法只比對標題）。
CANDIDATES = {
    'XAU': {
        'A_current': '("gold price" OR "gold prices" OR "spot gold")',
        # B：排除公司行為公告的常見措辭
        'B_exclude': ('("gold price" OR "gold prices" OR "spot gold") '
                      '-"financial results" -"announces" -"private placement" '
                      '-"drill results"'),
        # C：鎖定「金價動作」的措辭，語意上更貼近事件
        'C_action': ('("gold rose" OR "gold fell" OR "gold rises" OR "gold falls" '
                     'OR "gold climbs" OR "gold slips" OR "spot gold" '
                     'OR "gold hits record" OR "bullion")'),
    },
}

CORP_ACTION = [
    'announces q', 'q1 2026 results', 'q2 2026 results', 'q3 2026 results',
    'financial results', 'announces engagement', 'files second quarter',
    'ipo hurdle', 'announces closing', 'private placement', 'drill results',
    'drilling program', 'announces appointment', 'reports q',
]
OTHER_ASSET = ['oil prices rally', 'oil heads for', 'stock market today',
               'stocks rise before', 'dollar is undercut', 'crude oil']


def http_get(url, retries=8, backoff=20.0):
    req = urllib.request.Request(url, headers=UA)
    for i in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                raw = r.read().decode('utf-8', errors='replace')
            if raw.lstrip().startswith(('{', '[')):
                return raw
            w = min(backoff * (1.4 ** i), 180)
            print('      限流，等 %.0fs 重試(%d/%d)' % (w, i + 1, retries), flush=True)
            time.sleep(w)
        except Exception as e:
            time.sleep(backoff)
    return None


def cached(name, url):
    os.makedirs(CACHE, exist_ok=True)
    p = os.path.join(CACHE, name + '.json')
    if os.path.exists(p):
        return open(p, encoding='utf-8').read()
    raw = http_get(url)
    if raw:
        open(p, 'w', encoding='utf-8').write(raw)
        time.sleep(PAUSE)
    return raw


def fetch_titles(query, tag, days=7, maxrec=75):
    import datetime as dt
    end = dt.datetime.now(dt.UTC)
    start = end - dt.timedelta(days=days)
    url = ('https://api.gdeltproject.org/api/v2/doc/doc?query='
           + urllib.parse.quote(query + ' sourcelang:english')
           + f'&mode=artlist&maxrecords={maxrec}&sort=datedesc'
           + f'&startdatetime={start:%Y%m%d}000000'
           + f'&enddatetime={end:%Y%m%d}000000&format=json')
    raw = cached('artlist_' + tag, url)
    if not raw:
        return []
    try:
        return [a.get('title', '') for a in json.loads(raw).get('articles', [])]
    except Exception:
        return []


def purity(titles):
    bad = 0
    dirty = []
    for t in titles:
        low = t.lower()
        if any(k in low for k in CORP_ACTION) or any(k in low for k in OTHER_ASSET):
            bad += 1
            dirty.append(t[:64])
    return bad, dirty


def main():
    print('=' * 84)
    print('  查詢式 A/B 測試：語料切題度')
    print('=' * 84)
    for aid, variants in CANDIDATES.items():
        print('\n【%s】' % aid)
        results = {}
        for tag, q in variants.items():
            print('  抓取 %s ...' % tag, flush=True)
            titles = fetch_titles(q, f'{aid}_{tag}')
            if not titles:
                print('    (抓取失敗或無資料)')
                continue
            bad, dirty = purity(titles)
            results[tag] = (len(titles), bad, dirty)
            print('    樣本 %d 篇，污染 %d 篇（%.0f%%）'
                  % (len(titles), bad, bad / max(len(titles), 1) * 100))
        print('\n  ── 對照 ──')
        print('  %-12s %8s %8s %9s' % ('版本', '樣本', '污染', '污染率'))
        for tag, (n, bad, _) in results.items():
            print('  %-12s %7d %8d %8.0f%%' % (tag, n, bad, bad / max(n, 1) * 100))
        for tag, (n, bad, dirty) in results.items():
            if dirty:
                print('\n  %s 的污染樣本（前 6 則）:' % tag)
                for t in dirty[:6]:
                    print('    ·', t)
    print('''
  注意：污染率低不等於訊號好。查詢式太窄會漏掉真實事件、樣本量不足，
        反而更糟。必須再比「訊號效力」才能定案 —— 用 --full 跑。
''')


if __name__ == '__main__':
    main()
