import json, math, time, urllib.parse, urllib.request
from statistics import mean

YAHOO_MAP={
 'EURUSD':'EURUSD=X','GBPUSD':'GBPUSD=X','USDJPY':'JPY=X','USDCHF':'CHF=X','AUDUSD':'AUDUSD=X','USDCAD':'CAD=X','NZDUSD':'NZDUSD=X','EURGBP':'EURGBP=X','EURJPY':'EURJPY=X','GBPJPY':'GBPJPY=X','AUDJPY':'AUDJPY=X','EURAUD':'EURAUD=X','GBPAUD':'GBPAUD=X','XAUUSD':'GC=F','XAGUSD':'SI=F','WTI':'CL=F','USOIL':'CL=F','BRENT':'BZ=F','NATGAS':'NG=F','SPX':'^GSPC','SP500':'^GSPC','NAS100':'^NDX','NDX':'^NDX','US30':'^DJI','DOW':'^DJI','DAX':'^GDAXI','FTSE100':'^FTSE','NIKKEI':'^N225','BTCUSD':'BTC-USD','ETHUSD':'ETH-USD','XRPUSD':'XRP-USD','SOLUSD':'SOL-USD','BNBUSD':'BNB-USD','ADAUSD':'ADA-USD'}
INTERVALS={'15m':'15m','30m':'30m','1h':'1h','1d':'1d'}
RANGES={'15m':'7d','30m':'20d','1h':'45d','1d':'900d'}

def yahoo_symbol(s):
 s=s.upper().replace('/','').replace('-','')
 return YAHOO_MAP.get(s, s if s.endswith('=X') or s.startswith('^') else None)

def fetch(symbol, interval):
    """Fetch verified OHLC candles. 4h is built from 1h candles so it is not mislabeled."""
    if interval == '4h':
        base = fetch(symbol, '1h')
        out=[]
        bucket=None; group=[]
        for r in base:
            b=(r['t']//14400)*14400
            if bucket is None: bucket=b
            if b!=bucket:
                if len(group)>=3:
                    out.append({'t':bucket,'open':group[0]['open'],'high':max(x['high'] for x in group),'low':min(x['low'] for x in group),'close':group[-1]['close'],'volume':sum(x['volume'] for x in group)})
                bucket=b; group=[]
            group.append(r)
        if len(group)>=3:
            out.append({'t':bucket,'open':group[0]['open'],'high':max(x['high'] for x in group),'low':min(x['low'] for x in group),'close':group[-1]['close'],'volume':sum(x['volume'] for x in group)})
        if len(out)<60: raise ValueError(f'Not enough verified 4h candle data for {symbol}')
        return out
    ys=yahoo_symbol(symbol)
    if not ys: raise ValueError(f'Unsupported symbol: {symbol}')
    days={'15m':7,'30m':20,'1h':45,'1d':900}[interval]
    params=urllib.parse.urlencode({'period1':int(time.time())-days*86400,'period2':int(time.time()),'interval':INTERVALS[interval],'events':'history','includeAdjustedClose':'true'})
    url='https://query1.finance.yahoo.com/v8/finance/chart/'+urllib.parse.quote(ys,safe='')+'?'+params
    req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 PipsMasterAcademy/1.0'})
    with urllib.request.urlopen(req,timeout=12) as r: raw=json.loads(r.read().decode())
    result=(raw.get('chart') or {}).get('result') or []
    if not result: raise ValueError(f'No verified market response for {symbol} {interval}')
    res=result[0]; ts=res.get('timestamp') or []; q=res['indicators']['quote'][0]
    rows=[]
    for i,t in enumerate(ts):
        try:
            o,h,l,c,v=q['open'][i],q['high'][i],q['low'][i],q['close'][i],q.get('volume',[0]*len(ts))[i]
            if None not in (o,h,l,c): rows.append({'t':t,'open':float(o),'high':float(h),'low':float(l),'close':float(c),'volume':float(v or 0)})
        except (IndexError,TypeError,ValueError): pass
    if len(rows)<60: raise ValueError(f'Not enough verified candle data for {symbol} {interval}')
    return rows

def ema(vals,n):
 k=2/(n+1); e=vals[0]
 for x in vals[1:]: e=x*k+e*(1-k)
 return e

def atr(rows,n=14):
 trs=[]
 for i,r in enumerate(rows):
  prev=rows[i-1]['close'] if i else r['close']; trs.append(max(r['high']-r['low'],abs(r['high']-prev),abs(r['low']-prev)))
 return mean(trs[-n:]) if len(trs)>=n else mean(trs)

def analyze(rows):
    closes=[r['close'] for r in rows]; e20=ema(closes[-120:],20); e50=ema(closes[-120:],50); last=closes[-1]; a=atr(rows)
    slope=ema(closes[-40:],20)-ema(closes[-60:-20],20) if len(closes)>=60 else 0
    if last>e20>e50 and slope>0: trend='Bullish'
    elif last<e20<e50 and slope<0: trend='Bearish'
    else: trend='Neutral'
    recent=rows[-60:]
    resistance=max(r['high'] for r in recent); support=min(r['low'] for r in recent)
    # Use the nearest qualifying zone that agrees with the dominant trend.
    if trend=='Bullish':
        direction='BUY'; zone_type='Demand / support'; zone=support; dist=max(last-support,0)
    elif trend=='Bearish':
        direction='SELL'; zone_type='Supply / resistance'; zone=resistance; dist=max(resistance-last,0)
    else:
        buy_dist=max(last-support,0); sell_dist=max(resistance-last,0)
        if buy_dist<=sell_dist: direction='BUY'; zone_type='Demand / support'; zone=support; dist=buy_dist
        else: direction='SELL'; zone_type='Supply / resistance'; zone=resistance; dist=sell_dist
    candles=max(1,math.ceil(dist/max(a,1e-12)))
    # The projected minutes are an estimate from recent ATR, not a promise about future price.
    return {'trend':trend,'last':last,'atr':a,'support':support,'resistance':resistance,'direction':direction,'zone_type':zone_type,'zone':zone,'distance':dist,'candles_to_zone':candles}

def pip_size(symbol):
    s=symbol.upper().replace('/','')
    if s.endswith('JPY'): return 0.01
    if s.startswith('XAU') or s.startswith('XAG'): return 0.01
    return 0.0001

def backtest(rows, lookahead=12):
    """Simple historical validation of the same trend/zone rule; never presented as guaranteed accuracy."""
    if len(rows)<160: return {'samples':0,'wins':0,'losses':0,'win_rate':None}
    wins=losses=0
    for i in range(80,len(rows)-lookahead,5):
        part=rows[:i+1]; a=analyze(part); entry=a['last']; target=a['atr']*1.0
        if a['direction']=='BUY':
            hit_win=any(r['high']>=entry+target for r in rows[i+1:i+1+lookahead]); hit_loss=any(r['low']<=entry-target for r in rows[i+1:i+1+lookahead])
        else:
            hit_win=any(r['low']<=entry-target for r in rows[i+1:i+1+lookahead]); hit_loss=any(r['high']>=entry+target for r in rows[i+1:i+1+lookahead])
        if hit_win and not hit_loss: wins+=1
        elif hit_loss and not hit_win: losses+=1
    n=wins+losses
    return {'samples':n,'wins':wins,'losses':losses,'win_rate':round(wins/n*100,1) if n else None}

