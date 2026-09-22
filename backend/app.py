from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
import base64, hashlib, hmac, json
import os, random, secrets, sqlite3, time

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
import bcrypt
from pydantic import BaseModel, EmailStr

from .market_data import fetch, analyze_setup, pip_size, backtest, trend_info, utc_iso, norm_symbol

ADMIN_EMAIL = os.getenv('PMA_ADMIN_EMAIL', 'ugoloevidence81@gmail.com').lower()
ADMIN_USERNAME = os.getenv('PMA_ADMIN_USERNAME', 'PipsMaster')
ADMIN_FULL_NAME = os.getenv('PMA_ADMIN_FULL_NAME', 'Ugolo Evidence')
ADMIN_PASSWORD = os.getenv('PMA_ADMIN_PASSWORD', '')
TOKEN_SECRET = os.getenv('PMA_SECRET_KEY', '') or 'pma-dev-secret-change-this-in-render'
TOKEN_TTL = int(os.getenv('PMA_TOKEN_TTL', str(60*60*24*30)))
QUALIFICATION_HOURS = int(os.getenv('PMA_REFERRAL_QUALIFICATION_HOURS', '48'))
DB = os.getenv('PMA_DB', 'pma.db')
sessions = {}

app = FastAPI(title='Pips Master Academy API', version='2.0')
app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_methods=['*'], allow_headers=['*'])

RANKS = [
    ('Beginner I', 0), ('Beginner II', 500), ('Beginner III', 1200), ('Beginner IV', 2100), ('Beginner V', 3500),
    ('Amateur I', 5500), ('Amateur II', 8000), ('Amateur III', 11000), ('Amateur IV', 15000), ('Amateur V', 20000),
    ('Professional I', 27000), ('Professional II', 36000), ('Professional III', 48000), ('Professional IV', 62000), ('Professional V', 80000),
    ('Expert I', 100000), ('Expert II', 125000), ('Expert III', 155000), ('Expert IV', 190000), ('Expert V', 230000),
    ('Master I', 275000), ('Master II', 325000), ('Master III', 385000), ('Master IV', 455000), ('Master V', 535000),
    ('Pips Master', 650000),
]

LESSONS = [
    {'id':'basics-01','course':'Forex Basics','title':'What is Forex?','xp':150},
    {'id':'basics-02','course':'Forex Basics','title':'Currency pairs and pips','xp':150},
    {'id':'charts-01','course':'Chart Reading','title':'Candlesticks','xp':175},
    {'id':'charts-02','course':'Chart Reading','title':'Support and resistance','xp':175},
    {'id':'structure-01','course':'Market Structure','title':'Higher highs and lower lows','xp':200},
    {'id':'structure-02','course':'Market Structure','title':'Breaks of structure','xp':200},
    {'id':'zones-01','course':'Supply & Demand','title':'Demand zones','xp':200},
    {'id':'zones-02','course':'Supply & Demand','title':'Supply zones','xp':200},
    {'id':'risk-01','course':'Risk Management','title':'Risk per trade','xp':225},
    {'id':'risk-02','course':'Risk Management','title':'Position sizing','xp':225},
    {'id':'risk-03','course':'Risk Management','title':'Risk-to-reward','xp':225},
    {'id':'psych-01','course':'Trading Psychology','title':'Discipline and consistency','xp':225},
    {'id':'analysis-01','course':'Technical Analysis','title':'Multi-timeframe analysis','xp':250},
    {'id':'analysis-02','course':'Technical Analysis','title':'Momentum and confirmation','xp':250},
    {'id':'journal-01','course':'Trading Journal','title':'Building a trade plan','xp':250},
    {'id':'journal-02','course':'Trading Journal','title':'Reviewing your decisions','xp':250},
]
TASKS = [
    {'id':'task-profile','title':'Complete your profile','xp':75},
    {'id':'task-calculator','title':'Use the risk calculator','xp':50},
    {'id':'task-read-basics','title':'Finish a beginner lesson','xp':50},
    {'id':'task-multi-tf','title':'Review all five timeframes','xp':75},
    {'id':'task-community','title':'Make a useful community post','xp':75},
    {'id':'task-referral','title':'Share your referral link','xp':50},
    {'id':'task-journal','title':'Write a personal trade-plan note','xp':100},
    {'id':'task-risk-review','title':'Review your risk rules','xp':75},
    {'id':'task-weekly-check','title':'Complete your weekly learning check','xp':100},
    {'id':'task-challenge','title':'Complete a monthly learning challenge','xp':150},
    {'id':'task-consistency','title':'Maintain a learning routine','xp':100},
    {'id':'task-advanced','title':'Complete an advanced lesson','xp':200},
]
DAILY_TASKS = [
    {'id':'daily-review-timeframes','title':'Review today’s 15m, 30m, 1H, 4H and 1D trends','xp':20},
    {'id':'daily-lesson','title':'Complete one learning lesson','xp':30},
    {'id':'daily-calculator','title':'Use one calculator tool with a practice example','xp':20},
    {'id':'daily-journal','title':'Write one learning or trade-plan note','xp':25},
    {'id':'daily-scanner-review','title':'Review one automated scanner setup','xp':20},
    {'id':'daily-community','title':'Make one useful community contribution','xp':20},
]


class Signup(BaseModel):
    username: str
    full_name: str
    email: EmailStr
    password: str
    confirm_password: str
    referral: str = ''


class Login(BaseModel):
    email: EmailStr
    password: str


class Msg(BaseModel):
    text: str = ''
    media_data: str = ''
    media_type: str = ''


class Profile(BaseModel):
    full_name: str
    username: str
    phone: str = ''
    dob: str = ''
    profile_picture: str = ''


class PasswordChange(BaseModel):
    password: str


class Completion(BaseModel):
    item_id: str


def hash_password(password):
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')


def verify_password(password, stored_hash):
    try:
        return bcrypt.checkpw(password.encode('utf-8'), stored_hash.encode('utf-8'))
    except Exception:
        return False


def db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    c.execute('''CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY, username TEXT UNIQUE, full_name TEXT, email TEXT UNIQUE,
        password TEXT, pma_id TEXT UNIQUE, referral_code TEXT UNIQUE, referrer TEXT,
        role TEXT DEFAULT 'user', phone TEXT DEFAULT '', dob TEXT DEFAULT '', profile_picture TEXT DEFAULT '',
        created INTEGER, xp INTEGER DEFAULT 0, last_active INTEGER DEFAULT 0, login_count INTEGER DEFAULT 0,
        activity_count INTEGER DEFAULT 0
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS messages(
        id INTEGER PRIMARY KEY, username TEXT, pma_id TEXT, text TEXT, media_data TEXT DEFAULT '',
        media_type TEXT DEFAULT '', created INTEGER
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS notifications(
        id INTEGER PRIMARY KEY, username TEXT, title TEXT, text TEXT, type TEXT DEFAULT 'info', created INTEGER, read INTEGER DEFAULT 0,
        target_page TEXT DEFAULT '', target_ref TEXT DEFAULT ''
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS referrals(
        id INTEGER PRIMARY KEY, referrer_id INTEGER NOT NULL, referred_id INTEGER NOT NULL,
        challenge_month TEXT NOT NULL, status TEXT DEFAULT 'pending', created INTEGER NOT NULL,
        qualification_due INTEGER NOT NULL, qualified_at INTEGER, flagged INTEGER DEFAULT 0,
        reason TEXT DEFAULT '', UNIQUE(referrer_id,referred_id)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS lesson_progress(
        user_id INTEGER NOT NULL, lesson_id TEXT NOT NULL, completed_at INTEGER NOT NULL,
        PRIMARY KEY(user_id,lesson_id)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS task_progress(
        user_id INTEGER NOT NULL, task_id TEXT NOT NULL, completed_at INTEGER NOT NULL,
        PRIMARY KEY(user_id,task_id)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS daily_task_progress(
        user_id INTEGER NOT NULL, task_id TEXT NOT NULL, day TEXT NOT NULL, completed_at INTEGER NOT NULL,
        PRIMARY KEY(user_id,task_id,day)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS feedback(
        id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, username TEXT NOT NULL, category TEXT NOT NULL,
        rating INTEGER NOT NULL, message TEXT NOT NULL, created INTEGER NOT NULL, status TEXT DEFAULT 'new'
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS activity_log(
        id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, day TEXT NOT NULL, event_type TEXT NOT NULL, created INTEGER NOT NULL
    )''')
    # Small migrations for databases created by previous PMA versions.
    notif_existing = {r['name'] for r in c.execute("PRAGMA table_info(notifications)").fetchall()}
    for name, ddl in {
        'target_page':'ALTER TABLE notifications ADD COLUMN target_page TEXT DEFAULT ''',
        'target_ref':'ALTER TABLE notifications ADD COLUMN target_ref TEXT DEFAULT ''',
    }.items():
        if name not in notif_existing:
            c.execute(ddl)

    existing = {r['name'] for r in c.execute("PRAGMA table_info(users)").fetchall()}
    for name, ddl in {
        'xp':'ALTER TABLE users ADD COLUMN xp INTEGER DEFAULT 0',
        'last_active':'ALTER TABLE users ADD COLUMN last_active INTEGER DEFAULT 0',
        'login_count':'ALTER TABLE users ADD COLUMN login_count INTEGER DEFAULT 0',
        'activity_count':'ALTER TABLE users ADD COLUMN activity_count INTEGER DEFAULT 0',
    }.items():
        if name not in existing:
            c.execute(ddl)

    # Keep notification history for 14 days only. Clearing the top-right inbox never deletes history.
    c.execute('DELETE FROM notifications WHERE created < ?', (int(time.time()) - 14*86400,))

    # If the admin password is configured in the deployment environment, make sure the
    # designated admin account exists and can authenticate from any device. No password is
    # stored in frontend code or source files.
    if ADMIN_PASSWORD:
        admin_row = c.execute('SELECT * FROM users WHERE lower(email)=lower(?)', (ADMIN_EMAIL,)).fetchone()
        if admin_row:
            c.execute('UPDATE users SET username=?,full_name=?,role=? WHERE id=?', (ADMIN_USERNAME, ADMIN_FULL_NAME, 'admin', admin_row['id']))
            if not verify_password(ADMIN_PASSWORD, admin_row['password']):
                c.execute('UPDATE users SET password=? WHERE id=?', (hash_password(ADMIN_PASSWORD), admin_row['id']))
        else:
            now = int(time.time())
            pma = 'PMA-ADMIN001'
            referral_code = 'PMAADMIN001'
            c.execute('INSERT INTO users(username,full_name,email,password,pma_id,referral_code,referrer,role,created,xp,last_active,login_count,activity_count) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                      (ADMIN_USERNAME, ADMIN_FULL_NAME, ADMIN_EMAIL, hash_password(ADMIN_PASSWORD), pma, referral_code, '', 'admin', now, 0, now, 0, 1))

    c.commit()
    return c


def month_key(ts=None):
    return datetime.fromtimestamp(ts or time.time(), timezone.utc).strftime('%Y-%m')


def user_out(row):
    return {
        'username': row['username'], 'full_name': row['full_name'], 'email': row['email'],
        'pma_id': row['pma_id'], 'referral_code': row['referral_code'], 'role': row['role'],
        'phone': row['phone'] or '', 'dob': row['dob'] or '', 'profile_picture': row['profile_picture'] or '',
    }


def referral_rank_for_count(count):
    count = max(0, int(count or 0))
    levels = [
        ('Referral Newcomer', 0),
        ('Referral Starter', 10),
        ('Referral Builder', 25),
        ('Referral Pro', 50),
        ('Referral Champion', 80),
        ('Referral Elite', 100),
        ('Referral Legend', 250),
    ]
    current, current_min = levels[0]
    next_name, next_min = None, None
    for i, (name, threshold) in enumerate(levels):
        if count >= threshold:
            current, current_min = name, threshold
            if i + 1 < len(levels):
                next_name, next_min = levels[i + 1]
        else:
            break
    progress = 100 if next_min is None else round(min(100, max(0, (count-current_min)/max(next_min-current_min,1)*100)), 1)
    return {'referral_rank':current,'referral_rank_min':current_min,'next_referral_rank':next_name,'next_referral_count':next_min,'referral_rank_progress':progress}


def rank_for_xp(xp):
    current = RANKS[0][0]
    current_min = RANKS[0][1]
    next_name = None
    next_min = None
    for i, (name, threshold) in enumerate(RANKS):
        if xp >= threshold:
            current, current_min = name, threshold
            if i + 1 < len(RANKS):
                next_name, next_min = RANKS[i + 1]
        else:
            break
    if next_min is None:
        progress = 100
    else:
        progress = round(min(100, max(0, (xp - current_min) / max(next_min - current_min, 1) * 100)), 1)
    return {'rank': current, 'rank_min_xp': current_min, 'next_rank': next_name, 'next_rank_xp': next_min, 'rank_progress': progress}


def record_activity(c, user_id, event_type, xp=0):
    now = int(time.time())
    day = datetime.fromtimestamp(now, timezone.utc).strftime('%Y-%m-%d')
    c.execute('INSERT INTO activity_log(user_id,day,event_type,created) VALUES(?,?,?,?)', (user_id,day,event_type,now))
    c.execute('UPDATE users SET activity_count=COALESCE(activity_count,0)+1,last_active=?,xp=COALESCE(xp,0)+? WHERE id=?', (now,xp,user_id))


def daily_streak(c, user_id):
    days = [r['day'] for r in c.execute('SELECT DISTINCT day FROM activity_log WHERE user_id=? ORDER BY day DESC LIMIT 370',(user_id,)).fetchall()]
    if not days: return 0
    day_set = set(datetime.strptime(x,'%Y-%m-%d').date() for x in days)
    today = datetime.now(timezone.utc).date()
    if today not in day_set and (today - timedelta(days=1)) not in day_set:
        return 0
    cursor = today if today in day_set else today - timedelta(days=1)
    streak = 0
    while cursor in day_set:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


def _token_pack(payload):
    body = base64.urlsafe_b64encode(json.dumps(payload, separators=(',', ':')).encode()).decode().rstrip('=')
    sig = hmac.new(TOKEN_SECRET.encode(), body.encode(), hashlib.sha256).hexdigest()
    return body + '.' + sig


def _token_unpack(token):
    try:
        body, sig = token.split('.', 1)
        expected = hmac.new(TOKEN_SECRET.encode(), body.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        raw = base64.urlsafe_b64decode(body + '=' * (-len(body) % 4))
        payload = json.loads(raw.decode())
        if int(payload.get('exp', 0)) < int(time.time()):
            return None
        return payload
    except Exception:
        return None


def make_token(user_id):
    return _token_pack({'uid': int(user_id), 'exp': int(time.time()) + TOKEN_TTL})


def notification_target(typ):
    return {
        'referral':'referrals', 'community':'community', 'task':'progress',
        'signal':'signals', 'account':'profile', 'security':'profile', 'learning':'progress', 'feedback':'feedback'
    }.get(typ, 'home')


def push_notice(c, username, title, text, typ='info', target_page=''):
    page = target_page or notification_target(typ)
    c.execute('INSERT INTO notifications(username,title,text,type,created,read,target_page,target_ref) VALUES(?,?,?,?,?,?,?,?)',
              (username,title,text,typ,int(time.time()),0,page,''))


def get_locked(c):
    row = c.execute("SELECT value FROM settings WHERE key='community_locked'").fetchone()
    return bool(row and row['value'] == '1')


def set_locked(c, value):
    c.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('community_locked',?)", ('1' if value else '0',))


def current(req: Request):
    token = req.headers.get('Authorization','').replace('Bearer ','').strip()
    payload = _token_unpack(token)
    if not payload:
        raise HTTPException(401,'Please log in again.')
    uid = payload.get('uid')
    c = db(); row = c.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone()
    if not row:
        c.close(); raise HTTPException(401,'Session expired.')
    # Update presence only; do not inflate activity_count just because the UI polls the API.
    c.execute('UPDATE users SET last_active=? WHERE id=?',(int(time.time()),uid)); c.commit(); c.close()
    return row


def resolve_referrer(c, referral):
    value = (referral or '').strip()
    if not value: return None
    return c.execute('SELECT * FROM users WHERE lower(referral_code)=lower(?) OR lower(username)=lower(?) OR lower(pma_id)=lower(?) LIMIT 1',(value,value,value)).fetchone()


def qualify_referrals(c):
    now = int(time.time())
    rows = c.execute("SELECT r.*,u.username AS referred_username,u.email AS referred_email,u.login_count,u.activity_count,u.last_active,ref.username AS referrer_username FROM referrals r JOIN users u ON u.id=r.referred_id JOIN users ref ON ref.id=r.referrer_id WHERE r.status='pending' AND r.qualification_due<=? ORDER BY r.id",(now,)).fetchall()
    for r in rows:
        genuine_activity = (r['login_count'] or 0) >= 1 and (r['activity_count'] or 0) >= 2 and (r['last_active'] or 0) > r['created']
        if genuine_activity:
            c.execute('UPDATE referrals SET status="qualified",qualified_at=? WHERE id=?',(now,r['id']))
            c.execute('UPDATE users SET xp=COALESCE(xp,0)+25 WHERE id=?',(r['referrer_id'],))
            push_notice(c, r['referrer_username'], 'Referral qualified', f"{r['referred_username']} is now a qualified referral.", 'referral') if 'referrer_username' in r.keys() else None
        else:
            # Keep it pending; the qualification check can run again after the member becomes active.
            c.execute('UPDATE referrals SET qualification_due=? WHERE id=?',(now + 24*3600,r['id']))
    c.commit()


@app.get('/api/health')
def health():
    return {'ok':True,'service':'pma-api','time':utc_iso()}


@app.post('/api/auth/signup')
def signup(x: Signup):
    if x.password != x.confirm_password: raise HTTPException(400,'Passwords do not match.')
    if len(x.password) < 8: raise HTTPException(400,'Password must be at least 8 characters.')
    c = db()
    if c.execute('SELECT 1 FROM users WHERE lower(email)=lower(?)',(str(x.email),)).fetchone():
        c.close(); raise HTTPException(400,'That email is already registered. Please log in.')
    if c.execute('SELECT 1 FROM users WHERE lower(username)=lower(?)',(x.username.strip(),)).fetchone():
        c.close(); raise HTTPException(400,'That username is already in use.')
    pma = f'PMA-{random.randint(100000,999999)}'
    while c.execute('SELECT 1 FROM users WHERE pma_id=?',(pma,)).fetchone():
        pma = f'PMA-{random.randint(100000,999999)}'
    role = 'admin' if ADMIN_PASSWORD and str(x.email).lower() == ADMIN_EMAIL.lower() and x.password == ADMIN_PASSWORD else 'user'
    now = int(time.time())
    referrer = resolve_referrer(c, x.referral)
    c.execute('INSERT INTO users(username,full_name,email,password,pma_id,referral_code,referrer,role,created,xp,last_active,login_count,activity_count) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
              (x.username.strip(),x.full_name.strip(),str(x.email).lower(),hash_password(x.password),pma,pma.replace('-',''),referrer['username'] if referrer else '',role,now,0,now,0,1))
    uid = c.execute('SELECT last_insert_rowid() AS id').fetchone()['id']
    c.execute('INSERT INTO activity_log(user_id,day,event_type,created) VALUES(?,?,?,?)',(uid,datetime.fromtimestamp(now,timezone.utc).strftime('%Y-%m-%d'),'signup',now))
    if referrer and referrer['id'] != uid:
        c.execute('INSERT OR IGNORE INTO referrals(referrer_id,referred_id,challenge_month,status,created,qualification_due) VALUES(?,?,?,?,?,?)',
                  (referrer['id'],uid,month_key(now),'pending',now,now + QUALIFICATION_HOURS*3600))
        push_notice(c, referrer['username'], 'New referral', f"{x.username} joined through your referral link. It is pending qualification.", 'referral')
    row = c.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone()
    push_notice(c,row['username'],'Welcome to Pips Master Academy','Your account was created successfully.','account')
    c.commit(); c.close()
    token = make_token(uid)
    return {'user':user_out(row),'token':token}


@app.post('/api/auth/login')
def login(x: Login):
    c = db(); row = c.execute('SELECT * FROM users WHERE lower(email)=lower(?)',(str(x.email),)).fetchone()
    if not row or not verify_password(x.password,row['password']): c.close(); raise HTTPException(401,'Email or password is incorrect.')
    now = int(time.time())
    c.execute('UPDATE users SET last_active=?,login_count=COALESCE(login_count,0)+1,activity_count=COALESCE(activity_count,0)+1 WHERE id=?',(now,row['id']))
    c.execute('INSERT INTO activity_log(user_id,day,event_type,created) VALUES(?,?,?,?)',(row['id'],datetime.fromtimestamp(now,timezone.utc).strftime('%Y-%m-%d'),'login',now))
    push_notice(c,row['username'],'New login','Your account was signed in successfully.','security'); c.commit(); c.close()
    token=make_token(row['id'])
    return {'user':user_out(row),'token':token}


@app.post('/api/auth/logout')
def logout(req: Request):
    # Tokens are signed and expire automatically; logout is handled client-side.
    return {'ok':True}


@app.get('/api/auth/profile')
def get_profile(req: Request):
    u=current(req); return {'user':user_out(u)}


@app.put('/api/auth/profile')
def update_profile(req: Request, x: Profile):
    u=current(req); c=db()
    if c.execute('SELECT 1 FROM users WHERE lower(username)=lower(?) AND id<>?',(x.username,u['id'])).fetchone():
        c.close(); raise HTTPException(400,'That username is already in use.')
    old_username = u['username']
    new_username = x.username.strip()
    c.execute('UPDATE users SET full_name=?,username=?,phone=?,dob=?,profile_picture=?,last_active=? WHERE id=?',(x.full_name.strip(),new_username,x.phone.strip(),x.dob,x.profile_picture or '',int(time.time()),u['id']))
    c.execute('UPDATE notifications SET username=? WHERE username=?',(new_username,old_username))
    c.execute('UPDATE referrals SET reason=reason WHERE referred_id=?',(u['id'],))
    push_notice(c,x.username.strip(),'Profile saved','Your profile changes were saved successfully.','account'); c.commit()
    row=c.execute('SELECT * FROM users WHERE id=?',(u['id'],)).fetchone(); c.close(); return {'user':user_out(row)}


@app.put('/api/auth/password')
def change_password(req: Request, x: PasswordChange):
    u=current(req)
    if len(x.password) < 8: raise HTTPException(400,'Password must be at least 8 characters.')
    c=db(); c.execute('UPDATE users SET password=? WHERE id=?',(hash_password(x.password),u['id'])); push_notice(c,u['username'],'Password updated','Your password was updated successfully.','security'); c.commit(); c.close(); return {'ok':True}


@app.get('/api/notifications')
def notifications(req: Request):
    u=current(req); c=db(); rows=c.execute('SELECT * FROM notifications WHERE username=? ORDER BY id DESC LIMIT 200',(u['username'],)).fetchall(); c.close()
    return {'notifications':[{'id':r['id'],'title':r['title'],'text':r['text'],'type':r['type'],'time':datetime.fromtimestamp(r['created'],timezone.utc).strftime('%Y-%m-%d %H:%M UTC'),'read':bool(r['read']),'target_page':r['target_page'] or notification_target(r['type']),'target_ref':r['target_ref'] or ''} for r in rows]}


class NotificationRead(BaseModel):
    notification_id: int


@app.post('/api/notifications/read-one')
def notifications_read_one(req: Request, x: NotificationRead):
    u=current(req); c=db()
    row=c.execute('SELECT id FROM notifications WHERE id=? AND username=?',(x.notification_id,u['username'])).fetchone()
    if not row:
        c.close(); raise HTTPException(404,'Notification not found.')
    c.execute('UPDATE notifications SET read=1 WHERE id=? AND username=?',(x.notification_id,u['username']))
    c.commit(); c.close(); return {'ok':True}


@app.post('/api/notifications/read')
def notifications_read(req: Request):
    u=current(req); c=db(); c.execute('UPDATE notifications SET read=1 WHERE username=?',(u['username'],)); c.commit(); c.close(); return {'ok':True}


class Feedback(BaseModel):
    category: str = 'General'
    rating: int = 5
    message: str


@app.post('/api/feedback')
def submit_feedback(req: Request, x: Feedback):
    u=current(req)
    message=x.message.strip()
    if not message:
        raise HTTPException(400,'Please write your feedback before sending.')
    rating=max(1,min(5,int(x.rating)))
    category=(x.category or 'General').strip()[:40]
    c=db(); now=int(time.time())
    c.execute('INSERT INTO feedback(user_id,username,category,rating,message,created,status) VALUES(?,?,?,?,?,?,?)',
              (u['id'],u['username'],category,rating,message,now,'new'))
    record_activity(c,u['id'],'feedback_submit',rating*5)
    push_notice(c,u['username'],'Feedback received','Thanks — your feedback was saved to your PMA account.','feedback')
    c.commit(); c.close()
    return {'ok':True}


@app.get('/api/feedback')
def my_feedback(req: Request):
    u=current(req); c=db(); rows=c.execute('SELECT category,rating,message,created,status FROM feedback WHERE user_id=? ORDER BY id DESC LIMIT 20',(u['id'],)).fetchall(); c.close()
    return {'feedback':[{'category':r['category'],'rating':r['rating'],'message':r['message'],'time':datetime.fromtimestamp(r['created'],timezone.utc).strftime('%Y-%m-%d %H:%M UTC'),'status':r['status']} for r in rows]}


def prepare_market_setup(symbol, market, trigger_timeframe='15m'):
    trigger_timeframe = trigger_timeframe if trigger_timeframe in {'1m','5m','15m','1h','4h','1d'} else '15m'
    # Load the context candles concurrently. This keeps the API responsive without
    # changing which multi-timeframe frames are used by the scanner.
    frame_names = ('15m','30m','1h','4h','1d')
    with ThreadPoolExecutor(max_workers=5) as pool:
        jobs = {pool.submit(fetch, symbol, tf): tf for tf in frame_names}
        frames = {}
        for job in as_completed(jobs):
            frames[jobs[job]] = job.result()
    trigger_rows = fetch(symbol, trigger_timeframe)
    setup = analyze_setup(trigger_rows, frames, trigger_timeframe)
    trends = {tf: trend_info(frames[tf]) for tf in frames}
    validation = backtest(trigger_rows)
    psize = pip_size(symbol)
    reasons = setup.get('reasons', [])
    if setup['direction'] != 'NO TRADE':
        reasons = reasons or ['Automated confluence conditions are being monitored.']
    return {
        'symbol':symbol.upper(),'market':market,'direction':setup['direction'],'setup_strength':setup['score'],'status':setup['status'],
        'entry_zone':round(setup['entry_zone'],8) if setup['entry_zone'] is not None else None,
        'entry_note':'Use the zone as a planning area, not an exact guaranteed fill.',
        'stop_loss':round(setup['stop_loss'],8) if setup['stop_loss'] is not None else None,
        'take_profit_1':round(setup['take_profit_1'],8) if setup['take_profit_1'] is not None else None,
        'take_profit_2':round(setup['take_profit_2'],8) if setup['take_profit_2'] is not None else None,
        'risk_reward':'1:1 / 1:2 target framework' if setup['direction'] != 'NO TRADE' else '—',
        'zone_type':setup.get('next_zone_type'),'next_zone':round(setup['next_zone'],8) if setup['next_zone'] is not None else None,
        'distance_to_next_zone':round(setup['distance_to_next_zone'],8) if setup['distance_to_next_zone'] is not None else None,
        'pips_to_next_zone':round((setup['distance_to_next_zone']/psize),1) if setup['distance_to_next_zone'] is not None else None,
        'candles_to_next_zone':setup.get('candles_to_next_zone'),'estimated_minutes_to_next_zone':setup.get('estimated_minutes_to_next_zone'),
        'timeframe':trigger_timeframe,'atr_15m':round(setup['atr'],8),'last':round(setup['last'],8),'support':round(setup['support'],8),'resistance':round(setup['resistance'],8),
        'rsi_15m':setup['rsi'],'structure':setup['structure'],'trigger_price':round(setup['trigger_price'],8) if setup['trigger_price'] is not None else None,
        'next_signal_status':'TRIGGERED' if setup['score'] >= 65 else 'WAITING FOR CONFIRMATION',
        'next_signal_trigger':setup['trigger_text'],'reasons':reasons,
        'trends':{tf:trends[tf]['trend'] for tf in trends},'trend_detail':trends,'trend_alignment':f"{sum(1 for v in trends.values() if v['trend']==setup['trend'])}/5",
        'validation':validation,'data_source':'Verified market chart feed','updated_at':utc_iso(),'method':'PMA confluence engine: trend + RSI + structure + multi-timeframe alignment + ATR zone projection'
    }


@app.get('/api/health')
def health():
    return {'ok':True,'service':'Pips Master Academy API','market_data':'Yahoo Finance chart feed','timeframes':['1m','5m','15m','1h','4h','1d'],'updated_at':utc_iso()}


@app.get('/api/market-data/test')
def market_data_test(symbol: str='EURUSD', timeframe: str='15m'):
    if timeframe not in {'1m','5m','15m','1h','4h','1d'}:
        raise HTTPException(400,'Unsupported timeframe. Use 1m, 5m, 15m, 1h, 4h or 1d.')
    try:
        rows=fetch(symbol,timeframe)
        return {'ok':True,'symbol':norm_symbol(symbol),'timeframe':timeframe,'candles':len(rows),'last_close':rows[-1]['close'],'updated_at':utc_iso()}
    except Exception as ex:
        raise HTTPException(503,f'Market data test failed: {ex}')


@app.get('/api/signals/scan')
def scan(market: str='Forex', symbols: str='EURUSD', timeframe: str='15m'):
    requested=[x.strip().upper() for x in symbols.split(',') if x.strip()][:20]
    opportunities=[]; errors=[]
    for sym in requested:
        try:
            opportunities.append(prepare_market_setup(sym,market,timeframe))
        except Exception as ex:
            errors.append({'symbol':sym,'error':str(ex)})
    # Prioritise actual ready setups, then the closest next-zone estimate.
    opportunities.sort(key=lambda x:(0 if x['direction']!='NO TRADE' else 1, x['estimated_minutes_to_next_zone'] if x['estimated_minutes_to_next_zone'] is not None else 10**9, -(x['setup_strength'] or 0)))
    return {
        'closest':opportunities[0] if opportunities else None,
        'timeframe': timeframe if timeframe in {'1m','5m','15m','1h','4h','1d'} else '15m',
        'opportunities':opportunities,'errors':errors,'market':market,'symbols':requested,
        'message':'Verified candle data loaded.' if opportunities else 'No verified candle data was returned; no signal is being invented.',
        'updated_at':utc_iso()
    }


@app.get('/api/signals/candles')
def candles(symbol: str='EURUSD', timeframe: str='15m'):
    try:
        return {'symbol':symbol.upper(),'timeframe':timeframe,'candles':fetch(symbol,timeframe)[-300:],'updated_at':utc_iso()}
    except Exception as ex:
        raise HTTPException(503,f'Live candle feed unavailable: {ex}')


@app.get('/api/day-trade/plan')
def day_trade_plan(market: str='Forex', symbols: str='EURUSD,GBPUSD,USDJPY,GBPJPY,XAUUSD,BTCUSD', timeframe: str='15m'):
    requested=[x.strip().upper() for x in symbols.split(',') if x.strip()][:15]
    results=[]; errors=[]
    for sym in requested:
        try:
            setup=prepare_market_setup(sym,market,timeframe)
            # Day-trade focus: user-selected trigger timeframe with 1h/4h context.
            context_ok=setup['trends'].get('1h')==setup['trends'].get('4h') and setup['direction']!='NO TRADE'
            setup['day_trade_state']='READY' if context_ok and setup['setup_strength']>=60 else 'WAITING'
            setup['day_trade_reason']=f"{timeframe} trigger is aligned with 1h and 4h context." if context_ok else 'Wait for cleaner 1h/4h confirmation.'
            results.append(setup)
        except Exception as ex:
            errors.append({'symbol':sym,'error':str(ex)})
    results.sort(key=lambda x:(0 if x['day_trade_state']=='READY' else 1,-(x['setup_strength'] or 0)))
    return {'date':datetime.now(timezone.utc).strftime('%Y-%m-%d'),'market':market,'setups':results,'errors':errors,'updated_at':utc_iso(),'note':'Day-trade projections are estimates based on verified candle data; future price movement is not guaranteed.'}


@app.get('/api/referrals')
def referrals(req: Request, month: str=''):
    u=current(req); c=db(); qualify_referrals(c)
    mk=month or month_key()
    rows=c.execute('SELECT * FROM referrals WHERE referrer_id=? ORDER BY id DESC',(u['id'],)).fetchall()
    qualified=[r for r in rows if r['status']=='qualified']
    month_rows=[r for r in qualified if r['challenge_month']==mk]
    pending=[r for r in rows if r['status']=='pending']
    total=len(qualified); month_count=len(month_rows); pending_count=len(pending)
    all_leaderboard=c.execute('''SELECT u.username,u.full_name,u.profile_picture,COUNT(r.id) AS qualified
        FROM referrals r JOIN users u ON u.id=r.referrer_id
        WHERE r.challenge_month=? AND r.status='qualified'
        GROUP BY r.referrer_id ORDER BY qualified DESC, MIN(r.qualified_at) ASC''',(mk,)).fetchall()
    rank=None
    for idx,row in enumerate(all_leaderboard):
        if row['username']==u['username']:
            rank=idx+1
            break
    leaderboard=all_leaderboard[:10]
    c.commit(); c.close()
    referral_rank = referral_rank_for_count(total)
    return {
        'month':mk,'qualified_total':total,'month_qualified':month_count,'pending':pending_count,
        'position':rank if leaderboard else None,
        **referral_rank,
        'monthly_leaderboard':[{'rank':i+1,'username':r['username'],'full_name':r['full_name'],'profile_picture':r['profile_picture'] or '','qualified':r['qualified']} for i,r in enumerate(leaderboard)],
        'history':[{'challenge_month':r['challenge_month'],'status':r['status'],'created':r['created'],'qualified_at':r['qualified_at']} for r in rows[:100]],
        'qualification_policy':f'Referrals are recorded immediately as pending and reviewed automatically after about {QUALIFICATION_HOURS} hours plus basic account activity.',
        'rank_policy':'Qualified referrals contribute XP to your permanent academy rank and also increase your separate referral rank.'
    }


@app.get('/api/leaderboard')
def leaderboard(req: Request, month: str=''):
    u=current(req); c=db(); qualify_referrals(c); mk=month or month_key()
    rows=c.execute('''SELECT u.username,u.full_name,u.profile_picture,u.xp,COUNT(r.id) AS qualified
        FROM users u LEFT JOIN referrals r ON r.referrer_id=u.id AND r.challenge_month=? AND r.status='qualified'
        GROUP BY u.id ORDER BY u.xp DESC, qualified DESC LIMIT 100''',(mk,)).fetchall()
    out=[]
    for i,r in enumerate(rows):
        rank=rank_for_xp(r['xp'] or 0)
        out.append({'rank':i+1,'username':r['username'],'full_name':r['full_name'],'profile_picture':r['profile_picture'] or '', 'xp':r['xp'] or 0, 'academy_rank':rank['rank'],'monthly_referrals':r['qualified'] or 0})
    c.close(); return {'month':mk,'leaderboard':out,'factors':['qualified referrals','completed tasks','learning progress','long-term activity and consistency'],'note':'Academy rank is permanent XP progress; the monthly referral challenge is separate.'}


@app.get('/api/progress')
def progress(req: Request):
    u=current(req); c=db(); qualify_referrals(c)
    user=c.execute('SELECT * FROM users WHERE id=?',(u['id'],)).fetchone()
    completed_lessons=c.execute('SELECT lesson_id FROM lesson_progress WHERE user_id=?',(u['id'],)).fetchall()
    completed_tasks=c.execute('SELECT task_id FROM task_progress WHERE user_id=?',(u['id'],)).fetchall()
    today=datetime.now(timezone.utc).strftime('%Y-%m-%d')
    completed_daily=c.execute('SELECT task_id FROM daily_task_progress WHERE user_id=? AND day=?',(u['id'],today)).fetchall()
    lifetime_refs=c.execute("SELECT COUNT(*) AS n FROM referrals WHERE referrer_id=? AND status='qualified'",(u['id'],)).fetchone()['n']
    monthly_refs=c.execute("SELECT COUNT(*) AS n FROM referrals WHERE referrer_id=? AND status='qualified' AND challenge_month=?",(u['id'],month_key())).fetchone()['n']
    streak=daily_streak(c,u['id'])
    rank=rank_for_xp(user['xp'] or 0)
    learning_pct=round(len(completed_lessons)/len(LESSONS)*100,1)
    tasks_pct=round(len(completed_tasks)/len(TASKS)*100,1)
    referral_pct=round(min(100,lifetime_refs/250*100),1)
    consistency_pct=round(min(100,streak/30*100),1)
    overall=round(learning_pct*0.45+tasks_pct*0.25+referral_pct*0.20+consistency_pct*0.10,1)
    referral_rank = referral_rank_for_count(lifetime_refs)
    c.close()
    return {
        'xp':user['xp'] or 0,**rank,'overall_progress':overall,'learning_progress':learning_pct,'tasks_progress':tasks_pct,
        'referral_progress':referral_pct,'consistency_progress':consistency_pct,'streak':streak,
        'completed_lessons':len(completed_lessons),'total_lessons':len(LESSONS),'completed_tasks':len(completed_tasks),'total_tasks':len(TASKS),'completed_daily_tasks':len(completed_daily),'total_daily_tasks':len(DAILY_TASKS),
        'qualified_referrals_lifetime':lifetime_refs,'qualified_referrals_this_month':monthly_refs,
        'levels_are_long_term':True,'rank_factors':['qualified referrals','completed tasks','learning progress','overall progress/consistency'],
        'lessons':LESSONS,'tasks':TASKS,'daily_tasks':DAILY_TASKS,'completed_daily_task_ids':[r['task_id'] for r in completed_daily],
    }


@app.post('/api/progress/lesson')
def complete_lesson(req: Request, x: Completion):
    u=current(req); lesson=next((i for i in LESSONS if i['id']==x.item_id),None)
    if not lesson: raise HTTPException(404,'Lesson not found.')
    c=db(); exists=c.execute('SELECT 1 FROM lesson_progress WHERE user_id=? AND lesson_id=?',(u['id'],x.item_id)).fetchone()
    if not exists:
        c.execute('INSERT INTO lesson_progress(user_id,lesson_id,completed_at) VALUES(?,?,?)',(u['id'],x.item_id,int(time.time())))
        record_activity(c,u['id'],'lesson_complete',lesson['xp'])
        push_notice(c,u['username'],'Lesson completed',f"You completed: {lesson['title']}.",'learning')
    c.commit(); c.close(); return {'ok':True,'new_completion':not bool(exists),'item':lesson}


@app.post('/api/progress/daily-task')
def complete_daily_task(req: Request, x: Completion):
    u=current(req); task=next((i for i in DAILY_TASKS if i['id']==x.item_id),None)
    if not task: raise HTTPException(404,'Daily task not found.')
    day=datetime.now(timezone.utc).strftime('%Y-%m-%d')
    c=db(); exists=c.execute('SELECT 1 FROM daily_task_progress WHERE user_id=? AND task_id=? AND day=?',(u['id'],x.item_id,day)).fetchone()
    if not exists:
        c.execute('INSERT INTO daily_task_progress(user_id,task_id,day,completed_at) VALUES(?,?,?,?)',(u['id'],x.item_id,day,int(time.time())))
        record_activity(c,u['id'],'daily_task_complete',task['xp'])
        push_notice(c,u['username'],'Daily task completed',f"You completed: {task['title']}.",'task')
    c.commit(); c.close(); return {'ok':True,'new_completion':not bool(exists),'item':task}


@app.post('/api/progress/task')
def complete_task(req: Request, x: Completion):
    u=current(req); task=next((i for i in TASKS if i['id']==x.item_id),None)
    if not task: raise HTTPException(404,'Task not found.')
    c=db(); exists=c.execute('SELECT 1 FROM task_progress WHERE user_id=? AND task_id=?',(u['id'],x.item_id)).fetchone()
    if not exists:
        c.execute('INSERT INTO task_progress(user_id,task_id,completed_at) VALUES(?,?,?)',(u['id'],x.item_id,int(time.time())))
        record_activity(c,u['id'],'task_complete',task['xp'])
        push_notice(c,u['username'],'Task completed',f"You completed: {task['title']}.",'task')
    c.commit(); c.close(); return {'ok':True,'new_completion':not bool(exists),'item':task}


@app.get('/api/community/messages')
def get_messages(req: Request):
    current(req); c=db(); rows=c.execute('SELECT * FROM messages ORDER BY id ASC LIMIT 300').fetchall(); is_locked=get_locked(c); c.close()
    return {'locked':is_locked,'messages':[{'username':r['username'],'pma_id':r['pma_id'],'text':r['text'],'media_data':r['media_data'],'media_type':r['media_type'],'time':datetime.fromtimestamp(r['created'],timezone.utc).strftime('%H:%M')} for r in rows]}


@app.post('/api/community/messages')
def post_message(req: Request, x: Msg):
    u=current(req); c=db(); is_locked=get_locked(c)
    if is_locked and u['role']!='admin': c.close(); raise HTTPException(403,'Community chat is locked by the administrator.')
    if not x.text.strip() and not x.media_data: c.close(); raise HTTPException(400,'Message cannot be empty.')
    now=int(time.time())
    c.execute('INSERT INTO messages(username,pma_id,text,media_data,media_type,created) VALUES(?,?,?,?,?,?)',(u['username'],u['pma_id'],x.text,x.media_data,x.media_type,now))
    record_activity(c,u['id'],'community_post',10)
    users=c.execute('SELECT username FROM users WHERE username<>?',(u['username'],)).fetchall()
    for r in users: push_notice(c,r['username'],'New community message',f"{u['username']} posted in the community.",'community')
    c.commit(); c.close(); return {'ok':True}


@app.post('/api/admin/community/toggle')
def toggle(req: Request):
    u=current(req)
    if u['role']!='admin': raise HTTPException(403,'Admin access required.')
    c=db(); new_state=not get_locked(c); set_locked(c,new_state)
    users=c.execute('SELECT username FROM users').fetchall()
    for r in users: push_notice(c,r['username'],'Community status','The community is now '+('locked.' if new_state else 'open.'),'community')
    c.commit(); c.close(); return {'locked':new_state}


@app.get('/api/admin/status')
def admin_status(req: Request):
    u=current(req)
    if u['role']!='admin':
        raise HTTPException(403,'Admin access required.')
    c=db(); locked=get_locked(c); c.close()
    return {'is_admin':True,'username':u['username'],'email':u['email'],'community_locked':locked}


@app.get('/api/admin/stats')
def admin_stats(req: Request):
    u=current(req)
    if u['role']!='admin': raise HTTPException(403,'Admin access required.')
    c=db(); qualify_referrals(c)
    total=c.execute('SELECT COUNT(*) n FROM users').fetchone()['n']
    active=c.execute('SELECT COUNT(*) n FROM users WHERE last_active>=?',(int(time.time())-7*86400,)).fetchone()['n']
    refs=c.execute("SELECT COUNT(*) n FROM referrals WHERE status='qualified'").fetchone()['n']
    pending=c.execute("SELECT COUNT(*) n FROM referrals WHERE status='pending'").fetchone()['n']
    locked=get_locked(c)
    feedback_count=c.execute("SELECT COUNT(*) n FROM feedback WHERE status='new'").fetchone()['n']
    c.commit(); c.close()
    return {'total_users':total,'active_7d':active,'qualified_referrals':refs,'pending_referrals':pending,'feedback_new':feedback_count,'community_locked':locked,'rank_stages':['Beginner','Amateur','Professional','Expert','Master','Pips Master']}
