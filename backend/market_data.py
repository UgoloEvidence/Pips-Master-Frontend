import json
import math
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from statistics import mean

YAHOO_MAP = {
    'EURUSD':'EURUSD=X','GBPUSD':'GBPUSD=X','USDJPY':'JPY=X','USDCHF':'CHF=X','AUDUSD':'AUDUSD=X','USDCAD':'CAD=X','NZDUSD':'NZDUSD=X',
    'EURGBP':'EURGBP=X','EURJPY':'EURJPY=X','GBPJPY':'GBPJPY=X','AUDJPY':'AUDJPY=X','EURAUD':'EURAUD=X','GBPAUD':'GBPAUD=X','EURCHF':'EURCHF=X','GBPCHF':'GBPCHF=X',
    'XAUUSD':'GC=F','XAGUSD':'SI=F','XPTUSD':'PL=F','XPDUSD':'PA=F','WTI':'CL=F','USOIL':'CL=F','UKOIL':'BZ=F','BRENT':'BZ=F','NATGAS':'NG=F','COPPER':'HG=F',
    'SPX':'^GSPC','SP500':'^GSPC','SPX500':'^GSPC','NAS100':'^NDX','NDX':'^NDX','US30':'^DJI','DOW':'^DJI','DAX':'^GDAXI','GER40':'^GDAXI','FTSE100':'^FTSE','UK100':'^FTSE','NIKKEI':'^N225','JP225':'^N225','FRA40':'^FCHI',
    'BTCUSD':'BTC-USD','ETHUSD':'ETH-USD','XRPUSD':'XRP-USD','SOLUSD':'SOL-USD','BNBUSD':'BNB-USD','ADAUSD':'ADA-USD','LTCUSD':'LTC-USD'
}
INTERVALS = {'1m':'1m','5m':'5m','15m':'15m','30m':'30m','1h':'1h','1d':'1d'}
RANGES_DAYS = {'1m':7,'5m':60,'15m':7,'30m':30,'1h':90,'1d':900}
TIMEFRAME_MINUTES = {'1m':1,'5m':5,'15m':15,'30m':30,'1h':60,'4h':240,'1d':1440}
CACHE = {}


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
        if cached and now - cached[0] < 20:
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
    if cached and now - cached[0] < 20:
        return cached[1]

    params = urllib.parse.urlencode({
        'period1': int(now) - RANGES_DAYS[interval] * 86400,
        'period2': int(now),
        'interval': INTERVALS[interval],
        'events': 'history',
        'includeAdjustedClose': 'true',
    })
    raw = None
    last_error = None
    for host in ('query1.finance.yahoo.com', 'query2.finance.yahoo.com'):
        url = f'https://{host}/v8/finance/chart/{urllib.parse.quote(ys, safe="")}?{params}'
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 PipsMasterAcademy/2.0',
            'Accept': 'application/json',
        })
        try:
            with urllib.request.urlopen(req, timeout=12) as response:
                raw = json.loads(response.read().decode())
            result = ((raw.get('chart') or {}).get('result') or []) if raw else []
            if result:
                break
            last_error = ValueError(f'No verified response for {symbol} {interval}')
        except Exception as exc:
            last_error = exc

    result = ((raw.get('chart') or {}).get('result') or []) if raw else []
    if not result:
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


def analyze_setup(rows15, frames, trigger_timeframe='15m'):
    t15 = trend_info(rows15)
    tf_minutes = TIMEFRAME_MINUTES.get(trigger_timeframe, 15)
    last = rows15[-1]['close']
    a = atr(rows15)
    support = t15['support']
    resistance = t15['resistance']
    trend_scores = []
    for key in ('15m','30m','1h','4h','1d'):
        info = trend_info(frames[key])
        trend_scores.append(info['trend'])
    bullish_count = trend_scores.count('Bullish')
    bearish_count = trend_scores.count('Bearish')
    if bullish_count >= 3 and bearish_count <= 1:
        direction = 'BUY'
    elif bearish_count >= 3 and bullish_count <= 1:
        direction = 'SELL'
    else:
        # Keep the current trend as the directional idea, but flag weak/conflicted conditions.
        direction = 'BUY' if t15['trend'] == 'Bullish' else 'SELL' if t15['trend'] == 'Bearish' else 'NO TRADE'

    structure = structure_label(rows15)
    score = 0
    reasons = []
    if direction == 'BUY':
        if t15['trend'] == 'Bullish': score += 20; reasons.append('15m trend is bullish')
        if bullish_count >= 3: score += 25; reasons.append('multiple timeframes support BUY')
        if t15['rsi'] >= 50: score += 10; reasons.append('RSI supports positive momentum')
        if 'bullish' in structure.lower(): score += 10; reasons.append('recent structure is bullish')
        entry_zone = support + a * 0.25
        zone_type = 'Demand / support'
        next_zone = resistance
        next_zone_type = 'Supply / resistance'
        risk = max(last - stop_loss, a * 0.25)
        stop_loss = support - a * 0.25
        tp1 = last + risk
        tp2 = last + risk * 2
        trigger_price = t15['trigger_high']
        trigger_text = f'{trigger_timeframe} close above {trigger_price:.8f}'
    elif direction == 'SELL':
        if t15['trend'] == 'Bearish': score += 20; reasons.append('15m trend is bearish')
        if bearish_count >= 3: score += 25; reasons.append('multiple timeframes support SELL')
        if t15['rsi'] <= 50: score += 10; reasons.append('RSI supports negative momentum')
        if 'bearish' in structure.lower(): score += 10; reasons.append('recent structure is bearish')
        entry_zone = resistance - a * 0.25
        zone_type = 'Supply / resistance'
        next_zone = support
        next_zone_type = 'Demand / support'
        stop_loss = resistance + a * 0.25
        risk = max(stop_loss - last, a * 0.25)
        tp1 = last - risk
        tp2 = last - risk * 2
        trigger_price = t15['trigger_low']
        trigger_text = f'{trigger_timeframe} close below {trigger_price:.8f}'
    else:
        return {
            'direction':'NO TRADE', 'score':score, 'status':'MULTI-TF CONFLICT', 'reasons':['Timeframes are not sufficiently aligned'],
            'structure':structure, 'trigger_text':'Wait for multi-timeframe alignment', 'trigger_price':None,
            'entry_zone':None, 'stop_loss':None, 'take_profit_1':None, 'take_profit_2':None,
            'next_zone':None, 'next_zone_type':None, 'candles_to_next_zone':None, 'estimated_minutes_to_next_zone':None,
            'distance_to_next_zone':None, 'atr':a, 'last':last, 'support':support, 'resistance':resistance,
            'rsi':t15['rsi'], 'trend':t15['trend'], 'trend_scores':trend_scores,
        }

    distance = max(abs(next_zone - last), 0)
    candles = max(1, min(96, math.ceil(distance / max(a, 1e-12))))
    score += 15 if distance <= a * 6 else 5
    score = min(100, score)
    status = 'SIGNAL READY' if score >= 65 else 'WATCHING'
    return {
        'direction': direction,
        'score': score,
        'status': status,
        'reasons': reasons,
        'structure': structure,
        'trigger_text': trigger_text,
        'trigger_price': trigger_price,
        'entry_zone': entry_zone,
        'stop_loss': stop_loss,
        'take_profit_1': tp1,
        'take_profit_2': tp2,
        'next_zone': next_zone,
        'next_zone_type': next_zone_type,
        'candles_to_next_zone': candles,
        'estimated_minutes_to_next_zone': candles * tf_minutes,
        'distance_to_next_zone': distance,
        'atr': a,
        'last': last,
        'support': support,
        'resistance': resistance,
        'rsi': t15['rsi'],
        'trend': t15['trend'],
        'trend_scores': trend_scores,
    }


def backtest(rows, lookahead=12):
    """Simple historical validation of the rule set. This is historical, not a guarantee."""
    if len(rows) < 180:
        return {'samples': 0, 'wins': 0, 'losses': 0, 'win_rate': None}
    wins = losses = 0
    for i in range(100, len(rows) - lookahead, 6):
        part = rows[:i + 1]
        info = trend_info(part)
        entry = part[-1]['close']
        target = max(atr(part), 1e-12)
        if info['trend'] == 'Bullish':
            hit_win = any(r['high'] >= entry + target for r in rows[i + 1:i + 1 + lookahead])
            hit_loss = any(r['low'] <= entry - target for r in rows[i + 1:i + 1 + lookahead])
        elif info['trend'] == 'Bearish':
            hit_win = any(r['low'] <= entry - target for r in rows[i + 1:i + 1 + lookahead])
            hit_loss = any(r['high'] >= entry + target for r in rows[i + 1:i + 1 + lookahead])
        else:
            continue
        if hit_win and not hit_loss:
            wins += 1
        elif hit_loss and not hit_win:
            losses += 1
    n = wins + losses
    return {'samples': n, 'wins': wins, 'losses': losses, 'win_rate': round(wins / n * 100, 1) if n else None}


def utc_iso(timestamp=None):
    return datetime.fromtimestamp(timestamp or time.time(), tz=timezone.utc).isoformat()
