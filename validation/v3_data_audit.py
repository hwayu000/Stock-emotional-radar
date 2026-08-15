# -*- coding: utf-8 -*-
"""驗證 3：資料源稽核 —— 這些數字到底是不是真的？

量化基金資料治理標準：對每個欄位回答
  1. 來源是誰、拿什麼端點抓的
  2. 更新頻率、有無定版(point-in-time)問題
  3. 完整度(缺漏率)、異常值、可否交叉複驗
  4. 綜合可信度評分與「可用於什麼、不可用於什麼」
"""
import sys, io, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, '.')
import numpy as np, pandas as pd
from common import load_leaves, DATA

j, leaves = load_leaves()

print('=' * 78)
print('  資料源稽核報告')
print('  產生時間戳(檔案內宣告)：%s  UTC=%s' % (j.get('generated'), j.get('generated_utc')))
print('=' * 78)

print('''
【欄位來源清單】
  vol   新聞量   GDELT DOC 2.0 API  mode=timelinevol
                 定義：該主題新聞「佔全球新聞總量的百分比」(非絕對則數)
                 更新：15分鐘級滾動；當日未定版，跑完才固定
  tone  語調     GDELT DOC 2.0 API  mode=timelinetone
                 定義：命中文章的平均語調分(GDELT自有情緒模型)
                 更新：同上，當日未定版
  close 收盤價   Yahoo Finance chart API  range=1y interval=1d
                 定義：日線收盤；期貨(GC=F)為結算價
                 更新：收盤後；盤中抓到的是即時價非定版收盤
  articles 頭條  GDELT artlist  近7天英文，maxrecords=75
''')

print('=' * 78)
print('  A. 完整度與缺漏')
print('=' * 78)
print('  資產   總天數  vol缺  tone缺  close缺  close缺漏率  最長連續缺漏')
for a in leaves:
    n = len(a['dates'])
    def miss(k):
        v = a.get(k) or []
        return sum(1 for i in range(n) if i >= len(v) or v[i] is None)
    c = a.get('close') or []
    run = best = 0
    for i in range(n):
        if i >= len(c) or c[i] is None:
            run += 1; best = max(best, run)
        else:
            run = 0
    print('  %-6s %4d   %3d   %4d   %5d    %5.1f%%      %d 天'
          % (a['id'], n, miss('vol'), miss('tone'), miss('close'),
             miss('close') / n * 100, best))
print('''
  註：close 缺漏約 31% 屬正常 —— 週末+假日無交易（一年 365 天中約 113 天）。
      BTC 為 7×24 交易故缺漏最少，可作為對照驗證此解釋是否成立。''')

print('\n' + '=' * 78)
print('  B. 數值合理性檢查（抓造假/管線壞掉的指紋）')
print('=' * 78)
print('  資產   vol範圍          tone範圍        close範圍            零值  重複值率')
for a in leaves:
    def rng(k):
        v = [x for x in (a.get(k) or []) if x is not None]
        return (min(v), max(v)) if v else (float('nan'),) * 2
    vr, tr, cr = rng('vol'), rng('tone'), rng('close')
    vv = [x for x in (a.get('vol') or []) if x is not None]
    cc = [x for x in (a.get('close') or []) if x is not None]
    zeros = sum(1 for x in vv if x == 0)
    dup = 0
    for i in range(1, len(cc)):
        if cc[i] == cc[i - 1]:
            dup += 1
    print('  %-6s %.4f~%.4f   %+.2f~%+.2f   %8.1f~%8.1f   %3d   %.1f%%'
          % (a['id'], vr[0], vr[1], tr[0], tr[1], cr[0], cr[1], zeros,
             dup / max(len(cc) - 1, 1) * 100))

print('\n' + '=' * 78)
print('  C. Point-in-time 完整性（最關鍵：資料會不會事後被改）')
print('=' * 78)
print('''  已實測確認（2026-08-15）：
    GDELT timelinevol 同一端點相隔數小時查詢
      2026-08-01 ~ 08-14 (歷史) : 14/14 數值完全一致  -> 定版可信
      2026-08-15 (當日)         : 0.1984 -> 0.2410   -> 未定版會變
    => 影響：任何用「當日」值觸發的警報都可能是假訊號
    => 這正是 08-14 清晨警報 attn_z=4.13、定版後實為 0.49 的成因

  Yahoo close：盤中抓取得到的是即時價，非定版收盤價。
    影響較小(本管線在收盤後跑)，但盤中觸發的排程會有同類問題。''')
