# -*- coding: utf-8 -*-
"""驗證 2：KL 散度門檻 —— 舊法(rolling q95) vs 新法(EWM+2sd)

檢定：
  A. 門檻凍結診斷：舊法警戒線有多少比例的日子是「動都不動」的
  B. 訊號有效性  ：兩法各自的突破事件，是否真的預示波動放大
  C. 敏感度分析  ：新法的 k 值(2.0/2.5/3.0)與 span(60/90/120) 該怎麼選
"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, '.')
import numpy as np, pandas as pd
from common import load_leaves, ffill, first_breaches, permutation_test, fmt_p

j, leaves = load_leaves()

def kl_ser(a):
    return pd.Series([np.nan if v is None else v for v in a['kl']],
                     index=pd.to_datetime(a['dates'])).dropna()

print('=' * 78)
print('  驗證 2A：舊門檻「凍結」診斷')
print('  rolling(180).quantile(0.95) 的致命問題：分位數是排序取位置，')
print('  一批極值只要還在窗內，門檻就固定在同一數值不動')
print('=' * 78)
print('  資產    有效天數  門檻不變的天數   最長連續凍結   凍結期間門檻值')
for a in leaves:
    s = kl_ser(a)
    old = s.rolling(180, min_periods=60).quantile(0.95).shift(1).dropna()
    d = old.diff().abs()
    frozen = (d < 1e-9)
    # 最長連續凍結
    best = cur = 0; bestval = None
    for i, f in enumerate(frozen):
        if f:
            cur += 1
            if cur > best:
                best = cur; bestval = old.iloc[i]
        else:
            cur = 0
    print('  %-6s  %4d      %4d (%.0f%%)        %3d 天        %s'
          % (a['id'], len(old), frozen.sum(), frozen.sum() / len(old) * 100,
             best, ('%.4f' % bestval) if bestval is not None else 'n/a'))

print('\n' + '=' * 78)
print('  驗證 2B：兩法突破事件的訊號有效性（事件後波動放大倍數）')
print('=' * 78)
H = [1, 3, 5]

def test_method(name, thfunc):
    print('\n  --- %s ---' % name)
    print('    期間  事件數   事件後波幅  常態波幅  放大   p值')
    for h in H:
        ev_vals, pools, ks = [], [], []
        for a in leaves:
            s = kl_ser(a)
            th = thfunc(s)
            dates = list(s.index)
            c_all = ffill(a.get('close') or [])
            dmap = {pd.Timestamp(d): i for i, d in enumerate(pd.to_datetime(a['dates']))}
            vals = list(s.values)
            thv = list(th.reindex(s.index).values)
            idx = first_breaches(vals, thv)
            n = len(a['dates'])
            valid = [abs(c_all[i + h] / c_all[i] - 1) * 100
                     for i in range(n - h) if c_all[i] and c_all[i + h]]
            got = []
            for e in idx:
                i = dmap.get(dates[e])
                if i is not None and i < n - h and c_all[i] and c_all[i + h]:
                    got.append(abs(c_all[i + h] / c_all[i] - 1) * 100)
            ev_vals += got; pools.append(np.array(valid)); ks.append(len(got))
        if len(ev_vals) < 5:
            print('    %3dD  樣本不足(%d)' % (h, len(ev_vals))); continue
        obs = np.mean(ev_vals)
        p, nm, _ = permutation_test(obs, pools, ks)
        print('    %3dD   %3d     %6.2f%%    %6.2f%%   %.2fx  %s'
              % (h, len(ev_vals), obs, nm, obs / nm, fmt_p(p)))

test_method('舊法 rolling(180).q95',
            lambda s: s.rolling(180, min_periods=60).quantile(0.95).shift(1))
test_method('新法 EWM(span=90)+2.0sd',
            lambda s: (s.ewm(span=90, min_periods=30).mean()
                       + 2.0 * s.ewm(span=90, min_periods=30).std()).shift(1))
