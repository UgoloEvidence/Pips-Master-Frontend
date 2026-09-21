import json, math, time, urllib.parse, urllib.request
from statistics import mean

YAHOO_MAP={
 'EURUSD':'EURUSD=X','GBPUSD':'GBPUSD=X','USDJPY':'JPY=X','USDCHF':'CHF=X','AUDUSD':'AUDUSD=X','USDCAD':'CAD=X','NZDUSD':'NZDUSD=X','EURGBP':'EURGBP=X','EURJPY':'EURJPY=X','GBPJPY':'GBPJPY=X','AUDJPY':'AUDJPY=X','EURAUD':'EURAUD=X','GBPAUD':'GBPAUD=X','XAUUSD':'GC=F','XAGUSD':'SI=F','WTI':'CL=F','USOIL':'CL=F','BRENT':'BZ=F','NATGAS':'NG=F','SPX':'^GSPC','SP500':'^GSPC','NAS100':'^NDX','NDX':'^NDX','US30':'^DJI','DOW':'^DJI','DAX':'^GDAXI','FTSE100':'^FTSE','NIKKEI':'^N225','BTCUSD':'BTC-USD','ETHUSD':'ETH-USD','XRPUSD':'XRP-USD','SOLUSD':'SOL-USD','BNBUSD':'BNB-USD','ADAUSD':'ADA-USD'}
INTERVALS={'15m':'15m','30m':'30m','1h':'1h','4h':'1h','1d':'1d'}
RANGES={'15m':'5d','30m':'10d','1h':'1mo','4h':'3mo','1d':'1y'}

def yahoo_symbol(s):
 s=s.upper().replace('/','').replace('-','')
 return YAHOO_MAP.get(s, s if s.endswith('=X') or s.startswith('^') else None)

def fetch(symbol, interval):
 ys=yahoo_symbol(symbol)
 if not ys: raise ValueError(f'Unsupported symbol: {symbol}')
 params=urllib.parse.urlencode({'period1':int(time.time())-({'15m':7,'30m':20,'1h':45,'4h':180,'1d':900}[interval])*86400,'period2':int(time.time()),'interval':INTERVALS[interval],'events':'history','includeAdjustedClose':'true'})
 url='https://query1.finance.yahoo.com/v8/finance/chart/'+urllib.parse.quote(ys,safe='')+'?'+params
 req=urllib.request.Request(url,headers={'User-Agent':'PipsMasterAcademy/1.0'})
 with urllib.request.urlopen(req,timeout=12) as r: raw=json.loads(r.read().decode())
 res=raw['chart']['result'][0]; ts=res.get('timestamp') or []; q=res['indicators']['quote'][0]
 rows=[]
 for i,t in enumerate(ts):
  try:
   o,h,l,c,v=q['open'][i],q['high'][i],q['low'][i],q['close'][i],q.get('volume',[0]*len(ts))[i]
   if None not in (o,h,l,c): rows.append({'t':t,'open':float(o),'high':float(h),'low':float(l),'close':float(c),'volume':float(v or 0)})
  except (IndexError,TypeError,ValueError): pass
 if len(rows)<60: raise ValueError(f'Not enough candle data for {symbol} {interval}')
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
 closes=[r['close'] for r in rows]; e20=ema(closes[-100:],20); e50=ema(closes[-100:],50); last=closes[-1]; a=atr(rows)
 if last>e20>e50: trend='Bullish'
 elif last<e20<e50: trend='Bearish'
 else: trend='Mixed'
 recent=rows[-40:]; resistance=max(r['high'] for r in recent); support=min(r['low'] for r in recent)
 # Entry zones are derived from recent swing levels plus a volatility buffer; they are estimates, not predictions.
 candidates=[]
 if last < resistance:
  candidates.append(('SELL','Supply / resistance',resistance,max(resistance-last,0)))
 if last > support:
  candidates.append(('BUY','Demand / support',support,max(last-support,0)))
 direction='BUY' if trend=='Bullish' else 'SELL' if trend=='Bearish' else min(candidates,key=lambda x:x[3])[0]
 chosen=[c for c in candidates if c[0]==direction] or candidates
 zone=min(chosen,key=lambda x:x[3])
 dist=zone[3]; candles=max(1,math.ceil(dist/max(a,1e-9)*0.75))
 return {'trend':trend,'last':last,'atr':a,'support':support,'resistance':resistance,'direction':zone[0],'zone_type':zone[1],'zone':zone[2],'distance':dist,'candles_to_zone':candles}
