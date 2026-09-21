const YAHOO={EURUSD:'EURUSD=X',GBPUSD:'GBPUSD=X',USDJPY:'JPY=X',GBPJPY:'GBPJPY=X',AUDUSD:'AUDUSD=X',USDCAD:'CAD=X',USDCHF:'CHF=X',NZDUSD:'NZDUSD=X',EURJPY:'EURJPY=X',EURGBP:'EURGBP=X',EURCHF:'EURCHF=X',GBPCHF:'GBPCHF=X',AUDJPY:'AUDJPY=X',CADJPY:'CADJPY=X',XAUUSD:'GC=F',XAGUSD:'SI=F',XPTUSD:'PL=F',XPDUSD:'PA=F',US30:'^DJI',NAS100:'^NDX',SPX500:'^GSPC',SPX:'^GSPC',GER40:'^GDAXI',UK100:'^FTSE',FRA40:'^FCHI',JP225:'^N225',BTCUSD:'BTC-USD',ETHUSD:'ETH-USD',SOLUSD:'SOL-USD',XRPUSD:'XRP-USD',LTCUSD:'LTC-USD',USOIL:'CL=F',UKOIL:'BZ=F',NATGAS:'NG=F',COPPER:'HG=F'};
const TF={ '15m':15, '30m':30, '1h':60, '4h':240, '1d':1440 };
function norm(s){return String(s).toUpperCase().replace(/[\\/-]/g,'')}
function yahooSymbol(s){return YAHOO[norm(s)]||null}
async function fetchBiquote(sym,tf){
  const u=`https://biquote.io/api/${encodeURIComponent(norm(sym))}/ohlc?interval=${tf}&limit=500`;
  const r=await fetch(u,{headers:{'Accept':'application/json'}}); if(!r.ok) throw new Error(`Biquote HTTP ${r.status}`);
  const j=await r.json(); const bars=j?.bars||j?.data||[];
  const rows=bars.map(b=>({t:Math.floor(new Date(b.openTime||b.time||b.timestamp).getTime()/1000),open:Number(b.open),high:Number(b.high),low:Number(b.low),close:Number(b.close),volume:Number(b.volume||0)})).filter(x=>[x.t,x.open,x.high,x.low,x.close].every(Number.isFinite)).sort((a,b)=>a.t-b.t);
  if(rows.length<80) throw new Error(`Only ${rows.length} ${tf} candles returned`); return rows;
}
async function fetchYahoo(sym,tf){
  const y=yahooSymbol(sym); if(!y) throw new Error('No Yahoo symbol mapping');
  const days={15:7,30:20,60:60,240:180,1440:900}[TF[tf]||tf];
  const interval=tf==='4h'?'1h':tf==='1d'?'1d':tf;
  const p1=Math.floor(Date.now()/1000)-days*86400,p2=Math.floor(Date.now()/1000);
  const u=`https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(y)}?period1=${p1}&period2=${p2}&interval=${interval}&events=history&includeAdjustedClose=true`;
  const r=await fetch(u,{headers:{'User-Agent':'Mozilla/5.0','Accept':'application/json'}}); if(!r.ok) throw new Error(`Yahoo HTTP ${r.status}`);
  const j=await r.json(),res=j?.chart?.result?.[0]; if(!res) throw new Error('Yahoo returned no result'); const q=res.indicators?.quote?.[0]||{},ts=res.timestamp||[];
  const rows=[]; for(let i=0;i<ts.length;i++){const x={t:ts[i],open:Number(q.open?.[i]),high:Number(q.high?.[i]),low:Number(q.low?.[i]),close:Number(q.close?.[i]),volume:Number(q.volume?.[i]||0)};if([x.t,x.open,x.high,x.low,x.close].every(Number.isFinite))rows.push(x)}
  if(tf==='4h') return aggregate4h(rows); if(rows.length<80) throw new Error(`Only ${rows.length} ${tf} candles returned`); return rows;
}
function aggregate4h(rows){const out=[];let b=null;for(const r of rows){const d=new Date(r.t*1000),key=d.toISOString().slice(0,10)+'-'+Math.floor(d.getUTCHours()/4);if(!b||b.key!==key){b={key,t:r.t,open:r.open,high:r.high,low:r.low,close:r.close,volume:r.volume};out.push(b)}else{b.high=Math.max(b.high,r.high);b.low=Math.min(b.low,r.low);b.close=r.close;b.volume+=r.volume}}return out.slice(-300)}
async function candles(sym,tf){try{return {rows:await fetchBiquote(sym,tf),source:'Biquote live OHLC'}}catch(e){return {rows:await fetchYahoo(sym,tf),source:'Yahoo Finance chart feed'}}}
function ema(v,n){const k=2/(n+1);let e=v[0];for(let i=1;i<v.length;i++)e=v[i]*k+e*(1-k);return e}
function rsi(v,n=14){if(v.length<n+1)return 50;let g=0,l=0;for(let i=1;i<=n;i++){const d=v[i]-v[i-1];g+=Math.max(d,0);l+=Math.max(-d,0)}let ag=g/n,al=l/n;for(let i=n+1;i<v.length;i++){const d=v[i]-v[i-1];ag=(ag*(n-1)+Math.max(d,0))/n;al=(al*(n-1)+Math.max(-d,0))/n}return al===0?100:100-100/(1+ag/al)}
function atr(rows,n=14){const tr=[];for(let i=0;i<rows.length;i++){const p=i?rows[i-1].close:rows[i].close;tr.push(Math.max(rows[i].high-rows[i].low,Math.abs(rows[i].high-p),Math.abs(rows[i].low-p)))}return tr.slice(-n).reduce((a,b)=>a+b,0)/Math.min(n,tr.length)}
function swings(rows,n=50){const r=rows.slice(-n);return {support:Math.min(...r.map(x=>x.low)),resistance:Math.max(...r.map(x=>x.high))}}
function trend(rows){const c=rows.map(x=>x.close),last=c.at(-1),e20=ema(c.slice(-120),20),e50=ema(c.slice(-160),50),e100=ema(c.slice(-220),100),rr=rsi(c);const s=swings(rows,30);let t='Neutral';if(last>e20&&e20>e50&&e50>e100&&rr>=52)t='Bullish';else if(last<e20&&e20<e50&&e50<e100&&rr<=48)t='Bearish';else if(last>e20&&e20>e50)t='Bullish';else if(last<e20&&e20<e50)t='Bearish';return {trend:t,rsi:+rr.toFixed(1),ema20:e20,ema50:e50,ema100:e100,support:s.support,resistance:s.resistance}}
function pipSize(sym){const s=norm(sym);if(s.includes('JPY'))return 0.01;if(s==='XAUUSD'||s==='XAGUSD')return 0.01;if(s.includes('BTC')||s.includes('ETH')||s.includes('XRP')||s.includes('SOL')||s.includes('LTC'))return 0.01;return 0.0001}
function analyze15(rows,sym){const c=rows.map(x=>x.close),last=c.at(-1),a=atr(rows),tr=trend(rows),sup=tr.support,res=tr.resistance;let direction,zone,zoneType,distance;if(tr.trend==='Bullish'){direction='BUY';zone=sup;zoneType='Demand / support';distance=Math.max(0,last-zone)}else if(tr.trend==='Bearish'){direction='SELL';zone=res;zoneType='Supply / resistance';distance=Math.max(0,zone-last)}else{const bd=Math.abs(last-sup),sd=Math.abs(res-last);if(bd<=sd){direction='BUY';zone=sup;zoneType='Demand / support';distance=bd}else{direction='SELL';zone=res;zoneType='Supply / resistance';distance=sd}}
 const pip=pipSize(sym),pips=distance/pip;
 // ETA is a volatility-based estimate, not a promise. Use recent ATR as the expected travel unit and cap the estimate.
 const candles=Math.max(1,Math.min(96,Math.ceil(distance/Math.max(a,1e-12))));
 const minutes=candles*15;
 return {last,atr:a,support:sup,resistance:res,direction,zone,zoneType,distance,pips:+pips.toFixed(1),pipSize:pip,candles,minutes,trend:tr}}
async function scanOne(sym,market){
 const frames=['15m','30m','1h','4h','1d']; const data={}; let source='';
 for(const tf of frames){const d=await candles(sym,tf);data[tf]=d.rows;source=source?source+' + '+d.source:d.source}
 const a=analyze15(data['15m'],sym),trends={};for(const tf of frames)trends[tf]=trend(data[tf]).trend;
 // Require higher-timeframe alignment for a stronger detector state; otherwise keep it as WATCHING rather than inventing confirmation.
 const aligned=(trends['15m']===trends['30m']&&trends['1h']===trends['4h']);
 const status=aligned&&a.candles<=2?'ZONE APPROACHING':aligned?'WATCHING':'MULTI-TF CONFLICT';
 return {symbol:sym,market,direction:a.direction,zone_type:a.zoneType,zone:+a.zone.toFixed(8),distance:+a.distance.toFixed(8),pips_to_zone:a.pips,candles_to_zone:a.candles,estimated_minutes_to_entry:a.minutes,timeframe:'15m',trends,last:+a.last.toFixed(8),support:+a.support.toFixed(8),resistance:+a.resistance.toFixed(8),atr_15m:+a.atr.toFixed(8),status,data_source:source,updated_at:new Date().toISOString(),method:'EMA20/50/100 + RSI + recent swing support/resistance + ATR travel estimate'}}
exports.handler=async(event)=>{try{const qs=event.queryStringParameters||{},market=qs.market||'Forex',symbols=(qs.symbols||'EURUSD').split(',').map(norm).filter(Boolean).slice(0,12),results=[],errors=[];for(const s of symbols){try{results.push(await scanOne(s,market))}catch(e){errors.push({symbol:s,error:e.message})}}results.sort((a,b)=>a.estimated_minutes_to_entry-b.estimated_minutes_to_entry);return {statusCode:200,headers:{'content-type':'application/json','cache-control':'no-store'},body:JSON.stringify({closest:results[0]||null,opportunities:results,errors,market,symbols,message:results.length?'Live candle data loaded.':'No live candle data could be verified from the configured providers.'})}}catch(e){return {statusCode:503,headers:{'content-type':'application/json','cache-control':'no-store'},body:JSON.stringify({message:e.message})}}};
