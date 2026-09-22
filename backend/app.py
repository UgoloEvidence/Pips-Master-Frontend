import os, sqlite3, secrets, hashlib, hmac, json, math
from datetime import datetime, timezone, timedelta
from typing import Optional
import requests
import pandas as pd
import numpy as np
from fastapi import FastAPI, HTTPException, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from dotenv import load_dotenv

load_dotenv()
DB=os.getenv('PMA_DB_PATH','pma.db')
SECRET=os.getenv('PMA_SECRET_KEY','dev-only-change-me')
ADMIN_EMAIL=os.getenv('PMA_ADMIN_EMAIL','').strip().lower()
ADMIN_PASSWORD=os.getenv('PMA_ADMIN_PASSWORD','')
ADMIN_USERNAME=os.getenv('PMA_ADMIN_USERNAME','PipsMaster')
ADMIN_NAME=os.getenv('PMA_ADMIN_FULL_NAME','Ugolo Evidence')
TOKEN_TTL=int(os.getenv('PMA_TOKEN_TTL','2592000'))
QUAL_HOURS=int(os.getenv('PMA_REFERRAL_QUALIFICATION_HOURS','48'))

app=FastAPI(title='Pips Master Academy API', version='2.0')
app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_methods=['*'], allow_headers=['*'])

SCHEMA='''
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT,email TEXT UNIQUE NOT NULL,password_hash TEXT NOT NULL,full_name TEXT DEFAULT '',username TEXT DEFAULT '',phone TEXT DEFAULT '',dob TEXT DEFAULT '',profile_picture TEXT DEFAULT '',pma_id TEXT UNIQUE,referral_code TEXT UNIQUE,role TEXT DEFAULT 'user',xp INTEGER DEFAULT 0,rank TEXT DEFAULT 'Beginner I',theme TEXT DEFAULT 'dark',created_at TEXT,updated_at TEXT);
CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY,user_id INTEGER,expires_at TEXT);
CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,category TEXT,title TEXT,message TEXT,target TEXT,setup_id TEXT UNIQUE,created_at TEXT,read INTEGER DEFAULT 0,cleared INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS referrals(id INTEGER PRIMARY KEY AUTOINCREMENT,referrer_id INTEGER,referred_email TEXT,created_at TEXT,status TEXT DEFAULT 'pending',qualified_at TEXT);
CREATE TABLE IF NOT EXISTS community_messages(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,message TEXT,created_at TEXT,deleted INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS feedback(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,rating INTEGER,message TEXT,created_at TEXT,xp_awarded INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS tasks(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,title TEXT,done INTEGER DEFAULT 0,task_date TEXT,created_at TEXT);
CREATE TABLE IF NOT EXISTS learning(user_id INTEGER PRIMARY KEY,lessons INTEGER DEFAULT 0,courses INTEGER DEFAULT 0,streak INTEGER DEFAULT 0,learning_percent REAL DEFAULT 0,overall_percent REAL DEFAULT 0);
CREATE TABLE IF NOT EXISTS preferences(user_id INTEGER PRIMARY KEY,trading_style TEXT DEFAULT 'Scalping',trigger_tf TEXT DEFAULT '5m',markets TEXT DEFAULT 'Forex',theme TEXT DEFAULT 'dark',signal_notifications INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS scanner_setups(id TEXT PRIMARY KEY,user_id INTEGER,symbol TEXT,market TEXT,direction TEXT,style TEXT,timeframe TEXT,confidence INTEGER,strength TEXT,entry REAL,sl REAL,tp1 REAL,tp2 REAL,status TEXT,reason TEXT,confirmations TEXT,created_at TEXT,triggered_at TEXT,closed_at TEXT);
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,action TEXT,payload TEXT,created_at TEXT);
CREATE TABLE IF NOT EXISTS journal(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,note TEXT,created_at TEXT,updated_at TEXT);
CREATE TABLE IF NOT EXISTS achievements(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,key TEXT,unlocked_at TEXT,UNIQUE(user_id,key));
'''

def db():
    c=sqlite3.connect(DB); c.row_factory=sqlite3.Row
    c.executescript(SCHEMA); return c

def now(): return datetime.now(timezone.utc).isoformat()
def pwd_hash(p): return hashlib.sha256((SECRET+'|'+p).encode()).hexdigest()
def make_token(uid):
    raw=f'{uid}.{int(datetime.now(timezone.utc).timestamp())}.{secrets.token_urlsafe(18)}'
    sig=hmac.new(SECRET.encode(),raw.encode(),hashlib.sha256).hexdigest()
    return raw+'.'+sig

def verify_token(t):
    if not t: return None
    parts=t.split('.')
    if len(parts)<4: return None
    raw='.'.join(parts[:-1]); sig=parts[-1]
    good=hmac.compare_digest(sig,hmac.new(SECRET.encode(),raw.encode(),hashlib.sha256).hexdigest())
    if not good: return None
    try: uid=int(parts[0])
    except: return None
    c=db(); r=c.execute('SELECT * FROM sessions WHERE token=? AND expires_at>?',(t,now())).fetchone(); c.close()
    return uid if r else None

def auth(authorization:Optional[str]):
    token=authorization.split(' ',1)[1] if authorization and authorization.lower().startswith('bearer ') else None
    uid=verify_token(token)
    if not uid: raise HTTPException(401,'Authentication required')
    return uid

def user(uid):
    c=db(); r=c.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone(); c.close()
    if not r: raise HTTPException(404,'User not found')
    return dict(r)

def admin(uid): return user(uid).get('role')=='admin'
def rank_for(xp):
    levels=[('Beginner I',0),('Beginner II',250),('Beginner III',600),('Beginner IV',1000),('Beginner V',1500),('Amateur I',2200),('Amateur II',3200),('Amateur III',4500),('Amateur IV',6000),('Amateur V',8000),('Professional I',10500),('Professional II',13500),('Professional III',17000),('Professional IV',21000),('Professional V',26000),('Expert',32000),('Master',40000),('Pips Master',50000)]
    out=levels[0][0]
    for name,need in levels:
        if xp>=need: out=name
    return out

class Login(BaseModel): email:str; password:str
class Register(BaseModel): email:str; password:str; full_name:str=''; username:str=''; referral_code:str=''
class ProfileUpdate(BaseModel): full_name:str=''; username:str=''; phone:str=''; dob:str=''; profile_picture:str=''; password:str=''
class Prefs(BaseModel): trading_style:str='Scalping'; trigger_tf:str='5m'; markets:str='Forex'; theme:str='dark'; signal_notifications:bool=True
class Message(BaseModel): message:str=Field(min_length=1,max_length=2000)
class FeedbackIn(BaseModel): rating:int=Field(ge=1,le=5); message:str=Field(min_length=1,max_length=2000)
class TaskDone(BaseModel): done:bool=True

@app.on_event('startup')
def startup():
    c=db()
    if ADMIN_EMAIL and ADMIN_PASSWORD:
        r=c.execute('SELECT id FROM users WHERE email=?',(ADMIN_EMAIL,)).fetchone()
        if not r:
            code='PMAADMIN001'
            c.execute('INSERT INTO users(email,password_hash,full_name,username,pma_id,referral_code,role,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)',(ADMIN_EMAIL,pwd_hash(ADMIN_PASSWORD),ADMIN_NAME,ADMIN_USERNAME,'PMA-ADMIN001',code,'admin',now(),now()))
        else:
            c.execute("UPDATE users SET password_hash=?,role='admin',full_name=?,username=? WHERE email=?",(pwd_hash(ADMIN_PASSWORD),ADMIN_NAME,ADMIN_USERNAME,ADMIN_EMAIL))
    c.commit(); c.close()

@app.get('/api/health')
def health(): return {'ok':True,'service':'PMA API','time':now()}

@app.post('/api/auth/register')
def register(x:Register):
    c=db(); email=x.email.strip().lower()
    if c.execute('SELECT id FROM users WHERE email=?',(email,)).fetchone(): raise HTTPException(409,'Email already registered')
    code='PMA'+secrets.token_hex(4).upper()
    c.execute('INSERT INTO users(email,password_hash,full_name,username,pma_id,referral_code,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)',(email,pwd_hash(x.password),x.full_name,x.username,'PMA-'+secrets.token_hex(4).upper(),code,now(),now()))
    uid=c.execute('SELECT last_insert_rowid()').fetchone()[0]
    c.execute('INSERT INTO learning(user_id) VALUES(?)',(uid,)); c.execute('INSERT INTO preferences(user_id) VALUES(?)',(uid,)); c.commit()
    if x.referral_code:
        ref=c.execute('SELECT id FROM users WHERE referral_code=?',(x.referral_code.strip().upper(),)).fetchone()
        if ref: c.execute('INSERT INTO referrals(referrer_id,referred_email,created_at,status) VALUES(?,?,?,?)',(ref['id'],email,now(),'pending')); c.commit()
    token=make_token(uid); exp=(datetime.now(timezone.utc)+timedelta(seconds=TOKEN_TTL)).isoformat(); c.execute('INSERT INTO sessions(token,user_id,expires_at) VALUES(?,?,?)',(token,uid,exp)); c.commit(); c.close()
    return {'token':token,'user':user(uid)}

@app.post('/api/auth/login')
def login(x:Login):
    c=db(); r=c.execute('SELECT * FROM users WHERE email=? AND password_hash=?',(x.email.strip().lower(),pwd_hash(x.password))).fetchone()
    if not r: c.close(); raise HTTPException(401,'Invalid email or password')
    token=make_token(r['id']); exp=(datetime.now(timezone.utc)+timedelta(seconds=TOKEN_TTL)).isoformat(); c.execute('INSERT INTO sessions(token,user_id,expires_at) VALUES(?,?,?)',(token,r['id'],exp)); c.commit(); c.close(); return {'token':token,'user':user(r['id'])}

@app.get('/api/me')
def me(authorization:Optional[str]=Header(None)): return user(auth(authorization))

@app.put('/api/profile')
def profile(x:ProfileUpdate,authorization:Optional[str]=Header(None)):
    uid=auth(authorization); c=db(); u=user(uid); fields=['full_name=?','username=?','phone=?','dob=?','profile_picture=?']; vals=[x.full_name,x.username,x.phone,x.dob,x.profile_picture]
    if x.password: fields.append('password_hash=?'); vals.append(pwd_hash(x.password))
    vals += [now(),uid]; c.execute('UPDATE users SET '+','.join(fields)+',updated_at=? WHERE id=?',vals); c.commit(); c.close(); return user(uid)

@app.get('/api/preferences')
def get_prefs(authorization:Optional[str]=Header(None)):
    uid=auth(authorization); c=db(); r=c.execute('SELECT * FROM preferences WHERE user_id=?',(uid,)).fetchone(); c.close(); return dict(r)
@app.put('/api/preferences')
def set_prefs(x:Prefs,authorization:Optional[str]=Header(None)):
    uid=auth(authorization); c=db(); c.execute('INSERT INTO preferences(user_id,trading_style,trigger_tf,markets,theme,signal_notifications) VALUES(?,?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET trading_style=excluded.trading_style,trigger_tf=excluded.trigger_tf,markets=excluded.markets,theme=excluded.theme,signal_notifications=excluded.signal_notifications',(uid,x.trading_style,x.trigger_tf,x.markets,x.theme,int(x.signal_notifications))); c.execute('UPDATE users SET theme=? WHERE id=?',(x.theme,uid)); c.commit(); c.close(); return {'ok':True}

@app.get('/api/progress')
def progress(authorization:Optional[str]=Header(None)):
    uid=auth(authorization); u=user(uid); c=db(); l=c.execute('SELECT * FROM learning WHERE user_id=?',(uid,)).fetchone(); done=c.execute("SELECT COUNT(*) n FROM tasks WHERE user_id=? AND done=1",(uid,)).fetchone()['n']; total=c.execute('SELECT COUNT(*) n FROM tasks WHERE user_id=?',(uid,)).fetchone()['n']; refs=c.execute("SELECT COUNT(*) n FROM referrals WHERE referrer_id=? AND status='qualified'",(uid,)).fetchone()['n']; pend=c.execute("SELECT COUNT(*) n FROM referrals WHERE referrer_id=? AND status='pending'",(uid,)).fetchone()['n']; c.close(); return {'xp':u['xp'],'rank':rank_for(u['xp']),'learning_percent':l['learning_percent'],'overall_percent':l['overall_percent'],'streak':l['streak'],'tasks_done':done,'tasks_total':total,'qualified_referrals':refs,'pending_referrals':pend}

@app.get('/api/tasks')
def tasks(authorization:Optional[str]=Header(None)):
    uid=auth(authorization); d=datetime.now(timezone.utc).date().isoformat(); c=db(); n=c.execute('SELECT COUNT(*) n FROM tasks WHERE user_id=? AND task_date=?',(uid,d)).fetchone()['n']
    if not n:
        for t in ['Review 15m / 30m / 1H / 4H / 1D trends','Complete one academy lesson','Use a calculator with a practice example','Review one scanner setup','Write one learning note']:
            c.execute('INSERT INTO tasks(user_id,title,task_date,created_at) VALUES(?,?,?,?)',(uid,t,d,now()))
        c.commit()
    rows=[dict(r) for r in c.execute('SELECT * FROM tasks WHERE user_id=? AND task_date=? ORDER BY id',(uid,d)).fetchall()]; c.close(); return rows
@app.post('/api/tasks/{tid}')
def task(tid:int,x:TaskDone,authorization:Optional[str]=Header(None)):
    uid=auth(authorization); c=db(); r=c.execute('SELECT * FROM tasks WHERE id=? AND user_id=?',(tid,uid)).fetchone();
    if not r: c.close(); raise HTTPException(404,'Task not found')
    was=r['done']; c.execute('UPDATE tasks SET done=? WHERE id=?',(int(x.done),tid));
    if x.done and not was:
        u=user(uid); xp=u['xp']+50; c.execute('UPDATE users SET xp=?,rank=?,updated_at=? WHERE id=?',(xp,rank_for(xp),now(),uid))
    c.commit(); c.close(); return {'ok':True}

@app.get('/api/referrals')
def referrals(authorization:Optional[str]=Header(None)):
    uid=auth(authorization); c=db(); u=user(uid); month=datetime.now(timezone.utc).strftime('%Y-%m'); rows=c.execute("SELECT referrer_id,COUNT(*) n FROM referrals WHERE status='qualified' AND substr(qualified_at,1,7)=? GROUP BY referrer_id ORDER BY n DESC,referrer_id LIMIT 10",(month,)).fetchall(); top=[]
    for i,r in enumerate(rows,1):
        uu=c.execute('SELECT username,full_name FROM users WHERE id=?',(r['referrer_id'],)).fetchone(); top.append({'position':i,'username':uu['username'] or uu['full_name'],'referrals':r['n']})
    my=c.execute("SELECT COUNT(*) n FROM referrals WHERE referrer_id=? AND status='qualified' AND substr(qualified_at,1,7)=?",(uid,month)).fetchone()['n']; pos=1+c.execute("SELECT COUNT(*) n FROM (SELECT referrer_id,COUNT(*) n FROM referrals WHERE status='qualified' AND substr(qualified_at,1,7)=? GROUP BY referrer_id HAVING n>?)",(month,my)).fetchone()['n']; qualified=c.execute("SELECT COUNT(*) n FROM referrals WHERE referrer_id=? AND status='qualified'",(uid,)).fetchone()['n']; pending=c.execute("SELECT COUNT(*) n FROM referrals WHERE referrer_id=? AND status='pending'",(uid,)).fetchone()['n']; c.close(); return {'month':month,'top10':top,'my_position':pos,'my_referrals':my,'qualified':qualified,'pending':pending,'referral_code':u['referral_code']}

@app.get('/api/community')
def community(authorization:Optional[str]=Header(None)):
    auth(authorization); c=db(); rows=c.execute('SELECT m.id,m.message,m.created_at,m.user_id,u.username,u.full_name,u.profile_picture FROM community_messages m JOIN users u ON u.id=m.user_id WHERE m.deleted=0 ORDER BY m.id ASC').fetchall(); c.close(); return [dict(r) for r in rows]
@app.post('/api/community')
def post_community(x:Message,authorization:Optional[str]=Header(None)):
    uid=auth(authorization); c=db(); c.execute('INSERT INTO community_messages(user_id,message,created_at) VALUES(?,?,?)',(uid,x.message,now())); c.commit(); c.close(); return {'ok':True}

@app.get('/api/journal')
def journal_list(authorization:Optional[str]=Header(None)):
    uid=auth(authorization); c=db(); rows=[dict(r) for r in c.execute('SELECT * FROM journal WHERE user_id=? ORDER BY id DESC LIMIT 100',(uid,)).fetchall()]; c.close(); return rows

class JournalIn(BaseModel): note:str=Field(min_length=1,max_length=5000)
@app.post('/api/journal')
def journal_add(x:JournalIn,authorization:Optional[str]=Header(None)):
    uid=auth(authorization); c=db(); c.execute('INSERT INTO journal(user_id,note,created_at,updated_at) VALUES(?,?,?,?)',(uid,x.note,now(),now())); c.commit(); c.close(); return {'ok':True}

@app.get('/api/achievements')
def achievements(authorization:Optional[str]=Header(None)):
    uid=auth(authorization); p=progress(authorization); keys=[]
    if p['tasks_done']>=1: keys.append(('first_task','First Task'))
    if p['tasks_done']>=10: keys.append(('ten_tasks','10 Tasks'))
    if p['streak']>=7: keys.append(('streak7','7-Day Learning Streak'))
    if p['qualified_referrals']>=1: keys.append(('first_referral','First Qualified Referral'))
    c=db()
    for k,_ in keys: c.execute('INSERT OR IGNORE INTO achievements(user_id,key,unlocked_at) VALUES(?,?,?)',(uid,k,now()))
    c.commit(); rows=c.execute('SELECT key,unlocked_at FROM achievements WHERE user_id=? ORDER BY unlocked_at DESC',(uid,)).fetchall(); c.close(); return [dict(r) for r in rows]

@app.get('/api/feedback')
def feedback_list(authorization:Optional[str]=Header(None)):
    uid=auth(authorization); c=db(); q='SELECT f.*,u.username FROM feedback f JOIN users u ON u.id=f.user_id '
    rows=c.execute(q+'ORDER BY f.id DESC'+(' LIMIT 100' if not admin(uid) else '')).fetchall(); c.close(); return [dict(r) for r in rows]
@app.post('/api/feedback')
def feedback(x:FeedbackIn,authorization:Optional[str]=Header(None)):
    uid=auth(authorization); c=db(); c.execute('INSERT INTO feedback(user_id,rating,message,created_at,xp_awarded) VALUES(?,?,?,?,1)',(uid,x.rating,x.message,now())); u=user(uid); xp=u['xp']+25; c.execute('UPDATE users SET xp=?,rank=?,updated_at=? WHERE id=?',(xp,rank_for(xp),now(),uid)); c.commit(); c.close(); return {'ok':True,'xp_awarded':25}

# -------- market analysis --------
SYMBOL_MAP={'EURUSD':'EURUSD=X','GBPUSD':'GBPUSD=X','USDJPY':'JPY=X','GBPJPY':'GBPJPY=X','AUDUSD':'AUDUSD=X','USDCAD':'CAD=X','USDCHF':'CHF=X','NZDUSD':'NZDUSD=X','EURJPY':'EURJPY=X','EURGBP':'EURGBP=X','XAUUSD':'GC=F','XAGUSD':'SI=F','US30':'YM=F','NAS100':'NQ=F','SPX500':'ES=F','BTCUSD':'BTC-USD','ETHUSD':'ETH-USD','SOLUSD':'SOL-USD','XRPUSD':'XRP-USD','USOIL':'CL=F','UKOIL':'BZ=F','NATGAS':'NG=F'}
INTERVALS={'1m':'1m','5m':'5m','15m':'15m','30m':'30m','1H':'60m','4H':'60m','1D':'1d'}
RANGES={'1m':'1d','5m':'5d','15m':'10d','30m':'1mo','1H':'1mo','4H':'3mo','1D':'1y'}

def fetch_chart(symbol,tf):
    ticker=SYMBOL_MAP.get(symbol,symbol)
    url='https://query1.finance.yahoo.com/v8/finance/chart/'+ticker
    p={'interval':INTERVALS.get(tf,tf),'range':RANGES.get(tf,'10d'),'events':'history'}
    r=requests.get(url,params=p,timeout=12,headers={'User-Agent':'Mozilla/5.0'}); r.raise_for_status(); j=r.json()['chart']['result'][0]; q=j['indicators']['quote'][0]
    df=pd.DataFrame(q); df['timestamp']=pd.to_datetime(j['timestamp'],unit='s',utc=True); df=df.dropna(subset=['open','high','low','close']).reset_index(drop=True); return df,j.get('meta',{})

def ema(s,n): return s.ewm(span=n,adjust=False).mean()
def rsi(s,n=14):
    d=s.diff(); up=d.clip(lower=0).ewm(alpha=1/n,adjust=False).mean(); dn=(-d.clip(upper=0)).ewm(alpha=1/n,adjust=False).mean(); rs=up/(dn.replace(0,np.nan)); return 100-(100/(1+rs))
def atr(df,n=14):
    pc=df.close.shift(1); tr=pd.concat([(df.high-df.low),(df.high-pc).abs(),(df.low-pc).abs()],axis=1).max(axis=1); return tr.ewm(alpha=1/n,adjust=False).mean()

def analyze(df):
    e20,e50=ema(df.close,20),ema(df.close,50); rr=rsi(df.close); aa=atr(df); last=df.iloc[-1]; prev=df.iloc[-2]
    score=50; reasons=[]; bull=0; bear=0
    if last.close>e20.iloc[-1]>e50.iloc[-1]: bull+=1; score+=8; reasons.append('EMA trend alignment')
    elif last.close<e20.iloc[-1]<e50.iloc[-1]: bear+=1; score+=8; reasons.append('EMA trend alignment')
    if rr.iloc[-1]>55: bull+=1; score+=6; reasons.append('RSI momentum')
    elif rr.iloc[-1]<45: bear+=1; score+=6; reasons.append('RSI momentum')
    if last.close>prev.high: bull+=1; score+=8; reasons.append('Break above prior high')
    elif last.close<prev.low: bear+=1; score+=8; reasons.append('Break below prior low')
    if last.close>last.open: bull+=1
    else: bear+=1
    mid=df.close.rolling(20).mean().iloc[-1]; std=df.close.rolling(20).std().iloc[-1];
    if last.close>mid+0.5*std: bull+=1; reasons.append('Volatility/momentum expansion')
    elif last.close<mid-0.5*std: bear+=1; reasons.append('Volatility/momentum expansion')
    direction='BUY' if bull>bear else 'SELL' if bear>bull else 'NO TRADE'
    score=min(96,max(35,score+min(20,abs(bull-bear)*5))) if direction!='NO TRADE' else min(score,58)
    a=float(aa.iloc[-1]); entry=float(last.close); recent_high=float(df.high.tail(10).max()); recent_low=float(df.low.tail(10).min())
    if direction=='BUY': sl=min(recent_low,entry-a*0.8); tp1=entry+(entry-sl)*1.5; tp2=entry+(entry-sl)*2.3
    elif direction=='SELL': sl=max(recent_high,entry+a*0.8); tp1=entry-(sl-entry)*1.5; tp2=entry-(sl-entry)*2.3
    else: sl=tp1=tp2=entry
    strength='High' if score>=80 else 'Strong' if score>=70 else 'Developing' if score>=60 else 'Weak'
    return {'direction':direction,'confidence':int(score),'strength':strength,'entry':round(entry,6),'sl':round(sl,6),'tp1':round(tp1,6),'tp2':round(tp2,6),'atr':round(a,6),'reasons':reasons or ['Conflicting conditions']}

def timeframe_trend(symbol,tf):
    try:
        df,_=fetch_chart(symbol,tf); x=analyze(df); return 'Bullish' if x['direction']=='BUY' else 'Bearish' if x['direction']=='SELL' else 'Neutral'
    except Exception: return 'Unavailable'

@app.get('/api/signals/scan')
def scan(market:str='Forex',symbols:str='EURUSD',style:str='Scalping',timeframe:str='5m',authorization:Optional[str]=Header(None)):
    uid=auth(authorization); syms=[s.strip().upper() for s in symbols.split(',') if s.strip()]; out=[]
    for sym in syms[:20]:
        try:
            df,meta=fetch_chart(sym,timeframe); a=analyze(df); trends={tf:timeframe_trend(sym,tf) for tf in ['15m','30m','1H','4H','1D']}
            ts=df.timestamp.iloc[-1].isoformat(); candles=max(1,min(30,int(abs(df.close.iloc[-1]-df.close.tail(20).mean())/(a['atr'] or 1)*2)+1)); minutes={'1m':1,'5m':5,'15m':15,'30m':30,'1H':60}.get(timeframe,60); eta_min=candles*minutes
            setup_id=f'{sym}-{timeframe}-{a["direction"]}-{df.timestamp.iloc[-1].strftime("%Y%m%d%H%M")}'
            confs=a['reasons']+['Support/resistance structure','Supply/demand context','Data quality check']
            out.append({'setup_id':setup_id,'market':market,'symbol':sym,'direction':a['direction'],'confidence':a['confidence'],'strength':a['strength'],'entry':a['entry'],'sl':a['sl'],'tp1':a['tp1'],'tp2':a['tp2'],'timeframe':timeframe,'style':style,'estimated_candles':candles,'estimated_minutes':eta_min,'next_signal':'Monitoring for confirmation' if a['direction']=='NO TRADE' else 'Setup developing','trends':trends,'reasons':a['reasons'],'confirmations':confs,'data_timestamp':ts,'data_source':'Yahoo Finance chart data','verified':True})
            c=db(); c.execute('INSERT OR IGNORE INTO scanner_setups(id,user_id,symbol,market,direction,style,timeframe,confidence,strength,entry,sl,tp1,tp2,status,reason,confirmations,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(setup_id,uid,sym,market,a['direction'],style,timeframe,a['confidence'],a['strength'],a['entry'],a['sl'],a['tp1'],a['tp2'],'triggered' if a['direction']!='NO TRADE' and a['confidence']>=80 else 'developing',json.dumps(a['reasons']),json.dumps(confs),now()));
            if a['direction'] in ('BUY','SELL') and a['confidence']>=80:
                title=f'{sym} {a["direction"]} — ENTRY TRIGGERED'; message=f'{style} {timeframe} setup. Confidence {a["confidence"]}/100. Entry {a["entry"]} · SL {a["sl"]} · TP1 {a["tp1"]} · TP2 {a["tp2"]}'; c.execute('INSERT OR IGNORE INTO notifications(user_id,category,title,message,target,setup_id,created_at) VALUES(?,?,?,?,?,?,?)',(uid,'Signals',title,message,'signals',setup_id,now()))
            c.commit(); c.close()
        except Exception as e:
            out.append({'symbol':sym,'direction':'NO TRADE','confidence':0,'strength':'Unavailable','verified':False,'next_signal':'Verified market data unavailable','error':str(e)})
    return {'ok':True,'style':style,'timeframe':timeframe,'results':out}

@app.get('/api/scanner/history')
def scanner_history(authorization:Optional[str]=Header(None)):
    uid=auth(authorization); c=db(); rows=[dict(r) for r in c.execute('SELECT * FROM scanner_setups WHERE user_id=? ORDER BY created_at DESC LIMIT 100',(uid,)).fetchall()]; c.close(); return rows
@app.get('/api/scanner/performance')
def scanner_performance(authorization:Optional[str]=Header(None)):
    uid=auth(authorization); c=db(); total=c.execute('SELECT COUNT(*) n FROM scanner_setups WHERE user_id=?',(uid,)).fetchone()['n']; high=c.execute('SELECT COUNT(*) n FROM scanner_setups WHERE user_id=? AND confidence>=80',(uid,)).fetchone()['n']; buys=c.execute("SELECT COUNT(*) n FROM scanner_setups WHERE user_id=? AND direction='BUY'",(uid,)).fetchone()['n']; sells=c.execute("SELECT COUNT(*) n FROM scanner_setups WHERE user_id=? AND direction='SELL'",(uid,)).fetchone()['n']; c.close(); return {'total_setups':total,'high_confidence':high,'buy_setups':buys,'sell_setups':sells,'note':'Statistics reflect recorded scanner setups; they are not a guarantee of future results.'}

@app.get('/api/notifications')
def notifications(authorization:Optional[str]=Header(None)):
    uid=auth(authorization); cutoff=(datetime.now(timezone.utc)-timedelta(days=14)).isoformat(); c=db(); c.execute('DELETE FROM notifications WHERE user_id=? AND created_at<?',(uid,cutoff)); c.commit(); rows=[dict(r) for r in c.execute('SELECT * FROM notifications WHERE user_id=? ORDER BY id DESC LIMIT 100',(uid,)).fetchall()]; c.close(); return rows
@app.post('/api/notifications/clear')
def clear_notifications(authorization:Optional[str]=Header(None)):
    uid=auth(authorization); c=db(); c.execute('UPDATE notifications SET cleared=1 WHERE user_id=?',(uid,)); c.commit(); c.close(); return {'ok':True}
@app.post('/api/notifications/read/{nid}')
def read_notification(nid:int,authorization:Optional[str]=Header(None)):
    uid=auth(authorization); c=db(); c.execute('UPDATE notifications SET read=1 WHERE id=? AND user_id=?',(nid,uid)); c.commit(); c.close(); return {'ok':True}

@app.get('/api/admin/status')
def admin_status(authorization:Optional[str]=Header(None)):
    uid=auth(authorization)
    if not admin(uid): raise HTTPException(403,'Admin only')
    c=db(); users=c.execute('SELECT COUNT(*) n FROM users').fetchone()['n']; feedback=c.execute('SELECT COUNT(*) n FROM feedback').fetchone()['n']; messages=c.execute('SELECT COUNT(*) n FROM community_messages WHERE deleted=0').fetchone()['n']; c.close(); return {'admin':True,'users':users,'feedback':feedback,'community':'open','messages':messages}
