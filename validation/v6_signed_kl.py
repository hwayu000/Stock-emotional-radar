# -*- coding: utf-8 -*-
"""有向散度（signed KL）嚴格檢定 —— P1 假設是真訊號還是小樣本假象？

作法：把 KL 乘上語調變化方向，得到有向指標。
  signed_kl > 0 : 敘事顯著轉樂觀
  signed_kl < 0 : 敘事顯著轉悲觀
檢定它能否預測「方向性報酬」（這是 attn_z 做不到的事）。

嚴格性：不放寬門檻湊樣本、置換檢定、報告樣本數與信賴區間。
"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, '.')
import numpy as np, pandas as pd
from common import load_leaves, ffill, first_breaches, permutation_test, fmt_p
rng = np.random.default_rng(7)

j, leaves = load_leaves()

def build(a):
    """回傳 (索引, signed_kl, 突破事件索引, 價格)"""
    d, kl, q = a['dates'], a['kl'], a.get('kl_q95') or []
    tone, c = a['tone'], ffill(a.get('close') or [])
    n = len(d)
    ev = first_breaches(kl, [q[i] if i < len(q) else None for i in range(len(kl))])
    signed = []
    for i in ev:
        rec = [t for t in tone[max(0,i-6):i+1] if t is not None]
        bas = [t for t in tone[max(0,i-96):i-6] if t is not None]
        if not rec or not bas: continue
        signed.append((i, np.mean(rec) - np.mean(bas)))
    return n, signed, c

H = [1,3,5,10]
print('=' * 78)
print('  有向散度：敘事轉悲觀 vs 轉樂觀，之後價格怎麼走')
print('=' * 78)

pos, neg, pool = {h:[] for h in H}, {h:[] for h in H}, {h:[] for h in H}
pools_by_asset = {h:[] for h in H}
for a in leaves:
    n, signed, c = build(a)
    for h in H:
        valid = [(c[i+h]/c[i]-1)*100 for i in range(n-h) if c[i] and c[i+h]]
        pools_by_asset[h].append((np.array(valid), 0))
        pool[h] += valid
    for i, dirv in signed:
        for h in H:
            if i < n-h and c[i] and c[i+h]:
                (pos if dirv>0 else neg)[h].append((c[i+h]/c[i]-1)*100)

print('  期間   轉悲觀後報酬(n)      轉樂觀後報酬(n)     基準      悲觀-樂觀')
for h in H:
    p_, n_, b_ = pos[h], neg[h], pool[h]
    if not p_ or not n_: continue
    se = np.std(n_,ddof=1)/np.sqrt(len(n_)) if len(n_)>1 else float('nan')
    print('  %3dD   %+6.2f%% (n=%2d)±%.2f   %+6.2f%% (n=%2d)      %+5.2f%%   %+6.2f%%'
          % (h, np.mean(n_), len(n_), 1.96*se, np.mean(p_), len(p_), np.mean(b_),
             np.mean(n_)-np.mean(p_)))

print('\n' + '=' * 78)
print('  置換檢定：「轉悲觀後上漲」是真的嗎？（把方向標籤隨機打散）')
print('=' * 78)
print('  期間   實際(悲觀-樂觀)   隨機打散平均   p值      判定')
for h in H:
    p_, n_ = pos[h], neg[h]
    if len(p_)<3 or len(n_)<3: continue
    obs = np.mean(n_) - np.mean(p_)
    allv = np.array(p_ + n_); k = len(n_)
    null = []
    for _ in range(20000):
        idx = rng.permutation(len(allv))
        null.append(allv[idx[:k]].mean() - allv[idx[k:]].mean())
    null = np.array(null)
    pv = float((np.abs(null) >= abs(obs)).mean())   # 雙尾
    mark = '顯著' if pv < 0.05 else ('邊際' if pv < 0.10 else '不顯著')
    print('  %3dD    %+6.2f%%          %+6.2f%%       %s   %s'
          % (h, obs, null.mean(), fmt_p(pv), mark))

print('''
  註：雙尾檢定。樣本僅 8~10 次事件，即使 p<0.05 也屬小樣本結果，
      需累積更多資料才能確認穩定性。''')
