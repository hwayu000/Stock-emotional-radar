# -*- coding: utf-8 -*-
"""驗證 11：財報季是否系統性墊高新聞量？

動機：v9 發現黃金語料有 32% 是礦業公司財報等例行性內容。
      財報是「每季固定發布」的，若它確實墊高 vol，應該在特定月份/週期
      看到系統性偏高 —— 這與事件驅動的注意力激增性質完全不同。

若確認有季節性，可在指標層做調整（例如基線改用同期比較），
不必更動查詢式（換查詢式會讓歷史資料不可比）。

檢定：
  A. 月份效應 —— 各月平均 vol 是否有系統性差異
  B. 財報季效應 —— 財報密集期（1月底、4月底、7月底、10月底）vs 其他時間
  C. 對 z 值的實際影響 —— 觸發事件是否集中在財報季
"""
import sys, io, json, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, '..', 'docs', 'data.js')

raw = open(DATA, encoding='utf-8').read()
j = json.loads(raw.split('=', 1)[1].strip().rstrip(';'))
leaves = []
for a in j['assets']:
    leaves += a['members'] if a.get('is_group') else [a]

# 財報密集期：各季結束後 2~6 週。用「月份+日」粗略界定
EARNINGS_WINDOWS = [
    (1, 20, 2, 15),   # Q4 財報
    (4, 20, 5, 15),   # Q1
    (7, 20, 8, 15),   # Q2
    (10, 20, 11, 15), # Q3
]


def in_earnings(datestr):
    m, d = int(datestr[5:7]), int(datestr[8:10])
    for m1, d1, m2, d2 in EARNINGS_WINDOWS:
        if (m == m1 and d >= d1) or (m == m2 and d <= d2):
            return True
    return False


print('=' * 84)
print('  A. 月份效應：各月平均新聞量（vol）')
print('=' * 84)
print('  %-6s' % '資產' + ''.join('%6s' % ('%02d月' % m) for m in range(1, 13)))
print('  ' + '-' * 78)
for m_ in leaves:
    by = {k: [] for k in range(1, 13)}
    for d, v in zip(m_['dates'], m_['vol']):
        if v is not None:
            by[int(d[5:7])].append(v)
    row = '  %-6s' % m_['id']
    for k in range(1, 13):
        row += '%6s' % (('%.3f' % np.mean(by[k])) if by[k] else '  — ')
    print(row)

print()
print('=' * 84)
print('  B. 財報季 vs 非財報季（vol 平均）')
print('=' * 84)
print('  %-6s %10s %10s %8s %10s' % ('資產', '財報季', '非財報季', '比值', '判定'))
print('  ' + '-' * 78)
for m_ in leaves:
    e, o = [], []
    for d, v in zip(m_['dates'], m_['vol']):
        if v is None:
            continue
        (e if in_earnings(d) else o).append(v)
    if not e or not o:
        continue
    r = np.mean(e) / np.mean(o)
    tag = '偏高' if r > 1.10 else ('偏低' if r < 0.90 else '無明顯差異')
    print('  %-6s %9.4f %10.4f %8.2fx %10s'
          % (m_['id'], np.mean(e), np.mean(o), r, tag))

print()
print('=' * 84)
print('  C. 觸發事件是否集中在財報季？')
print('=' * 84)
print('  若指標只是在測「財報發布」而非「市場注意力」，事件會不成比例地')
print('  集中在財報季 —— 這會是查詢式污染影響到訊號的直接證據。')
print()
print('  %-6s %8s %10s %12s %10s' % ('資產', '總事件', '財報季內', '財報季佔比', '期望佔比'))
print('  ' + '-' * 78)
for m_ in leaves:
    z = m_['attn_z']
    ev, prev = [], False
    for i, v in enumerate(z):
        hot = v is not None and v > 2.5
        if hot and not prev:
            ev.append(i)
        prev = hot
    if not ev:
        continue
    ine = sum(1 for i in ev if in_earnings(m_['dates'][i]))
    # 期望佔比 = 財報季天數 / 總天數
    edays = sum(1 for d in m_['dates'] if in_earnings(d))
    exp = edays / len(m_['dates']) * 100
    act = ine / len(ev) * 100
    print('  %-6s %7d %10d %11.0f%% %9.0f%%'
          % (m_['id'], len(ev), ine, act, exp))

print()
print('=' * 84)
print('  D. 偏斜的顯著性（蒙地卡羅二項檢定，20000 次）')
print('=' * 84)
rng = np.random.default_rng(11)
print('  %-6s %8s %8s %10s %10s %s' % ('資產', '事件數', '季內', '實際佔比', 'p值', '判定'))
print('  ' + '-' * 74)
for m_ in leaves:
    z = m_['attn_z']
    ev, prev = [], False
    for i, v in enumerate(z):
        h = v is not None and v > 2.5
        if h and not prev:
            ev.append(i)
        prev = h
    if not ev:
        continue
    ine = sum(1 for i in ev if in_earnings(m_['dates'][i]))
    p0 = sum(1 for d in m_['dates'] if in_earnings(d)) / len(m_['dates'])
    sim = rng.binomial(len(ev), p0, 20000)
    pv = float((sim >= ine).mean())
    tag = '顯著偏斜' if pv < 0.05 else ('邊際' if pv < 0.10 else '無顯著偏斜')
    print('  %-6s %7d %8d %9.0f%% %10.4f %s'
          % (m_['id'], len(ev), ine, ine / len(ev) * 100, pv, tag))

print()
print('=' * 84)
print('  E. 關鍵檢定：財報季內的事件，訊號效力是否較差？')
print('=' * 84)
print('  原假設「財報噪音稀釋訊號」若成立，季內放大倍數應明顯低於季外。')
print()
print('  %-6s %10s %8s %10s %8s' % ('資產', '季內3D放大', '事件數', '季外3D放大', '事件數'))
print('  ' + '-' * 74)


def ffill_(c):
    o, last = [], None
    for v in c:
        if v is not None:
            last = v
        o.append(last)
    return o


allin, allout = [], []
for m_ in leaves:
    z, c = m_['attn_z'], ffill_(m_.get('close') or [])
    n = len(m_['dates'])
    ev, prev = [], False
    for i, v in enumerate(z):
        h = v is not None and v > 2.5
        if h and not prev:
            ev.append(i)
        prev = h
    base = [abs(c[i + 3] / c[i] - 1) * 100 for i in range(n - 3) if c[i] and c[i + 3]]
    if not base:
        continue
    b = np.mean(base)
    ins = [abs(c[i + 3] / c[i] - 1) * 100 for i in ev
           if in_earnings(m_['dates'][i]) and i < n - 3 and c[i] and c[i + 3]]
    out = [abs(c[i + 3] / c[i] - 1) * 100 for i in ev
           if not in_earnings(m_['dates'][i]) and i < n - 3 and c[i] and c[i + 3]]
    allin += [v / b for v in ins]
    allout += [v / b for v in out]
    print('  %-6s %9s %8d %10s %8d'
          % (m_['id'], ('%.2fx' % (np.mean(ins) / b)) if ins else '  n/a ', len(ins),
             ('%.2fx' % (np.mean(out) / b)) if out else '  n/a ', len(out)))

if allin and allout:
    ri, ro = np.mean(allin), np.mean(allout)
    print('  ' + '-' * 74)
    print('  合計   %9.2fx %8d %10.2fx %8d' % (ri, len(allin), ro, len(allout)))
    print()
    if ro > ri * 1.2:
        print('  >>> 季外 %.2fx 明顯強於季內 %.2fx —— 支持「財報噪音稀釋訊號」' % (ro, ri))
    elif ri > ro * 1.2:
        print('  >>> 季內 %.2fx 反而強於季外 %.2fx —— 不支持該假設。' % (ri, ro))
        print('      合理解釋：財報本身就是真實市場事件，會同時帶動新聞量與價格波動。')
        print('      「新聞量在財報季升高」非污染假象，而是指標正確捕捉到真實事件。')
    else:
        print('  >>> 兩者相近，無明確證據')

print('''
  限制：本樣本僅一年、每資產 6~15 個事件，季內外各分後只剩 2~10 個，
        任何差距都可能是隨機波動。財報季亦採「各季結束後 2~6 週」粗略界定，
        非精確財報日曆。結論須待 8.6 年大樣本 + 精確日曆重驗。
''')
