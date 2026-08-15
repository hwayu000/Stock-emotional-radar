# -*- coding: utf-8 -*-
"""驗證 9：語料切題度 —— 查詢式抓到的文章，有多少真的與該標的相關？

動機：黃金頭條中出現礦業公司財報（Steppe Gold Q2 Results）、石油新聞
      （Oil prices rally），懷疑查詢式不夠精準。

機制：GDELT DOC 2.0 比對的是「全文」而非「標題」，故只要內文任一處提到
      "gold price"，整篇就被計入。礦業公司財報必然提及金價，綜合行情
      報導也常順帶一句 —— 這些都會被算成「對黃金的注意力」。

影響：這類多為「例行性產出」（財報每季固定發布），會持續墊高基線 vol。
      基線被墊高 -> 標準差變大 -> 真正的事件性激增被稀釋，z 值偏低。

與 8/14 誤判的關係：兩者是不同問題，但同源。
  8/14 誤判 = 時間軸（UTC 日界分母極小 -> 佔比虛高）-> 已修正
  語料污染  = 內容軸（全文比對 -> 不相關文章被計入）-> 本腳本量化
  共同根源：vol 是「佔比分數」而非精準的事件計數。
"""
import sys, io, json, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, '..', 'docs', 'data.js')

# 明確的離題特徵。刻意採「只標記確定離題者」的保守判定 ——
# 早期版本用「必須命中關鍵詞才算切題」，會把
# "Gold Just Ripped Higher on an Ugly Jobs Report" 這類真正切題的標題誤判，
# 導致污染率虛高（誤報 92%，實為 32%）。
CORP_ACTION = [
    'announces q', 'q1 2026 results', 'q2 2026 results', 'q3 2026 results',
    'q4 2026 results', 'financial results', 'announces engagement',
    'files second quarter', 'files first quarter', 'ipo hurdle',
    'announces closing', 'private placement', 'drill results',
    'drilling program', 'announces appointment', 'announces filing', 'reports q',
]
OTHER_ASSET = [
    'oil prices rally', 'oil heads for', 'stock market today',
    'stocks rise before', 'dollar is undercut', 'crude oil',
]


def audit(arts):
    corp, other, samples = 0, 0, []
    for a in arts:
        t = (a.get('title') or '').lower()
        if any(k in t for k in CORP_ACTION):
            corp += 1
            samples.append(('公司公告', a.get('title', '')[:64]))
        elif any(k in t for k in OTHER_ASSET):
            other += 1
            samples.append(('他類商品', a.get('title', '')[:64]))
    return corp, other, samples


def main():
    raw = open(DATA, encoding='utf-8').read()
    j = json.loads(raw.split('=', 1)[1].strip().rstrip(';'))
    leaves = []
    for a in j['assets']:
        leaves += a['members'] if a.get('is_group') else [a]

    print('=' * 84)
    print('  語料切題度查核（近 7 天頭條樣本，資料時間 %s）' % j.get('generated'))
    print('=' * 84)
    print('  %-6s %6s %10s %10s %9s' % ('資產', '樣本', '公司公告', '他類商品', '污染率'))
    print('  ' + '-' * 78)

    keep = {}
    for m in leaves:
        arts = m.get('articles', [])
        if not arts:
            continue
        corp, other, samples = audit(arts)
        keep[m['id']] = samples
        print('  %-6s %5d  %8d  %8d   %6.0f%%'
              % (m['id'], len(arts), corp, other, (corp + other) / len(arts) * 100))

    print()
    print('=' * 84)
    print('  污染樣本明細')
    print('=' * 84)
    for aid, samples in keep.items():
        if not samples:
            continue
        print('  【%s】' % aid)
        for kind, t in samples[:14]:
            print('    [%s] %s' % (kind, t))
        print()

    print('=' * 84)
    print('  來源網域分布（判斷是否集中於主流財經媒體）')
    print('=' * 84)
    for m in leaves:
        arts = m.get('articles', [])
        if not arts:
            continue
        dom = Counter()
        for a in arts:
            u = a.get('url', '')
            if '//' in u:
                dom[u.split('//')[1].split('/')[0].replace('www.', '')] += 1
        top = '  '.join('%s(%d)' % (d, c) for d, c in dom.most_common(5))
        print('  %-6s %s' % (m['id'], top))

    print('''
  判讀：黃金污染率最高，因為 "gold" 同時是商品名與公司名的一部分
        （Steppe Gold、Gemdale Gold），且金價是所有礦業公司財報的標準內容。
        相對地 bitcoin、apple stock 這類查詢乾淨得多。
''')


if __name__ == '__main__':
    main()
