from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
import base64, hashlib, hmac, json
import os, random, secrets, sqlite3, time, threading

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
import bcrypt
from pydantic import BaseModel, EmailStr

from .market_data import fetch, analyze_setup, pip_size, backtest, trend_info, utc_iso, norm_symbol, _tv_scan, _tv_scan_many, _tv_setup, yahoo_verified_snapshots, DEFAULT_FOREX_WATCHLIST, optimize_strict_scanner

ADMIN_EMAIL = os.getenv('PMA_ADMIN_EMAIL', 'ugoloevidence81@gmail.com').lower()
ADMIN_USERNAME = os.getenv('PMA_ADMIN_USERNAME', 'PipsMaster')
ADMIN_FULL_NAME = os.getenv('PMA_ADMIN_FULL_NAME', 'Ugolo Evidence')
ADMIN_PASSWORD = os.getenv('PMA_ADMIN_PASSWORD', 'my62020')
TOKEN_SECRET = os.getenv('PMA_SECRET_KEY', '') or 'pma-dev-secret-change-this-in-render'
TOKEN_TTL = int(os.getenv('PMA_TOKEN_TTL', str(60*60*24*30)))
VAPID_PUBLIC_KEY = os.getenv('PMA_VAPID_PUBLIC_KEY') or os.getenv('VAPID_PUBLIC_KEY') or 'BDuFoIUEKTsHTSl5SXZEIWNaYK317R0F5gnOLgD0iqXHXCsP49bo7mLfIDFG54DPvpEOGO4Qo4HFudz4iRnGCBI'
VAPID_PRIVATE_KEY = os.getenv('PMA_VAPID_PRIVATE_KEY') or os.getenv('VAPID_PRIVATE_KEY', '')
VAPID_SUBJECT = os.getenv('PMA_VAPID_SUBJECT') or os.getenv('VAPID_SUBJECT') or 'mailto:admin@example.com'
QUALIFICATION_HOURS = int(os.getenv('PMA_REFERRAL_QUALIFICATION_HOURS', '48'))
DB = os.getenv('PMA_DB', 'pma.db')
sessions = {}
_DB_INIT_LOCK = threading.Lock()
_DB_READY = False

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
    reply_to_id: int = 0
    temporary: bool = False

class PrivateMessage(BaseModel):
    text: str

class MessageRequestModel(BaseModel):
    user_id: int

class RequestDecision(BaseModel):
    action: str

class CommunityMessageAction(BaseModel):
    text: str = ''

class CommunityReaction(BaseModel):
    emoji: str

class CommunityRequest(BaseModel):
    action: str = 'request'

class CommunityModeration(BaseModel):
    user_id: int
    action: str
    note: str = ''

class CommunitySettings(BaseModel):
    name: str = 'PMA Community'
    bio: str = 'A place for PMA members to learn, share and discuss the markets.'
    profile_picture: str = ''
    disappearing_seconds: int = 86400
    temporary_enabled: bool = False
    temporary_seconds: int = 86400


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
    global _DB_READY
    # Render can receive overlapping API requests. Use WAL + a longer busy timeout
    # so normal concurrent reads/writes do not fail with "database is locked".
    c=sqlite3.connect(DB,timeout=30,check_same_thread=False)
    c.row_factory=sqlite3.Row
    c.execute('PRAGMA busy_timeout=30000')
    if not _DB_READY:
        with _DB_INIT_LOCK:
            if not _DB_READY:
                c.execute('PRAGMA journal_mode=WAL')
                c.execute('PRAGMA synchronous=NORMAL')
                c.executescript('''
                CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE, full_name TEXT, email TEXT UNIQUE, password TEXT, pma_id TEXT UNIQUE, referral_code TEXT UNIQUE, referrer TEXT, role TEXT DEFAULT 'user', phone TEXT DEFAULT '', dob TEXT DEFAULT '', profile_picture TEXT DEFAULT '', created INTEGER, xp INTEGER DEFAULT 0, last_active INTEGER DEFAULT 0, login_count INTEGER DEFAULT 0, activity_count INTEGER DEFAULT 0);
                CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY, username TEXT, pma_id TEXT, text TEXT, media_data TEXT DEFAULT '', media_type TEXT DEFAULT '', reply_to_id INTEGER DEFAULT 0, edited INTEGER DEFAULT 0, created INTEGER, temporary INTEGER DEFAULT 0, expires_at INTEGER DEFAULT 0, deleted INTEGER DEFAULT 0, deleted_by TEXT DEFAULT '', deleted_at INTEGER DEFAULT 0);
                CREATE TABLE IF NOT EXISTS community_members(user_id INTEGER PRIMARY KEY, status TEXT DEFAULT 'pending', role TEXT DEFAULT 'member', warning_count INTEGER DEFAULT 0, suspended_until INTEGER DEFAULT 0, joined_at INTEGER DEFAULT 0, updated_at INTEGER DEFAULT 0, note TEXT DEFAULT '');
                CREATE TABLE IF NOT EXISTS community_settings(id INTEGER PRIMARY KEY CHECK(id=1), name TEXT DEFAULT 'PMA Community', bio TEXT DEFAULT 'A place for PMA members to learn, share and discuss the markets.', profile_picture TEXT DEFAULT '', disappearing_seconds INTEGER DEFAULT 86400, temporary_enabled INTEGER DEFAULT 0, temporary_seconds INTEGER DEFAULT 86400, updated_at INTEGER DEFAULT 0);
                CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY, username TEXT, title TEXT, text TEXT, type TEXT DEFAULT 'info', created INTEGER, read INTEGER DEFAULT 0, target_page TEXT DEFAULT '', target_ref TEXT DEFAULT ''); CREATE TABLE IF NOT EXISTS push_subscriptions(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, endpoint TEXT UNIQUE NOT NULL, p256dh TEXT NOT NULL, auth TEXT NOT NULL, created INTEGER DEFAULT 0, updated INTEGER DEFAULT 0);
                CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT);
                CREATE TABLE IF NOT EXISTS referrals(id INTEGER PRIMARY KEY, referrer_id INTEGER NOT NULL, referred_id INTEGER NOT NULL, challenge_month TEXT NOT NULL, status TEXT DEFAULT 'pending', created INTEGER NOT NULL, qualification_due INTEGER NOT NULL, qualified_at INTEGER, flagged INTEGER DEFAULT 0, reason TEXT DEFAULT '', UNIQUE(referrer_id,referred_id));
                CREATE TABLE IF NOT EXISTS lesson_progress(user_id INTEGER NOT NULL, lesson_id TEXT NOT NULL, completed_at INTEGER NOT NULL, PRIMARY KEY(user_id,lesson_id));
                CREATE TABLE IF NOT EXISTS task_progress(user_id INTEGER NOT NULL, task_id TEXT NOT NULL, completed_at INTEGER NOT NULL, PRIMARY KEY(user_id,task_id));
                CREATE TABLE IF NOT EXISTS daily_task_progress(user_id INTEGER NOT NULL, task_id TEXT NOT NULL, day TEXT NOT NULL, completed_at INTEGER NOT NULL, PRIMARY KEY(user_id,task_id,day));
                CREATE TABLE IF NOT EXISTS feedback(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, username TEXT NOT NULL, category TEXT NOT NULL, rating INTEGER NOT NULL, message TEXT NOT NULL, created INTEGER NOT NULL, status TEXT DEFAULT 'new');
                CREATE TABLE IF NOT EXISTS activity_log(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, day TEXT NOT NULL, event_type TEXT NOT NULL, created INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS trade_history(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, symbol TEXT NOT NULL, market TEXT NOT NULL, timeframe TEXT NOT NULL, direction TEXT NOT NULL, entry REAL, stop_loss REAL, take_profit REAL, outcome TEXT NOT NULL, reason TEXT DEFAULT '', opened_at INTEGER NOT NULL, closed_at INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS signal_history(id INTEGER PRIMARY KEY, user_id INTEGER, symbol TEXT NOT NULL, market TEXT NOT NULL, timeframe TEXT NOT NULL, direction TEXT NOT NULL, status TEXT NOT NULL, setup_strength REAL, entry REAL, stop_loss REAL, take_profit REAL, reason TEXT DEFAULT '', event_key TEXT UNIQUE, created INTEGER NOT NULL);
                ''')
                message_existing={r['name'] for r in c.execute("PRAGMA table_info(messages)").fetchall()}
                if 'reply_to_id' not in message_existing: c.execute("ALTER TABLE messages ADD COLUMN reply_to_id INTEGER DEFAULT 0")
                if 'edited' not in message_existing: c.execute("ALTER TABLE messages ADD COLUMN edited INTEGER DEFAULT 0")
                for name,ddl in {'temporary':'ALTER TABLE messages ADD COLUMN temporary INTEGER DEFAULT 0','expires_at':'ALTER TABLE messages ADD COLUMN expires_at INTEGER DEFAULT 0','deleted':'ALTER TABLE messages ADD COLUMN deleted INTEGER DEFAULT 0','deleted_by':'ALTER TABLE messages ADD COLUMN deleted_by TEXT DEFAULT ''','deleted_at':'ALTER TABLE messages ADD COLUMN deleted_at INTEGER DEFAULT 0'}.items():
                    if name not in message_existing: c.execute(ddl)
                community_settings_existing={r['name'] for r in c.execute("PRAGMA table_info(community_settings)").fetchall()}
                if 'bio' not in community_settings_existing: c.execute("ALTER TABLE community_settings ADD COLUMN bio TEXT DEFAULT 'A place for PMA members to learn, share and discuss the markets.'")
                if 'temporary_enabled' not in community_settings_existing: c.execute("ALTER TABLE community_settings ADD COLUMN temporary_enabled INTEGER DEFAULT 0")
                if 'temporary_seconds' not in community_settings_existing: c.execute("ALTER TABLE community_settings ADD COLUMN temporary_seconds INTEGER DEFAULT 86400")
                notif_existing={r['name'] for r in c.execute("PRAGMA table_info(notifications)").fetchall()}
                if 'target_page' not in notif_existing: c.execute("ALTER TABLE notifications ADD COLUMN target_page TEXT DEFAULT ''")
                if 'target_ref' not in notif_existing: c.execute("ALTER TABLE notifications ADD COLUMN target_ref TEXT DEFAULT ''")
                existing={r['name'] for r in c.execute("PRAGMA table_info(users)").fetchall()}
                for name,ddl in {'xp':'ALTER TABLE users ADD COLUMN xp INTEGER DEFAULT 0','last_active':'ALTER TABLE users ADD COLUMN last_active INTEGER DEFAULT 0','login_count':'ALTER TABLE users ADD COLUMN login_count INTEGER DEFAULT 0','activity_count':'ALTER TABLE users ADD COLUMN activity_count INTEGER DEFAULT 0'}.items():
                    if name not in existing: c.execute(ddl)
                now=int(time.time())
                c.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('history_retention_enabled','1')")
                c.execute("INSERT OR IGNORE INTO community_settings(id,name,bio,profile_picture,disappearing_seconds,temporary_enabled,temporary_seconds,updated_at) VALUES(1,'PMA Community','A place for PMA members to learn, share and discuss the markets.','',86400,0,86400,?)",(now,))
                c.execute("UPDATE community_settings SET disappearing_seconds=86400, temporary_seconds=86400 WHERE id=1")
                c.execute("INSERT OR IGNORE INTO community_members(user_id,status,role,joined_at,updated_at) SELECT id,'approved',CASE WHEN role='admin' THEN 'admin' ELSE 'member' END,?,? FROM users",(now,now))
                c.execute('DELETE FROM notifications WHERE created < ?',(now-14*86400,))
                c.execute('CREATE INDEX IF NOT EXISTS idx_notifications_user_created ON notifications(username,created DESC)')
                c.execute('CREATE INDEX IF NOT EXISTS idx_trade_history_user_closed ON trade_history(user_id,closed_at DESC)')
                c.execute('CREATE INDEX IF NOT EXISTS idx_referrals_referrer_status_month ON referrals(referrer_id,status,challenge_month)')
                c.execute('CREATE INDEX IF NOT EXISTS idx_feedback_created ON feedback(created DESC)')
                c.execute('''CREATE TABLE IF NOT EXISTS message_requests(id INTEGER PRIMARY KEY, sender_id INTEGER NOT NULL, receiver_id INTEGER NOT NULL, status TEXT DEFAULT 'pending', created INTEGER NOT NULL, responded INTEGER DEFAULT 0, UNIQUE(sender_id,receiver_id))''')
                c.execute('''CREATE TABLE IF NOT EXISTS private_conversations(id INTEGER PRIMARY KEY, user_a INTEGER NOT NULL, user_b INTEGER NOT NULL, created INTEGER NOT NULL, last_message INTEGER DEFAULT 0, UNIQUE(user_a,user_b))''')
                c.execute('''CREATE TABLE IF NOT EXISTS private_messages(id INTEGER PRIMARY KEY, conversation_id INTEGER NOT NULL, sender_id INTEGER NOT NULL, receiver_id INTEGER NOT NULL, text TEXT NOT NULL, created INTEGER NOT NULL, edited INTEGER DEFAULT 0, deleted INTEGER DEFAULT 0, deleted_by TEXT DEFAULT '')''')
                c.execute('''CREATE TABLE IF NOT EXISTS message_reactions(id INTEGER PRIMARY KEY, message_id INTEGER NOT NULL, user_id INTEGER NOT NULL, emoji TEXT NOT NULL, created INTEGER NOT NULL, UNIQUE(message_id,user_id,emoji))''')
                c.execute('''CREATE TABLE IF NOT EXISTS message_views(id INTEGER PRIMARY KEY, message_id INTEGER NOT NULL, user_id INTEGER NOT NULL, viewed INTEGER NOT NULL, UNIQUE(message_id,user_id))''')
                c.execute('CREATE INDEX IF NOT EXISTS idx_messages_created ON messages(created DESC)')
                c.execute('CREATE INDEX IF NOT EXISTS idx_signal_history_user_created ON signal_history(user_id,created DESC)')
                if ADMIN_PASSWORD:
                    ar=c.execute('SELECT * FROM users WHERE lower(email)=lower(?)',(ADMIN_EMAIL,)).fetchone()
                    if ar:
                        c.execute('UPDATE users SET username=?,full_name=?,role=? WHERE id=?',(ADMIN_USERNAME,ADMIN_FULL_NAME,'admin',ar['id']))
                        # One-time credential migration for this rebuild. After the marker is set, user-changed passwords are preserved.
                        if c.execute("SELECT 1 FROM settings WHERE key='admin_password_migration_v3'").fetchone() is None:
                            c.execute('UPDATE users SET password=? WHERE id=?',(hash_password(ADMIN_PASSWORD),ar['id']))
                            c.execute("INSERT INTO settings(key,value) VALUES('admin_password_migration_v3','1')")
                    else:
                        c.execute('INSERT INTO users(username,full_name,email,password,pma_id,referral_code,referrer,role,created,xp,last_active,login_count,activity_count) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(ADMIN_USERNAME,ADMIN_FULL_NAME,ADMIN_EMAIL,hash_password(ADMIN_PASSWORD),'PMA-ADMIN001','PMAADMIN001','', 'admin',now,0,now,0,1))
                        c.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('admin_password_migration_v3','1')")
                c.commit(); _DB_READY=True
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


def _send_native_push_async(subscriptions, payload):
    """Send browser push outside the caller's SQLite transaction."""
    if not webpush or not VAPID_PRIVATE_KEY or not subscriptions:
        return
    for sub in subscriptions:
        try:
            webpush(
                subscription_info={
                    'endpoint': sub['endpoint'],
                    'keys': {'p256dh': sub['p256dh'], 'auth': sub['auth']}
                },
                data=payload,
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims={'sub': VAPID_SUBJECT}
            )
        except Exception:
            # A failed/expired browser subscription must never break login or
            # another normal database operation.
            continue


def push_notice(c, username, title, text, typ='info', target_page=''):
    page = target_page or notification_target(typ)
    c.execute(
        'INSERT INTO notifications(username,title,text,type,created,read,target_page,target_ref) '
        'VALUES(?,?,?,?,?,?,?,?)',
        (username, title, text, typ, int(time.time()), 0, page, '')
    )

    # IMPORTANT: do not perform an external Web Push HTTP request while this
    # SQLite connection has an open write transaction. Network latency can hold
    # SQLite's write lock long enough to cause "database is locked".
    if webpush and VAPID_PRIVATE_KEY:
        row = c.execute(
            'SELECT id FROM users WHERE username=?', (username,)
        ).fetchone()
        if row:
            subs = c.execute(
                'SELECT endpoint,p256dh,auth FROM push_subscriptions WHERE user_id=?',
                (row['id'],)
            ).fetchall()
            subscriptions = [
                {
                    'endpoint': s['endpoint'],
                    'p256dh': s['p256dh'],
                    'auth': s['auth']
                }
                for s in subs
            ]
            if subscriptions:
                payload = json.dumps({
                    'title': title,
                    'body': text,
                    'type': typ,
                    'target_page': page
                })
                threading.Thread(
                    target=_send_native_push_async,
                    args=(subscriptions, payload),
                    daemon=True
                ).start()


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
    c.execute('INSERT OR REPLACE INTO community_members(user_id,status,role,joined_at,updated_at,note) VALUES(?,?,?,?,?,?)',(uid,'approved' if role=='admin' else 'pending','admin' if role=='admin' else 'member',now if role=='admin' else 0,now,'Approved automatically for administrator' if role=='admin' else 'Awaiting administrator approval'))
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
    email=str(x.email).strip().lower()
    # Retry SQLite busy errors and keep external push work out of the login transaction.
    # The admin account is deterministically seeded during DB initialization.
    last_error=None
    for attempt in range(5):
        c=None
        try:
            c=db(); row=c.execute('SELECT * FROM users WHERE lower(email)=lower(?)',(email,)).fetchone()
            if not row or not verify_password(x.password,row['password']):
                c.close(); raise HTTPException(401,'Email or password is incorrect.')
            now=int(time.time())
            c.execute('UPDATE users SET last_active=?,login_count=COALESCE(login_count,0)+1,activity_count=COALESCE(activity_count,0)+1 WHERE id=?',(now,row['id']))
            c.execute('INSERT INTO activity_log(user_id,day,event_type,created) VALUES(?,?,?,?)',(row['id'],datetime.fromtimestamp(now,timezone.utc).strftime('%Y-%m-%d'),'login',now))
            c.commit()
            c.close()
            token=make_token(row['id'])
            return {'user':user_out(row),'token':token}
        except HTTPException:
            raise
        except sqlite3.OperationalError as ex:
            last_error=ex
            try:
                if c: c.rollback(); c.close()
            except Exception: pass
            if 'locked' not in str(ex).lower() or attempt==4:
                raise HTTPException(503,'Login service is temporarily busy. Please retry in a moment.')
            time.sleep(0.25*(attempt+1))
        except Exception as ex:
            try:
                if c: c.close()
            except Exception: pass
            raise HTTPException(500,'Login service could not complete the request.')
    raise HTTPException(503,f'Login service is temporarily busy: {last_error}')


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


class PushSubscription(BaseModel):
    endpoint: str
    keys: dict

@app.get('/api/push/public-key')
def push_public_key():
    return {'public_key': VAPID_PUBLIC_KEY}

@app.post('/api/push/subscribe')
def push_subscribe(req: Request, x: PushSubscription):
    u=current(req)
    keys=x.keys or {}
    if not x.endpoint or not keys.get('p256dh') or not keys.get('auth'):
        raise HTTPException(400,'Invalid push subscription.')
    c=db()
    now=int(time.time())
    c.execute('INSERT INTO push_subscriptions(user_id,endpoint,p256dh,auth,created,updated) VALUES(?,?,?,?,?,?) '
              'ON CONFLICT(endpoint) DO UPDATE SET user_id=excluded.user_id,p256dh=excluded.p256dh,auth=excluded.auth,updated=excluded.updated',
              (u['id'],x.endpoint,keys['p256dh'],keys['auth'],now,now))
    c.commit(); c.close()
    return {'ok':True}

@app.delete('/api/push/subscribe')
def push_unsubscribe(req: Request, x: PushSubscription):
    u=current(req)
    c=db(); c.execute('DELETE FROM push_subscriptions WHERE user_id=? AND endpoint=?',(u['id'],x.endpoint)); c.commit(); c.close()
    return {'ok':True}

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

@app.delete('/api/notifications/history')
def notifications_delete_history(req: Request):
    u=current(req); c=db(); c.execute('DELETE FROM notifications WHERE username=?',(u['username'],)); c.commit(); c.close(); return {'ok':True}


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


def prepare_market_setup(symbol, market, trigger_timeframe='15m', tv_snaps=None):
    trigger_timeframe = trigger_timeframe if trigger_timeframe in {'1m','5m','15m','1h','4h','1d'} else '15m'
    # Primary live source: one TradingView scanner request carries all MTF snapshots.
    # This removes the old six-request Yahoo bottleneck that caused long loading states.
    try:
        tfs = ['15m','30m','1h','4h','1d']
        if trigger_timeframe not in tfs:
            tfs.append(trigger_timeframe)
        snaps = tv_snaps if tv_snaps is not None else _tv_scan(symbol, market, tfs)
        setup = _tv_setup(symbol, market, trigger_timeframe, snaps)
        psize = pip_size(symbol)
        trends = {tf:_snapshot_trend_safe(snaps[tf]) for tf in snaps}
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
            'distance_to_entry_zone':round(abs(setup['entry_zone']-setup['last']),8) if setup['entry_zone'] is not None else None,
            'pips_to_entry_zone':round(abs(setup['entry_zone']-setup['last'])/psize,1) if setup['entry_zone'] is not None else None,
            'pips_to_next_zone':round((setup['distance_to_next_zone']/psize),1) if setup['distance_to_next_zone'] is not None else None,
            'candles_to_next_zone':setup.get('candles_to_next_zone'),'estimated_minutes_to_next_zone':setup.get('estimated_minutes_to_next_zone'),
            'timeframe':trigger_timeframe,'atr_15m':round(setup['atr'],8),'last':round(setup['last'],8),'support':round(setup['support'],8) if setup['support'] is not None else None,'resistance':round(setup['resistance'],8) if setup['resistance'] is not None else None,
            'rsi_trigger':setup['rsi'],'structure':setup['structure'],'trigger_price':round(setup['trigger_price'],8) if setup['trigger_price'] is not None else None,
            'next_signal_status':'TRIGGERED' if setup['status']=='SIGNAL READY' else 'WAITING FOR CONFIRMATION',
            'trade_state':'ACTIVE' if setup['status']=='SIGNAL READY' else setup['status'],'next_signal_trigger':setup['trigger_text'],'reasons':setup['reasons'],
            'trends':{tf:trends[tf] for tf in ('15m','30m','1h','4h','1d') if tf in trends},
            'trend_detail':{tf:{'trend':trends[tf], 'rsi':snaps[tf].get('rsi'), 'close':snaps[tf].get('close'), 'ema20':snaps[tf].get('ema20'), 'ema50':snaps[tf].get('ema50')} for tf in snaps},
            'trend_alignment':f"{sum(1 for v in setup['context_trends'].values() if v==setup['trend'])}/5" if setup['trend'] != 'Neutral' else '0/5',
            'validation':setup['validation'],'data_source':'Verified TradingView scanner feed','updated_at':utc_iso(),
            'market_regime':setup.get('market_regime','UNKNOWN'),'fib_50':setup.get('fib_50'),'fib_618':setup.get('fib_618'),'fib_zone_low':setup.get('fib_zone_low'),'fib_zone_high':setup.get('fib_zone_high'),
            'in_retracement_zone':setup.get('in_retracement_zone',False),'retracement_location':setup.get('retracement_location',''),'liquidity_sweep':setup.get('liquidity_sweep',False),'mss_choch':setup.get('mss_choch',False),'displacement_confirmation':setup.get('displacement_confirmation',False),'fvg_confirmation':setup.get('fvg_confirmation',False),'news_filter':setup.get('news_filter','NOT_CONNECTED'),'spread_filter':setup.get('spread_filter','DATA_PROVIDER_DEPENDENT'),
            'strategy_confluence':setup.get('strategy_confluence',[]),'detected_patterns':setup.get('detected_patterns',[]),'pattern_count':setup.get('pattern_count',0),'strategy_state':setup.get('strategy_state','WAITING'),'confirmation_candle_time':setup.get('confirmation_candle_time'),'confirmation_candle_closed':setup.get('confirmation_candle_closed',False),'confirmation_age_seconds':setup.get('confirmation_age_seconds'),'entry_fresh':setup.get('entry_fresh',False),'late_entry_blocked':setup.get('late_entry_blocked',False),
            'method':'PMA confluence engine: TradingView MTF trend + RSI + technical rating + pivot trigger + ATR risk structure'
        }
    except Exception as tv_error:
        # Fast verified fallback: build the same forecast-first engine from Yahoo
        # OHLC candles. Do not run the expensive historical backtest on every live
        # screen refresh; history/backtesting has its own endpoint.
        try:
            tfs = ['15m','30m','1h','4h','1d']
            if trigger_timeframe not in tfs: tfs.append(trigger_timeframe)
            snaps = yahoo_verified_snapshots(symbol, tfs)
            setup = _tv_setup(symbol, market, trigger_timeframe, snaps)
            psize = pip_size(symbol)
            trends = {tf:_snapshot_trend_safe(snaps[tf]) for tf in snaps}
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
                'distance_to_entry_zone':round(abs(setup['entry_zone']-setup['last']),8) if setup['entry_zone'] is not None else None,
                'pips_to_entry_zone':round(abs(setup['entry_zone']-setup['last'])/psize,1) if setup['entry_zone'] is not None else None,
                'pips_to_next_zone':round((setup['distance_to_next_zone']/psize),1) if setup['distance_to_next_zone'] is not None else None,
                'candles_to_next_zone':setup.get('candles_to_next_zone'),'estimated_minutes_to_next_zone':setup.get('estimated_minutes_to_next_zone'),
                'timeframe':trigger_timeframe,'atr_15m':round(setup['atr'],8),'last':round(setup['last'],8),
                'support':round(setup['support'],8) if setup['support'] is not None else None,
                'resistance':round(setup['resistance'],8) if setup['resistance'] is not None else None,
                'rsi_trigger':setup['rsi'],'structure':setup['structure'],
                'trigger_price':round(setup['trigger_price'],8) if setup['trigger_price'] is not None else None,
                'next_signal_status':'TRIGGERED' if setup['status']=='SIGNAL READY' else 'WAITING FOR CONFIRMATION',
                'trade_state':'ACTIVE' if setup['status']=='SIGNAL READY' else setup['status'],'next_signal_trigger':setup['trigger_text'],'reasons':setup['reasons'],
                'trends':{tf:trends[tf] for tf in ('15m','30m','1h','4h','1d') if tf in trends},
                'trend_detail':{tf:{'trend':trends[tf], 'rsi':snaps[tf].get('rsi'), 'close':snaps[tf].get('close'), 'ema20':snaps[tf].get('ema20'), 'ema50':snaps[tf].get('ema50')} for tf in snaps},
                'trend_alignment':f"{sum(1 for v in setup['context_trends'].values() if v==setup['trend'])}/5" if setup['trend'] != 'Neutral' else '0/5',
                'validation':setup['validation'],'data_source':'Verified Yahoo Finance OHLC fallback','updated_at':utc_iso(),
                'market_regime':setup.get('market_regime','UNKNOWN'),'fib_50':setup.get('fib_50'),'fib_618':setup.get('fib_618'),'fib_zone_low':setup.get('fib_zone_low'),'fib_zone_high':setup.get('fib_zone_high'),
                'in_retracement_zone':setup.get('in_retracement_zone',False),'retracement_location':setup.get('retracement_location',''),'liquidity_sweep':setup.get('liquidity_sweep',False),'mss_choch':setup.get('mss_choch',False),'displacement_confirmation':setup.get('displacement_confirmation',False),'fvg_confirmation':setup.get('fvg_confirmation',False),'news_filter':setup.get('news_filter','NOT_CONNECTED'),'spread_filter':setup.get('spread_filter','DATA_PROVIDER_DEPENDENT'),
                'strategy_confluence':setup.get('strategy_confluence',[]),'detected_patterns':setup.get('detected_patterns',[]),'pattern_count':setup.get('pattern_count',0),'strategy_state':setup.get('strategy_state','WAITING'),'confirmation_candle_time':setup.get('confirmation_candle_time'),'confirmation_candle_closed':setup.get('confirmation_candle_closed',False),'confirmation_age_seconds':setup.get('confirmation_age_seconds'),'entry_fresh':setup.get('entry_fresh',False),'late_entry_blocked':setup.get('late_entry_blocked',False),
                'method':'PMA confluence engine: verified OHLC trend + RSI + structure + MTF alignment + ATR zone projection'
            }
        except Exception as yahoo_error:
            raise ValueError(f'TradingView feed failed ({tv_error}); verified Yahoo fallback failed ({yahoo_error})')


def _snapshot_trend_safe(snapshot):
    close, e20, e50, e100 = snapshot.get('close'), snapshot.get('ema20'), snapshot.get('ema50'), snapshot.get('ema100')
    if None in (close, e20, e50): return 'Neutral'
    if close > e20 > e50 and (e100 is None or e50 > e100): return 'Bullish'
    if close < e20 < e50 and (e100 is None or e50 < e100): return 'Bearish'
    return 'Neutral'


@app.get('/api/health')
def health():
    return {'ok':True,'service':'Pips Master Academy API','market_data':'TradingView scanner feed with Yahoo fallback','timeframes':['1m','5m','15m','1h','4h','1d'],'updated_at':utc_iso()}


@app.get('/api/market-data/test')
def market_data_test(symbol: str='EURUSD', timeframe: str='15m'):
    if timeframe not in {'1m','5m','15m','1h','4h','1d'}:
        raise HTTPException(400,'Unsupported timeframe. Use 1m, 5m, 15m, 1h, 4h or 1d.')
    try:
        snaps=_tv_scan(symbol,'Forex',[timeframe])
        s=snaps[timeframe]
        return {'ok':True,'provider':'TradingView scanner','symbol':norm_symbol(symbol),'timeframe':timeframe,'last_close':s.get('close'),'rsi':s.get('rsi'),'recommendation':s.get('recommend'),'updated_at':utc_iso()}
    except Exception as ex:
        raise HTTPException(503,f'Market data test failed: {ex}')


def _record_signal_event(setup, user_id=None):
    try:
        if not setup or setup.get('direction') in (None,'NO TRADE'): return
        event_key='|'.join(str(setup.get(k,'')) for k in ('symbol','market','timeframe','direction','status','entry_zone','stop_loss','take_profit_1'))
        reason=setup.get('day_trade_reason') or setup.get('reasons') or ''
        if isinstance(reason,list): reason=' • '.join(str(x) for x in reason)
        c=db(); c.execute('INSERT OR IGNORE INTO signal_history(user_id,symbol,market,timeframe,direction,status,setup_strength,entry,stop_loss,take_profit,reason,event_key,created) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(user_id,setup.get('symbol',''),setup.get('market',''),setup.get('timeframe',''),setup.get('direction',''),setup.get('status',''),setup.get('setup_strength'),setup.get('entry_zone'),setup.get('stop_loss'),setup.get('take_profit_1'),reason,event_key,int(time.time()))); c.commit(); c.close()
    except Exception: pass

@app.get('/api/signals/scan')
def scan(market: str='Forex', symbols: str='', timeframe: str='15m', selected: str=''):
    requested=[x.strip().upper() for x in symbols.split(',') if x.strip()][:20] if symbols.strip() else []
    if not requested:
        requested=DEFAULT_FOREX_WATCHLIST[:] if market=='Forex' else []
    requested=requested[:8]
    if selected:
        selected=selected.strip().upper()
        requested=[selected]+[x for x in requested if x!=selected]
    requested=requested[:8]
    if not requested: return {'closest':None,'closest_pair':None,'timeframe':timeframe,'opportunities':[],'errors':[{'scope':'request','error':'No supported symbol selected'}],'market':market,'symbols':[],'pairs_scanned':0,'message':'Select a supported market symbol.','updated_at':utc_iso()}
    tfs=['15m','30m','1h','4h','1d']
    if timeframe not in tfs: tfs.append(timeframe)
    opportunities=[]; errors=[]
    # First try the whole watchlist through TradingView. Missing symbols fall through
    # to the verified Yahoo OHLC path in parallel below.
    batch={}
    try: batch=_tv_scan_many(requested,market,tfs)
    except Exception as ex: errors.append({'scope':'batch','error':str(ex)})
    def build(sym):
        if sym in batch: return prepare_market_setup(sym,market,timeframe,batch[sym])
        return prepare_market_setup(sym,market,timeframe)
    # Parallel symbol builds prevent one unavailable market from serially blocking all others.
    with ThreadPoolExecutor(max_workers=min(8,len(requested))) as pool:
        jobs={pool.submit(build,sym):sym for sym in requested}
        for job in as_completed(jobs):
            sym=jobs[job]
            try:
                setup=job.result(); opportunities.append(setup); _record_signal_event(setup,None)
            except Exception as ex: errors.append({'symbol':sym,'error':str(ex)})
    opportunities.sort(key=lambda x:(0 if x.get('status') in ('SIGNAL READY','ACTIVE') else 1, x.get('distance_to_entry_zone') if x.get('distance_to_entry_zone') is not None else 10**18, -(x.get('setup_strength') or 0)))
    closest=next((x for x in opportunities if x.get('symbol')==selected), None) if selected else None
    closest=closest or (opportunities[0] if opportunities else None)
    return {'closest':closest,'closest_pair':closest.get('symbol') if closest else None,
            'timeframe':timeframe if timeframe in {'1m','5m','15m','1h','4h','1d'} else '15m',
            'opportunities':opportunities,'errors':errors,'market':market,'symbols':requested,
            'pairs_scanned':len(opportunities),'minimum_pairs':6 if market=='Forex' else min(6,len(requested)),
            'message':f'Verified market snapshots loaded for {len(opportunities)} symbol(s).' if opportunities else 'No verified market data was returned; no signal is being invented.',
            'updated_at':utc_iso(),'batch_fast_path':bool(batch)}


@app.get('/api/scanner/backtest')
def scanner_backtest(market: str='Forex', symbols: str='', timeframes: str='15m,1h,4h'):
    if market != 'Forex':
        raise HTTPException(400, 'The optimization engine currently targets Forex currency pairs.')
    requested=[x.strip().upper() for x in symbols.split(',') if x.strip()] if symbols.strip() else DEFAULT_FOREX_WATCHLIST[:]
    tfs=[x.strip() for x in timeframes.split(',') if x.strip() and x.strip() in {'15m','1h','4h'}]
    if not tfs: tfs=['15m','1h','4h']
    try:
        return optimize_strict_scanner(requested[:6], tfs)
    except Exception as ex:
        raise HTTPException(503, f'Backtest engine could not complete: {ex}')


@app.get('/api/signals/candles')
def candles(symbol: str='EURUSD', timeframe: str='15m'):
    try:
        return {'symbol':symbol.upper(),'timeframe':timeframe,'candles':fetch(symbol,timeframe)[-300:],'updated_at':utc_iso()}
    except Exception as ex:
        raise HTTPException(503,f'Live candle feed unavailable: {ex}')


@app.get('/api/day-trade/plan')
def day_trade_plan(market: str='Forex', symbols: str='EURUSD,GBPUSD,USDJPY,GBPJPY,XAUUSD,BTCUSD', timeframe: str='15m'):
    requested=[x.strip().upper() for x in symbols.split(',') if x.strip()][:8]
    results=[]; errors=[]
    tfs=['15m','30m','1h','4h','1d']
    if timeframe not in tfs: tfs.append(timeframe)
    batch={}
    try: batch=_tv_scan_many(requested,market,tfs)
    except Exception as ex: errors.append({'scope':'batch','error':str(ex)})
    def build(sym):
        setup=prepare_market_setup(sym,market,timeframe,batch.get(sym))
        context_ok=setup['trends'].get('1h')==setup['trends'].get('4h') and setup['direction']!='NO TRADE'
        setup['day_trade_state']='READY' if context_ok and setup['status']=='SIGNAL READY' else ('FORECAST' if setup['direction']!='NO TRADE' else setup['status'])
        setup['day_trade_reason']=f"{timeframe} forecast is aligned with 1H and 4H context." if context_ok else 'Trend is context only. Wait for the planned pullback, sniper candle confirmation and risk trigger before entering.'
        setup['live_trade_state']='READY TO BUY' if setup['status']=='SIGNAL READY' and setup['direction']=='BUY' else ('READY TO SELL' if setup['status']=='SIGNAL READY' and setup['direction']=='SELL' else ('WAITING FOR CONFIRMATION' if setup['direction']!='NO TRADE' else setup['status']))
        return setup
    with ThreadPoolExecutor(max_workers=min(8,max(1,len(requested)))) as pool:
        jobs={pool.submit(build,sym):sym for sym in requested}
        for job in as_completed(jobs):
            sym=jobs[job]
            try: results.append(job.result())
            except Exception as ex: errors.append({'symbol':sym,'error':str(ex)})
    results.sort(key=lambda x:(0 if x['day_trade_state']=='READY' else 1,x.get('distance_to_entry_zone') if x.get('distance_to_entry_zone') is not None else 10**18))
    return {'date':datetime.now(timezone.utc).strftime('%Y-%m-%d'),'market':market,'setups':results,'errors':errors,'updated_at':utc_iso(),'batch_fast_path':bool(batch),'note':'Trend is context only. Entries require a pullback into demand/supply and rejection confirmation.'}


@app.get('/api/trade-monitor/history')
def trade_monitor_history(req: Request, days: int = 7):
    u=current(req); days=max(1,min(30,int(days or 7))); cutoff=int(time.time())-days*86400
    c=db(); rows=c.execute('SELECT * FROM trade_history WHERE user_id=? AND closed_at>=? ORDER BY closed_at DESC',(u['id'],cutoff)).fetchall(); c.close()
    counts={'take_profit':0,'stop_loss':0,'manual_close':0,'close_in_profit':0,'close_in_loss':0}
    items=[]
    for r in rows:
        outcome=r['outcome']; counts[outcome]=counts.get(outcome,0)+1
        items.append({k:r[k] for k in ('id','symbol','market','timeframe','direction','entry','stop_loss','take_profit','outcome','reason','opened_at','closed_at')})
    return {'days':days,'counts':counts,'total':len(items),'trades':items}


class TradeHistoryEvent(BaseModel):
    symbol: str
    market: str = 'Forex'
    timeframe: str = '15m'
    direction: str
    entry: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    outcome: str
    reason: str = ''
    opened_at: int | None = None


@app.post('/api/trade-monitor/history')
def trade_monitor_history_add(req: Request, x: TradeHistoryEvent):
    u=current(req); allowed={'take_profit','stop_loss','manual_close','close_in_profit','close_in_loss'}
    if x.outcome not in allowed: raise HTTPException(400,'Unsupported trade outcome')
    now=int(time.time()); opened=int(x.opened_at or now)
    c=db(); c.execute('INSERT INTO trade_history(user_id,symbol,market,timeframe,direction,entry,stop_loss,take_profit,outcome,reason,opened_at,closed_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
        (u['id'],x.symbol.upper(),x.market,x.timeframe,x.direction,x.entry,x.stop_loss,x.take_profit,x.outcome,x.reason,opened,now)); c.commit(); c.close()
    return {'ok':True}


@app.get('/api/signal-history')
def signal_history(req: Request, days: int = 7, limit: int = 200):
    u=current(req); c=db(); cutoff=int(time.time())-max(1,min(days,30))*86400
    rows=c.execute('SELECT * FROM signal_history WHERE (user_id=? OR user_id IS NULL) AND created>=? ORDER BY created DESC LIMIT ?', (u['id'],cutoff,max(1,min(limit,500)))).fetchall(); c.close()
    return {'days':days,'signals':[dict(r) for r in rows]}

@app.get('/api/feedback/summary')
def feedback_summary(req: Request):
    current(req); c=db(); row=c.execute('SELECT COUNT(*) n,COALESCE(AVG(rating),0) avg FROM feedback').fetchone(); dist=c.execute('SELECT rating,COUNT(*) n FROM feedback GROUP BY rating').fetchall(); c.close()
    return {'count':int(row['n'] or 0),'average':round(float(row['avg'] or 0),2),'distribution':{str(r['rating']):int(r['n']) for r in dist}}

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
        'lessons':LESSONS,'tasks':TASKS,'daily_tasks':DAILY_TASKS,'completed_lesson_ids':[r['lesson_id'] for r in completed_lessons],'completed_task_ids':[r['task_id'] for r in completed_tasks],'completed_daily_task_ids':[r['task_id'] for r in completed_daily],
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


def history_retention_enabled(c):
    r=c.execute("SELECT value FROM settings WHERE key='history_retention_enabled'").fetchone()
    return str(r['value'])!='0' if r else True

@app.get('/api/scanner/analytics')
def scanner_analytics(req: Request, days: int=30):
    u=current(req); days=max(1,min(365,int(days or 30))); cutoff=int(time.time())-days*86400
    c=db()
    trades=c.execute('SELECT * FROM trade_history WHERE user_id=? AND closed_at>=? ORDER BY closed_at DESC',(u['id'],cutoff)).fetchall()
    signals=c.execute('SELECT * FROM signal_history WHERE (user_id=? OR user_id IS NULL) AND created>=? ORDER BY created DESC',(u['id'],cutoff)).fetchall(); c.close()
    wins=sum(1 for r in trades if r['outcome']=='take_profit' or r['outcome']=='close_in_profit')
    losses=sum(1 for r in trades if r['outcome']=='stop_loss' or r['outcome']=='close_in_loss')
    closed=wins+losses
    by_tf={}; by_dir={}; by_market={};
    for r in trades:
        for bucket,key in ((by_tf,r['timeframe']),(by_dir,r['direction']),(by_market,r['market'])):
            z=bucket.setdefault(key,{'trades':0,'wins':0,'losses':0}); z['trades']+=1; z['wins']+=int(r['outcome'] in ('take_profit','close_in_profit')); z['losses']+=int(r['outcome'] in ('stop_loss','close_in_loss'))
    def finish(x):
        for v in x.values(): v['win_rate']=round(v['wins']*100/max(v['wins']+v['losses'],1),1) if v['wins']+v['losses'] else None
        return x
    return {'days':days,'closed_trades':len(trades),'wins':wins,'losses':losses,'win_rate':round(wins*100/closed,1) if closed else None,'signals':len(signals),'by_timeframe':finish(by_tf),'by_direction':finish(by_dir),'by_market':finish(by_market),'note':'Historical measurements only; not a prediction of future results.'}

@app.get('/api/history/settings')
def history_settings(req: Request):
    u=current(req); c=db(); enabled=history_retention_enabled(c); c.close(); return {'enabled':enabled,'days':7}

@app.post('/api/history/settings')
def history_settings_update(req: Request, x: dict):
    u=current(req)
    if u['role']!='admin': raise HTTPException(403,'Admin access required.')
    enabled=bool(x.get('enabled',True)); c=db(); c.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('history_retention_enabled',?)",('1' if enabled else '0',)); c.commit(); c.close(); return {'ok':True,'enabled':enabled,'days':7}

@app.get('/api/history')
def history_all(req: Request, days: int=7):
    u=current(req); c=db(); enabled=history_retention_enabled(c); now=int(time.time()); cutoff=now-7*86400
    if enabled:
        c.execute('DELETE FROM trade_history WHERE closed_at<?',(cutoff,))
        c.execute('DELETE FROM signal_history WHERE created<? AND (user_id=? OR user_id IS NULL)',(cutoff,u['id']))
        c.commit()
    rows=c.execute('SELECT * FROM trade_history WHERE user_id=? ORDER BY closed_at DESC LIMIT 300',(u['id'],)).fetchall()
    sig=c.execute('SELECT * FROM signal_history WHERE (user_id=? OR user_id IS NULL) ORDER BY created DESC LIMIT 300',(u['id'],)).fetchall()
    c.close(); return {'enabled':enabled,'days':7,'trades':[dict(r) for r in rows],'signals':[dict(r) for r in sig]}

def community_settings_row(c):
    r=c.execute('SELECT * FROM community_settings WHERE id=1').fetchone()
    return {'name':r['name'] if r else 'PMA Community','bio':r['bio'] if r and 'bio' in r.keys() else 'A place for PMA members to learn, share and discuss the markets.','profile_picture':r['profile_picture'] if r else '', 'disappearing_seconds':int(r['disappearing_seconds'] or 0) if r else 86400,'temporary_enabled':bool(r['temporary_enabled']) if r and 'temporary_enabled' in r.keys() else False,'temporary_seconds':int(r['temporary_seconds'] or 86400) if r and 'temporary_seconds' in r.keys() else 86400}

def community_member(c,user_id):
    return c.execute('SELECT * FROM community_members WHERE user_id=?',(user_id,)).fetchone()

def require_community_member(req):
    u=current(req); c=db(); m=community_member(c,u['id'])
    if u['role']=='admin' and (not m or m['status']!='approved'):
        now=int(time.time()); c.execute("INSERT OR REPLACE INTO community_members(user_id,status,role,warning_count,suspended_until,joined_at,updated_at,note) VALUES(?,?,?,?,?,?,?,?)",(u['id'],'approved','admin',m['warning_count'] if m else 0,0,m['joined_at'] if m else now,now,'Administrator access')); c.commit(); m=community_member(c,u['id'])
    if not m or m['status']!='approved':
        c.close(); raise HTTPException(403,'Community access is awaiting administrator approval.')
    if m['suspended_until'] and int(m['suspended_until'])>int(time.time()):
        until=datetime.fromtimestamp(m['suspended_until'],timezone.utc).isoformat(); c.close(); raise HTTPException(403,f'Community access is suspended until {until}.')
    return u,c,m

@app.get('/api/community/status')
def community_status(req: Request):
    u=current(req); c=db(); m=community_member(c,u['id']); settings=community_settings_row(c)
    if u['role']=='admin' and (not m or m['status']!='approved'):
        now=int(time.time()); c.execute("INSERT OR REPLACE INTO community_members(user_id,status,role,warning_count,suspended_until,joined_at,updated_at,note) VALUES(?,?,?,?,?,?,?,?)",(u['id'],'approved','admin',m['warning_count'] if m else 0,0,m['joined_at'] if m else now,now,'Administrator access')); c.commit(); m=community_member(c,u['id'])
    pending=bool(m and m['status']=='pending'); approved=bool(m and m['status']=='approved'); suspended=bool(m and m['status']=='suspended' and (m['suspended_until'] or 0)>int(time.time()))
    c.close(); return {'approved':approved,'pending':pending,'suspended':suspended,'status':m['status'] if m else 'pending','role':m['role'] if m else 'member','settings':settings}

@app.post('/api/community/join')
def community_join(req: Request, x: CommunityRequest):
    u=current(req); c=db(); m=community_member(c,u['id']); now=int(time.time())
    if m and m['status']=='approved': c.close(); return {'ok':True,'status':'approved'}
    c.execute('INSERT OR REPLACE INTO community_members(user_id,status,role,warning_count,suspended_until,joined_at,updated_at,note) VALUES(?,?,?,?,?,?,?,?)',(u['id'],'pending','admin' if u['role']=='admin' else 'member',m['warning_count'] if m else 0,0,m['joined_at'] if m else 0,now,'Join request submitted'))
    admins=c.execute("SELECT username FROM users WHERE role='admin'").fetchall()
    for a in admins: push_notice(c,a['username'],'Community join request',f"{u['username']} requested access to the community.",'community')
    c.commit(); c.close(); return {'ok':True,'status':'pending'}

@app.get('/api/community/members')
def community_member_list(req: Request):
    u,c,m=require_community_member(req)
    rows=c.execute("SELECT u.id,u.username,u.full_name,u.pma_id,u.profile_picture,u.role,cm.status,cm.joined_at FROM users u JOIN community_members cm ON cm.user_id=u.id WHERE cm.status='approved' ORDER BY CASE WHEN u.role='admin' THEN 0 ELSE 1 END,u.username COLLATE NOCASE").fetchall()
    c.close()
    return {'members':[dict(r) for r in rows]}

@app.get('/api/community/messages')
def get_messages(req: Request, q: str=''):
    u,c,m=require_community_member(req); locked=get_locked(c); settings=community_settings_row(c); now=int(time.time())
    # Only messages explicitly marked temporary expire. Permanent community history is never removed here.
    c.execute('DELETE FROM messages WHERE temporary=1 AND expires_at>0 AND expires_at<=?',(now,)); c.commit()
    if q.strip():
        rows=c.execute('SELECT * FROM messages WHERE (deleted=1 OR text LIKE ?) ORDER BY id ASC LIMIT 300',(f'%{q.strip()}%',)).fetchall()
    else:
        rows=c.execute('SELECT * FROM messages ORDER BY id ASC LIMIT 300').fetchall()
    out=[]
    for r in rows:
        reply=None
        if r['reply_to_id']:
            rr=c.execute('SELECT id,username,text FROM messages WHERE id=?',(r['reply_to_id'],)).fetchone()
            if rr: reply={'id':rr['id'],'username':rr['username'],'text':rr['text']}
        reactions=c.execute('SELECT emoji,COUNT(*) n FROM message_reactions WHERE message_id=? GROUP BY emoji ORDER BY n DESC',(r['id'],)).fetchall()
        viewers=c.execute('SELECT COUNT(*) n FROM message_views WHERE message_id=?',(r['id'],)).fetchone()['n']
        remaining=max(0,int(r['expires_at'] or 0)-now) if r['temporary'] else 0
        out.append({'id':r['id'],'username':r['username'],'pma_id':r['pma_id'],'text':r['text'],'media_data':r['media_data'],'media_type':r['media_type'],'reply_to':reply,'edited':bool(r['edited']),'deleted':bool(r['deleted']),'deleted_by':r['deleted_by'] or '', 'time':datetime.fromtimestamp(r['created'],timezone.utc).strftime('%H:%M'),'created':r['created'],'temporary':bool(r['temporary']),'expires_at':r['expires_at'] or 0,'seconds_remaining':remaining,'reactions':[dict(x) for x in reactions],'views':viewers})
    c.close(); return {'locked':locked,'settings':settings,'messages':out,'server_time':now}

@app.post('/api/community/messages')
def post_message(req: Request, x: Msg):
    u,c,m=require_community_member(req); is_locked=get_locked(c)
    if is_locked and u['role']!='admin': c.close(); raise HTTPException(403,'Community chat is locked by the administrator.')
    if not x.text.strip() and not x.media_data: c.close(); raise HTTPException(400,'Message cannot be empty.')
    reply_id=int(x.reply_to_id or 0)
    if reply_id and not c.execute('SELECT 1 FROM messages WHERE id=?',(reply_id,)).fetchone(): reply_id=0
    settings=community_settings_row(c); now=int(time.time())
    temporary=bool(x.temporary and settings['temporary_enabled']) if u['role']!='admin' else bool(x.temporary and settings['temporary_enabled'])
    expires=now+max(3600,int(settings['temporary_seconds'] or 86400)) if temporary else 0
    c.execute('INSERT INTO messages(username,pma_id,text,media_data,media_type,reply_to_id,edited,created,temporary,expires_at,deleted,deleted_by,deleted_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(u['username'],u['pma_id'],x.text.strip(),x.media_data,x.media_type,reply_id,0,now,1 if temporary else 0,expires,0,'',0))
    record_activity(c,u['id'],'community_post',10)
    users=c.execute('SELECT username FROM users WHERE username<>?',(u['username'],)).fetchall()
    for r in users: push_notice(c,r['username'],'New community message',f"{u['username']} posted in the community.",'community')
    c.commit(); c.close(); return {'ok':True,'temporary':temporary,'expires_at':expires}

@app.patch('/api/community/messages/{message_id}')
def edit_message(req: Request, message_id: int, x: CommunityMessageAction):
    u,c,m=require_community_member(req); row=c.execute('SELECT * FROM messages WHERE id=?',(message_id,)).fetchone()
    if not row: c.close(); raise HTTPException(404,'Message not found.')
    if row['deleted']: c.close(); raise HTTPException(400,'Deleted messages cannot be edited.')
    if row['username']!=u['username'] and u['role']!='admin': c.close(); raise HTTPException(403,'You can only edit your own message.')
    text=x.text.strip()
    if not text: c.close(); raise HTTPException(400,'Message cannot be empty.')
    c.execute('UPDATE messages SET text=?,edited=1 WHERE id=?',(text,message_id)); c.commit(); c.close(); return {'ok':True}

@app.delete('/api/community/messages/{message_id}')
def delete_message(req: Request, message_id: int):
    u,c,m=require_community_member(req); row=c.execute('SELECT * FROM messages WHERE id=?',(message_id,)).fetchone()
    if not row: c.close(); raise HTTPException(404,'Message not found.')
    if row['username'] != u['username'] and u['role'] != 'admin': c.close(); raise HTTPException(403,'You can only delete your own message.')
    marker='This message was deleted by admin.' if u['role']=='admin' and row['username']!=u['username'] else 'This message was deleted.'
    c.execute("UPDATE messages SET text=?,media_data='',media_type='',deleted=1,deleted_by=?,deleted_at=? WHERE id=?",(marker,u['username'],int(time.time()),message_id)); c.commit(); c.close(); return {'ok':True}

@app.post('/api/community/messages/{message_id}/react')
def react_community_message(req: Request, message_id: int, x: CommunityReaction):
    u,c,m=require_community_member(req); row=c.execute('SELECT id FROM messages WHERE id=?',(message_id,)).fetchone()
    if not row: c.close(); raise HTTPException(404,'Message not found.')
    emoji=x.emoji.strip()[:8]
    if not emoji: c.close(); raise HTTPException(400,'Reaction required.')
    exists=c.execute('SELECT id FROM message_reactions WHERE message_id=? AND user_id=? AND emoji=?',(message_id,u['id'],emoji)).fetchone()
    if exists: c.execute('DELETE FROM message_reactions WHERE id=?',(exists['id'],))
    else: c.execute('INSERT INTO message_reactions(message_id,user_id,emoji,created) VALUES(?,?,?,?)',(message_id,u['id'],emoji,int(time.time())))
    c.commit(); c.close(); return {'ok':True}

@app.post('/api/community/messages/{message_id}/view')
def view_community_message(req: Request, message_id: int):
    u,c,m=require_community_member(req); row=c.execute('SELECT id FROM messages WHERE id=?',(message_id,)).fetchone()
    if not row: c.close(); raise HTTPException(404,'Message not found.')
    c.execute('INSERT OR REPLACE INTO message_views(message_id,user_id,viewed) VALUES(?,?,?)',(message_id,u['id'],int(time.time()))); c.commit(); c.close(); return {'ok':True}

def _private_pair(a,b):
    return (a,b) if a<b else (b,a)

def _private_allowed(sender, receiver):
    if sender['id']==receiver['id']: return False
    # Members may never initiate a request or message to the administrator.
    if sender['role']!='admin' and receiver['role']=='admin': return False
    return True

def _conversation_for(c,a,b,create=False):
    ua,ub=_private_pair(a,b)
    row=c.execute('SELECT * FROM private_conversations WHERE user_a=? AND user_b=?',(ua,ub)).fetchone()
    if not row and create:
        c.execute('INSERT OR IGNORE INTO private_conversations(user_a,user_b,created,last_message) VALUES(?,?,?,0)',(ua,ub,int(time.time())))
        row=c.execute('SELECT * FROM private_conversations WHERE user_a=? AND user_b=?',(ua,ub)).fetchone()
    return row

@app.get('/api/members')
def public_members(req: Request):
    u=current(req); c=db()
    rows=c.execute("SELECT id,username,full_name,pma_id,profile_picture,role,created FROM users WHERE role IN ('user','admin') AND id<>? ORDER BY CASE WHEN role='admin' THEN 0 ELSE 1 END, username COLLATE NOCASE",(u['id'],)).fetchall()
    out=[dict(r) for r in rows]
    for r in out: r['can_message']=bool(u['role']=='admin' or r['role']!='admin')
    c.close(); return {'members':out}

@app.get('/api/members/{user_id}')
def public_member_profile(req: Request, user_id: int):
    u=current(req); c=db(); r=c.execute('SELECT id,username,full_name,pma_id,profile_picture,role,created FROM users WHERE id=?',(user_id,)).fetchone()
    if not r: c.close(); raise HTTPException(404,'Member not found.')
    out=dict(r); out['can_message']=bool(u['role']=='admin' or r['role']!='admin')
    reqrow=c.execute("SELECT status FROM message_requests WHERE sender_id=? AND receiver_id=? ORDER BY id DESC LIMIT 1",(u['id'],user_id)).fetchone()
    reverse=c.execute("SELECT status FROM message_requests WHERE sender_id=? AND receiver_id=? ORDER BY id DESC LIMIT 1",(user_id,u['id'])).fetchone()
    conv=_conversation_for(c,u['id'],user_id,False)
    out['request_status']=reqrow['status'] if reqrow else ('accepted' if conv else '')
    out['incoming_request']=reverse['status'] if reverse and reverse['status']=='pending' else ''
    out['conversation_id']=conv['id'] if conv else None
    c.close(); return out

@app.get('/api/message-requests')
def message_requests(req: Request):
    u=current(req); c=db()
    incoming=c.execute("SELECT r.id,r.status,r.created,u.id user_id,u.username,u.full_name,u.profile_picture,u.role FROM message_requests r JOIN users u ON u.id=r.sender_id WHERE r.receiver_id=? ORDER BY r.id DESC",(u['id'],)).fetchall()
    outgoing=c.execute("SELECT r.id,r.status,r.created,u.id user_id,u.username,u.full_name,u.profile_picture,u.role FROM message_requests r JOIN users u ON u.id=r.receiver_id WHERE r.sender_id=? ORDER BY r.id DESC",(u['id'],)).fetchall()
    c.close(); return {'incoming':[dict(r) for r in incoming],'outgoing':[dict(r) for r in outgoing]}

@app.post('/api/message-requests')
def create_message_request(req: Request, x: MessageRequestModel):
    u=current(req); c=db(); target=c.execute('SELECT * FROM users WHERE id=?',(x.user_id,)).fetchone()
    if not target: c.close(); raise HTTPException(404,'Member not found.')
    if not _private_allowed(u,target): c.close(); raise HTTPException(403,'Members cannot message or request the administrator.')
    if target['role']=='admin': c.close(); raise HTTPException(403,'Members cannot message or request the administrator.')
    if _conversation_for(c,u['id'],target['id'],False): c.close(); return {'ok':True,'status':'accepted','conversation_id':_conversation_for(c,u['id'],target['id'],False)['id']}
    existing=c.execute('SELECT * FROM message_requests WHERE sender_id=? AND receiver_id=?',(u['id'],target['id'])).fetchone()
    if existing and existing['status']=='pending': c.close(); return {'ok':True,'status':'pending'}
    now=int(time.time()); c.execute('INSERT OR REPLACE INTO message_requests(sender_id,receiver_id,status,created,responded) VALUES(?,?,?,?,0)',(u['id'],target['id'],'pending',now)); push_notice(c,target['username'],'New message request',f"{u['username']} wants to start a private conversation with you.",'community'); c.commit(); c.close(); return {'ok':True,'status':'pending'}

@app.post('/api/message-requests/{request_id}')
def decide_message_request(req: Request, request_id: int, x: RequestDecision):
    u=current(req); action=x.action.lower().strip(); c=db(); r=c.execute('SELECT * FROM message_requests WHERE id=? AND receiver_id=?',(request_id,u['id'])).fetchone()
    if not r: c.close(); raise HTTPException(404,'Message request not found.')
    if r['status']!='pending': c.close(); return {'ok':True,'status':r['status']}
    if action not in ('accept','decline'): c.close(); raise HTTPException(400,'Use accept or decline.')
    now=int(time.time())
    if action=='decline': c.execute('UPDATE message_requests SET status=?,responded=? WHERE id=?',('declined',now,request_id)); c.commit(); c.close(); return {'ok':True,'status':'declined'}
    sender=c.execute('SELECT * FROM users WHERE id=?',(r['sender_id'],)).fetchone()
    if not sender or sender['role']=='admin': c.close(); raise HTTPException(400,'Invalid member request.')
    c.execute('UPDATE message_requests SET status=?,responded=? WHERE id=?',('accepted',now,request_id)); conv=_conversation_for(c,u['id'],sender['id'],True); push_notice(c,sender['username'],'Message request accepted',f"{u['username']} accepted your message request.",'community'); c.commit(); c.close(); return {'ok':True,'status':'accepted','conversation_id':conv['id']}

@app.post('/api/private/start/{user_id}')
def admin_start_private(req: Request, user_id: int):
    u=current(req)
    if u['role']!='admin': raise HTTPException(403,'Only the administrator can start a conversation without a request.')
    c=db(); target=c.execute('SELECT * FROM users WHERE id=?',(user_id,)).fetchone()
    if not target: c.close(); raise HTTPException(404,'Member not found.')
    conv=_conversation_for(c,u['id'],target['id'],True); c.commit(); c.close(); return {'ok':True,'conversation_id':conv['id']}

@app.get('/api/private/conversations')
def private_conversations(req: Request):
    u=current(req); c=db()
    rows=c.execute("SELECT c.*, CASE WHEN c.user_a=? THEN ub.id ELSE ua.id END other_id, CASE WHEN c.user_a=? THEN ub.username ELSE ua.username END other_username, CASE WHEN c.user_a=? THEN ub.full_name ELSE ua.full_name END other_full_name, CASE WHEN c.user_a=? THEN ub.profile_picture ELSE ua.profile_picture END other_picture, CASE WHEN c.user_a=? THEN ub.role ELSE ua.role END other_role FROM private_conversations c JOIN users ua ON ua.id=c.user_a JOIN users ub ON ub.id=c.user_b WHERE c.user_a=? OR c.user_b=? ORDER BY c.last_message DESC,c.id DESC",(u['id'],u['id'],u['id'],u['id'],u['id'],u['id'],u['id'])).fetchall()
    out=[]
    for r in rows:
        last=c.execute('SELECT text,created FROM private_messages WHERE conversation_id=? ORDER BY id DESC LIMIT 1',(r['id'],)).fetchone()
        d=dict(r); d['last_text']=last['text'] if last else ''; d['last_created']=last['created'] if last else 0; out.append(d)
    c.close(); return {'conversations':out}

@app.get('/api/private/conversations/{conversation_id}')
def private_messages(req: Request, conversation_id: int):
    u=current(req); c=db(); conv=c.execute('SELECT * FROM private_conversations WHERE id=? AND (user_a=? OR user_b=?)',(conversation_id,u['id'],u['id'])).fetchone()
    if not conv: c.close(); raise HTTPException(404,'Conversation not found.')
    other_id=conv['user_b'] if conv['user_a']==u['id'] else conv['user_a']; other=c.execute('SELECT id,username,full_name,profile_picture,role FROM users WHERE id=?',(other_id,)).fetchone()
    rows=c.execute('SELECT * FROM private_messages WHERE conversation_id=? ORDER BY id ASC LIMIT 500',(conversation_id,)).fetchall(); c.close()
    return {'conversation':dict(conv),'other':dict(other) if other else None,'messages':[dict(r) for r in rows]}

@app.post('/api/private/conversations/{conversation_id}')
def send_private_message(req: Request, conversation_id: int, x: PrivateMessage):
    u=current(req); text=x.text.strip(); c=db(); conv=c.execute('SELECT * FROM private_conversations WHERE id=? AND (user_a=? OR user_b=?)',(conversation_id,u['id'],u['id'])).fetchone()
    if not conv: c.close(); raise HTTPException(404,'Conversation not found.')
    other_id=conv['user_b'] if conv['user_a']==u['id'] else conv['user_a']; other=c.execute('SELECT * FROM users WHERE id=?',(other_id,)).fetchone()
    if not text: c.close(); raise HTTPException(400,'Message cannot be empty.')
    if not _private_allowed(u,other): c.close(); raise HTTPException(403,'Members cannot message the administrator.')
    now=int(time.time()); c.execute('INSERT INTO private_messages(conversation_id,sender_id,receiver_id,text,created,edited,deleted,deleted_by) VALUES(?,?,?,?,?,0,0,\'\')',(conversation_id,u['id'],other_id,text,now)); c.execute('UPDATE private_conversations SET last_message=? WHERE id=?',(now,conversation_id)); push_notice(c,other['username'],'New private message',f"{u['username']} sent you a private message.",'community'); c.commit(); c.close(); return {'ok':True}

@app.post('/api/community/leave')
def leave_community(req: Request):
    u=current(req); c=db()
    if u['role']=='admin': c.close(); raise HTTPException(400,'The administrator cannot leave the community.')
    c.execute("UPDATE community_members SET status='removed',updated_at=?,note='Left the community voluntarily' WHERE user_id=?",(int(time.time()),u['id']))
    c.commit(); c.close(); return {'ok':True,'status':'removed'}

@app.get('/api/admin/community/members')
def community_members(req: Request, status: str=''):
    u=current(req)
    if u['role']!='admin': raise HTTPException(403,'Admin access required.')
    c=db(); sql="SELECT u.id,u.username,u.full_name,u.email,u.pma_id,u.profile_picture,u.last_active,u.role AS account_role, cm.status,cm.role AS community_role,cm.warning_count,cm.suspended_until,cm.joined_at,cm.note FROM users u JOIN community_members cm ON cm.user_id=u.id"; params=[]
    if status: sql+=' WHERE cm.status=?'; params.append(status)
    sql+=" ORDER BY CASE cm.status WHEN 'pending' THEN 0 WHEN 'approved' THEN 1 ELSE 2 END, u.username COLLATE NOCASE"
    rows=c.execute(sql,params).fetchall(); c.close(); return {'members':[dict(r) for r in rows]}

@app.post('/api/admin/community/moderate')
def moderate_community(req: Request, x: CommunityModeration):
    u=current(req)
    if u['role']!='admin': raise HTTPException(403,'Admin access required.')
    c=db(); target=c.execute('SELECT * FROM users WHERE id=?',(x.user_id,)).fetchone()
    if not target: c.close(); raise HTTPException(404,'Member not found.')
    if target['role']=='admin' and x.action in ('remove','suspend'): c.close(); raise HTTPException(400,'Administrator accounts cannot be removed or suspended here.')
    m=community_member(c,x.user_id); now=int(time.time())
    if not m: c.close(); raise HTTPException(404,'Community membership not found.')
    if x.action=='approve': status='approved'; joined=now; note=x.note or 'Approved by administrator'; until=0
    elif x.action=='remove': status='removed'; joined=m['joined_at'] or 0; note=x.note or 'Removed by administrator'; until=0
    elif x.action=='warn': status=m['status']; joined=m['joined_at'] or 0; note=x.note or 'Community warning'; until=m['suspended_until'] or 0; c.execute('UPDATE community_members SET warning_count=warning_count+1,updated_at=?,note=? WHERE user_id=?',(now,note,x.user_id))
    elif x.action=='suspend': status='suspended'; joined=m['joined_at'] or 0; note=x.note or 'Suspended by administrator'; until=now+86400
    elif x.action=='restore': status='approved'; joined=m['joined_at'] or now; note=x.note or 'Restored by administrator'; until=0
    else: c.close(); raise HTTPException(400,'Unsupported moderation action.')
    if x.action!='warn': c.execute('UPDATE community_members SET status=?,joined_at=?,updated_at=?,note=?,suspended_until=? WHERE user_id=?',(status,joined,now,note,until,x.user_id))
    push_notice(c,target['username'],'Community moderation',note,'community'); c.commit(); c.close(); return {'ok':True,'status':status}

@app.post('/api/admin/community/settings')
def update_community_settings(req: Request, x: CommunitySettings):
    u=current(req)
    if u['role']!='admin': raise HTTPException(403,'Admin access required.')
    seconds=86400; name=x.name.strip()[:80] or 'PMA Community'; bio=x.bio.strip()[:300] or 'A place for PMA members to learn, share and discuss the markets.'; now=int(time.time())
    c=db(); c.execute('UPDATE community_settings SET name=?,bio=?,profile_picture=?,disappearing_seconds=?,temporary_enabled=?,temporary_seconds=?,updated_at=? WHERE id=1',(name,bio,x.profile_picture,seconds,1 if x.temporary_enabled else 0,seconds,now)); c.commit(); out=community_settings_row(c); c.close(); return {'ok':True,'settings':out}


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
