# -*- coding: utf-8 -*-
"""驗證 1：注意力指標 (attn_z) 是否具備可用的預測力？

檢定三個互斥假設：
  H1 方向性：激增後價格傾向上漲(或下跌) -> 若成立可做方向交易
  H2 波動性：激增後波動放大不問方向     -> 若成立適合做波動/風控訊號
  H3 無訊號：與隨機無異                 -> 應廢棄或重新設計指標
"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, '.')
import numpy as np
from common import load_leaves, ffill, first_breaches, permutation_test, benjamini_hochberg, fmt_p

j, leaves = load_leaves()
H = [1, 3, 5, 10, 20]
THS = [2.0, 2.5, 3.0]

print('=' * 78)
print('  驗證 1：注意力指標 attn_z 的預測力')
print('  樣本：%d 資產 × %d 天，置換檢定 10000 次，BH-FDR 校正' % (len(leaves), len(leaves[0]['dates'])))
print('=' * 78)

def gather(th, h, mode):
    """mode='dir' 有號報酬 / 'abs' 絕對報酬(波動)"""
    ev_vals, pools, ks = [], [], []
    for a in leaves:
        z = a.get('attn_z') or []
        c = ffill(a.get('close') or [])
        n = len(a['dates'])
        idx = first_breaches([z[i] if i < len(z) else None for i in range(n)], th)
        f = (lambda x: x) if mode == 'dir' else abs
        valid = [f(c[i + h] / c[i] - 1) * 100
                 for i in range(n - h) if c[i] and c[i + h]]
        got = [f(c[i + h] / c[i] - 1) * 100
               for i in idx if i < n - h and c[i] and c[i + h]]
        ev_vals += got
        pools.append(np.array(valid))
        ks.append(len(got))
    return np.array(ev_vals), pools, ks

for mode, title, hyp in (('dir', '【H1 方向性】事件後有號報酬 (+上漲/-下跌)', 'H1'),
                         ('abs', '【H2 波動性】事件後絕對報酬 (不問方向)', 'H2')):
    print('\n' + title)
    print('  閾值  期間  樣本   實際值    隨機值   差異     p值     FDR')
    rows, ps = [], []
    for th in THS:
        for h in H:
            ev, pools, ks = gather(th, h, mode)
            if len(ev) < 10:
                continue
            obs = ev.mean()
            p, nm, ns = permutation_test(obs, pools, ks)
            rows.append((th, h, len(ev), obs, nm, p))
            ps.append(p)
    passed = benjamini_hochberg(ps) if ps else []
    for (th, h, n, obs, nm, p), ok in zip(rows, passed):
        print('  %.1f  %3dD  %4d  %+7.2f%%  %+7.2f%%  %+6.2f%%  %s  %s'
              % (th, h, n, obs, nm, obs - nm, fmt_p(p), '通過' if ok else '  -'))

print('\n' + '=' * 78)
print('判讀：H1 若通過極少 -> 不可做方向交易；H2 若廣泛通過 -> 應定位為波動/風控訊號')
print('=' * 78)
