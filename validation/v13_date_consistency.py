# -*- coding: utf-8 -*-
"""驗證 13：卡片日期一致性稽核

起因（2026-08-17 使用者回報）：
    畫面大字顯示 -2.45（負），同一張圖的注意力曲線末端卻往上衝（+2.12），
    使用者合理懷疑「資料源出問題」。實際稽核後發現資料完全正確，
    問題是「同一張卡片上並列了三個不同日子的數字，卻沒有任何一個標日期」：

        大字 -2.45          → 2026-08-16（最後定版日）
        「今日即時 2.12」    → 2026-08-17（未定版）
        「當日波動 0.385%」  → 2026-08-14（最後有前一日收盤可比的交易日）

    三個日子疊在 120px 高的卡片內，視覺上讀起來像是同一天的三個指標。
    這不是資料錯誤，是「未標註時間基準」造成的判讀錯誤 —— 但後果一樣嚴重：
    使用者會開始不信任整個系統。

本腳本的職責：
    每次 data.js 更新後，機械化檢查「畫面上並列的數字，其時間基準是否已標註」。
    這類問題肉眼很難抓（數字全都是對的），只能靠稽核腳本。

用法：
    py v13_date_consistency.py                    # 檢查線上 data.js
    py v13_date_consistency.py ../docs/data.js    # 檢查本地檔案
"""
import sys, io, json, os, urllib.request
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

LIVE = 'https://hwayu000.github.io/Stock-emotional-radar/data.js'


def load(src):
    if src.startswith('http'):
        req = urllib.request.Request(src, headers={'User-Agent': 'Mozilla/5.0'})
        s = urllib.request.urlopen(req, timeout=60).read().decode('utf-8')
    else:
        s = open(src, encoding='utf-8').read()
    i = s.index('{')
    return json.loads(s[i:s.rindex('}') + 1])


def check(asset):
    """回傳 (問題清單, 資訊清單)"""
    problems, info = [], []
    aid = asset.get('id', '?')
    L = asset.get('latest') or {}
    q = asset.get('quality') or {}
    vr = asset.get('vol_regime') or {}
    dates = asset.get('dates') or []

    if not dates:
        return problems, info

    last_date = dates[-1]
    settled = q.get('settled_through')

    # ── 檢查 1：大字（定版 z）必須帶日期 ──
    if L.get('attn_z_settled') is not None:
        if not L.get('attn_z_settled_date'):
            problems.append(
                '定版 z 值 %s 沒有 attn_z_settled_date —— 卡片大字無法標日期，'
                '使用者會誤以為是今天的值' % L['attn_z_settled'])
        elif L['attn_z_settled_date'] != settled:
            problems.append(
                'attn_z_settled_date(%s) 與 quality.settled_through(%s) 不一致'
                % (L['attn_z_settled_date'], settled))

    # ── 檢查 2：即時 z 必須帶日期 ──
    if L.get('attn_z') is not None and not L.get('attn_z_date'):
        problems.append('即時 z 值 %s 沒有 attn_z_date' % L['attn_z'])
    elif L.get('attn_z_date') and L['attn_z_date'] != last_date:
        problems.append('attn_z_date(%s) 不等於序列最後一天(%s)'
                        % (L['attn_z_date'], last_date))

    # ── 檢查 3：波動情境必須帶日期（本次的核心漏洞）──
    if vr:
        if not vr.get('date'):
            problems.append(
                'vol_regime 沒有 date 欄位 —— 波動 %s%% 實際可能來自更早的交易日，'
                '與大字並列會造成日期混淆' % vr.get('today_move'))

    # ── 檢查 4：揭露三個數字的時間跨度（即使都標了日期，跨太多天仍要提醒）──
    stamps = {}
    if L.get('attn_z_settled_date'):
        stamps['大字(定版z)'] = L['attn_z_settled_date']
    if L.get('attn_z_date'):
        stamps['即時z'] = L['attn_z_date']
    if vr.get('date'):
        stamps['當日波動'] = vr['date']

    if stamps:
        uniq = sorted(set(stamps.values()))
        desc = '　'.join('%s=%s' % (k, v) for k, v in stamps.items())
        info.append('%s 卡片時間基準：%s' % (aid, desc))
        if len(uniq) > 1:
            span = (max(uniq), min(uniq))
            info.append('  ⚠ 同卡片並列 %d 個不同日期（%s ~ %s）—— '
                        '每一個都必須在 UI 上標出來' % (len(uniq), span[1], span[0]))

    # ── 檢查 5：未定版天數合理性 ──
    prov = asset.get('provisional') or []
    npro = sum(1 for p in prov if p)
    if npro > 1:
        problems.append('未定版天數 %d > 1 —— 正常只有今天一天未定版，'
                        '請檢查 is_provisional 判定' % npro)

    # ── 檢查 6：定版日與今天的落差 ──
    if settled and last_date:
        from datetime import date
        d1 = date.fromisoformat(settled)
        d2 = date.fromisoformat(last_date)
        gap = (d2 - d1).days
        if gap > 3:
            problems.append('定版日(%s)落後序列末日(%s) %d 天 —— '
                            '可能是抓取中斷' % (settled, last_date, gap))
        elif gap > 1:
            info.append('  註：定版日落後 %d 天（%s → %s），'
                        '週末無新聞量屬正常' % (gap, settled, last_date))

    return problems, info


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else LIVE
    d = load(src)
    print('=' * 78)
    print('  卡片日期一致性稽核')
    print('  來源：%s' % src)
    print('  資料產生時間：%s UTC' % d.get('generated'))
    print('=' * 78)

    total_p = 0
    for a in d.get('assets', []):
        if a.get('is_group'):
            continue
        problems, info = check(a)
        print()
        for line in info:
            print('  ' + line)
        if problems:
            total_p += len(problems)
            for p in problems:
                print('  ✗ [%s] %s' % (a.get('id'), p))
        else:
            print('  ✓ [%s] 日期標註完整' % a.get('id'))

    print()
    print('=' * 78)
    if total_p:
        print('  結果：發現 %d 個問題' % total_p)
    else:
        print('  結果：全部通過 —— 每個並列數字都帶有可辨識的時間基準')
    print('=' * 78)
    return 1 if total_p else 0


if __name__ == '__main__':
    sys.exit(main())
