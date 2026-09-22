from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from passlib.context import CryptContext
import secrets,time,sqlite3,os,random
from .market_data import fetch, analyze, pip_size, backtest

ADMIN_EMAIL='ugoloevidence81@gmail.com'
app=FastAPI(title='Pips Master Academy API')
app.add_middleware(CORSMiddleware,allow_origins=['*'],allow_methods=['*'],allow_headers=['*'])
DB=os.getenv('PMA_DB','pma.db'); pwd=CryptContext(schemes=['bcrypt'],deprecated='auto'); sessions={}

def db():
 c=sqlite3.connect(DB); c.row_factory=sqlite3.Row
 c.execute('''CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,username TEXT UNIQUE,full_name TEXT,email TEXT UNIQUE,password TEXT,pma_id TEXT UNIQUE,referral_code TEXT UNIQUE,referrer TEXT,role TEXT DEFAULT 'user',phone TEXT DEFAULT '',dob TEXT DEFAULT '',profile_picture TEXT DEFAULT '',created INTEGER)''')
 c.execute('''CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY,username TEXT,pma_id TEXT,text TEXT,media_data TEXT DEFAULT '',media_type TEXT DEFAULT '',created INTEGER)''')
 c.execute('''CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY,username TEXT,title TEXT,text TEXT,type TEXT DEFAULT 'info',created INTEGER,read INTEGER DEFAULT 0)''')
 c.execute('''CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT)'''); c.commit(); return c

def one_time_admin_reset():
 if os.getenv('RESET_ADMIN_ACCOUNT_ONCE','').lower()!='true': return
 c=db(); done=c.execute("SELECT value FROM settings WHERE key='admin_reset_done'").fetchone()
 if not done:
  c.execute('DELETE FROM users WHERE lower(email)=lower(?)',(ADMIN_EMAIL,)); c.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('admin_reset_done','true')"); c.commit()
 c.close()
one_time_admin_reset()

class Signup(BaseModel): username:str; full_name:str; email:EmailStr; password:str; confirm_password:str; referral:str=''
class Login(BaseModel): email:EmailStr; password:str
class Msg(BaseModel): text:str=''; media_data:str=''; media_type:str=''
class Profile(BaseModel): full_name:str; username:str; phone:str=''; dob:str=''; profile_picture:str=''
class PasswordChange(BaseModel): password:str

def user_out(r): return {'username':r['username'],'full_name':r['full_name'],'email':r['email'],'pma_id':r['pma_id'],'referral_code':r['referral_code'],'role':r['role'],'phone':r['phone'] or '','dob':r['dob'] or '','profile_picture':r['profile_picture'] or ''}
def current(req):
 s=req.headers.get('Authorization','').replace('Bearer ',''); uid=sessions.get(s)
 if not uid: raise HTTPException(401,'Please log in.')
 c=db(); r=c.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone(); c.close()
 if not r: raise HTTPException(401,'Session expired.')
 return r

def push_notice(c,username,title,text,typ='info'):
 c.execute('INSERT INTO notifications(username,title,text,type,created,read) VALUES(?,?,?,?,?,0)',(username,title,text,typ,int(time.time())))

def get_locked(c):
 r=c.execute("SELECT value FROM settings WHERE key='community_locked'").fetchone()
 return bool(r and r['value']=='1')

def set_locked(c,value):
 c.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('community_locked',?)",('1' if value else '0',))

@app.get('/api/health')
def health(): return {'ok':True}

@app.post('/api/auth/signup')
def signup(x:Signup):
 if x.password!=x.confirm_password: raise HTTPException(400,'Passwords do not match.')
 if len(x.password)<8: raise HTTPException(400,'Password must be at least 8 characters.')
 c=db()
 if c.execute('SELECT 1 FROM users WHERE lower(email)=lower(?)',(x.email,)).fetchone(): c.close(); raise HTTPException(400,'That email is already registered. Please log in.')
 pma=f'PMA-{random.randint(100000,999999)}'; refcode=pma.replace('-','')
 while c.execute('SELECT 1 FROM users WHERE pma_id=?',(pma,)).fetchone(): pma=f'PMA-{random.randint(100000,999999)}'; refcode=pma.replace('-','')
 role='admin' if x.email.lower()==ADMIN_EMAIL else 'user'
 c.execute('INSERT INTO users(username,full_name,email,password,pma_id,referral_code,referrer,role,created) VALUES(?,?,?,?,?,?,?,?,?)',(x.username,x.full_name,str(x.email),pwd.hash(x.password),pma,refcode,x.referral,role,int(time.time())))
 r=c.execute('SELECT * FROM users WHERE id=last_insert_rowid()').fetchone(); push_notice(c,r['username'],'Welcome to Pips Master Academy','Your account was created successfully.','account'); c.commit(); c.close()
 token=secrets.token_urlsafe(32); sessions[token]=r['id']; return {'user':user_out(r),'token':token}

@app.post('/api/auth/login')
def login(x:Login):
 c=db();r=c.execute('SELECT * FROM users WHERE lower(email)=lower(?)',(x.email,)).fetchone();
 if not r or not pwd.verify(x.password,r['password']): c.close(); raise HTTPException(401,'Email or password is incorrect.')
 push_notice(c,r['username'],'New login','Your account was signed in successfully.','security'); c.commit(); c.close(); token=secrets.token_urlsafe(32);sessions[token]=r['id'];return {'user':user_out(r),'token':token}

@app.post('/api/auth/logout')
def logout(req:Request): sessions.pop(req.headers.get('Authorization','').replace('Bearer ',''),None); return {'ok':True}

@app.get('/api/auth/profile')
def get_profile(req:Request):
 u=current(req); return {'user':user_out(u)}

@app.put('/api/auth/profile')
def update_profile(req:Request,x:Profile):
 u=current(req); c=db();
 if c.execute('SELECT 1 FROM users WHERE lower(username)=lower(?) AND id<>?',(x.username,u['id'])).fetchone(): c.close(); raise HTTPException(400,'That username is already in use.')
 c.execute('UPDATE users SET full_name=?,username=?,phone=?,dob=?,profile_picture=? WHERE id=?',(x.full_name,x.username,x.phone,x.dob,x.profile_picture,u['id'])); push_notice(c,x.username,'Profile saved','Your profile changes were saved successfully.','account'); c.commit(); r=c.execute('SELECT * FROM users WHERE id=?',(u['id'],)).fetchone(); c.close(); return {'user':user_out(r)}

@app.put('/api/auth/password')
def change_password(req:Request,x:PasswordChange):
 u=current(req)
 if len(x.password)<8: raise HTTPException(400,'Password must be at least 8 characters.')
 c=db(); c.execute('UPDATE users SET password=? WHERE id=?',(pwd.hash(x.password),u['id'])); push_notice(c,u['username'],'Password updated','Your password was updated successfully.','security'); c.commit(); c.close(); return {'ok':True}

@app.get('/api/notifications')
def notifications(req:Request):
 u=current(req); c=db(); rows=c.execute('SELECT * FROM notifications WHERE username=? ORDER BY id DESC LIMIT 60',(u['username'],)).fetchall(); c.close(); return {'notifications':[{'id':r['id'],'title':r['title'],'text':r['text'],'type':r['type'],'time':time.strftime('%Y-%m-%d %H:%M',time.localtime(r['created'])),'read':bool(r['read'])} for r in rows]}
@app.post('/api/notifications/read')
def notifications_read(req:Request):
 u=current(req); c=db(); c.execute('UPDATE notifications SET read=1 WHERE username=?',(u['username'],)); c.commit(); c.close(); return {'ok':True}

@app.get('/api/signals/scan')
def scan(market:str='Forex',symbols:str='EURUSD'):
 requested=[x.strip().upper() for x in symbols.split(',') if x.strip()] or ['EURUSD']; opportunities=[]; errors=[]
 for sym in requested[:30]:
  try:
   rows=fetch(sym,'15m'); a=analyze(rows); trends={}
   for tf in ('15m','30m','1h','4h','1d'):
    try: trends[tf]=analyze(fetch(sym,tf))['trend']
    except Exception: trends[tf]='Unavailable'
   pips=round(a['distance']/pip_size(sym),1); mins=a['candles_to_zone']*15; validation=backtest(rows); alignment=sum(1 for v in trends.values() if v==a['trend'])
   opportunities.append({'symbol':sym,'market':market,'direction':a['direction'],'zone_type':a['zone_type'],'zone':round(a['zone'],8),'distance':round(a['distance'],8),'pips_to_zone':pips,'atr':round(a['atr'],8),'candles_to_zone':a['candles_to_zone'],'estimated_minutes_to_entry':mins,'timeframe':'15m','trends':trends,'trend_errors':trend_errors,'trend_alignment':f'{alignment}/5','last':round(a['last'],8),'support':round(a['support'],8),'resistance':round(a['resistance'],8),'validation':validation,'status':'ZONE APPROACHING' if a['candles_to_zone']<=2 else 'WATCHING'})
  except Exception as ex: errors.append({'symbol':sym,'error':str(ex)})
 opportunities.sort(key=lambda x:x['estimated_minutes_to_entry']); return {'closest':opportunities[0] if opportunities else None,'opportunities':opportunities,'errors':errors,'market':market,'symbols':requested,'message':('Verified candle data loaded.' if opportunities else 'No verified candle data was returned; no signal is being invented.')}

@app.get('/api/signals/candles')
def candles(symbol:str='EURUSD',timeframe:str='15m'):
 try: return {'symbol':symbol.upper(),'timeframe':timeframe,'candles':fetch(symbol,timeframe)[-200:]}
 except Exception as ex: raise HTTPException(503,f'Live candle feed unavailable: {ex}')

@app.get('/api/community/messages')
def get_messages(req:Request):
 current(req); c=db(); rows=c.execute('SELECT * FROM messages ORDER BY id ASC LIMIT 300').fetchall(); is_locked=get_locked(c); c.close(); return {'locked':is_locked,'messages':[{'username':r['username'],'pma_id':r['pma_id'],'text':r['text'],'media_data':r['media_data'],'media_type':r['media_type'],'time':time.strftime('%H:%M',time.localtime(r['created']))} for r in rows]}
@app.post('/api/community/messages')
def post_message(req:Request,x:Msg):
 u=current(req); c0=db(); is_locked=get_locked(c0); c0.close()
 if is_locked and u['role']!='admin': raise HTTPException(403,'Community chat is locked by the administrator.')
 if not x.text.strip() and not x.media_data: raise HTTPException(400,'Message cannot be empty.')
 c=db(); c.execute('INSERT INTO messages(username,pma_id,text,media_data,media_type,created) VALUES(?,?,?,?,?,?)',(u['username'],u['pma_id'],x.text,x.media_data,x.media_type,int(time.time())))
 # notify all other members
 users=c.execute('SELECT username FROM users WHERE username<>?',(u['username'],)).fetchall()
 for r in users: push_notice(c,r['username'],'New community message',f"{u['username']} posted in the community.",'community')
 c.commit(); c.close(); return {'ok':True}
@app.post('/api/admin/community/toggle')
def toggle(req:Request):
 u=current(req)
 if u['role']!='admin': raise HTTPException(403,'Admin access required.')
 c=db(); new_state=not get_locked(c); set_locked(c,new_state)
 users=c.execute('SELECT username FROM users').fetchall()
 for r in users: push_notice(c,r['username'],'Community status','The community is now '+('locked.' if new_state else 'open.'),'community')
 c.commit(); c.close(); return {'locked':new_state}
