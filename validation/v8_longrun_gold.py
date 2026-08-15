# -*- coding: utf-8 -*-
"""驗證 8：黃金 22.6 年日線 —— 波動聚集基準與注意力訊號的增量價值

為什麼需要長歷史：注意力訊號目前只有一年樣本。但「事件後波動放大」
這件事，金融市場本來就有已知的波動聚集現象（volatility clustering）。
必須先用長歷史量化這個基準，才知道注意力訊號有沒有超越它的增量價值。

資料：Yahoo Finance GC=F 日線 5683 筆（2003-12-31 ~ 2026-08-14）
"""
import sys, io, json, os, datetime as dt, urllib.request
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, 'gold_daily.json')

if not os.path.exists(CACHE):
    # 首次執行自動抓取。注意：range=max 會回月線，必須用 period1/period2 指定日線
    print('首次執行，從 Yahoo Finance 抓取黃金日線歷史...', flush=True)
    p1 = int(dt.datetime(2004, 1, 1).timestamp())
    p2 = int(dt.datetime.now().timestamp())
    url = (f'https://query1.finance.yahoo.com/v8/finance/chart/GC=F'
           f'?period1={p1}&period2={p2}&interval=1d')
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    raw = json.loads(urllib.request.urlopen(req, timeout=90).read().decode())
    r = raw['chart']['result'][0]
    json.dump({'ts': r['timestamp'],
               'close': r['indicators']['quote'][0]['close']},
              open(CACHE, 'w'))
    print(f'已快取 {CACHE}', flush=True)

d = json.load(open(CACHE))
rows = [(dt.datetime.fromtimestamp(t, dt.UTC).date(), c)
        for t, c in zip(d['ts'], d['close']) if c is not None]
dates = [r[0] for r in rows]
px = np.array([r[1] for r in rows])
ret = np.diff(px) / px[:-1] * 100
absr = np.abs(ret)

print('=' * 78)
print('  黃金長歷史基準：%d 筆日線（%s ~ %s，%.1f 年）'
      % (len(px), dates[0], dates[-1], (dates[-1] - dates[0]).days / 365.25))
print('=' * 78)
print('  日均絕對報酬 %.3f%% ｜ 報酬標準差 %.3f%%' % (absr.mean(), ret.std(ddof=1)))

print('\n' + '=' * 78)
print('  A. 波動聚集：光看「昨天波動大」能預測多少？')
print('=' * 78)
print('  這是免費的基準線 —— 任何新指標都必須打敗它才有價值\n')
print('  分位門檻   事件數   1D放大   3D放大   5D放大   10D放大')
for qq in (0.90, 0.95, 0.99):
    th = np.quantile(absr, qq)
    hi = set(np.where(absr > th)[0])
    line = '  前%2d%%(>%.2f%%)  %4d  ' % (int((1 - qq) * 100), th, len(hi))
    for h in (1, 3, 5, 10):
        ev, base = [], []
        for i in range(len(px) - h):
            r = abs(px[i + h] / px[i] - 1) * 100
            base.append(r)
            if i in hi:
                ev.append(r)
        line += '  %5.2fx' % (np.mean(ev) / np.mean(base))
    print(line)

print('\n' + '=' * 78)
print('  B. 波動的可預測性有多久？（自相關衰減）')
print('=' * 78)
print('  lag   絕對報酬自相關   判讀')
for lag in (1, 2, 3, 5, 10, 20, 40, 60):
    if lag >= len(absr):
        break
    c = np.corrcoef(absr[:-lag], absr[lag:])[0, 1]
    bar = '#' * int(max(0, c * 100))
    tag = '強' if c > 0.15 else ('中' if c > 0.08 else '弱')
    print('  %3d      %+.4f        %s %s' % (lag, c, tag, bar))

print('''
  判讀：波動自相關衰減得比報酬慢得多，這正是波動聚集的來源。
        注意力訊號若要有價值，必須在「控制住當日波動」後仍有解釋力
        —— 見 v7_incremental.py 的層內比較。''')

print('\n' + '=' * 78)
print('  C. 極端事件回顧：22 年來最大的 15 次單日波動')
print('=' * 78)
idx = np.argsort(absr)[::-1][:15]
print('  日期          單日報酬    後5日累積    後20日累積')
for i in sorted(idx):
    r5 = (px[i + 5] / px[i] - 1) * 100 if i + 5 < len(px) else float('nan')
    r20 = (px[i + 20] / px[i] - 1) * 100 if i + 20 < len(px) else float('nan')
    print('  %s   %+7.2f%%    %+7.2f%%     %+7.2f%%'
          % (dates[i + 1], ret[i], r5, r20))
