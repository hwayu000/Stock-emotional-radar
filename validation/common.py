# -*- coding: utf-8 -*-
"""驗證框架共用工具：載入資料、事件抽取、統計檢定。

嚴格性原則（全部檢定共用）：
  1. 無前視偏誤：任何 t 時點的指標只能用 <= t 的資料
  2. 事件去重：連續突破只算首次，避免同一事件重複計數膨脹樣本
  3. 對照組明確：事件組 vs 非事件組，而非事件組 vs 全體
  4. 顯著性用置換檢定（不假設常態分布），非 t 檢定
  5. 多重比較校正：同時測多個閾值×多個期間時回報 FDR
"""
import json, os
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, '..', 'docs', 'data.js')


def load_leaves(path=DATA):
    """載入所有葉節點資產（攤平 US 群組）"""
    raw = open(path, encoding='utf-8').read()
    j = json.loads(raw.split('=', 1)[1].strip().rstrip(';'))
    leaves = []
    for a in j['assets']:
        if 'dates' in a:
            leaves.append(a)
        else:
            leaves += [m for m in a.get('members', []) if 'dates' in m]
    return j, leaves


def ffill(c):
    """價格前向填補（週末/假日無收盤）"""
    out, last = [], None
    for v in c:
        if v is not None:
            last = v
        out.append(last)
    return out


def first_breaches(series, thresh):
    """抽取「首次突破」索引。連續突破期間只記第一天。

    thresh 可為純量或等長序列（動態門檻）。
    """
    ev, prev = [], False
    for i, v in enumerate(series):
        if v is None:
            hot = False
        else:
            t = thresh[i] if isinstance(thresh, (list, np.ndarray)) else thresh
            hot = t is not None and not np.isnan(t) and v > t
        if hot and not prev:
            ev.append(i)
        prev = hot
    return ev


def permutation_test(observed, pools, n_event_per_asset, stat=np.mean,
                     n_iter=10000, seed=42):
    """置換檢定：在各資產的合法索引池中隨機抽同樣數量的假事件。

    回傳 (p值, 虛無分布均值, 虛無分布標準差)
    保持每資產抽樣數與真實事件數一致，避免資產組成偏移污染虛無分布。
    """
    rng = np.random.default_rng(seed)
    null = []
    for _ in range(n_iter):
        s = []
        for (valid_vals, k) in zip(pools, n_event_per_asset):
            if k == 0 or len(valid_vals) < k:
                continue
            s.extend(rng.choice(valid_vals, size=k, replace=False))
        if s:
            null.append(stat(s))
    null = np.array(null)
    if len(null) == 0:
        return float('nan'), float('nan'), float('nan')
    p = float((null >= observed).mean())
    return p, float(null.mean()), float(null.std(ddof=1))


def benjamini_hochberg(pvals, alpha=0.05):
    """FDR 多重比較校正。回傳每個 p 值是否通過。"""
    p = np.asarray(pvals, dtype=float)
    n = len(p)
    order = np.argsort(p)
    passed = np.zeros(n, dtype=bool)
    crit = alpha * (np.arange(1, n + 1)) / n
    sorted_p = p[order]
    below = sorted_p <= crit
    if below.any():
        kmax = np.max(np.where(below)[0])
        passed[order[:kmax + 1]] = True
    return passed


def fmt_p(p):
    if np.isnan(p):
        return '  n/a '
    if p < 0.001:
        return '<0.001'
    return '%.4f' % p
