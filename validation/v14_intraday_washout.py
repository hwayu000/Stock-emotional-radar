# -*- coding: utf-8 -*-
"""驗證 14：注意力激增日的日內結構與「洗盤」檢定

起因（2026-08-18 使用者提問）：
    「同比對比 Z>2 時波動率多少？統計 Z>2 每 4H 情況？
      然後是跌破收盤或開盤價是與否？因為我看歷史都會大洗盤」

三個問題分別對應三種量測：

  Q1 波動率同比 —— 激增日的波動比常態高多少（日變動、日內振幅 H-L）
  Q2 每 4H 結構 —— 一天六根 4H K 棒，波動集中在哪一段？
  Q3 洗盤檢定   —— 「大洗盤」需要可證偽的定義，本腳本用三個獨立指標：
                     ① 是否跌破前日收盤（破前收）
                     ② 是否跌破當日開盤（破開盤）
                     ③ 是否「先破後拉」——盤中跌破前收，但收盤收回其上
                        （這才是真正的洗盤：假跌破洗掉停損，再拉回）

篩選層級（使用者要求兩層並列對比）：
    第一層 z > 2.5   現行警戒值
    第二層 z > 2.0
    第三層 z > 1.5   使用者新增的第二層過濾

資料範圍：
    日線 / 洗盤檢定：2018-01 ~ 2026-08（8.6 年，GDELT 長期快取）
    4H 日內結構    ：2024-08 ~ 2026-08（Yahoo 4H 僅回溯約 730 天，硬限制）

用法：
    py v14_intraday_washout.py
"""
import sys, io, json, os, datetime as dt, urllib.request
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, 'cache_history')
PXC = os.path.join(HERE, 'px_cache')
UA = {'User-Agent': 'Mozilla/5.0'}
rng = np.random.default_rng(14)

TIERS = [(2.5, '現行警戒'), (2.0, '舊警戒'), (1.5, '第二層過濾')]


# ────────────────────────── 資料載入 ──────────────────────────
def load_z():
    """回傳 dates(list[str]), z(np.array) —— 與 radar.py 同一套算法"""
    raw = json.load(open(os.path.join(CACHE, 'merged_XAU_timelinevol.json'),
                         encoding='utf-8'))
    vol = {f'{k[:4]}-{k[4:6]}-{k[6:8]}': v for k, v in raw.items()}
    dates = sorted(vol)
    v = np.array([vol[d] if vol[d] > 0 else np.nan for d in dates])
    z = np.full(len(v), np.nan)
    for i in range(90, len(v)):
        w = v[i - 90:i]
        w = w[~np.isnan(w)]
        if len(w) < 30 or np.isnan(v[i]):
            continue
        sd = w.std(ddof=1)
        if sd > 0:
            z[i] = (v[i] - w.mean()) / sd
    return dates, z


def fetch(interval, days, cache_name):
    """抓 GC=F OHLC；日線走既有快取邏輯，4H 另存"""
    p = os.path.join(PXC, cache_name)
    if os.path.exists(p):
        return json.load(open(p))
    p2 = int(dt.datetime.now().timestamp())
    p1 = p2 - days * 86400
    url = (f'https://query1.finance.yahoo.com/v8/finance/chart/GC%3DF'
           f'?period1={p1}&period2={p2}&interval={interval}')
    r = json.loads(urllib.request.urlopen(
        urllib.request.Request(url, headers=UA), timeout=90).read())
    res = r['chart']['result'][0]
    q = res['indicators']['quote'][0]
    d = {'ts': res['timestamp'], 'open': q['open'], 'high': q['high'],
         'low': q['low'], 'close': q['close']}
    os.makedirs(PXC, exist_ok=True)
    json.dump(d, open(p, 'w'))
    return d


def daily_ohlc():
    """日線 OHLC dict[date] = (o,h,l,c)"""
    d = fetch('1d', 3300, 'XAU_ohlc_1d.json')
    out = {}
    for t, o, h, l, c in zip(d['ts'], d['open'], d['high'], d['low'], d['close']):
        if c is None or o is None:
            continue
        out[dt.datetime.fromtimestamp(t, dt.UTC).strftime('%Y-%m-%d')] = (o, h, l, c)
    return out


def bars_4h():
    """4H K 棒 dict[date] = list[(slot, o,h,l,c)]

    ⚠ 時段必須「歸位到 4H 槽」再統計。
      期貨週在美東週日 21:00 開盤，部分交易日的首根 K 棒會落在非 4 的倍數
      整點（例：01:00、13:00、16:01 的補收盤棒）。若直接用 u.hour 當鍵，
      同一個實際時段會被拆成兩列，統計表會出現 12 列而非 6 列，
      且每列樣本數被腰斬（第一版就踩到）。故一律 floor 到 4 小時槽。
    """
    d = fetch('4h', 720, 'XAU_ohlc_4h.json')
    out = {}
    for t, o, h, l, c in zip(d['ts'], d['open'], d['high'], d['low'], d['close']):
        if c is None or o is None:
            continue
        u = dt.datetime.fromtimestamp(t, dt.UTC)
        slot = (u.hour // 4) * 4          # 歸位：0/4/8/12/16/20
        out.setdefault(u.strftime('%Y-%m-%d'), []).append((slot, o, h, l, c))
    # 同槽若有多根（補棒），合併為一根：取 open=首、close=末、high/low=極值
    merged = {}
    for day, bars in out.items():
        agg = {}
        for slot, o, h, l, c in sorted(bars, key=lambda x: x[0]):
            if slot in agg:
                po, ph, pl, _ = agg[slot]
                agg[slot] = (po, max(ph, h), min(pl, l), c)
            else:
                agg[slot] = (o, h, l, c)
        merged[day] = [(s, *v) for s, v in sorted(agg.items())]
    return merged


# ────────────────────────── 工具 ──────────────────────────
def events(dates, z, th):
    """首次突破去重"""
    ev, prev = [], False
    for i, x in enumerate(z):
        hot = (not np.isnan(x)) and x > th
        if hot and not prev:
            ev.append(dates[i])
        prev = hot
    return ev


def perm_p(obs, pool, k, n=10000):
    if k == 0 or len(pool) < k:
        return float('nan')
    pool = np.array(pool)
    null = [pool[rng.choice(len(pool), k, replace=False)].mean() for _ in range(n)]
    return float((np.array(null) >= obs).mean())


def pfmt(p):
    return 'n/a' if np.isnan(p) else ('<.001' if p < .001 else '%.3f' % p)


# ────────────────────────── Q1 波動率同比 ──────────────────────────
def q1_volatility(dates, z, oh):
    print('=' * 86)
    print('  Q1　激增日波動率 vs 常態（黃金 2018-01 ~ 2026-08）')
    print('=' * 86)
    print('  「同比」= 事件當日的波動，除以全期間所有交易日的平均波動')
    print()

    keys = sorted(oh)
    idx = {d: i for i, d in enumerate(keys)}
    # 常態基準
    b_move, b_range = [], []
    for i in range(1, len(keys)):
        o, h, l, c = oh[keys[i]]
        pc = oh[keys[i - 1]][3]
        b_move.append(abs(c / pc - 1) * 100)
        b_range.append((h - l) / pc * 100)
    bm, br = np.mean(b_move), np.mean(b_range)

    print('  常態基準：日變動 %.2f%%　日內振幅(H-L) %.2f%%　(n=%d 交易日)'
          % (bm, br, len(b_move)))
    print()
    print('  %-14s %5s  %-18s %-20s' % ('篩選層級', 'n', '日變動', '日內振幅 H-L'))
    print('  ' + '-' * 80)

    for th, lbl in TIERS:
        ev = events(dates, z, th)
        mv, rg = [], []
        for d in ev:
            if d not in idx or idx[d] == 0:
                continue
            i = idx[d]
            o, h, l, c = oh[d]
            pc = oh[keys[i - 1]][3]
            mv.append(abs(c / pc - 1) * 100)
            rg.append((h - l) / pc * 100)
        if len(mv) < 5:
            continue
        pm = perm_p(np.mean(mv), b_move, len(mv))
        pr = perm_p(np.mean(rg), b_range, len(rg))
        print('  z>%.1f %-8s %5d  %.2f%% (%.2fx) p=%-5s %.2f%% (%.2fx) p=%s'
              % (th, lbl, len(mv), np.mean(mv), np.mean(mv) / bm, pfmt(pm),
                 np.mean(rg), np.mean(rg) / br, pfmt(pr)))
    print()
    print('  讀法：括號內為放大倍數。>1 代表當天比平常更會動。')
    print('  ⚠ 這是「事件當天」的波動，不是預測力 —— 新聞多的當天本來就會波動大，')
    print('     有預測價值的是「事件之後」的波動（見 v12 大樣本回測）。')
    print()


# ────────────────────────── Q2 每 4H 結構 ──────────────────────────
def q2_intraday(dates, z, b4):
    print('=' * 86)
    print('  Q2　激增日的日內 4H 結構（2024-08 ~ 2026-08，Yahoo 4H 上限約 730 天）')
    print('=' * 86)
    print('  黃金期貨一天約 6 根 4H K 棒（UTC）。看波動集中在哪一段。')
    print()

    have = set(b4)
    # 常態：每個 UTC 時段的平均振幅
    slot_base = {}
    for d, bars in b4.items():
        for hh, o, h, l, c in bars:
            if o:
                slot_base.setdefault(hh, []).append((h - l) / o * 100)

    for th, lbl in TIERS:
        ev = [d for d in events(dates, z, th) if d in have]
        if len(ev) < 3:
            print('  z>%.1f (%s)：樣本不足（n=%d），略過' % (th, lbl, len(ev)))
            continue
        slot_ev = {}
        for d in ev:
            for hh, o, h, l, c in b4[d]:
                if o:
                    slot_ev.setdefault(hh, []).append((h - l) / o * 100)
        print('  ── z>%.1f（%s）　事件 n=%d ──' % (th, lbl, len(ev)))
        print('    UTC時段      台北時間      激增日振幅   常態振幅   放大')
        for hh in sorted(slot_ev):
            a = slot_ev[hh]
            b = slot_base.get(hh, [])
            if len(a) < 3 or len(b) < 10:
                continue
            tp = (hh + 8) % 24
            print('    %02d:00-%02d:00  %02d:00-%02d:00   %6.2f%%    %6.2f%%   %.2fx'
                  % (hh, (hh + 4) % 24, tp, (tp + 4) % 24,
                     np.mean(a), np.mean(b), np.mean(a) / np.mean(b)))
        print()


# ────────────────────────── Q3 洗盤檢定 ──────────────────────────
def q3_washout(dates, z, oh):
    print('=' * 86)
    print('  Q3　「大洗盤」檢定 —— 跌破前收 / 跌破開盤 / 先破後拉')
    print('=' * 86)
    print('  「洗盤」需要可證偽的定義。本檢定用三個獨立指標：')
    print('    ① 破前收：盤中最低 < 前一日收盤')
    print('    ② 破開盤：盤中最低 < 當日開盤')
    print('    ③ 先破後拉：盤中跌破前收，但收盤 > 前收（真洗盤 = 假跌破再收回）')
    print()

    keys = sorted(oh)
    idx = {d: i for i, d in enumerate(keys)}

    def stats(days):
        n = b1 = b2 = b3 = 0
        wick = []
        for d in days:
            if d not in idx or idx[d] == 0:
                continue
            i = idx[d]
            o, h, l, c = oh[d]
            pc = oh[keys[i - 1]][3]
            n += 1
            if l < pc:
                b1 += 1
                if c > pc:
                    b3 += 1          # 先破後拉
            if l < o:
                b2 += 1
            wick.append((min(o, c) - l) / pc * 100)   # 下影線長度
        return n, b1, b2, b3, (np.mean(wick) if wick else float('nan'))

    n, b1, b2, b3, wk = stats(keys[1:])
    print('  常態基準（全部 %d 個交易日）：' % n)
    print('    破前收 %.1f%%　破開盤 %.1f%%　先破後拉 %.1f%%　平均下影線 %.2f%%'
          % (b1 / n * 100, b2 / n * 100, b3 / n * 100, wk))
    print()
    print('  %-14s %5s %10s %10s %12s %10s'
          % ('篩選層級', 'n', '破前收', '破開盤', '先破後拉', '下影線'))
    print('  ' + '-' * 80)
    for th, lbl in TIERS:
        ev = events(dates, z, th)
        n2, c1, c2, c3, w2 = stats(ev)
        if n2 < 5:
            continue
        print('  z>%.1f %-8s %5d %9.1f%% %9.1f%% %11.1f%% %9.2f%%'
              % (th, lbl, n2, c1 / n2 * 100, c2 / n2 * 100, c3 / n2 * 100, w2))
    print()
    print('  讀法：三個比率若與常態基準接近，代表「激增日特別會洗盤」不成立；')
    print('        明顯高於基準才算證據。下影線越長代表盤中殺得越深又拉回。')
    print()

    # ── 對稱檢定：洗盤只看下影線會有方向偏誤 ──
    # 若激增日「上影線也同樣變長」，代表那是雙向波動放大，不是單向洗盤。
    print('  ── 對稱檢定：上下影線一起看（排除「只看下影線」的確認偏誤）──')

    def wicks(days):
        up, dn, rng_ = [], [], []
        for d in days:
            if d not in idx or idx[d] == 0:
                continue
            i = idx[d]
            o, h, l, c = oh[d]
            pc = oh[keys[i - 1]][3]
            up.append((h - max(o, c)) / pc * 100)
            dn.append((min(o, c) - l) / pc * 100)
            rng_.append((h - l) / pc * 100)
        return np.mean(up), np.mean(dn), np.mean(rng_)

    bu, bd, brr = wicks(keys[1:])
    print('    %-14s %10s %10s %10s %s'
          % ('層級', '上影線', '下影線', '全幅', '下/上比'))
    print('    常態基準       %8.2f%% %9.2f%% %9.2f%%   %.2f'
          % (bu, bd, brr, bd / bu if bu else float('nan')))
    for th, lbl in TIERS:
        ev = events(dates, z, th)
        if len(ev) < 5:
            continue
        u2, d2, r2 = wicks(ev)
        print('    z>%.1f          %8.2f%% %9.2f%% %9.2f%%   %.2f'
              % (th, u2, d2, r2, d2 / u2 if u2 else float('nan')))
    print()
    print('  若「下/上比」與常態接近 → 影線是雙向拉長（單純波動放大），')
    print('  而非「特別愛往下洗」。比值明顯 >常態 才支持洗盤說。')
    print()


def main():
    dates, z = load_z()
    oh = daily_ohlc()
    print()
    q1_volatility(dates, z, oh)
    q3_washout(dates, z, oh)
    try:
        b4 = bars_4h()
        q2_intraday(dates, z, b4)
    except Exception as e:
        print('  [4H] 抓取失敗：%s' % e)


if __name__ == '__main__':
    main()
