# -*- coding: utf-8 -*-
"""驗證 7：注意力訊號有沒有「增量價值」？

背景：金融市場有已知的波動聚集現象（volatility clustering）——
昨天波動大，今天波動就傾向大。長歷史黃金(22.6年)實測 1D 放大 4.04x，
遠強於注意力訊號的 1.79x。

若注意力激增只是「伴隨當天大波動」，那它可能沒有獨立資訊，
只是重新發現了波動聚集。必須控制住這個混淆因子。

作法：條件化比較 —— 在「當日波動水準相同」的子集內，
比較有無注意力激增的後續波動差異。
"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, '.')
import numpy as np
from common import load_leaves, ffill, first_breaches, permutation_test, fmt_p

j, leaves = load_leaves()
TH = 2.5
H = [1, 3, 5]

print('=' * 78)
print('  注意力激增 vs 波動聚集：誰在解釋事件後的波動放大？')
print('=' * 78)

# 收集每個資產每一天的 (當日絕對報酬, 是否注意力激增, 後續波幅)
recs = []
for a in leaves:
    z = a.get('attn_z') or []
    c = ffill(a.get('close') or [])
    n = len(a['dates'])
    ev = set(first_breaches(z, TH))
    for i in range(1, n - max(H)):
        if not (c[i] and c[i - 1]):
            continue
        today = abs(c[i] / c[i - 1] - 1) * 100
        fut = {}
        ok = True
        for h in H:
            if c[i + h] and c[i]:
                fut[h] = abs(c[i + h] / c[i] - 1) * 100
            else:
                ok = False
        if ok:
            recs.append({'aid': a['id'], 'today': today, 'spike': i in ev, 'fut': fut})

print('  總樣本 %d 天，其中注意力激增 %d 天'
      % (len(recs), sum(r['spike'] for r in recs)))

# 依當日波動分三層，層內比較
allt = np.array([r['today'] for r in recs])
lo, hi = np.quantile(allt, [0.5, 0.9])
print('  當日波動分層門檻：低 <%.2f%% ｜ 中 %.2f~%.2f%% ｜ 高 >%.2f%%'
      % (lo, lo, hi, hi))

def layer(r):
    return '低' if r['today'] < lo else ('中' if r['today'] < hi else '高')

print('\n  ── 層內比較：當日波動相近時，有無注意力激增的後續波幅 ──')
print('  當日波動層   期間   激增日(n)      無激增(n)       差異    倍數')
for lname in ('低', '中', '高'):
    sub = [r for r in recs if layer(r) == lname]
    sp = [r for r in sub if r['spike']]
    ns = [r for r in sub if not r['spike']]
    if len(sp) < 5:
        print('  %-8s   樣本不足 (激增僅 %d 天)' % (lname, len(sp)))
        continue
    for h in H:
        a_ = np.mean([r['fut'][h] for r in sp])
        b_ = np.mean([r['fut'][h] for r in ns])
        print('  %-8s   %3dD   %6.2f%%(%3d)   %6.2f%%(%4d)   %+5.2f%%   %.2fx'
              % (lname if h == H[0] else '', h, a_, len(sp), b_, len(ns), a_ - b_, a_ / b_))

print('''
  判讀：若各層內激增日的倍數仍明顯 >1.0，代表注意力訊號有超越波動聚集的
        增量價值；若層內倍數趨近 1.0，代表原本的 1.79x 主要來自
        「激增日剛好也是大波動日」這個混淆。''')

print('\n' + '=' * 78)
print('  交叉檢定：注意力激增日，當天本身是不是就已經是大波動日？')
print('=' * 78)
sp_today = [r['today'] for r in recs if r['spike']]
ns_today = [r['today'] for r in recs if not r['spike']]
print('  激增日當天平均波動  %.3f%%' % np.mean(sp_today))
print('  非激增日當天平均波動 %.3f%%' % np.mean(ns_today))
print('  比值 %.2fx  -> %s'
      % (np.mean(sp_today) / np.mean(ns_today),
         '激增日確實伴隨大波動，混淆存在' if np.mean(sp_today) / np.mean(ns_today) > 1.2
         else '激增日當天波動與平時相近，混淆有限'))
