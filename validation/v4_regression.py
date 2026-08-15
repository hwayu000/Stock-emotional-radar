# -*- coding: utf-8 -*-
"""驗證 4：迴歸測試 —— 新舊警報規則在歷史上的實際差異

回答：改了之後會少發多少警報？少發的是不是真的假訊號？
"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, '.')
import numpy as np
from common import load_leaves, ffill, first_breaches

j, leaves = load_leaves()

print('=' * 78)
print('  迴歸測試：舊規則(z>2.0 + KL突破) vs 新規則(z>2.5，KL不觸發)')
print('=' * 78)
print('  資產    舊注意力警報  新注意力警報  減少   舊KL警報  新KL警報')
tot_old = tot_new = tot_klo = 0
for a in leaves:
    z = a.get('attn_z') or []
    kl = a.get('kl') or []
    q = a.get('kl_q95') or []
    old_a = len(first_breaches(z, 2.0))
    new_a = len(first_breaches(z, 2.5))
    klo = len(first_breaches(kl, [q[i] if i < len(q) else None for i in range(len(kl))]))
    tot_old += old_a; tot_new += new_a; tot_klo += klo
    print('  %-6s   %3d          %3d        -%d      %3d       0'
          % (a['id'], old_a, new_a, old_a - new_a, klo))
print('  ' + '-' * 66)
print('  合計     %3d          %3d        -%d      %3d       0'
      % (tot_old, tot_new, tot_old - tot_new, tot_klo))

print('''
  一年內警報總量：舊 %d 則 -> 新 %d 則（減少 %.0f%%）
    其中注意力警報 %d -> %d，KL 警報 %d -> 0（因無統計顯著性而移除）
''' % (tot_old + tot_klo, tot_new, (1 - tot_new / (tot_old + tot_klo)) * 100,
       tot_old, tot_new, tot_klo))

print('=' * 78)
print('  被濾掉的注意力事件（2.0<z<=2.5）是不是真的比較沒用？')
print('=' * 78)
H = [1, 3, 5]
band, strong, base = {h: [] for h in H}, {h: [] for h in H}, {h: [] for h in H}
for a in leaves:
    z = a.get('attn_z') or []
    c = ffill(a.get('close') or [])
    n = len(a['dates'])
    ev20 = set(first_breaches(z, 2.0))
    ev25 = set(first_breaches(z, 2.5))
    only_band = ev20 - ev25
    for h in H:
        for i in range(n - h):
            if not (c[i] and c[i + h]):
                continue
            r = abs(c[i + h] / c[i] - 1) * 100
            if i in only_band: band[h].append(r)
            elif i in ev25: strong[h].append(r)
            else: base[h].append(r)
print('  期間   弱訊號(2.0~2.5)   強訊號(>2.5)   常態     弱/常態  強/常態')
for h in H:
    b, s, bs = np.mean(band[h]), np.mean(strong[h]), np.mean(base[h])
    print('  %3dD      %6.2f%%(%d)      %6.2f%%(%d)   %6.2f%%    %.2fx    %.2fx'
          % (h, b, len(band[h]), s, len(strong[h]), bs, b / bs, s / bs))
print('''
  判讀：若「弱訊號/常態」接近 1.0，代表這批被濾掉的警報確實沒有訊號，
        移除它們是提升訊噪比而非丟失資訊。''')
