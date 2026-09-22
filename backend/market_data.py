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
RANGES_DAYS = {'1m':7,'5m':60,'15m':60,'30m':60,'1h':180,'1d':1825}
RANGES = {'1m':'7d','5m':'60d','15m':'60d','30m':'60d','1h':'180d','1d':'5y'}
TIMEFRAME_MINUTES = {'1m':1,'5m':5,'15m':15,'30m':30,'1h':60,'4h':240,'1d':1440}
CACHE = {}
CACHE_TTL = 120


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
    for host in ('query1.finance.yahoo.com', 'query2.finance.yahoo.com'):
        url = f'https://{host}/v8/finance/chart/{urllib.parse.quote(ys, safe="")}?{params}'
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/153 Safari/537.36 PMA/2.1',
            'Accept': 'application/json,text/plain,*/*',
            'Accept-Encoding': 'identity',
            'Referer': 'https://finance.yahoo.com/',
            'Connection': 'close',
        })
        try:
            with urllib.request.urlopen(req, timeout=18) as response:
                payload = response.read().decode('utf-8', errors='replace')
                raw = json.loads(payload)
            result = ((raw.get('chart') or {}).get('result') or []) if raw else []
            chart_error = ((raw.get('chart') or {}).get('error') or {}) if raw else {}
            if result:
                break
            last_error = ValueError(chart_error.get('description') or f'No verified response for {symbol} {interval}')
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
            status = 'APPROACHING'
            reasons.append(f'Waiting for {trigger_timeframe} close above {trigger_price:.8f}')
    elif sell_confluence:
        direction = 'SELL'
        reasons += ['Selected trigger timeframe is bearish', 'Momentum confirms SELL', 'Recent structure is bearish',
                    f'{bearish_count}/5 context timeframes are bearish']
        trigger_price = prev5_low
        if trigger_down:
            status = 'SIGNAL READY'
            reasons.append(f'{trigger_timeframe} close confirmed below the prior 5-candle low')
        else:
            status = 'APPROACHING'
            reasons.append(f'Waiting for {trigger_timeframe} close below {trigger_price:.8f}')
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

def utc_iso(timestamp=None):
    return datetime.fromtimestamp(timestamp or time.time(), tz=timezone.utc).isoformat()
