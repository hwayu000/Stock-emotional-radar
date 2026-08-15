# -*- coding: utf-8 -*-
"""驗證 12：大樣本回測（2018-01 ~ 2026-08，約 8.6 年）

取代先前僅一年樣本的所有結論。核心新增「樣本外驗證」——
把期間切兩半，前半校準、後半獨立驗證，這是識破過度擬合唯一有效的方法。

資料來源：cache_history/merged_<ID>_<mode>.json（由 fetch_history.py 抓取）
          價格：Yahoo Finance 日線

用法：
    py v12_bigsample.py            # 跑所有已完成抓取的資產
    py v12_bigsample.py XAU        # 只跑黃金
"""
import sys, io, json, os, datetime as dt, urllib.request
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, 'cache_history')
PXCACHE = os.path.join(HERE, 'px_cache')
rng = np.random.default_rng(12)

YAHOO = {'XAU': 'GC=F', 'BTC': 'BTC-USD', 'NVDA': 'NVDA',
         'AAPL': 'AAPL', 'MSFT': 'MSFT'}


def load_gdelt(aid, mode):
    p = os.path.join(CACHE, f'merged_{aid}_{mode}.json')
    if not os.path.exists(p):
        return None
    raw = json.load(open(p, encoding='utf-8'))
    # key 形如 20180101
    out = {}
    for k, v in raw.items():
        out[f'{k[:4]}-{k[4:6]}-{k[6:8]}'] = v
    return out


def load_px(aid):
    os.makedirs(PXCACHE, exist_ok=True)
    p = os.path.join(PXCACHE, f'{aid}.json')
    if os.path.exists(p):
        d = json.load(open(p))
    else:
        sym = YAHOO[aid]
        p1 = int(dt.datetime(2017, 6, 1).timestamp())
        p2 = int(dt.datetime.now().timestamp())
        url = (f'https://query1.finance.yahoo.com/v8/finance/chart/'
               f'{urllib.parse.quote(sym)}?period1={p1}&period2={p2}&interval=1d')
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        r = json.loads(urllib.request.urlopen(req, timeout=90).read().decode())
        res = r['chart']['result'][0]
        d = {'ts': res['timestamp'], 'close': res['indicators']['quote'][0]['close']}
        json.dump(d, open(p, 'w'))
    out = {}
    for t, c in zip(d['ts'], d['close']):
        if c is not None:
            out[dt.datetime.fromtimestamp(t, dt.UTC).strftime('%Y-%m-%d')] = c
    return out


def build(aid):
    vol = load_gdelt(aid, 'timelinevol')
    if not vol:
        return None
    dates = sorted(vol)
    # vol=0 視為缺漏（GDELT 該日故障），與 radar.py 一致
    v = np.array([vol[d] if vol[d] > 0 else np.nan for d in dates])
    # attn_z：90 天滾動基線，shift(1) 防前視
    z = np.full(len(v), np.nan)
    for i in range(90, len(v)):
        w = v[i - 90:i]
        w = w[~np.isnan(w)]
        if len(w) < 30 or np.isnan(v[i]):
            continue
        sd = w.std(ddof=1)
        if sd > 0:
            z[i] = (v[i] - w.mean()) / sd
    px = load_px(aid)
    c, last = [], None
    for d in dates:
        if d in px:
            last = px[d]
        c.append(last)
    return dates, v, z, c


def events(z, th):
    ev, prev = [], False
    for i, x in enumerate(z):
        hot = (not np.isnan(x)) and x > th
        if hot and not prev:
            ev.append(i)
        prev = hot
    return ev


def amp(c, idx, h, lo=None, hi=None):
    """事件後 h 日的絕對報酬；lo/hi 限定索引範圍（供樣本內外切分）"""
    out = []
    for i in idx:
        if lo is not None and i < lo:
            continue
        if hi is not None and i >= hi:
            continue
        if i + h < len(c) and c[i] and c[i + h]:
            out.append(abs(c[i + h] / c[i] - 1) * 100)
    return out


def baseline(c, h, lo=0, hi=None):
    hi = hi if hi is not None else len(c)
    return [abs(c[i + h] / c[i] - 1) * 100
            for i in range(lo, min(hi, len(c) - h)) if c[i] and c[i + h]]


def perm_p(obs, pool, k, n_iter=10000):
    if k == 0 or len(pool) < k:
        return float('nan')
    pool = np.array(pool)
    null = [pool[rng.choice(len(pool), k, replace=False)].mean() for _ in range(n_iter)]
    return float((np.array(null) >= obs).mean())


def report(aid):
    r = build(aid)
    if not r:
        print('  [%s] 無歷史資料，略過' % aid)
        return
    dates, v, z, c = r
    valid = int((~np.isnan(z)).sum())
    print('=' * 84)
    print('  【%s】大樣本回測  %s ~ %s（%d 天，attn_z 有效 %d 天）'
          % (aid, dates[0], dates[-1], len(dates), valid))
    print('=' * 84)

    for th in (2.0, 2.5, 3.0):
        ev = events(z, th)
        print('\n  ── 閾值 z>%.1f：%d 個事件 ──' % (th, len(ev)))
        print('    期間   事件數   事件後波幅   常態波幅   放大    p值')
        for h in (1, 3, 5, 10):
            a = amp(c, ev, h)
            b = baseline(c, h)
            if len(a) < 5:
                continue
            o, bm = np.mean(a), np.mean(b)
            p = perm_p(o, b, len(a))
            print('    %3dD    %4d      %6.2f%%    %6.2f%%   %.2fx  %s'
                  % (h, len(a), o, bm, o / bm,
                     ('<0.001' if p < 0.001 else '%.4f' % p)))

    # ── 樣本外驗證 ──
    split = len(dates) // 2
    print('\n  ── 樣本外驗證（前半校準 / 後半獨立驗證）──')
    print('    前半 %s ~ %s ｜ 後半 %s ~ %s'
          % (dates[0], dates[split - 1], dates[split], dates[-1]))
    print('    閾值  期間  前半放大(n)      後半放大(n)      後半p值   判定')
    for th in (2.5, 3.0):
        ev = events(z, th)
        for h in (1, 3, 5):
            a1 = amp(c, ev, h, hi=split)
            a2 = amp(c, ev, h, lo=split)
            b1 = baseline(c, h, 0, split)
            b2 = baseline(c, h, split)
            if len(a1) < 3 or len(a2) < 3:
                continue
            r1 = np.mean(a1) / np.mean(b1)
            r2 = np.mean(a2) / np.mean(b2)
            p2 = perm_p(np.mean(a2), b2, len(a2))
            ok = '通過' if (p2 < 0.05 and r2 > 1.0) else '未通過'
            print('    %.1f  %3dD   %.2fx (%2d)      %.2fx (%2d)      %6s   %s'
                  % (th, h, r1, len(a1), r2, len(a2),
                     ('<.001' if p2 < 0.001 else '%.3f' % p2), ok))
    print()


def main():
    want = sys.argv[1:] or ['XAU', 'BTC', 'NVDA', 'AAPL', 'MSFT']
    import urllib.parse
    globals()['urllib'].parse = urllib.parse
    for aid in want:
        try:
            report(aid)
        except Exception as e:
            print('  [%s] 失敗：%s' % (aid, e))


if __name__ == '__main__':
    import urllib.parse
    main()
