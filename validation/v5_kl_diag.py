# -*- coding: utf-8 -*-
"""KL 為何測不出訊號？診斷指標定義本身的問題，而非門檻。

三個候選病因：
  P1 方向資訊被丟棄：KL 是「分布差多遠」的純量，語調變樂觀/變悲觀同樣得高分，
     兩者價格意涵相反 -> 混在一起互相抵消
  P2 訊號被平滑掉：近 7 天 vs 前 90 天，7 天窗把突發事件攤平
  P3 分箱太粗：5 個 bin 只能分辨大幅分布移動，細微轉折看不到
"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, '.')
import numpy as np, pandas as pd
from common import load_leaves, ffill, first_breaches, permutation_test, fmt_p

j, leaves = load_leaves()

print('=' * 78)
print('  P1 檢定：KL 突破時，語調是往上還往下？兩者價格行為是否相反？')
print('=' * 78)

up_r, dn_r, base_r = {1:[],3:[],5:[]}, {1:[],3:[],5:[]}, {1:[],3:[],5:[]}
up_a, dn_a = {1:[],3:[],5:[]}, {1:[],3:[],5:[]}
for a in leaves:
    d, kl, q = a['dates'], a['kl'], a.get('kl_q95') or []
    tone = a['tone']; c = ffill(a.get('close') or [])
    n = len(d)
    ev = first_breaches(kl, [q[i] if i < len(q) else None for i in range(len(kl))])
    for i in ev:
        # 突破當下：近7天語調均值 vs 前90天語調均值 -> 判斷方向
        rec = [t for t in tone[max(0,i-6):i+1] if t is not None]
        bas = [t for t in tone[max(0,i-96):i-6] if t is not None]
        if not rec or not bas: continue
        direction = np.mean(rec) - np.mean(bas)
        for h in (1,3,5):
            if i < n-h and c[i] and c[i+h]:
                sr = (c[i+h]/c[i]-1)*100
                (up_r if direction>0 else dn_r)[h].append(sr)
                (up_a if direction>0 else dn_a)[h].append(abs(sr))
    for i in range(n-5):
        for h in (1,3,5):
            if i<n-h and c[i] and c[i+h]:
                base_r[h].append((c[i+h]/c[i]-1)*100)

print('  期間  語調轉樂觀時報酬  語調轉悲觀時報酬  基準報酬   差距')
for h in (1,3,5):
    u,dn,b = up_r[h], dn_r[h], base_r[h]
    if not u or not dn: continue
    print('  %3dD   %+7.2f%% (n=%2d)    %+7.2f%% (n=%2d)   %+6.2f%%   %+.2f%%'
          % (h, np.mean(u), len(u), np.mean(dn), len(dn), np.mean(b), np.mean(u)-np.mean(dn)))

print('''
  判讀：若「轉樂觀」與「轉悲觀」的報酬明顯分岔，代表 P1 成立 ——
        KL 丟掉方向資訊是它測不出訊號的主因，加回方向即可救活。''')

print('\n' + '=' * 78)
print('  P2 檢定：縮短觀測窗（7天 -> 3天）能否讓訊號浮現？')
print('=' * 78)

def kl_custom(tone_s, recent, base=90, bins=5):
    eps=1e-6; vals=tone_s.values; idx=tone_s.index; out={}
    for t in range(recent+base, len(vals)):
        rec=vals[t-recent+1:t+1]; bas=vals[t-recent-base+1:t-recent+1]
        bb=bas[~np.isnan(bas)]
        if len(bb)<10: continue
        edges=np.unique(np.quantile(bb,np.linspace(0,1,bins+1)))
        if len(edges)<3: continue
        p,_=np.histogram(rec,bins=edges); qq,_=np.histogram(bas,bins=edges)
        p=(p+eps)/(p+eps).sum(); qq=(qq+eps)/(qq+eps).sum()
        out[idx[t]]=float(np.sum(p*np.log(p/qq)))
    return pd.Series(out)

print('  觀測窗  事件數  事件後1D波幅  常態波幅  放大   p值')
for recent in (3,5,7,14):
    ev_vals, pools, ks = [], [], []
    for a in leaves:
        tone=pd.Series([np.nan if v is None else v for v in a['tone']],
                       index=pd.to_datetime(a['dates'])).dropna()
        s=kl_custom(tone,recent)
        if len(s)<60: continue
        th=(s.ewm(span=90,min_periods=30).mean()+2.0*s.ewm(span=90,min_periods=30).std()).shift(1)
        dmap={pd.Timestamp(x):i for i,x in enumerate(pd.to_datetime(a['dates']))}
        c=ffill(a.get('close') or []); n=len(a['dates'])
        idxs=first_breaches(list(s.values), list(th.reindex(s.index).values))
        dts=list(s.index)
        valid=[abs(c[i+1]/c[i]-1)*100 for i in range(n-1) if c[i] and c[i+1]]
        got=[]
        for e in idxs:
            i=dmap.get(dts[e])
            if i is not None and i<n-1 and c[i] and c[i+1]:
                got.append(abs(c[i+1]/c[i]-1)*100)
        ev_vals+=got; pools.append(np.array(valid)); ks.append(len(got))
    if len(ev_vals)<5: 
        print('  %3d天    樣本不足'%recent); continue
    obs=np.mean(ev_vals); p,nm,_=permutation_test(obs,pools,ks,n_iter=5000)
    print('  %3d天    %3d      %6.2f%%     %6.2f%%   %.2fx  %s'
          %(recent,len(ev_vals),obs,nm,obs/nm,fmt_p(p)))
