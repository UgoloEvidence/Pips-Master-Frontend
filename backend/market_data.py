import json
import math
import time
from bisect import bisect_right
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from statistics import mean
from concurrent.futures import ThreadPoolExecutor, as_completed

YAHOO_MAP = {
    'EURUSD':'EURUSD=X','GBPUSD':'GBPUSD=X','USDJPY':'JPY=X','USDCHF':'CHF=X','AUDUSD':'AUDUSD=X','USDCAD':'CAD=X','NZDUSD':'NZDUSD=X',
    'EURGBP':'EURGBP=X','EURJPY':'EURJPY=X','GBPJPY':'GBPJPY=X','AUDJPY':'AUDJPY=X','EURAUD':'EURAUD=X','GBPAUD':'GBPAUD=X','EURCAD':'EURCAD=X','GBPCAD':'GBPCAD=X','AUDCAD':'AUDCAD=X','AUDNZD':'AUDNZD=X','NZDCAD':'NZDCAD=X','CHFJPY':'CHFJPY=X','CADCHF':'CADCHF=X','GBPNZD':'GBPNZD=X','EURNZD':'EURNZD=X','EURCHF':'EURCHF=X','GBPCHF':'GBPCHF=X',
    'XAUUSD':'GC=F','XAGUSD':'SI=F','XPTUSD':'PL=F','XPDUSD':'PA=F','WTI':'CL=F','USOIL':'CL=F','UKOIL':'BZ=F','BRENT':'BZ=F','NATGAS':'NG=F','COPPER':'HG=F',
    'SPX':'^GSPC','SP500':'^GSPC','SPX500':'^GSPC','NAS100':'^NDX','NDX':'^NDX','US30':'^DJI','DOW':'^DJI','DAX':'^GDAXI','GER40':'^GDAXI','FTSE100':'^FTSE','UK100':'^FTSE','NIKKEI':'^N225','JP225':'^N225','FRA40':'^FCHI',
    'BTCUSD':'BTC-USD','ETHUSD':'ETH-USD','XRPUSD':'XRP-USD','SOLUSD':'SOL-USD','BNBUSD':'BNB-USD','ADAUSD':'ADA-USD','LTCUSD':'LTC-USD'
}
INTERVALS = {'1m':'1m','5m':'5m','15m':'15m','30m':'30m','1h':'1h','1d':'1d'}
RANGES_DAYS = {'1m':7,'5m':60,'15m':60,'30m':60,'1h':180,'1d':1825}
RANGES = {'1m':'7d','5m':'60d','15m':'60d','30m':'60d','1h':'180d','1d':'5y'}
TIMEFRAME_MINUTES = {'1m':1,'5m':5,'15m':15,'30m':30,'1h':60,'4h':240,'1d':1440}
CACHE = {}
CACHE_TTL = 120
TV_CACHE = {}
TV_CACHE_TTL = 8


def norm_symbol(symbol: str) -> str:
    return str(symbol).upper().replace('/', '').replace('-', '').strip()


def yahoo_symbol(symbol: str):
    s = norm_symbol(symbol)
    return YAHOO_MAP.get(s, s if s.endswith('=X') or s.startswith('^') else None)


def aggregate_4h(rows):
    out = []
    bucket = None
    group = []
    for row in rows:
        # UTC four-hour buckets: 00, 04, 08, 12, 16, 20.
        b = (int(row['t']) // 14400) * 14400
        if bucket is None:
            bucket = b
        if b != bucket:
            if len(group) >= 3:
                out.append({
                    't': bucket,
                    'open': group[0]['open'],
                    'high': max(x['high'] for x in group),
                    'low': min(x['low'] for x in group),
                    'close': group[-1]['close'],
                    'volume': sum(x['volume'] for x in group),
                })
            bucket = b
            group = []
        group.append(row)
    if len(group) >= 3:
        out.append({
            't': bucket,
            'open': group[0]['open'],
            'high': max(x['high'] for x in group),
            'low': min(x['low'] for x in group),
            'close': group[-1]['close'],
            'volume': sum(x['volume'] for x in group),
        })
    if len(out) < 60:
        raise ValueError('Not enough verified 4h candle data')
    return out


def fetch(symbol: str, interval: str):
    symbol = norm_symbol(symbol)
    if interval not in {'1m','5m','15m','30m','1h','4h','1d'}:
        raise ValueError(f'Unsupported timeframe: {interval}')
    if interval == '4h':
        key = (symbol, interval)
        now = time.time()
        cached = CACHE.get(key)
        if cached and now - cached[0] < CACHE_TTL:
            return cached[1]
        base = fetch(symbol, '1h')
        rows = aggregate_4h(base)
        CACHE[key] = (now, rows)
        return rows

    ys = yahoo_symbol(symbol)
    if not ys:
        raise ValueError(f'Unsupported symbol: {symbol}')
    key = (symbol, interval)
    now = time.time()
    cached = CACHE.get(key)
    if cached and now - cached[0] < CACHE_TTL:
        return cached[1]

    # Yahoo's chart endpoint is more reliable on Render when using a bounded
    # range instead of calculated Unix periods, especially for intraday data.
    params = urllib.parse.urlencode({
        'range': RANGES[interval],
        'interval': INTERVALS[interval],
        'events': 'history',
        'includeAdjustedClose': 'true',
    })
    raw = None
    last_error = None
    def yahoo_call(host):
        url = f'https://{host}/v8/finance/chart/{urllib.parse.quote(ys, safe="")}?{params}'
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/153 Safari/537.36 PMA/3.0',
            'Accept': 'application/json,text/plain,*/*',
            'Accept-Encoding': 'identity', 'Referer': 'https://finance.yahoo.com/',
            'Connection': 'close',
        })
        with urllib.request.urlopen(req, timeout=3.5) as response:
            return json.loads(response.read().decode('utf-8', errors='replace'))
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = [pool.submit(yahoo_call, host) for host in ('query1.finance.yahoo.com','query2.finance.yahoo.com')]
        for job in as_completed(jobs):
            try:
                candidate = job.result()
                result = ((candidate.get('chart') or {}).get('result') or []) if candidate else []
                if result:
                    raw = candidate
                    break
                err = ((candidate.get('chart') or {}).get('error') or {}) if candidate else {}
                last_error = ValueError(err.get('description') or f'No verified response for {symbol} {interval}')
            except Exception as exc:
                last_error = exc

    result = ((raw.get('chart') or {}).get('result') or []) if raw else []
    if not result:
        stale = CACHE.get(key)
        if stale and stale[1]:
            return stale[1]
        raise ValueError(f'No verified market response for {symbol} {interval}: {last_error}')

    res = result[0]
    timestamps = res.get('timestamp') or []
    quote = (res.get('indicators') or {}).get('quote', [{}])[0] or {}
    volumes = quote.get('volume') or [0] * len(timestamps)
    rows = []
    for i, timestamp in enumerate(timestamps):
        try:
            o, h, l, c = quote['open'][i], quote['high'][i], quote['low'][i], quote['close'][i]
            if None in (o, h, l, c):
                continue
            rows.append({
                't': int(timestamp), 'open': float(o), 'high': float(h), 'low': float(l),
                'close': float(c), 'volume': float(volumes[i] or 0),
            })
        except (IndexError, TypeError, ValueError):
            continue
    if len(rows) < 60:
        raise ValueError(f'Not enough verified candle data for {symbol} {interval}: {len(rows)} rows')
    CACHE[key] = (now, rows)
    return rows



TV_TF = {'1m':'1','5m':'5','15m':'15','30m':'30','1h':'60','4h':'240','1d':'1D'}
TV_TICKER_PREFIXES = {
    'Forex': ['OANDA:', 'FX_IDC:'],
    'Metals': ['OANDA:', 'TVC:'],
    'Crypto': ['COINBASE:', 'BINANCE:'],
    'Indices': ['CAPITALCOM:', 'TVC:'],
    'Commodities': ['TVC:', 'OANDA:'],
}


def _tv_field(base, tf):
    suffix = TV_TF[tf]
    return base if tf == '1d' else f'{base}|{suffix}'


def _tv_tickers(symbol, market='Forex'):
    s = norm_symbol(symbol)
    if market == 'Crypto' and s.endswith('USD'):
        return [p + s for p in TV_TICKER_PREFIXES['Crypto']]
    return [p + s for p in TV_TICKER_PREFIXES.get(market, ['OANDA:', 'FX_IDC:'])]



def yahoo_verified_snapshots(symbol: str, timeframes=None):
    """Build the same lightweight MTF snapshot shape used by the TradingView path,
    using verified Yahoo OHLC candles when the TradingView scanner is unavailable.
    All requested frames are fetched concurrently and cached by fetch()."""
    frames = tuple(dict.fromkeys(timeframes or ('15m','30m','1h','4h','1d')))
    # 4h is derived from the already-verified 1h candles, so fetch 1h once.
    needed = tuple(dict.fromkeys(tuple(tf for tf in frames if tf != '4h') + (('1h',) if '4h' in frames else ())))
    # Preserve every requested frame except derived 4h.
    direct = tuple(tf for tf in needed if tf != '4h')
    fetched = {}
    with ThreadPoolExecutor(max_workers=max(1, len(direct))) as pool:
        jobs = {pool.submit(fetch, symbol, tf): tf for tf in direct}
        for job in as_completed(jobs):
            tf = jobs[job]
            fetched[tf] = job.result()
    if '4h' in frames:
        fetched['4h'] = aggregate_4h(fetched['1h'])
    out = {}
    for tf in frames:
        rows = fetched[tf]
        info = trend_info(rows)
        last = rows[-1]
        trend = info['trend']
        rsi_v = info['rsi']
        # This is a derived technical-bias value from verified candles, not a
        # fabricated TradingView rating and not a probability of winning.
        rec = 0.55 if trend == 'Bullish' else (-0.55 if trend == 'Bearish' else 0.0)
        if trend == 'Bullish' and rsi_v < 52: rec = 0.20
        if trend == 'Bearish' and rsi_v > 48: rec = -0.20
        out[tf] = {
            'ticker': yahoo_symbol(symbol) or norm_symbol(symbol),
            'open': float(last['open']), 'high': float(last['high']),
            'low': float(last['low']), 'close': float(last['close']),
            'rsi': float(info['rsi']), 'ema20': float(info['ema20']),
            'ema50': float(info['ema50']), 'ema100': float(info['ema100']),
            'atr': float(atr(rows)), 'recommend': rec,
            's1': float(info['support']), 'r1': float(info['resistance']),
            'change': ((last['close']-rows[-2]['close'])/rows[-2]['close']*100) if len(rows)>1 and rows[-2]['close'] else 0.0,
            'provider': 'Yahoo Finance verified OHLC',
        }
    return out

def _tv_scan_many(symbols, market='Forex', timeframes=None):
    """Fetch one fresh TradingView snapshot for several symbols in a single request.

    This is the fast path for the scanner/day-trade watchlist. It keeps the same
    provider and fields as _tv_scan but removes the N-per-symbol HTTP round trips.
    """
    timeframes = tuple(timeframes or ('15m','30m','1h','4h','1d'))
    symbols = [norm_symbol(x) for x in symbols if norm_symbol(x)]
    if not symbols:
        return {}
    cache_key = ('many', tuple(sorted(symbols)), market, timeframes)
    now = time.time()
    cached = TV_CACHE.get(cache_key)
    if cached and now - cached[0] < TV_CACHE_TTL:
        return cached[1]
    columns=[]
    bases=['open','high','low','close','RSI','EMA20','EMA50','EMA100','ATR','Recommend.All',
           'Pivot.M.Classic.S1','Pivot.M.Classic.R1','change']
    for tf in timeframes:
        for base in bases:
            columns.append(_tv_field(base,tf))
    endpoint=('https://scanner.tradingview.com/forex/scan' if market in ('Forex','Metals') else
              ('https://scanner.tradingview.com/crypto/scan' if market=='Crypto' else
               'https://scanner.tradingview.com/global/scan'))
    tickers=[]
    for sym in symbols:
        prefixes=TV_TICKER_PREFIXES.get(market,['OANDA:','FX_IDC:'])
        for pref in prefixes:
            tickers.append(pref+sym)
    payload={'symbols':{'tickers':tickers,'query':{'types':[]}},'columns':columns,'range':[0,len(tickers)],'options':{'lang':'en'}}
    req=urllib.request.Request(endpoint,data=json.dumps(payload).encode('utf-8'),headers={
        'Content-Type':'application/json','Accept':'application/json','User-Agent':'Mozilla/5.0 PMA/5.0',
        'Origin':'https://www.tradingview.com','Referer':'https://www.tradingview.com/'})
    with urllib.request.urlopen(req,timeout=1.8) as response:
        raw=json.loads(response.read().decode('utf-8',errors='replace'))
    rows=raw.get('data') or []
    out={}
    wanted=set(symbols)
    for row in rows:
        ticker=str(row.get('s') or '')
        sym=None
        for candidate in symbols:
            if ticker.upper().endswith(':'+candidate) or ticker.upper()==candidate:
                sym=candidate; break
        if not sym or sym in out: continue
        vals=row.get('d') or []
        if len(vals)!=len(columns): continue
        flat=dict(zip(columns,vals)); snap={}
        for tf in timeframes:
            def num(base):
                v=flat.get(_tv_field(base,tf))
                try:return float(v) if v is not None else None
                except (TypeError,ValueError):return None
            snap[tf]={'ticker':ticker,'open':num('open'),'high':num('high'),'low':num('low'),'close':num('close'),
                      'rsi':num('RSI'),'ema20':num('EMA20'),'ema50':num('EMA50'),'ema100':num('EMA100'),'atr':num('ATR'),
                      'recommend':num('Recommend.All'),'s1':num('Pivot.M.Classic.S1'),'r1':num('Pivot.M.Classic.R1'),'change':num('change')}
        if any(snap[tf].get('close') is not None for tf in timeframes): out[sym]=snap
    if not out:
        raise ValueError(f'No verified TradingView rows returned for {market}')
    TV_CACHE[cache_key]=(time.time(),out)
    return out

def _tv_scan(symbol, market='Forex', timeframes=None):
    """Fetch a verified multi-timeframe snapshot quickly.

    The scanner uses one TradingView request containing every requested timeframe.
    Results are cached briefly so switching between scanner/MTF/day-trade views does
    not repeatedly hit the provider for the same fresh candle snapshot.
    """
    timeframes = tuple(timeframes or ('15m','30m','1h','4h','1d'))
    cache_key = (norm_symbol(symbol), market, timeframes)
    now = time.time()
    cached = TV_CACHE.get(cache_key)
    if cached and now - cached[0] < TV_CACHE_TTL:
        return cached[1]

    columns = []
    bases = ['open','high','low','close','RSI','EMA20','EMA50','EMA100','ATR','Recommend.All',
             'Pivot.M.Classic.S1','Pivot.M.Classic.R1','change']
    for tf in timeframes:
        for base in bases:
            columns.append(_tv_field(base, tf))

    def request_ticker(ticker):
        endpoint = ('https://scanner.tradingview.com/forex/scan' if market in ('Forex','Metals') else
                    ('https://scanner.tradingview.com/crypto/scan' if market == 'Crypto' else
                     'https://scanner.tradingview.com/global/scan'))
        payload = {'symbols': {'tickers': [ticker], 'query': {'types': []}},
                   'columns': columns, 'range': [0, 1], 'options': {'lang': 'en'}}
        req = urllib.request.Request(endpoint, data=json.dumps(payload).encode('utf-8'), headers={
            'Content-Type':'application/json','Accept':'application/json',
            'User-Agent':'Mozilla/5.0 PMA/4.0','Origin':'https://www.tradingview.com',
            'Referer':'https://www.tradingview.com/'})
        with urllib.request.urlopen(req, timeout=3.5) as response:
            raw = json.loads(response.read().decode('utf-8', errors='replace'))
        rows = raw.get('data') or []
        if not rows:
            raise ValueError(f'TradingView returned no row for {ticker}')
        values = rows[0].get('d') or []
        if len(values) != len(columns):
            raise ValueError(f'TradingView returned an unexpected column count for {ticker}')
        flat = dict(zip(columns, values))
        out = {}
        for tf in timeframes:
            def num(base):
                v = flat.get(_tv_field(base, tf))
                try: return float(v) if v is not None else None
                except (TypeError, ValueError): return None
            out[tf] = {'ticker': rows[0].get('s', ticker), 'open':num('open'), 'high':num('high'),
                       'low':num('low'), 'close':num('close'), 'rsi':num('RSI'), 'ema20':num('EMA20'),
                       'ema50':num('EMA50'), 'ema100':num('EMA100'), 'atr':num('ATR'),
                       'recommend':num('Recommend.All'), 's1':num('Pivot.M.Classic.S1'),
                       'r1':num('Pivot.M.Classic.R1'), 'change':num('change')}
        if not any(out[tf].get('close') is not None for tf in timeframes):
            raise ValueError(f'No verified close returned for {ticker}')
        return out

    tickers = _tv_tickers(symbol, market)
    last_error = None
    # Try provider symbols in parallel: a dead first ticker must not cost another full timeout.
    with ThreadPoolExecutor(max_workers=max(1, len(tickers))) as pool:
        jobs = {pool.submit(request_ticker, ticker): ticker for ticker in tickers}
        for job in as_completed(jobs):
            try:
                out = job.result()
                TV_CACHE[cache_key] = (time.time(), out)
                return out
            except Exception as exc:
                last_error = exc
    raise ValueError(f'No verified TradingView market response for {symbol}: {last_error}')


def _snapshot_trend(s):
    close, e20, e50, e100 = s.get('close'), s.get('ema20'), s.get('ema50'), s.get('ema100')
    if None in (close, e20, e50): return 'Neutral'
    if close > e20 > e50 and (e100 is None or e50 > e100): return 'Bullish'
    if close < e20 < e50 and (e100 is None or e50 < e100): return 'Bearish'
    if close > e20 > e50: return 'Bullish'
    if close < e20 < e50: return 'Bearish'
    return 'Neutral'


def _closed_candle_pair(symbol, timeframe):
    """Return the two most recent fully closed candles.

    The live provider can expose the currently forming candle. Sniper confirmation
    must never use that partial candle. A trigger is therefore evaluated only on a
    candle whose end time has already passed.
    """
    rows = fetch(symbol, timeframe)
    mins = TIMEFRAME_MINUTES.get(timeframe, 15)
    now_ts = int(time.time())
    closed = [r for r in rows if int(r.get('t', 0)) + mins * 60 <= now_ts]
    if len(closed) < 3:
        raise ValueError(f'No fully closed {timeframe} candle is available yet')
    return closed[-2], closed[-1], rows[-1]


def candle_confirmation(symbol, timeframe):
    """Use verified historical candles when available to confirm the sniper trigger.
    Returns the last/previous candle relationship without pretending a one-candle
    TradingView snapshot contains historical candle data.
    """
    try:
        rows = fetch(symbol, timeframe)
        if len(rows) < 3:
            return {'available':False,'reason':'Not enough verified candles'}
        prev, cur, live = _closed_candle_pair(symbol, timeframe)
        prev_bull = prev['close'] > prev['open']
        prev_bear = prev['close'] < prev['open']
        cur_bull = cur['close'] > cur['open']
        cur_bear = cur['close'] < cur['open']
        bullish_engulfing = (prev_bear and cur_bull and cur['open'] <= prev['close'] and cur['close'] >= prev['open'])
        bearish_engulfing = (prev_bull and cur_bear and cur['open'] >= prev['close'] and cur['close'] <= prev['open'])
        cur_range=max(cur['high']-cur['low'],1e-12)
        lower_wick=min(cur['open'],cur['close'])-cur['low']
        upper_wick=cur['high']-max(cur['open'],cur['close'])
        bullish_rejection=lower_wick >= cur_range*0.35 and cur['close'] >= cur['open']
        bearish_rejection=upper_wick >= cur_range*0.35 and cur['close'] <= cur['open']
        p2=rows[-3]
        recent=rows[-30:]
        range_high=max(r['high'] for r in recent); range_low=min(r['low'] for r in recent); midpoint=(range_high+range_low)/2
        bullish_fvg=cur['low'] > p2['high']
        bearish_fvg=cur['high'] < p2['low']
        bullish_sweep=cur['low'] < prev['low'] and cur['close'] > prev['low']
        bearish_sweep=cur['high'] > prev['high'] and cur['close'] < prev['high']
        displacement_up=cur['close']>cur['open'] and (cur['close']-cur['open']) >= cur_range*0.55
        displacement_down=cur['close']<cur['open'] and (cur['open']-cur['close']) >= cur_range*0.55
        bullish_mss=bullish_sweep and cur['close']>max(r['high'] for r in rows[-6:-1])
        bearish_mss=bearish_sweep and cur['close']<min(r['low'] for r in rows[-6:-1])
        avg_vol=mean([r.get('volume',0) for r in recent[:-1]]) if recent[:-1] else 0
        vsa_bull=bool(avg_vol and cur.get('volume',0)>avg_vol*1.25 and cur_bull and lower_wick>upper_wick)
        vsa_bear=bool(avg_vol and cur.get('volume',0)>avg_vol*1.25 and cur_bear and upper_wick>lower_wick)
        order_block_bullish=any(r['close']<r['open'] for r in rows[-5:-1]) and displacement_up
        order_block_bearish=any(r['close']>r['open'] for r in rows[-5:-1]) and displacement_down
        wyckoff_spring=bullish_sweep and cur_bull
        wyckoff_upthrust=bearish_sweep and cur_bear
        return {'available':True,'bullish_engulfing':bullish_engulfing,'bearish_engulfing':bearish_engulfing,
                'bullish_rejection':bullish_rejection,'bearish_rejection':bearish_rejection,
                'bullish_fvg':bullish_fvg,'bearish_fvg':bearish_fvg,'bullish_sweep':bullish_sweep,'bearish_sweep':bearish_sweep,
                'bullish_mss':bullish_mss,'bearish_mss':bearish_mss,'displacement_up':displacement_up,'displacement_down':displacement_down,
                'order_block_bullish':order_block_bullish,'order_block_bearish':order_block_bearish,'wyckoff_spring':wyckoff_spring,'wyckoff_upthrust':wyckoff_upthrust,
                'premium_discount':'discount' if cur['close']<=midpoint else 'premium','vsa_bull':vsa_bull,'vsa_bear':vsa_bear,
                'previous_open':prev['open'],'previous_close':prev['close'],'current_open':cur['open'],'current_close':cur['close'],
                'previous_time':prev.get('t'),'current_time':cur.get('t'),'live_close':live.get('close'),'closed_candle':True,'confirmation_age_seconds':max(0,int(time.time())-(cur.get('t',int(time.time()))+TIMEFRAME_MINUTES.get(timeframe,15)*60))}
    except Exception as exc:
        return {'available':False,'reason':str(exc)}



def _linreg_slope(values):
    if len(values) < 3:
        return 0.0
    n=len(values); xm=(n-1)/2; ym=sum(values)/n
    den=sum((i-xm)**2 for i in range(n)) or 1.0
    return sum((i-xm)*(v-ym) for i,v in enumerate(values))/den


def detect_chart_patterns(rows):
    """Detect common price-action/chart patterns on the selected timeframe.

    These are heuristic pattern recognizers, not standalone trade signals. A pattern
    can be displayed as confluence, but the main scanner still requires its existing
    pullback, confirmation-candle, freshness and risk gates before marking READY.
    """
    if len(rows) < 30:
        return []
    r=rows[-60:]
    closes=[x['close'] for x in r]
    highs=[x['high'] for x in r]
    lows=[x['low'] for x in r]
    avg=max(mean(closes),1e-12)
    a=max(atr(r),1e-12)
    patterns=[]

    def add(name,direction,confidence,description):
        patterns.append({'name':name,'direction':direction,'confidence':round(float(max(0,min(100,confidence))),1),'description':description})

    # Regression-based wedge / triangle geometry over the latest 24 candles.
    w=r[-24:]
    hi_s=_linreg_slope([x['high'] for x in w])/avg
    lo_s=_linreg_slope([x['low'] for x in w])/avg
    hi_span=max(x['high'] for x in w)-min(x['high'] for x in w)
    lo_span=max(x['low'] for x in w)-min(x['low'] for x in w)
    if hi_s < -0.00008 and lo_s < -0.00004 and abs(hi_s) > abs(lo_s)*1.10 and hi_span>2*a and lo_span>2*a:
        add('Falling Wedge','BUY',78,'Converging downward boundaries detected; wait for a bullish break/retest or lower-zone confirmation.')
    if hi_s > 0.00004 and lo_s > 0.00008 and abs(lo_s) > abs(hi_s)*1.10 and hi_span>2*a and lo_span>2*a:
        add('Rising Wedge','SELL',78,'Converging upward boundaries detected; wait for a bearish break/retest or upper-zone confirmation.')
    if hi_s < -0.00005 and lo_s > 0.00005 and hi_span>2*a and lo_span>2*a:
        add('Contracting Triangle','NEUTRAL',72,'Lower highs and higher lows are compressing price; wait for a confirmed breakout and retest.')

    # Local extrema for double-top/bottom and head-and-shoulders style structures.
    ph=[]; pl=[]
    for i in range(2,len(r)-2):
        if highs[i]>=max(highs[i-2:i+3]): ph.append((i,highs[i]))
        if lows[i]<=min(lows[i-2:i+3]): pl.append((i,lows[i]))
    tol=max(a*0.65,avg*0.0007)
    if len(ph)>=2:
        x1,y1=ph[-2]; x2,y2=ph[-1]
        if x2-x1>=4 and abs(y2-y1)<=tol:
            add('Double Top','SELL',76,'Two nearby swing highs detected; confirmation requires a neckline break/retest.')
    if len(pl)>=2:
        x1,y1=pl[-2]; x2,y2=pl[-1]
        if x2-x1>=4 and abs(y2-y1)<=tol:
            add('Double Bottom','BUY',76,'Two nearby swing lows detected; confirmation requires a neckline break/retest.')
    if len(ph)>=3:
        (i1,h1),(i2,h2),(i3,h3)=ph[-3:]
        shoulder=max(abs(h1-h3),tol*0.5)
        if i2-i1>=3 and i3-i2>=3 and h2>h1+tol*0.5 and h2>h3+tol*0.5 and abs(h1-h3)<=tol*1.25:
            add('Head & Shoulders','SELL',80,'Three-peak structure with a higher middle peak detected; neckline confirmation is required.')
    if len(pl)>=3:
        (i1,l1),(i2,l2),(i3,l3)=pl[-3:]
        if i2-i1>=3 and i3-i2>=3 and l2<l1-tol*0.5 and l2<l3-tol*0.5 and abs(l1-l3)<=tol*1.25:
            add('Inverse Head & Shoulders','BUY',80,'Three-trough structure with a lower middle trough detected; neckline confirmation is required.')

    # Flags / pennants: strong impulse followed by a compact correction.
    if len(r)>=18:
        impulse=r[-18:-8]; corr=r[-8:]
        impulse_move=impulse[-1]['close']-impulse[0]['close']
        corr_move=corr[-1]['close']-corr[0]['close']
        corr_range=max(x['high'] for x in corr)-min(x['low'] for x in corr)
        if impulse_move>3*a and abs(corr_move)<abs(impulse_move)*0.45 and corr_range<abs(impulse_move)*0.75:
            add('Bull Flag','BUY',74,'Strong bullish impulse followed by a compact pullback; wait for continuation confirmation.')
        if impulse_move<-3*a and abs(corr_move)<abs(impulse_move)*0.45 and corr_range<abs(impulse_move)*0.75:
            add('Bear Flag','SELL',74,'Strong bearish impulse followed by a compact pullback; wait for continuation confirmation.')

    # Breakout/retest and failed-break patterns.
    prior_hi=max(x['high'] for x in r[-21:-3]); prior_lo=min(x['low'] for x in r[-21:-3])
    recent=r[-3:]; last=recent[-1]
    near_hi=abs(last['close']-prior_hi)<=a*0.35
    near_lo=abs(last['close']-prior_lo)<=a*0.35
    if max(x['high'] for x in recent)>prior_hi and last['close']>prior_hi:
        add('Breakout / Retest','BUY',73,'Recent high was broken and price remains above the breakout area; retest confirmation is required.')
    if min(x['low'] for x in recent)<prior_lo and last['close']<prior_lo:
        add('Breakdown / Retest','SELL',73,'Recent low was broken and price remains below the breakdown area; retest confirmation is required.')
    if max(x['high'] for x in recent)>prior_hi and last['close']<prior_hi:
        add('Failed Break / Bull Trap','SELL',75,'Price swept a recent high but closed back below it; bearish confirmation is still required.')
    if min(x['low'] for x in recent)<prior_lo and last['close']>prior_lo:
        add('Failed Break / Bear Trap','BUY',75,'Price swept a recent low but closed back above it; bullish confirmation is still required.')

    # Range/consolidation.
    rg=max(x['high'] for x in r[-20:])-min(x['low'] for x in r[-20:])
    if rg <= max(a*7.0,avg*0.004):
        add('Range / Consolidation','NEUTRAL',68,'Price is compressed in a range; wait for a clean rejection or confirmed breakout.')

    # Deduplicate by pattern name while keeping the strongest observation.
    best={}
    for item in patterns:
        if item['name'] not in best or item['confidence']>best[item['name']]['confidence']:
            best[item['name']]=item
    return sorted(best.values(),key=lambda x:x['confidence'],reverse=True)[:6]

def _enhanced_context(symbol, trigger_tf, direction, close, atr_v):
    """Verified-candle confluence used as a second gate for live setups.
    This is deliberately conservative: missing data means the extra confirmation is unavailable.
    """
    try:
        rows=fetch(symbol, trigger_tf)
        if len(rows)<40:
            return {'available':False,'reason':'Not enough verified candles'}
        recent=rows[-40:]
        hi=max(r['high'] for r in recent); lo=min(r['low'] for r in recent)
        rng=max(hi-lo,1e-12)
        # 50% to 61.8% retracement measured from the recent impulse leg.
        if direction=='BUY':
            mid50=hi-rng*0.50
            fib618=hi-rng*0.618
        else:
            mid50=lo+rng*0.50
            fib618=lo+rng*0.618
        zone_low=min(mid50,fib618); zone_high=max(mid50,fib618)
        in_fib=zone_low-atr_v*0.12 <= close <= zone_high+atr_v*0.12
        cc=candle_confirmation(symbol,trigger_tf)
        patterns=detect_chart_patterns(rows)
        regime='TRENDING' if direction in ('BUY','SELL','BULLISH','BEARISH') else 'RANGING'
        # Range detection: recent high/low compression relative to ATR.
        ranges=[r['high']-r['low'] for r in recent[-14:]]
        avg_range=mean(ranges) if ranges else atr_v
        compressed=(rng <= max(atr_v*5.0, avg_range*8.0))
        if zone_low <= close <= zone_high: location='50–61.8% retracement'
        elif in_fib: location='near 50–61.8% retracement'
        else: location='outside primary retracement zone'
        bull_conf=sum(bool(cc.get(k)) for k in ('bullish_engulfing','bullish_rejection','bullish_sweep','bullish_mss','displacement_up','bullish_fvg','vsa_bull'))
        bear_conf=sum(bool(cc.get(k)) for k in ('bearish_engulfing','bearish_rejection','bearish_sweep','bearish_mss','displacement_down','bearish_fvg','vsa_bear'))
        confirmations=bull_conf if direction=='BUY' else bear_conf if direction=='SELL' else max(bull_conf,bear_conf)
        pattern_conf=sum(1 for p in patterns if p.get('direction') in (direction,'NEUTRAL'))
        return {'available':True,'fib50':mid50,'fib618':fib618,'fib_zone_low':zone_low,'fib_zone_high':zone_high,
                'in_fib_zone':in_fib,'retracement_location':location,'regime':regime,'compressed':compressed,
                'confirmations':confirmations,'pattern_confidence':pattern_conf,'patterns':patterns,'candle':cc}
    except Exception as ex:
        return {'available':False,'reason':str(ex)}

def _tv_setup(symbol, market, trigger_tf, snaps):
    """Create a forecast-first setup instead of chasing price at a zone.

    A setup can be a forecast before price reaches supply/demand. A READY state is
    reserved for an actual trigger/rejection condition. This is deliberately not a
    guarantee of the next market move.
    """
    trigger = snaps[trigger_tf]
    trend = _snapshot_trend(trigger)
    context = {tf: _snapshot_trend(snaps[tf]) for tf in ('15m','30m','1h','4h','1d') if tf in snaps}
    bull = sum(v == 'Bullish' for v in context.values())
    bear = sum(v == 'Bearish' for v in context.values())
    rec = trigger.get('recommend') if trigger.get('recommend') is not None else 0
    rsi_v = trigger.get('rsi') if trigger.get('rsi') is not None else 50
    close = trigger.get('close')
    atr_v = max(trigger.get('atr') or 0, 1e-12)
    s1, r1 = trigger.get('s1'), trigger.get('r1')
    if close is None: raise ValueError(f'No verified close for {symbol} {trigger_tf}')

    direction = 'NO TRADE'; status = 'WAITING FOR CONFIRMATION'; reasons = []
    entry = stop = tp1 = tp2 = next_zone = trigger_price = None
    zone_type = None

    near_supply = r1 is not None and r1 > close and (r1 - close) <= atr_v * 0.85
    near_demand = s1 is not None and s1 < close and (close - s1) <= atr_v * 0.85
    # High-precision gate: the goal is to reject marginal setups rather than
    # manufacture more signals. This reduces signal frequency, but it is the
    # main lever available when the objective is higher historical precision.
    # Avoid chasing when RSI is already stretched and require stronger MTF
    # alignment + TradingView technical confirmation.
    buy_rsi_ok = 52 <= rsi_v <= 68
    sell_rsi_ok = 32 <= rsi_v <= 48
    buy_context = trend == 'Bullish' and buy_rsi_ok and bull >= 3 and rec >= 0.25
    sell_context = trend == 'Bearish' and sell_rsi_ok and bear >= 3 and rec <= -0.25

    # Pullback-only entry rule: trend identifies the direction, but never authorizes
    # an immediate market entry. BUY requires a retrace into demand plus rejection;
    # SELL requires a retrace into supply plus rejection.
    zone_tol = atr_v * 0.18
    supply_reached = r1 is not None and close >= r1 - zone_tol
    demand_reached = s1 is not None and close <= s1 + zone_tol
    supply_broken = r1 is not None and close > r1 + atr_v * 0.25
    demand_broken = s1 is not None and close < s1 - atr_v * 0.25
    last_open = trigger.get('open') or close
    last_high = trigger.get('high') or close
    last_low = trigger.get('low') or close
    bullish_rejection = (s1 is not None and demand_reached and close > s1 and last_low <= s1 + zone_tol and close >= last_open and rec >= 0.25)
    bearish_rejection = (r1 is not None and supply_reached and close < r1 and last_high >= r1 - zone_tol and close <= last_open and rec <= -0.25)
    candle_conf = {'available':False}
    if bullish_rejection or bearish_rejection:
        candle_conf = candle_confirmation(symbol, trigger_tf)
    bullish_sniper = bullish_rejection and candle_conf.get('available') and candle_conf.get('bullish_engulfing')
    bearish_sniper = bearish_rejection and candle_conf.get('available') and candle_conf.get('bearish_engulfing')
    enhanced=_enhanced_context(symbol, trigger_tf, 'BUY' if buy_context else ('SELL' if sell_context else trend.upper()), close, atr_v)
    candle_conf = enhanced.get('candle', candle_conf) if enhanced.get('available') else candle_conf
    confirmed_close = candle_conf.get('current_close') if candle_conf.get('closed_candle') else None
    confirmation_age = candle_conf.get('confirmation_age_seconds') if candle_conf.get('closed_candle') else None
    tf_seconds = TIMEFRAME_MINUTES.get(trigger_tf, 15) * 60
    confirmation_fresh = bool(candle_conf.get('closed_candle')) and confirmation_age is not None and confirmation_age <= tf_seconds
    # The decisive candle must have CLOSED. Never trigger from an in-progress candle.
    bullish_sniper = bool(candle_conf.get('available') and candle_conf.get('bullish_rejection') and candle_conf.get('bullish_engulfing') and confirmation_fresh)
    bearish_sniper = bool(candle_conf.get('available') and candle_conf.get('bearish_rejection') and candle_conf.get('bearish_engulfing') and confirmation_fresh)
    fib_ok=bool(enhanced.get('in_fib_zone')) if enhanced.get('available') else False
    # A confirmed setup may use the 50–61.8% zone as confluence, but it is never
    # allowed to be the only reason for an entry.
    if enhanced.get('available'):
        if fib_ok: reasons.append('Verified 50–61.8% retracement confluence detected')
        if enhanced.get('confirmations',0)>=2: reasons.append(f"Lower-timeframe confirmation cluster: {enhanced.get('confirmations')}")
        for ptn in (enhanced.get('patterns') or [])[:3]:
            reasons.append(f"Chart pattern detected: {ptn['name']} ({ptn['direction']})")

    # Opposing-zone protection: once an uptrend reaches supply, do not issue BUY;
    # once a downtrend reaches demand, do not issue SELL. Wait for a fresh setup.
    if trend == 'Bullish' and supply_reached and not bullish_rejection:
        direction='NO TRADE'; status='ZONE REJECTION / NO BUY'; next_zone=s1 if s1 is not None else close-atr_v; entry=None; zone_type='Supply reached — BUY blocked'
        reasons=['Bullish trend remains context only','Price has reached/approached supply; BUY is blocked here','Wait for a fresh demand pullback instead of entering into rejection']
        trigger_text='NO BUY at supply; wait for the next demand pullback and rejection'
    elif trend == 'Bearish' and demand_reached and not bearish_rejection:
        direction='NO TRADE'; status='ZONE REJECTION / NO SELL'; next_zone=r1 if r1 is not None else close+atr_v; entry=None; zone_type='Demand reached — SELL blocked'
        reasons=['Bearish trend remains context only','Price has reached/approached demand; SELL is blocked here','Wait for a fresh supply pullback instead of entering into rejection']
        trigger_text='NO SELL at demand; wait for the next supply pullback and rejection'
    elif buy_context:
        direction='BUY'; status='FORECAST'
        trigger_price=s1 if s1 is not None else close-atr_v
        entry=trigger_price
        stop=(s1-atr_v*0.20) if s1 is not None else trigger_price-atr_v*0.20
        risk=max(entry-stop,atr_v*0.20)
        tp1=r1 if r1 is not None and r1>entry else close+risk
        tp2=tp1+risk
        next_zone=trigger_price; zone_type='Demand pullback / bullish continuation'
        reasons=['Bullish MTF trend identified; this is a forecast, not an immediate BUY',f'{bull}/5 context timeframes are bullish',f'RSI supports the bullish bias at {rsi_v:.1f}','Wait for price to retrace into demand and reject it before BUY']
        if supply_broken:
            direction='NO TRADE'; status='FORECAST INVALIDATED'; entry=None; stop=None; tp1=None; tp2=None
            reasons=['Bullish forecast invalidated: price has already broken the projected supply/resistance zone','No BUY is issued after an extended move; wait for a fresh pullback structure']
        elif bullish_sniper:
            status='SIGNAL READY'; entry=close; stop=(s1-atr_v*0.20) if s1 is not None else close-atr_v*0.20
            risk=max(entry-stop,atr_v*0.20); tp1=r1 if r1 is not None and r1>entry else entry+risk; tp2=tp1+risk
            reasons.append('Demand was reached and the verified trigger candle supplied sniper confirmation (rejection/engulfing)')
        trigger_text=f'WAIT for pullback into demand near {trigger_price:.8f}; require rejection + bullish engulfing/sniper confirmation before BUY'
        if bullish_rejection and not bullish_sniper:
            status='WAITING FOR CONFIRMATION'
            reasons.append('Zone rejection detected, but the verified candle confirmation is not strong enough for the sniper entry yet')
    elif sell_context:
        direction='SELL'; status='FORECAST'
        trigger_price=r1 if r1 is not None else close+atr_v
        entry=trigger_price
        stop=(r1+atr_v*0.20) if r1 is not None else trigger_price+atr_v*0.20
        risk=max(stop-entry,atr_v*0.20)
        tp1=s1 if s1 is not None and s1<entry else close-risk
        tp2=tp1-risk
        next_zone=trigger_price; zone_type='Supply pullback / bearish continuation'
        reasons=['Bearish MTF trend identified; this is a forecast, not an immediate SELL',f'{bear}/5 context timeframes are bearish',f'RSI supports the bearish bias at {rsi_v:.1f}','Wait for price to retrace into supply and reject it before SELL']
        if demand_broken:
            direction='NO TRADE'; status='FORECAST INVALIDATED'; entry=None; stop=None; tp1=None; tp2=None
            reasons=['Bearish forecast invalidated: price has already broken the projected demand/support zone','No SELL is issued after an extended move; wait for a fresh pullback structure']
        elif bearish_sniper:
            status='SIGNAL READY'; entry=close; stop=(r1+atr_v*0.20) if r1 is not None else close+atr_v*0.20
            risk=max(stop-entry,atr_v*0.20); tp1=s1 if s1 is not None and s1<entry else entry-risk; tp2=tp1-risk
            reasons.append('Supply was reached and the verified trigger candle supplied sniper confirmation (rejection/engulfing)')
        trigger_text=f'WAIT for pullback into supply near {trigger_price:.8f}; require rejection + bearish engulfing/sniper confirmation before SELL'
        if bearish_rejection and not bearish_sniper:
            status='WAITING FOR CONFIRMATION'
            reasons.append('Zone rejection detected, but the verified candle confirmation is not strong enough for the sniper entry yet')
    elif trend == 'Bullish' and bull >= 3:
        direction='NO TRADE'; status='WAITING FOR PULLBACK'; next_zone=s1 if s1 is not None else close-atr_v; entry=next_zone; zone_type='Demand pullback required'
        reasons=['Bullish trend identified across multiple timeframes','No BUY at current price: wait for a demand pullback and rejection']
        trigger_text=f'WAIT for demand pullback near {next_zone:.8f}; no market BUY'
    elif trend == 'Bearish' and bear >= 3:
        direction='NO TRADE'; status='WAITING FOR PULLBACK'; next_zone=r1 if r1 is not None else close+atr_v; entry=next_zone; zone_type='Supply pullback required'
        reasons=['Bearish trend identified across multiple timeframes','No SELL at current price: wait for a supply pullback and rejection']
        trigger_text=f'WAIT for supply pullback near {next_zone:.8f}; no market SELL'
    else:
        reasons=['Confluence is insufficient for a pullback forecast',f'Trigger timeframe trend: {trend}',f'TradingView technical rating: {rec:.2f}']
        trigger_text=f'Wait for clearer {trigger_tf} structure and a pullback zone'

    # Fresh-entry gate: once the confirming candle is no longer the latest closed
    # candle, or price has already travelled materially away from the confirmed
    # close, the setup expires. The scanner must wait for a new pullback/retest.
    late_entry_blocked = False
    if status == 'SIGNAL READY' and confirmed_close is not None:
        live_price = float(close)
        travel = abs(live_price - confirmed_close)
        max_travel = max(atr_v * 0.35, abs(confirmed_close) * 0.00008)
        if (not confirmation_fresh) or travel > max_travel:
            late_entry_blocked = True
            direction = 'NO TRADE'
            status = 'LATE ENTRY BLOCKED'
            entry = stop = tp1 = tp2 = None
            reasons.append('Late-entry protection: the confirmed candle is no longer fresh or price has already moved too far')
            reasons.append('Wait for a new pullback/rejection and a new candle-close confirmation')
            trigger_text = 'LATE ENTRY BLOCKED — wait for a fresh pullback and a newly closed confirmation candle'

    if direction == 'NO TRADE':
        distance=abs((next_zone or close)-close)
        tf_minutes=TIMEFRAME_MINUTES.get(trigger_tf,15)
        candles=max(1,min(96,math.ceil(distance/max(atr_v,1e-12)))) if distance else 0
        return {'direction':'NO TRADE','score':0,'status':status,'reasons':reasons,'structure':'Bullish trend / pullback pending' if trend=='Bullish' else ('Bearish trend / pullback pending' if trend=='Bearish' else 'Mixed / no confirmed structure'),
                'trigger_text':trigger_text,'trigger_price':trigger_price,'entry_zone':entry,'stop_loss':stop,
                'take_profit_1':tp1,'take_profit_2':tp2,'next_zone':next_zone,'next_zone_type':zone_type,'candles_to_next_zone':candles,
                'estimated_minutes_to_next_zone':candles*tf_minutes,'distance_to_next_zone':distance,'atr':atr_v,'last':close,'support':s1,'resistance':r1,
                'rsi':rsi_v,'trend':trend,'trend_scores':list(context.values()),'context_trends':context,
                'confirmation_candle_time': enhanced.get('candle',{}).get('current_time'),'confirmation_candle_closed': bool(enhanced.get('candle',{}).get('closed_candle')),'confirmation_age_seconds': enhanced.get('candle',{}).get('confirmation_age_seconds'),'entry_fresh': bool(status=='SIGNAL READY' and not late_entry_blocked),'late_entry_blocked': late_entry_blocked,
                'validation':{'samples':0,'wins':0,'losses':0,'win_rate':None,'rule':'Live TradingView snapshot; historical backtest unavailable'}}

    distance=abs((next_zone or close)-close)
    tf_minutes=TIMEFRAME_MINUTES.get(trigger_tf,15)
    candles=max(1,min(96,math.ceil(distance/max(atr_v,1e-12))))
    rec_confirm = rec >= 0.25 if direction == 'BUY' else rec <= -0.25
    # Strength is deliberately kept in a narrow 0-80 display range. It is a
    # setup-strength heuristic, NOT a probability of winning. A confirmed
    # entry must reach at least 70; anything below 70 remains a waiting state.
    raw_score=(20
              + (12 if (buy_rsi_ok if direction=='BUY' else sell_rsi_ok) else 0)
              + min(20,(bull if direction=='BUY' else bear)*4)
              + (12 if rec_confirm else 0)
              + (12 if fib_ok else 0)
              + min(14, int(enhanced.get('confirmations',0))*2 if enhanced.get('available') else 0)
              + min(12, int(enhanced.get('pattern_confidence',0))*3 if enhanced.get('available') else 0)
              + (10 if status=='SIGNAL READY' else 0))
    if status == 'SIGNAL READY':
        score=max(70,min(100,raw_score))
    elif direction in ('BUY','SELL'):
        score=max(1,min(79,raw_score))
    else:
        score=0
    # Critical confirmation vetoes prevent a pretty score from becoming a trade.
    if status=='SIGNAL READY' and (not fib_ok or (enhanced.get('confirmations',0)<1)):
        status='WAITING FOR CONFIRMATION'
        reasons.append('Critical confirmation gate not complete: retracement/candle evidence is insufficient')
        score=min(score,79)
    if status == 'SIGNAL READY' and score < 70:
        status='WAITING FOR CONFIRMATION'
        reasons.append('Setup strength is below the 70% entry threshold; wait for stronger confirmation')
    return {'direction':direction,'score':score,'status':status,'reasons':reasons,
            'structure':'Bullish forecast structure' if direction=='BUY' else 'Bearish forecast structure',
            'trigger_text':trigger_text,'trigger_price':trigger_price,'entry_zone':entry,'stop_loss':stop,
            'take_profit_1':tp1,'take_profit_2':tp2,'next_zone':next_zone,'next_zone_type':zone_type,
            'candles_to_next_zone':candles,'estimated_minutes_to_next_zone':candles*tf_minutes,
            'distance_to_next_zone':distance,'atr':atr_v,'last':close,'support':s1,'resistance':r1,'rsi':rsi_v,
            'trend':trend,'trend_scores':list(context.values()),'context_trends':context,
            'confirmation_candle_time': enhanced.get('candle',{}).get('current_time'),'confirmation_candle_closed': bool(enhanced.get('candle',{}).get('closed_candle')),'confirmation_age_seconds': enhanced.get('candle',{}).get('confirmation_age_seconds'),'entry_fresh': bool(status=='SIGNAL READY' and not late_entry_blocked),'late_entry_blocked': late_entry_blocked,
            'validation':{'samples':0,'wins':0,'losses':0,'win_rate':None,'rule':'Live TradingView snapshot; no historical result is presented as a backtest'},
            'available_strategies':['Supply/Demand','Order Blocks / IOF retest','Fair Value Gaps','Premium / Discount','Liquidity Sweeps','MSS / CHoCH','Wyckoff spring/upthrust','VSA volume confirmation','Breakout / Retest','Falling/Rising Wedges','Triangles','Flags / Pennants','Double Tops / Bottoms','Head & Shoulders','Failed Breaks / Traps'],
            'detected_patterns':enhanced.get('patterns',[]),'pattern_count':len(enhanced.get('patterns',[])),
            'market_regime': enhanced.get('regime','UNKNOWN'),
            'fib_50': enhanced.get('fib50'),'fib_618': enhanced.get('fib618'),'fib_zone_low': enhanced.get('fib_zone_low'),'fib_zone_high': enhanced.get('fib_zone_high'),
            'in_retracement_zone': bool(enhanced.get('in_fib_zone')),'retracement_location':enhanced.get('retracement_location',''),
            'liquidity_sweep': bool(candle_conf.get('bullish_sweep') or candle_conf.get('bearish_sweep')),'mss_choch': bool(candle_conf.get('bullish_mss') or candle_conf.get('bearish_mss')),
            'displacement_confirmation': bool(candle_conf.get('displacement_up') or candle_conf.get('displacement_down')),
            'fvg_confirmation': bool(candle_conf.get('bullish_fvg') or candle_conf.get('bearish_fvg')),
            'news_filter':'NOT_CONNECTED','spread_filter':'DATA_PROVIDER_DEPENDENT',
            'strategy_state': 'SNIPER CONFIRMED' if (bullish_sniper or bearish_sniper) else ('ZONE REJECTION' if (bullish_rejection or bearish_rejection) else 'WAITING'),
            'strategy_confluence': [x for x in [
                'Supply/Demand pullback' if (demand_reached or supply_reached) else None,
                'Premium/Discount: '+str(candle_conf.get('premium_discount')) if candle_conf.get('available') else None,
                'Liquidity sweep' if (candle_conf.get('bullish_sweep') or candle_conf.get('bearish_sweep')) else None,
                'MSS / structure shift' if (candle_conf.get('bullish_mss') or candle_conf.get('bearish_mss')) else None,
                'Fair Value Gap / Imbalance' if (candle_conf.get('bullish_fvg') or candle_conf.get('bearish_fvg')) else None,
                'Order Block / IOF retest context' if (candle_conf.get('order_block_bullish') or candle_conf.get('order_block_bearish')) else None,
                'Wyckoff spring/upthrust context' if (candle_conf.get('wyckoff_spring') or candle_conf.get('wyckoff_upthrust')) else None,
                'Displacement' if (candle_conf.get('displacement_up') or candle_conf.get('displacement_down')) else None,
                'Candle rejection' if (bullish_rejection or bearish_rejection) else None,
                'Bullish/Bearish engulfing confirmation' if (candle_conf.get('bullish_engulfing') or candle_conf.get('bearish_engulfing')) else None,
                'VSA volume confirmation' if (candle_conf.get('vsa_bull') or candle_conf.get('vsa_bear')) else None,
                *[f"Pattern: {p['name']}" for p in (enhanced.get('patterns') or [])[:3]],
            ] if x]}


def ema(values, n):
    if not values:
        return 0.0
    k = 2 / (n + 1)
    e = values[0]
    for value in values[1:]:
        e = value * k + e * (1 - k)
    return e


def rsi(values, n=14):
    if len(values) < n + 1:
        return 50.0
    gains = losses = 0.0
    for i in range(1, n + 1):
        delta = values[i] - values[i - 1]
        gains += max(delta, 0)
        losses += max(-delta, 0)
    avg_gain = gains / n
    avg_loss = losses / n
    for i in range(n + 1, len(values)):
        delta = values[i] - values[i - 1]
        avg_gain = (avg_gain * (n - 1) + max(delta, 0)) / n
        avg_loss = (avg_loss * (n - 1) + max(-delta, 0)) / n
    if avg_loss == 0:
        return 100.0
    return 100 - 100 / (1 + avg_gain / avg_loss)


def atr(rows, n=14):
    true_ranges = []
    for i, row in enumerate(rows):
        prev = rows[i - 1]['close'] if i else row['close']
        true_ranges.append(max(row['high'] - row['low'], abs(row['high'] - prev), abs(row['low'] - prev)))
    return mean(true_ranges[-n:]) if true_ranges else 0.0


def swing_points(rows, window=60):
    recent = rows[-window:]
    closes = [r['close'] for r in recent]
    support = min(r['low'] for r in recent)
    resistance = max(r['high'] for r in recent)
    trigger_high = max(r['high'] for r in recent[-5:])
    trigger_low = min(r['low'] for r in recent[-5:])
    midpoint = (support + resistance) / 2
    return {
        'support': support,
        'resistance': resistance,
        'trigger_high': trigger_high,
        'trigger_low': trigger_low,
        'midpoint': midpoint,
        'range': max(resistance - support, 0),
        'last_close': closes[-1],
    }


def trend_info(rows):
    closes = [r['close'] for r in rows]
    last = closes[-1]
    e20 = ema(closes[-120:], 20)
    e50 = ema(closes[-160:], 50)
    e100 = ema(closes[-220:], 100)
    rr = rsi(closes)
    swings = swing_points(rows, min(60, len(rows)))
    direction = 'Neutral'
    if last > e20 > e50 > e100:
        direction = 'Bullish'
    elif last < e20 < e50 < e100:
        direction = 'Bearish'
    elif last > e20 > e50:
        direction = 'Bullish'
    elif last < e20 < e50:
        direction = 'Bearish'
    return {
        'trend': direction,
        'rsi': round(rr, 1),
        'ema20': e20,
        'ema50': e50,
        'ema100': e100,
        **swings,
    }


def pip_size(symbol):
    s = norm_symbol(symbol)
    if s.endswith('JPY'):
        return 0.01
    if s in {'XAUUSD', 'XAGUSD', 'XPTUSD', 'XPDUSD'}:
        return 0.01
    if s.endswith('USD') and any(x in s for x in ('BTC','ETH','XRP','SOL','LTC','BNB','ADA')):
        return 0.01
    return 0.0001


def structure_label(rows):
    recent = rows[-12:]
    highs = [r['high'] for r in recent]
    lows = [r['low'] for r in recent]
    if highs[-1] > max(highs[:-2]) and lows[-1] >= min(lows[:-2]):
        return 'Higher High / bullish structure'
    if lows[-1] < min(lows[:-2]) and highs[-1] <= max(highs[:-2]):
        return 'Lower Low / bearish structure'
    return 'Range / mixed structure'


def analyze_setup(rows_trigger, frames, trigger_timeframe='15m'):
    """Build a conservative setup from the selected trigger timeframe plus fixed MTF context.

    Direction is not emitted as a READY trade merely because the higher-timeframe trend
    is bullish/bearish.  A directional setup needs trigger-timeframe trend, momentum,
    structure and a real breakout/rejection trigger.  This avoids the old behaviour
    where a SELL/BUY label could appear while price had not actually crossed the trigger.
    """
    t = trend_info(rows_trigger)
    tf_minutes = TIMEFRAME_MINUTES.get(trigger_timeframe, 15)
    last = rows_trigger[-1]['close']
    a = atr(rows_trigger)
    # Use recent structure for a tighter, setup-specific risk boundary instead of a
    # 60-candle extreme that could make the stop disproportionately wide.
    recent = rows_trigger[-12:]
    recent_low = min(r['low'] for r in recent[:-1]) if len(recent) > 1 else t['support']
    recent_high = max(r['high'] for r in recent[:-1]) if len(recent) > 1 else t['resistance']
    prev5_high = max(r['high'] for r in rows_trigger[-6:-1]) if len(rows_trigger) >= 6 else recent_high
    prev5_low = min(r['low'] for r in rows_trigger[-6:-1]) if len(rows_trigger) >= 6 else recent_low

    context_trends = {key: trend_info(frames[key]) for key in ('15m','30m','1h','4h','1d')}
    trend_scores = [v['trend'] for v in context_trends.values()]
    bullish_count = trend_scores.count('Bullish')
    bearish_count = trend_scores.count('Bearish')

    structure = structure_label(rows_trigger)
    trigger_up = last > prev5_high
    trigger_down = last < prev5_low

    # Selected timeframe drives the scanner; MTF context is confirmation, not the trigger.
    buy_confluence = (
        t['trend'] == 'Bullish' and t['rsi'] >= 50 and
        ('bullish' in structure.lower()) and bullish_count >= 2
    )
    sell_confluence = (
        t['trend'] == 'Bearish' and t['rsi'] <= 50 and
        ('bearish' in structure.lower()) and bearish_count >= 2
    )

    direction = 'NO TRADE'
    status = 'WAITING FOR CONFIRMATION'
    reasons = []
    trigger_price = None

    if buy_confluence:
        direction = 'BUY'
        reasons += ['Selected trigger timeframe is bullish', 'Momentum confirms BUY', 'Recent structure is bullish',
                    f'{bullish_count}/5 context timeframes are bullish']
        trigger_price = prev5_high
        if trigger_up:
            status = 'SIGNAL READY'
            reasons.append(f'{trigger_timeframe} close confirmed above the prior 5-candle high')
        else:
            status = 'FORECAST'
            reasons.append(f'Forecast BUY; planned pullback/confirmation near {trigger_price:.8f}')
    elif sell_confluence:
        direction = 'SELL'
        reasons += ['Selected trigger timeframe is bearish', 'Momentum confirms SELL', 'Recent structure is bearish',
                    f'{bearish_count}/5 context timeframes are bearish']
        trigger_price = prev5_low
        if trigger_down:
            status = 'SIGNAL READY'
            reasons.append(f'{trigger_timeframe} close confirmed below the prior 5-candle low')
        else:
            status = 'FORECAST'
            reasons.append(f'Forecast SELL; planned pullback/confirmation near {trigger_price:.8f}')
    else:
        reasons.append('Confluence is insufficient for a directional setup')
        if t['trend'] != 'Neutral':
            reasons.append(f'{trigger_timeframe} trend is {t["trend"]}, but confirmation is incomplete')

    # Tight, structure-aware stop: a small ATR buffer beyond the recent swing.
    # It is not a guarantee against a stop-out; the buffer is intentionally configurable.
    buffer = max(a * 0.15, 1e-12)
    if direction == 'BUY':
        entry_zone = prev5_high if trigger_up else prev5_high
        stop_loss = recent_low - buffer
        risk = max(entry_zone - stop_loss, buffer)
        tp1 = entry_zone + risk
        tp2 = entry_zone + risk * 2
        next_zone = t['resistance']
        next_zone_type = 'Supply / resistance'
        zone_type = 'Breakout / demand confirmation'
    elif direction == 'SELL':
        entry_zone = prev5_low if trigger_down else prev5_low
        stop_loss = recent_high + buffer
        risk = max(stop_loss - entry_zone, buffer)
        tp1 = entry_zone - risk
        tp2 = entry_zone - risk * 2
        next_zone = t['support']
        next_zone_type = 'Demand / support'
        zone_type = 'Breakdown / supply confirmation'
    else:
        return {
            'direction':'NO TRADE', 'score':0, 'status':'WAITING FOR CONFIRMATION',
            'reasons':reasons, 'structure':structure,
            'trigger_text':f'Wait for {trigger_timeframe} confirmation',
            'trigger_price':None, 'entry_zone':None, 'stop_loss':None,
            'take_profit_1':None, 'take_profit_2':None, 'next_zone':None,
            'next_zone_type':None, 'candles_to_next_zone':None,
            'estimated_minutes_to_next_zone':None, 'distance_to_next_zone':None,
            'atr':a, 'last':last, 'support':t['support'], 'resistance':t['resistance'],
            'rsi':t['rsi'], 'trend':t['trend'], 'trend_scores':trend_scores,
            'context_trends':context_trends, 'zone_type':None
        }

    score = 0
    score += 25 if t['trend'] in ('Bullish','Bearish') else 0
    score += 20 if ((direction == 'BUY' and t['rsi'] >= 50) or (direction == 'SELL' and t['rsi'] <= 50)) else 0
    score += 15 if ('bullish' in structure.lower() if direction == 'BUY' else 'bearish' in structure.lower()) else 0
    score += min(25, (bullish_count if direction == 'BUY' else bearish_count) * 5)
    score += 15 if (trigger_up if direction == 'BUY' else trigger_down) else 0
    score = min(100, score)

    distance = max(abs(next_zone - last), 0)
    candles = max(1, min(96, math.ceil(distance / max(a, 1e-12))))
    score = min(100, score)
    return {
        'direction': direction, 'score': score, 'status': status, 'reasons': reasons,
        'structure': structure, 'trigger_text': (
            f'{trigger_timeframe} close above {trigger_price:.8f}' if direction == 'BUY'
            else f'{trigger_timeframe} close below {trigger_price:.8f}'
        ), 'trigger_price': trigger_price, 'entry_zone': entry_zone,
        'stop_loss': stop_loss, 'take_profit_1': tp1, 'take_profit_2': tp2,
        'next_zone': next_zone, 'next_zone_type': next_zone_type,
        'zone_type': zone_type, 'candles_to_next_zone': candles,
        'estimated_minutes_to_next_zone': candles * tf_minutes,
        'distance_to_next_zone': distance, 'atr': a, 'last': last,
        'support': t['support'], 'resistance': t['resistance'], 'rsi': t['rsi'],
        'trend': t['trend'], 'trend_scores': trend_scores, 'context_trends': context_trends
    }

def backtest(rows, lookahead=12):
    """Historical check of the same trigger concept used by the scanner.

    This measures directional follow-through after a confirmed 5-candle breakout/
    breakdown, using ATR as the 1R unit. It is validation data, not a prediction.
    """
    if len(rows) < 220:
        return {'samples':0, 'wins':0, 'losses':0, 'win_rate':None, 'rule':'trigger breakout + ATR target/stop'}

    wins = losses = samples = 0
    for i in range(120, len(rows) - lookahead - 1):
        part = rows[:i + 1]
        info = trend_info(part)
        a = max(atr(part), 1e-12)
        recent = part[-12:]
        prev5_high = max(r['high'] for r in part[-6:-1])
        prev5_low = min(r['low'] for r in part[-6:-1])
        structure = structure_label(part)
        direction = None
        if info['trend'] == 'Bullish' and info['rsi'] >= 50 and 'bullish' in structure.lower() and part[-1]['close'] > prev5_high:
            direction = 'BUY'
        elif info['trend'] == 'Bearish' and info['rsi'] <= 50 and 'bearish' in structure.lower() and part[-1]['close'] < prev5_low:
            direction = 'SELL'
        if not direction:
            continue

        entry = part[-1]['close']
        if direction == 'BUY':
            stop = min(r['low'] for r in recent[:-1]) - a * 0.15
            risk = max(entry - stop, a * 0.15)
            target = entry + risk
            stop_price = entry - risk
            hit = None
            for r in rows[i+1:i+1+lookahead]:
                if r['low'] <= stop_price and r['high'] >= target:
                    hit = 'loss'  # conservative: both touched in same candle
                    break
                if r['high'] >= target:
                    hit = 'win'; break
                if r['low'] <= stop_price:
                    hit = 'loss'; break
        else:
            stop = max(r['high'] for r in recent[:-1]) + a * 0.15
            risk = max(stop - entry, a * 0.15)
            target = entry - risk
            stop_price = entry + risk
            hit = None
            for r in rows[i+1:i+1+lookahead]:
                if r['high'] >= stop_price and r['low'] <= target:
                    hit = 'loss'
                    break
                if r['low'] <= target:
                    hit = 'win'; break
                if r['high'] >= stop_price:
                    hit = 'loss'; break

        if hit:
            samples += 1
            if hit == 'win': wins += 1
            else: losses += 1

    return {
        'samples': samples, 'wins': wins, 'losses': losses,
        'win_rate': round((wins / samples) * 100, 1) if samples else None,
        'rule':'trigger breakout + structure + RSI + ATR-based 1R validation'
    }


DEFAULT_FOREX_WATCHLIST = ['EURUSD','GBPUSD','USDJPY','GBPJPY','AUDUSD','USDCAD']


def _asof_row(rows, timestamps, ts):
    """Return the latest completed context candle at or before trigger timestamp."""
    if not rows:
        return None
    idx = bisect_right(timestamps, ts) - 1
    return rows[:idx + 1] if idx >= 0 else None


def _strict_backtest(rows, context_frames=None, lookahead=12, mtf_min=3,
                     buy_rsi=(52, 68), sell_rsi=(32, 48), buffer_atr=0.20,
                     target_r=1.0):
    """Out-of-sample-style validation of the current high-precision filter.

    The live TradingView rating is not historically available through Yahoo's chart
    candles, so the historical engine validates the reproducible parts of the strict
    rule: trigger trend/structure, RSI window, MTF alignment, and ATR-based risk.
    A technical-rating proxy is reported separately rather than pretending it is a
    historical TradingView rating.
    """
    if len(rows) < 240:
        return {'samples':0,'wins':0,'losses':0,'win_rate':None,'avg_r':None,
                'rule':'strict MTF + RSI + structure + ATR validation',
                'rating_proxy':'not used; historical TradingView rating unavailable'}

    contexts = context_frames or {}
    context_ts = {tf:[r['t'] for r in rs] for tf,rs in contexts.items() if rs}
    wins = losses = samples = 0
    r_values = []
    timestamps = [r['t'] for r in rows]

    for i in range(180, len(rows) - lookahead - 1):
        part = rows[:i+1]
        info = trend_info(part)
        structure = structure_label(part)
        a = max(atr(part), 1e-12)
        prev5_high = max(r['high'] for r in part[-6:-1])
        prev5_low = min(r['low'] for r in part[-6:-1])
        last = part[-1]['close']

        context_trends = []
        for tf, cr in contexts.items():
            if tf not in context_ts:
                continue
            asof = _asof_row(cr, context_ts[tf], rows[i]['t'])
            if asof and len(asof) >= 120:
                context_trends.append(trend_info(asof)['trend'])
        bull = context_trends.count('Bullish')
        bear = context_trends.count('Bearish')

        direction = None
        if (info['trend'] == 'Bullish' and buy_rsi[0] <= info['rsi'] <= buy_rsi[1]
                and 'bullish' in structure.lower() and bull >= mtf_min):
            direction = 'BUY'
        elif (info['trend'] == 'Bearish' and sell_rsi[0] <= info['rsi'] <= sell_rsi[1]
                and 'bearish' in structure.lower() and bear >= mtf_min):
            direction = 'SELL'
        if not direction:
            continue

        # Require the same directional trigger that the strict scanner is designed
        # to trade; this avoids counting a setup merely because the trend is aligned.
        if direction == 'BUY' and last <= prev5_high:
            continue
        if direction == 'SELL' and last >= prev5_low:
            continue

        recent = part[-12:]
        if direction == 'BUY':
            stop = min(r['low'] for r in recent[:-1]) - a * buffer_atr
            risk = max(last - stop, a * buffer_atr)
            target = last + risk * target_r
            stop_price = last - risk
        else:
            stop = max(r['high'] for r in recent[:-1]) + a * buffer_atr
            risk = max(stop - last, a * buffer_atr)
            target = last - risk * target_r
            stop_price = last + risk

        hit = None
        for r in rows[i+1:i+1+lookahead]:
            if direction == 'BUY':
                if r['low'] <= stop_price and r['high'] >= target:
                    hit = 'loss'  # conservative same-candle handling
                    break
                if r['high'] >= target:
                    hit = 'win'; break
                if r['low'] <= stop_price:
                    hit = 'loss'; break
            else:
                if r['high'] >= stop_price and r['low'] <= target:
                    hit = 'loss'
                    break
                if r['low'] <= target:
                    hit = 'win'; break
                if r['high'] >= stop_price:
                    hit = 'loss'; break
        if hit:
            samples += 1
            if hit == 'win':
                wins += 1; r_values.append(target_r)
            else:
                losses += 1; r_values.append(-1.0)

    return {
        'samples': samples, 'wins': wins, 'losses': losses,
        'win_rate': round(wins * 100 / samples, 1) if samples else None,
        'avg_r': round(sum(r_values) / len(r_values), 3) if r_values else None,
        'rule':f'strict MTF({mtf_min}/5) + RSI + structure + breakout + {target_r:.1f}R ATR validation',
        'rating_proxy':'not used; historical TradingView rating unavailable'
    }


def optimize_strict_scanner(symbols=None, trigger_timeframes=None, market='Forex'):
    """Run a compact parameter sweep across multiple currency pairs in parallel.

    Results are sorted by validation win rate only when sample size is meaningful;
    sample counts remain visible so a high percentage from a tiny sample is not
    presented as proof of performance.
    """
    symbols = [norm_symbol(x) for x in (symbols or DEFAULT_FOREX_WATCHLIST)]
    trigger_timeframes = list(trigger_timeframes or ['15m','1h','4h'])
    configs = [
        {'name':'strict','mtf_min':3,'buy_rsi':(52,68),'sell_rsi':(32,48),'buffer_atr':0.20,'target_r':1.0},
        {'name':'very_strict','mtf_min':4,'buy_rsi':(54,66),'sell_rsi':(34,46),'buffer_atr':0.20,'target_r':1.0},
        {'name':'balanced_rr','mtf_min':3,'buy_rsi':(52,68),'sell_rsi':(32,48),'buffer_atr':0.20,'target_r':1.25},
    ]

    def one_symbol_tf(sym, tf):
        trigger_rows = fetch(sym, tf)
        context = {}
        context_tfs = ('15m','30m','1h','4h','1d')
        with ThreadPoolExecutor(max_workers=5) as pool:
            jobs={pool.submit(fetch,sym,ctf):ctf for ctf in context_tfs if ctf != tf}
            context[tf]=trigger_rows if tf in context_tfs else trigger_rows
            for job in as_completed(jobs):
                ctf=jobs[job]
                try: context[ctf]=job.result()
                except Exception: pass
        # If the selected trigger TF is 1m/5m, the context is still the fixed five frames.
        for ctf in context_tfs:
            if ctf not in context:
                try: context[ctf]=fetch(sym,ctf)
                except Exception: pass
        out=[]
        for cfg in configs:
            result=_strict_backtest(trigger_rows, context, mtf_min=cfg['mtf_min'],
                                    buy_rsi=cfg['buy_rsi'], sell_rsi=cfg['sell_rsi'],
                                    buffer_atr=cfg['buffer_atr'], target_r=cfg['target_r'])
            out.append({'symbol':sym,'timeframe':tf,**cfg,**result})
        return out

    tasks=[(sym,tf) for sym in symbols for tf in trigger_timeframes]
    rows_out=[]
    with ThreadPoolExecutor(max_workers=min(6,max(1,len(tasks)))) as pool:
        jobs={pool.submit(one_symbol_tf,sym,tf):(sym,tf) for sym,tf in tasks}
        for job in as_completed(jobs):
            sym,tf=jobs[job]
            try:
                rows_out.extend(job.result())
            except Exception as exc:
                rows_out.append({'symbol':sym,'timeframe':tf,'name':'unavailable','samples':0,
                                 'wins':0,'losses':0,'win_rate':None,'avg_r':None,'error':str(exc)})

    valid=[r for r in rows_out if r.get('samples',0) >= 20 and r.get('win_rate') is not None]
    best=max(valid, key=lambda r:(r['win_rate'], r['samples'])) if valid else None
    return {
        'market':market,
        'pairs_tested':symbols,
        'timeframes_tested':trigger_timeframes,
        'configs_tested':len(configs),
        'results':rows_out,
        'best_measured_configuration':best,
        'note':'Historical validation uses verified Yahoo candles. TradingView Recommend.All is not historically available here, so it is not fabricated or treated as a backtest input. The sweep is deliberately small to reduce overfitting; use out-of-sample/walk-forward testing before treating any configuration as robust.'
    }

def utc_iso(timestamp=None):
    return datetime.fromtimestamp(timestamp or time.time(), tz=timezone.utc).isoformat()
