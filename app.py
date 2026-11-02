import os, io, csv, sqlite3, secrets, time, re, math, json, mimetypes, uuid
from datetime import date, datetime, timedelta
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, session, g, make_response, abort, send_file
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from werkzeug.exceptions import HTTPException
from urllib.parse import urlparse
import hashlib, logging
import integrations as INT
import io as _io
import threading
import pyzipper
from PIL import Image, ImageOps, UnidentifiedImageError
Image.MAX_IMAGE_PIXELS = 40_000_000  # refuse decompression bombs

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.environ.get('SCHOOL_DB', os.path.join(BASE_DIR, 'school.db'))
app = Flask(__name__)
IS_PRODUCTION = os.environ.get('APP_ENV', '').lower() == 'production'
if IS_PRODUCTION and os.environ.get('FLASK_DEBUG') == '1':
    raise RuntimeError('Debug mode must never be switched on in production.')


def _secret_key():
    """SECRET_KEY from the environment. Outside production a random key is created once and kept beside the
    database, so everyone is not signed out every time the program restarts."""
    configured = os.environ.get('SECRET_KEY', '').strip()
    if IS_PRODUCTION:
        if len(configured) < 32: raise RuntimeError('SECRET_KEY must be set to at least 32 random characters when APP_ENV=production.')
        return configured
    if configured: return configured
    path = os.path.join(os.path.dirname(os.path.abspath(DB_PATH)), '.secret_key')
    try:
        with open(path, encoding='utf-8') as fh:
            value = fh.read().strip()
        if len(value) >= 32: return value
    except OSError: pass
    value = secrets.token_hex(32)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as fh: fh.write(value)
    except OSError: pass
    return value


app.secret_key = _secret_key()
app.config.update(MAX_CONTENT_LENGTH=8 * 1024 * 1024, SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax',
                  SESSION_COOKIE_SECURE=(os.environ.get('COOKIE_SECURE', '1' if IS_PRODUCTION else '0') == '1'), PERMANENT_SESSION_LIFETIME=1800)
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
app.config['TEMPLATES_AUTO_RELOAD'] = False

from pwa import register_pwa  # noqa: E402
PWA_ENDPOINTS = register_pwa(app, name='Fr. Joseph Connolly SVD Memorial School', short_name='FJC School', theme='#6B352A', background='#FFF1A6', description='School management system for Fr. Joseph Connolly SVD Memorial School, Saboba.')

ROLES = ['Administrator','Proprietor','Headteacher','Teacher','Class Teacher','Subject Teacher','Accountant','Admissions Officer','Librarian','Storekeeper','Parent/Guardian','Student']

FAMILY_ROLES = {'Administrator','Proprietor','Headteacher','Teacher','Admissions Officer','Class Teacher','Subject Teacher','Accountant','Librarian','Storekeeper'}  # staff roles that may also be a parent of pupils
ASSIGNABLE_ROLES = ['Administrator','Proprietor','Headteacher','Teacher','Admissions Officer','Class Teacher','Subject Teacher','Accountant','Librarian','Storekeeper','Parent/Guardian','Student']
STUDENT_ACCESS_ROLES = {'Administrator','Proprietor','Headteacher','Admissions Officer','Class Teacher','Subject Teacher','Teacher'}
FINANCE_ROLES = {'Administrator','Accountant','Proprietor','Headteacher'}
MANAGE_ROLES = {'Administrator','Headteacher','Admissions Officer'}
VIEW_ALL_ROLES = {'Administrator','Proprietor','Headteacher'}


def db():
    if 'db' not in g:
        g.db = sqlite3.connect(DB_PATH, timeout=15)
        g.db.execute('PRAGMA busy_timeout = 15000')
        g.db.row_factory = sqlite3.Row
        g.db.execute('PRAGMA foreign_keys = ON')
        g.db.execute('PRAGMA synchronous = NORMAL')
    return g.db

@app.teardown_appcontext
def close_db(_=None):
    conn = g.pop('db', None)
    if conn is not None: conn.close()


def init_db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    try: conn.execute('PRAGMA journal_mode = WAL')  # readers never block the writer; safer against power cuts
    except sqlite3.DatabaseError: pass
    conn.execute('PRAGMA foreign_keys = ON')
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS users (
      id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL,
      password_hash TEXT NOT NULL, full_name TEXT NOT NULL, role TEXT NOT NULL,
      assigned_class TEXT, student_id INTEGER, active INTEGER NOT NULL DEFAULT 1, must_change_password INTEGER NOT NULL DEFAULT 0,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS classes (
      id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL,
      stream TEXT DEFAULT '', active INTEGER NOT NULL DEFAULT 1
    );
    CREATE TABLE IF NOT EXISTS students (
      id INTEGER PRIMARY KEY AUTOINCREMENT, admission_no TEXT UNIQUE NOT NULL,
      first_name TEXT NOT NULL, last_name TEXT NOT NULL, dob TEXT, gender TEXT,
      nationality TEXT DEFAULT 'Ghanaian', address TEXT, admission_date TEXT NOT NULL,
      class_id INTEGER REFERENCES classes(id), guardian_name TEXT, guardian_phone TEXT,
      guardian_email TEXT, guardian_occupation TEXT, guardian_address TEXT,
      emergency_name TEXT, emergency_phone TEXT, status TEXT NOT NULL DEFAULT 'Active',
      notes TEXT DEFAULT '', photo_path TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS enrolment_history (
      id INTEGER PRIMARY KEY AUTOINCREMENT, student_id INTEGER NOT NULL REFERENCES students(id),
      class_name TEXT, academic_year TEXT, term TEXT, status TEXT, changed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS fees (
      id INTEGER PRIMARY KEY AUTOINCREMENT, receipt_no TEXT UNIQUE NOT NULL,
      student_id INTEGER NOT NULL REFERENCES students(id), amount REAL NOT NULL CHECK(amount > 0),
      payment_date TEXT NOT NULL, payment_method TEXT NOT NULL, purpose TEXT NOT NULL,
      received_by TEXT NOT NULL, notes TEXT DEFAULT '', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS fee_invoices (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      invoice_no TEXT UNIQUE NOT NULL,
      student_id INTEGER NOT NULL REFERENCES students(id),
      academic_year TEXT NOT NULL, term TEXT NOT NULL,
      description TEXT NOT NULL, amount REAL NOT NULL CHECK(amount >= 0),
      discount REAL NOT NULL DEFAULT 0 CHECK(discount >= 0),
      due_date TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'Open',
      created_by INTEGER REFERENCES users(id), created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      CHECK(discount <= amount)
    );
    CREATE TABLE IF NOT EXISTS parent_children (
      user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
      relationship TEXT NOT NULL DEFAULT 'Parent/Guardian',
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      PRIMARY KEY(user_id, student_id)
    );
    CREATE TABLE IF NOT EXISTS document_files (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      original_name TEXT NOT NULL, stored_name TEXT UNIQUE NOT NULL,
      mime_type TEXT NOT NULL, size_bytes INTEGER NOT NULL,
      category TEXT NOT NULL, student_id INTEGER REFERENCES students(id),
      uploaded_by INTEGER NOT NULL REFERENCES users(id),
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS login_attempts (username TEXT PRIMARY KEY, attempts INTEGER NOT NULL DEFAULT 0, locked_until REAL NOT NULL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS import_batches (token TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), rows_json TEXT NOT NULL, errors_json TEXT NOT NULL, created_at REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS admission_history (
      id INTEGER PRIMARY KEY AUTOINCREMENT, record_id INTEGER NOT NULL, status TEXT NOT NULL, previous_status TEXT,
      changed_by INTEGER, notes TEXT DEFAULT '', changed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS message_log (
      id INTEGER PRIMARY KEY AUTOINCREMENT, channel TEXT NOT NULL, recipient TEXT NOT NULL, subject TEXT DEFAULT '', body TEXT DEFAULT '',
      status TEXT NOT NULL, provider_ref TEXT DEFAULT '', error TEXT DEFAULT '', student_id INTEGER, sent_by INTEGER,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS momo_payments (
      id INTEGER PRIMARY KEY AUTOINCREMENT, reference TEXT NOT NULL UNIQUE, student_id INTEGER NOT NULL REFERENCES students(id), invoice_no TEXT NOT NULL,
      amount REAL NOT NULL, phone TEXT NOT NULL, network TEXT NOT NULL, status TEXT NOT NULL, provider TEXT NOT NULL DEFAULT 'paystack',
      message TEXT DEFAULT '', initiated_by INTEGER, fee_id INTEGER, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS audit_log (
      id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER REFERENCES users(id),
      action TEXT NOT NULL, entity TEXT, entity_id INTEGER, details TEXT,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS school_records (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      module_key TEXT NOT NULL,
      title TEXT NOT NULL,
      payload_json TEXT NOT NULL,
      student_id INTEGER REFERENCES students(id),
      class_name TEXT,
      event_date TEXT,
      amount_cedis REAL,
      status TEXT NOT NULL DEFAULT 'Recorded',
      created_by INTEGER REFERENCES users(id),
      updated_by INTEGER REFERENCES users(id),
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_school_records_module_date ON school_records(module_key,event_date);
    CREATE INDEX IF NOT EXISTS idx_school_records_student ON school_records(student_id);
    CREATE INDEX IF NOT EXISTS idx_students_class_status ON students(class_id,status);
    CREATE INDEX IF NOT EXISTS idx_students_admission_date ON students(admission_date);
    CREATE INDEX IF NOT EXISTS idx_students_name ON students(last_name,first_name);
    CREATE INDEX IF NOT EXISTS idx_fees_student_date ON fees(student_id,payment_date);
    CREATE INDEX IF NOT EXISTS idx_invoice_student ON fee_invoices(student_id,due_date);
    CREATE INDEX IF NOT EXISTS idx_parent_children_student ON parent_children(student_id);
    CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at);
    ''')
    student_cols={r[1] for r in conn.execute('PRAGMA table_info(students)').fetchall()}
    if 'photo_path' not in student_cols:
        conn.execute('ALTER TABLE students ADD COLUMN photo_path TEXT')
    user_cols={r[1] for r in conn.execute('PRAGMA table_info(users)').fetchall()}
    if 'must_change_password' not in user_cols:
        conn.execute('ALTER TABLE users ADD COLUMN must_change_password INTEGER NOT NULL DEFAULT 0')
    if 'subjects_taught' not in user_cols:
        conn.execute('ALTER TABLE users ADD COLUMN subjects_taught TEXT')
    default_admin=conn.execute('SELECT id,password_hash FROM users WHERE username=?',('admin',)).fetchone()
    if default_admin and check_password_hash(default_admin[1], 'ChangeMe123!'):
        conn.execute('UPDATE users SET must_change_password=1 WHERE id=?',(default_admin[0],))
    # This school's classes are Daycare, KG 1, KG 2, Primary 1-6 and JHS 1-3. Older databases used the names
    # Creche, Nursery and Kindergarten: rename them in place (same class ids) and fix every saved reference.
    renames = {'Creche': 'Daycare', 'Nursery': 'KG 1', 'Kindergarten': 'KG 2'}
    for old_name, new_name in renames.items():
        if conn.execute('SELECT 1 FROM classes WHERE name=?', (old_name,)).fetchone() and not conn.execute('SELECT 1 FROM classes WHERE name=?', (new_name,)).fetchone():
            conn.execute('UPDATE classes SET name=? WHERE name=?', (new_name, old_name))
            conn.execute('UPDATE users SET assigned_class=? WHERE assigned_class=?', (new_name, old_name))
            conn.execute('UPDATE school_records SET class_name=? WHERE class_name=?', (new_name, old_name))
    for rid, payload in conn.execute("SELECT id,payload_json FROM school_records WHERE payload_json LIKE '%class_name%'").fetchall():
        try: data = json.loads(payload)
        except (ValueError, TypeError): continue
        if isinstance(data, dict) and data.get('class_name') in renames:
            data['class_name'] = renames[data['class_name']]
            conn.execute('UPDATE school_records SET payload_json=? WHERE id=?', (json.dumps(data), rid))
    defaults = ['Daycare','KG 1','KG 2'] + [f'Primary {i}' for i in range(1,7)] + [f'JHS {i}' for i in range(1,4)]
    for name in defaults:
        conn.execute('INSERT OR IGNORE INTO classes(name) VALUES (?)', (name,))
    # Migrate existing one-child portal accounts into the normalized relationship table.
    conn.execute("INSERT OR IGNORE INTO parent_children(user_id,student_id) SELECT id,student_id FROM users WHERE role='Parent/Guardian' AND student_id IS NOT NULL")
    count = conn.execute('SELECT COUNT(*) FROM users').fetchone()[0]
    if count == 0:
        initial_password = os.environ.get('ADMIN_INITIAL_PASSWORD')
        initial_username = os.environ.get('ADMIN_INITIAL_USERNAME', 'admin').strip() or 'admin'
        if os.environ.get('APP_ENV', '').lower() == 'production' and (not initial_password or len(initial_password) < 16):
            conn.close()
            raise RuntimeError('For first production startup, set ADMIN_INITIAL_PASSWORD to a unique password of at least 16 characters.')
        initial_password = initial_password or 'ChangeMe123!'
        conn.execute('INSERT INTO users(username,password_hash,full_name,role,must_change_password) VALUES(?,?,?,?,1)',
                     (initial_username, generate_password_hash(initial_password), 'System Administrator', 'Administrator'))
    conn.commit(); conn.close()


SCHOOL_CODE=''.join(ch for ch in os.environ.get('SCHOOL_CODE','FJC').upper() if ch.isalnum()) or 'FJC'
DASHBOARD_ROLES={'Administrator','Proprietor','Headteacher','Admissions Officer','Class Teacher','Subject Teacher','Teacher'}

def home_url(user=None):
    """Landing page that each role is actually permitted to open."""
    user=user if user is not None else current_user()
    if not user: return url_for('login')
    role=user['role']
    if role in {'Parent/Guardian','Student'}: return url_for('portal')
    if role=='Accountant': return url_for('fees_directory')
    if role in DASHBOARD_ROLES: return url_for('dashboard')
    if role=='Librarian': return url_for('module_list',key='library')
    if role=='Storekeeper': return url_for('module_list',key='inventory')
    return url_for('module_list',key='calendar')

def _pw_fingerprint(password_hash):
    return hashlib.sha256(('fp:' + str(password_hash)).encode('utf-8')).hexdigest()[:20]


def current_user():
    if 'user' not in g:
        uid = session.get('user_id')
        user = db().execute('SELECT * FROM users WHERE id=? AND active=1', (uid,)).fetchone() if uid else None
        # A changed password ends every older session for that account.
        if user is not None and session.get('pwv') != _pw_fingerprint(user['password_hash']):
            user = None; session.clear()
        g.user = user
    return g.get('user')

def _my_children_count():
    u=current_user()
    if not u or u['role'] not in FAMILY_ROLES: return 0
    return db().execute('SELECT COUNT(*) FROM parent_children WHERE user_id=?',(u['id'],)).fetchone()[0]

@app.context_processor
def inject_globals():
    return {'home_url': home_url, 'current_user': current_user(), 'my_children_count': _my_children_count(), 'school_name': 'Fr. Joseph Connolly SVD Memorial School', 'today': date.today().isoformat()}


TEACHER_ROLES={'Class Teacher','Subject Teacher','Teacher'}
SUBJECT_TEACHER_CLASSES=['JHS 1','JHS 2','JHS 3']
ST_PREFIX='ST:'
SUBJECT_TEACHER_CHOICES=[('JHS 1','JHS 2'),('JHS 2','JHS 3'),('JHS 1','JHS 3'),('JHS 1','JHS 2','JHS 3')]
def st_value(names): return ST_PREFIX+','.join(names)
def st_label(names): return names[0] if len(names)==1 else ', '.join(names[:-1])+' & '+names[-1]
def parse_assigned(value):
    """Split a stored assigned_class into (class names, is_subject_teacher_choice). 'ST:JHS 1,JHS 2' is a subject-teacher choice; anything else is a plain class name."""
    value=(value or '').strip()
    if value.startswith(ST_PREFIX): return [n.strip() for n in value[len(ST_PREFIX):].split(',') if n.strip()], True
    return ([value] if value else []), False
def assigned_label(value):
    names,_=parse_assigned(value); return st_label(names) if names else ''
def normalise_assigned(role,value):
    """Validate the class chosen on the user form. Returns the value to store, or False when it is not allowed for the role."""
    value=(value or '').strip()
    if not value: return None
    names,is_st=parse_assigned(value)
    if is_st:
        if role!='Subject Teacher' or not names or any(n not in SUBJECT_TEACHER_CLASSES for n in names) or len(set(names))!=len(names): return False
        return st_value(sorted(names,key=SUBJECT_TEACHER_CLASSES.index))
    if role=='Subject Teacher' and value in SUBJECT_TEACHER_CLASSES: return st_value([value])
    return value
def class_scope(user):
    """Class names a signed-in teacher may work in, or None when the user is not class-limited.
    Class and general teachers: their assigned class. Subject teachers: the JHS classes chosen for them (one, two or all three);
    accounts created before this choice existed, or with no class chosen, keep JHS 1, JHS 2 and JHS 3."""
    if not user or user['role'] not in TEACHER_ROLES: return None
    names,is_st=parse_assigned(user['assigned_class'])
    if user['role']=='Subject Teacher' and not is_st:
        names+=[c for c in SUBJECT_TEACHER_CLASSES if c not in names]
    return names
app.jinja_env.filters['assigned_label']=assigned_label
STARTER_SUBJECTS=['English Language','Mathematics','Integrated Science','Social Studies','Religious & Moral Education','Computing','French','Ghanaian Language','Creative Arts & Design','Career Technology']
def user_subjects(user):
    """Subjects recorded on a user account (a JSON list), or []."""
    try: v=json.loads(user['subjects_taught'] or '[]')
    except (ValueError,TypeError,KeyError,IndexError): return []
    return [str(x) for x in v if str(x).strip()] if isinstance(v,list) else []
def subject_scope(user):
    """Subjects a Subject Teacher may enter results for, or None when any subject is allowed (no subjects set, or another role)."""
    if not user or user['role']!='Subject Teacher': return None
    return user_subjects(user) or None
def subject_catalogue():
    """Subject names from the Subjects & Teaching register; a starter JHS list until the register has entries."""
    names=sorted({str(r['payload'].get('subject_name','')).strip() for r in _records('subjects') if str(r['payload'].get('subject_name','')).strip()},key=str.casefold)
    return names or list(STARTER_SUBJECTS)
def clean_subjects(role,values,keep=()):
    """Validate the subjects chosen for a user. Returns (json text or None, error)."""
    if role!='Subject Teacher': return None,None
    allowed=set(subject_catalogue())|set(keep); out=[]
    for v in values:
        v=v.strip()
        if not v or v in out: continue
        if v not in allowed: return None,'Choose subjects from the school subject list.'
        out.append(v)
    return (json.dumps(out) if out else None),None
app.jinja_env.filters['subjects_label']=lambda v: ', '.join(user_subjects({'subjects_taught':v}))
def _in(names): return '('+','.join('?'*len(names))+')'

def login_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not current_user():
            flash('Please sign in to continue.', 'warning'); return redirect(url_for('login'))
        return fn(*args, **kwargs)
    return wrapped


def roles_required(*roles):
    def deco(fn):
        @wraps(fn)
        @login_required
        def wrapped(*args, **kwargs):
            if current_user()['role'] not in roles:
                abort(403)
            return fn(*args, **kwargs)
        return wrapped
    return deco


def audit(action, entity=None, entity_id=None, details=''):
    u = current_user()
    db().execute('INSERT INTO audit_log(user_id,action,entity,entity_id,details) VALUES(?,?,?,?,?)',
                 (u['id'] if u else None, action, entity, entity_id, details))
    db().commit()


def make_admission_no():
    year = date.today().year
    # Find the next unused sequence instead of relying on COUNT(), which breaks after deletions/imports.
    rows = db().execute("SELECT admission_no FROM students WHERE admission_no LIKE ?", (f'{SCHOOL_CODE}-{year}-%',)).fetchall()
    used = {r['admission_no'] for r in rows}
    n = 1
    while f'{SCHOOL_CODE}-{year}-{n:04d}' in used:
        n += 1
    return f'{SCHOOL_CODE}-{year}-{n:04d}'

@app.route('/')
def index():
    return redirect(home_url())

_DUMMY_HASH = generate_password_hash(secrets.token_hex(16))

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username','').strip()[:150]
        conn = db()
        attempt = conn.execute('SELECT attempts, locked_until FROM login_attempts WHERE username=?', (username,)).fetchone()
        now = time.time()
        if attempt and attempt['locked_until'] > now:
            flash('Too many sign-in attempts. Wait 15 minutes before trying again.', 'error')
            return render_template('login.html'), 429
        user = conn.execute('SELECT * FROM users WHERE username=? AND active=1', (username,)).fetchone()
        supplied_password = request.form.get('password', '')[:1024]
        # Always check a hash so the response time does not reveal whether a username exists.
        password_ok = check_password_hash(user['password_hash'] if user else _DUMMY_HASH, supplied_password)
        if user and password_ok:
            conn.execute('DELETE FROM login_attempts WHERE username=?', (username,)); conn.commit()
            session.clear(); session.permanent = True; session['user_id'] = user['id']; session['pwv'] = _pw_fingerprint(user['password_hash']); session['csrf'] = secrets.token_hex(32)
            audit('login','user',user['id'],'Successful sign-in')
            return redirect(url_for('change_password') if user['must_change_password'] else home_url(user))
        attempts = (attempt['attempts'] if attempt and attempt['locked_until'] <= now else 0) + 1
        locked_until = now + 900 if attempts >= 5 else 0
        conn.execute('INSERT INTO login_attempts(username,attempts,locked_until) VALUES(?,?,?) ON CONFLICT(username) DO UPDATE SET attempts=excluded.attempts, locked_until=excluded.locked_until', (username, attempts, locked_until)); conn.commit()
        flash('Invalid username or password.', 'error')
    return render_template('login.html')

@app.route('/logout', methods=['POST'])
@login_required
def logout():
    audit('logout','user',current_user()['id'],'Signed out'); session.clear(); return redirect(url_for('login'))

@app.before_request
def enforce_password_rotation():
    if request.endpoint not in ({'login','change_password','logout','static'} | PWA_ENDPOINTS) and current_user() and current_user()['must_change_password']:
        return redirect(url_for('change_password'))

@app.before_request
def csrf_guard():
    if request.method == 'POST' and request.endpoint not in ('login','paystack_webhook'):
        token = session.get('csrf')
        supplied = request.form.get('_csrf','')
        if not token or not secrets.compare_digest(token, supplied):
            abort(400, 'Your session token is missing or expired. Refresh the page and try again.')

@app.context_processor
def csrf_context():
    return {'csrf_token': session.get('csrf','')}

def dashboard_scene(conn, scope, scoped, show_fees, class_rows):
    """Per-class numbers for the 3D dashboard view. Same scope and permissions as the rest of the dashboard:
    enrolment counts follow the user's classes, and fee figures are only built for leadership roles."""
    scope_sql = f' AND c.name IN {_in(scope)}' if scoped else ''
    scope_args = list(scope) if scoped else []
    listed = {r['id'] for r in class_rows if r['id']}
    by_class = {}
    for r in conn.execute("SELECT s.class_id cid, COALESCE(NULLIF(s.gender,''),'Unspecified') g, COUNT(*) n FROM students s LEFT JOIN classes c ON c.id=s.class_id "
                          "WHERE s.status='Active'" + scope_sql + " GROUP BY s.class_id, g", scope_args):
        key = r['cid'] if r['cid'] in listed else None
        d = by_class.setdefault(key, {'boys': 0, 'girls': 0, 'other': 0})
        d['boys' if r['g'] == 'Male' else 'girls' if r['g'] == 'Female' else 'other'] += r['n']
    enrol = []
    for r in class_rows:
        d = by_class.get(r['id'], {'boys': 0, 'girls': 0, 'other': 0})
        enrol.append({'name': r['name'], 'boys': d['boys'], 'girls': d['girls'], 'other': d['other'], 'total': r['n']})
    fees = []
    if show_fees:
        acc = {}
        for r in conn.execute("""SELECT s.class_id cid, i.amount-i.discount net,
                                 COALESCE((SELECT SUM(f.amount) FROM fees f WHERE f.student_id=i.student_id AND f.purpose=i.invoice_no),0) paid
                                 FROM fee_invoices i JOIN students s ON s.id=i.student_id"""):
            key = r['cid'] if r['cid'] in listed else None
            a = acc.setdefault(key, {'billed': 0.0, 'paid': 0.0, 'outstanding': 0.0})
            a['billed'] += r['net']; a['paid'] += r['paid']; a['outstanding'] += max(0.0, r['net'] - r['paid'])
        for r in class_rows:
            a = acc.get(r['id'])
            if a is None and r['id'] is None: continue
            a = a or {'billed': 0.0, 'paid': 0.0, 'outstanding': 0.0}
            fees.append({'name': r['name'], **{k: round(v, 2) for k, v in a.items()}})
        if None in acc and not any(r['id'] is None for r in class_rows):
            fees.append({'name': 'Unassigned', **{k: round(v, 2) for k, v in acc[None].items()}})
    return {'enrol': enrol, 'fees': fees}

@app.route('/dashboard')
@roles_required(*sorted(DASHBOARD_ROLES))
def dashboard():
    conn = db(); user = current_user()
    scope = class_scope(user); scoped = scope is not None
    if scoped and not scope:
        abort(403)
    scope_sql = f' AND c.name IN {_in(scope)}' if scoped else ''
    scope_args = list(scope) if scoped else []
    base = 'FROM students s LEFT JOIN classes c ON c.id=s.class_id WHERE 1=1' + scope_sql
    today = date.today()

    total = conn.execute('SELECT COUNT(*) ' + base, scope_args).fetchone()[0]
    status_counts = {r['status']: r['n'] for r in conn.execute('SELECT s.status status, COUNT(*) n ' + base + ' GROUP BY s.status', scope_args)}
    active = status_counts.get('Active', 0)
    transferred = status_counts.get('Transferred', 0)
    withdrawn = status_counts.get('Withdrawn', 0)
    graduated = status_counts.get('Graduated', 0)

    # Gender is reported for ACTIVE students so it reconciles with the Active card and the class chart.
    genders = {'Male': 0, 'Female': 0, 'Other': 0, 'Unspecified': 0}
    for r in conn.execute("SELECT COALESCE(NULLIF(s.gender,''),'Unspecified') g, COUNT(*) n " + base + " AND s.status='Active' GROUP BY g", scope_args):
        genders[r['g'] if r['g'] in genders else 'Other'] += r['n']

    # Active enrolment per class. Anything not in a listed class is shown as Unassigned so the chart always adds up to Active.
    class_rows = [dict(r) for r in conn.execute(
        "SELECT c.id, c.name, COUNT(s.id) n FROM classes c LEFT JOIN students s ON s.class_id=c.id AND s.status='Active' "
        "WHERE c.active=1" + (f' AND c.name IN {_in(scope)}' if scoped else '') + " GROUP BY c.id ORDER BY c.id", scope_args)]
    unassigned = 0 if scoped else max(0, active - sum(r['n'] for r in class_rows))
    if unassigned:
        class_rows.append({'id': None, 'name': 'Unassigned', 'n': unassigned})

    # Admissions for the last 12 calendar months including the current one; empty months are shown as 0.
    months = []
    y, m = today.year, today.month
    for _ in range(12):
        months.append((y, m)); m -= 1
        if m == 0: y, m = y - 1, 12
    months.reverse()
    first_day = date(months[0][0], months[0][1], 1).isoformat()
    counts = {r['mo']: r['n'] for r in conn.execute(
        "SELECT substr(s.admission_date,1,7) mo, COUNT(*) n " + base + " AND s.admission_date>=? AND s.admission_date<=? GROUP BY mo",
        scope_args + [first_day, today.isoformat()])}
    month_rows = [{'key': f'{yy}-{mm:02d}', 'label': date(yy, mm, 1).strftime('%b %Y'), 'n': counts.get(f'{yy}-{mm:02d}', 0)} for yy, mm in months]
    new_this_month = month_rows[-1]['n']

    # Attendance entered today (scoped to a teacher's own class) and fees collected this month.
    # Fee totals are financial data: only leadership roles see them, never teachers or the admissions officer.
    att_sql = "SELECT COUNT(*) total, COALESCE(SUM(CASE WHEN status IN ('Present','Late') THEN 1 ELSE 0 END),0) present FROM school_records WHERE module_key='attendance' AND event_date=?"
    att_args = [today.isoformat()]
    if scoped:
        att_sql += f' AND class_name IN {_in(scope)}'; att_args += scope
    att = conn.execute(att_sql, att_args).fetchone()
    attendance_today, present_today = att['total'], att['present']
    show_fees = user['role'] in {'Administrator', 'Proprietor', 'Headteacher'}
    fees_month = conn.execute('SELECT COALESCE(SUM(amount),0) FROM fees WHERE payment_date>=? AND payment_date<=?', (today.replace(day=1).isoformat(), today.isoformat())).fetchone()[0] if show_fees else None
    recent = conn.execute('SELECT s.*, c.name class_name ' + base + ' ORDER BY s.created_at DESC, s.id DESC LIMIT 8', scope_args).fetchall()
    scene = dashboard_scene(conn, scope, scoped, show_fees, class_rows)
    return render_template('dashboard.html', scene=scene, scene_json=json.dumps(scene), total=total, active=active, transferred=transferred, withdrawn=withdrawn, graduated=graduated,
                           genders=genders, class_rows=class_rows, month_rows=month_rows, recent=recent, new_this_month=new_this_month,
                           class_count=len([r for r in class_rows if r['id']]), unassigned=unassigned,
                           attendance_today=attendance_today, present_today=present_today, fees_month=fees_month, show_fees=show_fees)

def _save_passport_photo(upload, category, old_path=None):
    """Validate, normalize and privately store a passport photograph."""
    if not upload or not upload.filename:
        return old_path
    if category not in {'students', 'staff'}:
        raise ValueError('Invalid photograph category.')
    limit = 5 * 1024 * 1024
    if upload.content_length and upload.content_length > limit:
        raise ValueError('Passport photo must be 5 MB or smaller.')
    data = upload.stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError('Passport photo must be 5 MB or smaller.')
    if not data:
        raise ValueError('Choose a photograph to upload.')
    try:
        from io import BytesIO
        with Image.open(BytesIO(data)) as source:
            if source.format not in {'JPEG', 'PNG', 'WEBP'}:
                raise ValueError('Upload a valid JPEG, PNG or WebP image.')
            if source.width < 50 or source.height < 50 or source.width > 8000 or source.height > 8000:
                raise ValueError('Photograph dimensions must be between 50 and 8000 pixels.')
            source.verify()
        with Image.open(BytesIO(data)) as source:
            image = ImageOps.exif_transpose(source).convert('RGB')
            image.thumbnail((1600, 1600))
            folder = os.path.join(document_upload_dir(), 'passport_photos', category)
            os.makedirs(folder, exist_ok=True)
            filename = uuid.uuid4().hex + '.jpg'
            target = os.path.join(folder, filename)
            image.save(target, format='JPEG', quality=88, optimize=True)
    except ValueError:
        raise
    except (UnidentifiedImageError, OSError, SyntaxError):
        raise ValueError('The selected file is not a valid, readable photograph.')
    return os.path.relpath(target, document_upload_dir()).replace(os.sep, '/')

@app.route('/private/passport/<path:photo_path>')
@login_required
def private_passport_photo(photo_path):
    # Resolve only paths stored by this application and keep all images private.
    root=os.path.realpath(os.path.join(document_upload_dir(),'passport_photos'))
    requested=photo_path.replace('\\','/')
    if requested.startswith('passport_photos/'):
        requested=requested[len('passport_photos/'):]
    target=os.path.realpath(os.path.join(root,requested))
    if not target.startswith(root + os.sep) or not os.path.isfile(target): abort(404)
    user=current_user(); role=user['role']
    stored=os.path.relpath(target,root).replace(os.sep,'/')
    if stored.startswith('students/'):
        canonical='passport_photos/'+stored
        row=db().execute('SELECT id,class_id FROM students WHERE photo_path=?',(canonical,)).fetchone()
        if not row: abort(404)
        if role in {'Parent/Guardian'}:
            allowed=db().execute('SELECT 1 FROM parent_children WHERE user_id=? AND student_id=?',(user['id'],row['id'])).fetchone()
            if not allowed: abort(403)
        elif role in FAMILY_ROLES and db().execute('SELECT 1 FROM parent_children WHERE user_id=? AND student_id=?',(user['id'],row['id'])).fetchone():
            pass  # a staff member who is also this pupil's parent
        elif role=='Student':
            if user['student_id'] != row['id']: abort(403)
        elif role in {'Administrator','Proprietor','Headteacher','Admissions Officer','Accountant'}:
            # Accountants need profile photographs for identity checks on fee and payment records.
            pass
        elif role in TEACHER_ROLES:
            class_row=db().execute('SELECT name FROM classes WHERE id=?',(row['class_id'],)).fetchone() if row['class_id'] else None
            if not class_row or class_row['name'] not in class_scope(user): abort(403)
        else: abort(403)
    elif stored.startswith('staff/'):
        if role not in {'Administrator','Proprietor','Headteacher','Accountant'}: abort(403)
        # Staff photo records are stored as payload JSON. Verify the requested
        # path is referenced by an existing staff record before serving it.
        found=False
        for item in db().execute("SELECT payload_json FROM school_records WHERE module_key='staff'").fetchall():
            try: payload=json.loads(item['payload_json'])
            except (ValueError,TypeError): continue
            if payload.get('passport_photo_path')=='passport_photos/'+stored: found=True; break
        if not found: abort(404)
    else: abort(404)
    response=send_file(target,conditional=True,max_age=0)
    response.headers['Cache-Control']='private, no-store'
    response.headers['X-Content-Type-Options']='nosniff'
    return response

@app.route('/students')
@roles_required(*STUDENT_ACCESS_ROLES)
def students():
    conn=db(); q=request.args.get('q','').strip(); selected_student=request.args.get('student_id',''); class_id=request.args.get('class_id',''); status=request.args.get('status',''); gender=request.args.get('gender','')
    sql='SELECT s.*, c.name class_name FROM students s LEFT JOIN classes c ON c.id=s.class_id WHERE 1=1'; args=[]
    if selected_student.isdigit(): sql += ' AND s.id=?'; args.append(int(selected_student))
    if q: sql += ' AND (s.first_name||\' \'||s.last_name LIKE ? OR s.admission_no LIKE ? OR s.guardian_phone LIKE ?)'; args += [f'%{q}%']*3
    if class_id.isdigit(): sql+=' AND s.class_id=?'; args.append(int(class_id))
    if status: sql+=' AND s.status=?'; args.append(status)
    if gender: sql+=' AND s.gender=?'; args.append(gender)
    _sc=class_scope(current_user())
    if _sc is not None:
        if not _sc: abort(403)
        sql+=f' AND c.name IN {_in(_sc)}'; args+=_sc
    sql+=' ORDER BY s.last_name,s.first_name'
    rows=conn.execute(sql,args).fetchall()
    return render_template('students.html', students=rows, student_choices=[x for x in conn.execute("SELECT s.id,s.admission_no,s.first_name,s.last_name,c.name class_name FROM students s LEFT JOIN classes c ON c.id=s.class_id ORDER BY s.last_name,s.first_name").fetchall() if _sc is None or x['class_name'] in _sc], classes=conn.execute('SELECT * FROM classes WHERE active=1 ORDER BY id').fetchall(), filters={'q':q,'student_id':selected_student,'class_id':class_id,'status':status,'gender':gender}, can_manage=current_user()['role'] in MANAGE_ROLES)

@app.route('/students/new', methods=['GET','POST'])
@roles_required(*MANAGE_ROLES)
def student_new():
    conn=db(); classes=conn.execute('SELECT * FROM classes WHERE active=1 ORDER BY id').fetchall()
    if request.method=='POST':
        f=request.form; first=f.get('first_name','').strip(); last=f.get('last_name','').strip(); adm=f.get('admission_no','').strip() or make_admission_no()
        valid_status={'Active','Transferred','Withdrawn','Graduated'}; valid_gender={'','Male','Female','Other'}
        try: date.fromisoformat(f.get('admission_date',''))
        except ValueError: flash('Enter a valid admission date.','error'); return render_template('student_form.html', student=None, classes=classes, admission_no=adm, title='Register student', form=request.form)
        if f.get('dob'):
            try: date.fromisoformat(f.get('dob'))
            except ValueError: flash('Enter a valid date of birth.','error'); return render_template('student_form.html', student=None, classes=classes, admission_no=adm, title='Register student', form=request.form)
        if not first or not last or not f.get('admission_date'):
            flash('First name, last name, and admission date are required.','error')
        elif f.get('status','Active') not in valid_status or f.get('gender','') not in valid_gender:
            flash('Choose a valid enrolment status and gender.','error')
        elif f.get('class_id','').isdigit() and not conn.execute('SELECT 1 FROM classes WHERE id=? AND active=1',(int(f['class_id']),)).fetchone():
            flash('Choose a valid active class.','error')
        elif f.get('dob') and date.fromisoformat(f['dob']) > date.today():
            flash('Date of birth cannot be in the future.','error')
        elif f.get('guardian_phone','').strip() and conn.execute('SELECT 1 FROM students WHERE lower(first_name)=lower(?) AND lower(last_name)=lower(?) AND dob=? AND guardian_phone=?',(first,last,f.get('dob') or None,f.get('guardian_phone','').strip())).fetchone():
            flash('A possible duplicate student exists with the same name, date of birth and guardian phone. Review the directory before registering again.','error')
        elif conn.execute('SELECT 1 FROM students WHERE admission_no=?',(adm,)).fetchone():
            flash('That admission number already exists. Please use a unique number.','error')
        else:
            class_id=int(f['class_id']) if f.get('class_id','').isdigit() else None
            try: photo_path=_save_passport_photo(request.files.get('passport_photo'),'students')
            except ValueError as exc:
                flash(str(exc),'error'); return render_template('student_form.html', student=None, classes=classes, admission_no=adm, title='Register student', form=request.form)
            cur=conn.execute('''INSERT INTO students(admission_no,first_name,last_name,dob,gender,nationality,address,admission_date,class_id,guardian_name,guardian_phone,guardian_email,guardian_occupation,guardian_address,emergency_name,emergency_phone,status,notes,photo_path)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(adm,first,last,f.get('dob') or None,f.get('gender') or None,f.get('nationality') or 'Ghanaian',f.get('address','').strip(),f['admission_date'],class_id,f.get('guardian_name','').strip(),f.get('guardian_phone','').strip(),f.get('guardian_email','').strip(),f.get('guardian_occupation','').strip(),f.get('guardian_address','').strip(),f.get('emergency_name','').strip(),f.get('emergency_phone','').strip(),f.get('status','Active'),f.get('notes','').strip(),photo_path))
            sid=cur.lastrowid
            cls=conn.execute('SELECT name FROM classes WHERE id=?',(class_id,)).fetchone()
            conn.execute('INSERT INTO enrolment_history(student_id,class_name,academic_year,term,status) VALUES(?,?,?,?,?)',(sid,cls['name'] if cls else '',date.today().year,'Current',f.get('status','Active')))
            conn.commit(); audit('create','student',sid,adm); flash(f'Student record saved. Admission number: {adm}','success'); return redirect(url_for('student_detail', student_id=sid))
    return render_template('student_form.html', student=None, classes=classes, admission_no=make_admission_no(), title='Register student', form=request.form)

@app.route('/students/<int:student_id>')
@roles_required(*STUDENT_ACCESS_ROLES)
def student_detail(student_id):
    conn=db(); s=conn.execute('SELECT s.*,c.name class_name FROM students s LEFT JOIN classes c ON c.id=s.class_id WHERE s.id=?',(student_id,)).fetchone()
    if not s: abort(404)
    u=current_user()
    _sc=class_scope(u)
    if _sc is not None and s['class_name'] not in _sc: abort(403)
    fees=conn.execute('SELECT * FROM fees WHERE student_id=? ORDER BY payment_date DESC,id DESC',(student_id,)).fetchall()
    history=conn.execute('SELECT * FROM enrolment_history WHERE student_id=? ORDER BY changed_at DESC',(student_id,)).fetchall()
    return render_template('student_detail.html', student=s, fees=fees, history=history, can_manage=u['role'] in MANAGE_ROLES, can_finance=u['role'] in FINANCE_ROLES)

@app.route('/students/<int:student_id>/edit', methods=['GET','POST'])
@roles_required(*MANAGE_ROLES)
def student_edit(student_id):
    conn=db(); s=conn.execute('SELECT * FROM students WHERE id=?',(student_id,)).fetchone()
    if not s: abort(404)
    classes=conn.execute('SELECT * FROM classes WHERE active=1 ORDER BY id').fetchall()
    if request.method=='POST':
        f=request.form; first=f.get('first_name','').strip(); last=f.get('last_name','').strip(); adm=f.get('admission_no','').strip()
        try: date.fromisoformat(f.get('admission_date',''))
        except ValueError: flash('Enter a valid admission date.','error'); return render_template('student_form.html', student=s, classes=classes, admission_no=s['admission_no'], title='Edit student', form=request.form if request.method=='POST' else None)
        if f.get('dob'):
            try: date.fromisoformat(f.get('dob'))
            except ValueError: flash('Enter a valid date of birth.','error'); return render_template('student_form.html', student=s, classes=classes, admission_no=s['admission_no'], title='Edit student', form=request.form if request.method=='POST' else None)
        if not first or not last or not adm or not f.get('admission_date'): flash('Name, admission number, and admission date are required.','error')
        elif f.get('status','Active') not in {'Active','Transferred','Withdrawn','Graduated'} or f.get('gender','') not in {'','Male','Female','Other'}: flash('Choose a valid enrolment status and gender.','error')
        elif conn.execute('SELECT 1 FROM students WHERE admission_no=? AND id<>?',(adm,student_id)).fetchone(): flash('Admission number is already assigned to another student.','error')
        else:
            class_id=int(f['class_id']) if f.get('class_id','').isdigit() else None
            old_class=conn.execute('SELECT name FROM classes WHERE id=?',(s['class_id'],)).fetchone()
            new_class=conn.execute('SELECT name FROM classes WHERE id=?',(class_id,)).fetchone()
            status=f.get('status','Active')
            try: photo_path=_save_passport_photo(request.files.get('passport_photo'),'students',s['photo_path'])
            except ValueError as exc:
                flash(str(exc),'error'); return render_template('student_form.html', student=s, classes=classes, admission_no=s['admission_no'], title='Edit student', form=request.form if request.method=='POST' else None)
            conn.execute('''UPDATE students SET photo_path=?,admission_no=?,first_name=?,last_name=?,dob=?,gender=?,nationality=?,address=?,admission_date=?,class_id=?,guardian_name=?,guardian_phone=?,guardian_email=?,guardian_occupation=?,guardian_address=?,emergency_name=?,emergency_phone=?,status=?,notes=?,updated_at=CURRENT_TIMESTAMP WHERE id=?''',
             (photo_path,adm,first,last,f.get('dob') or None,f.get('gender') or None,f.get('nationality') or 'Ghanaian',f.get('address','').strip(),f['admission_date'],class_id,f.get('guardian_name','').strip(),f.get('guardian_phone','').strip(),f.get('guardian_email','').strip(),f.get('guardian_occupation','').strip(),f.get('guardian_address','').strip(),f.get('emergency_name','').strip(),f.get('emergency_phone','').strip(),status,f.get('notes','').strip(),student_id))
            if (old_class['name'] if old_class else '') != (new_class['name'] if new_class else '') or status != s['status']:
                conn.execute('INSERT INTO enrolment_history(student_id,class_name,academic_year,term,status) VALUES(?,?,?,?,?)',(student_id,new_class['name'] if new_class else '',date.today().year,'Current',status))
            conn.commit(); audit('update','student',student_id,adm); flash('Student record updated.','success'); return redirect(url_for('student_detail',student_id=student_id))
    s=conn.execute('SELECT s.*,c.name class_name FROM students s LEFT JOIN classes c ON c.id=s.class_id WHERE s.id=?',(student_id,)).fetchone()
    return render_template('student_form.html', student=s, classes=classes, admission_no=s['admission_no'], title='Edit student', form=request.form if request.method=='POST' else None)

@app.route('/classes', methods=['GET','POST'])
@roles_required('Administrator','Headteacher')
def classes():
    conn=db()
    if request.method=='POST':
        name=request.form.get('name','').strip(); stream=request.form.get('stream','').strip()
        if not name: flash('Enter a class name.','error')
        else:
            try: conn.execute('INSERT INTO classes(name,stream) VALUES(?,?)',(name,stream)); conn.commit(); audit('create','class',None,name); flash('Class added.','success')
            except sqlite3.IntegrityError: flash('A class with this name already exists.','error')
        return redirect(url_for('classes'))
    rows=conn.execute('SELECT c.*,COUNT(s.id) student_count FROM classes c LEFT JOIN students s ON s.class_id=c.id AND s.status=\'Active\' GROUP BY c.id ORDER BY c.id').fetchall()
    return render_template('classes.html', classes=rows)

def _open_invoices(conn,student_id):
    """Invoices for a student with their remaining balance, for the payment form."""
    rows=conn.execute('''SELECT i.*,COALESCE((SELECT SUM(f.amount) FROM fees f WHERE f.student_id=i.student_id AND f.purpose=i.invoice_no),0) paid
      FROM fee_invoices i WHERE i.student_id=? ORDER BY i.due_date''',(student_id,)).fetchall()
    return [dict(r,balance=round(max(0,float(r['amount'])-float(r['discount'])-float(r['paid'])),2)) for r in rows]

@app.route('/fees/new/<int:student_id>', methods=['GET','POST'])
@roles_required('Administrator','Accountant')
def fee_new(student_id):
    conn=db(); s=conn.execute('SELECT s.*,c.name class_name FROM students s LEFT JOIN classes c ON c.id=s.class_id WHERE s.id=?',(student_id,)).fetchone()
    if not s: abort(404)
    if request.method=='POST':
        f=request.form
        try: amount=round(float(f.get('amount','0')),2)
        except (ValueError,TypeError): amount=0
        payment_date=f.get('payment_date') or date.today().isoformat()
        try: date.fromisoformat(payment_date)
        except ValueError: payment_date=''
        payment_method=f.get('payment_method','Cash')
        if not math.isfinite(amount) or amount<=0: flash('Enter a valid amount greater than zero.','error')
        elif not payment_date: flash('Enter a valid payment date.','error')
        elif payment_method not in {'Cash','Mobile Money','Bank transfer','Cheque','Other'}: flash('Choose a valid payment method.','error')
        elif not f.get('purpose','').strip(): flash('Enter the payment purpose.','error')
        else:
            purpose=f.get('purpose','').strip()
            invoice_no=f.get('invoice_no','').strip()
            notes=f.get('notes','').strip()
            def _back(): return render_template('fee_form.html',student=s,invoices=_open_invoices(conn,student_id),today=date.today().isoformat(),form=f)
            if invoice_no:
                invoice=conn.execute('SELECT invoice_no,amount,discount FROM fee_invoices WHERE invoice_no=? AND student_id=?',(invoice_no,student_id)).fetchone()
                if not invoice: flash('Choose a valid invoice for this student.','error'); return _back()
                already=conn.execute('SELECT COALESCE(SUM(amount),0) FROM fees WHERE student_id=? AND purpose=?',(student_id,invoice_no)).fetchone()[0]
                balance=round(float(invoice['amount'])-float(invoice['discount'])-float(already),2)
                if amount>balance+0.004:
                    flash(f'This payment (GH₵ {amount:.2f}) is more than the outstanding balance of GH₵ {max(balance,0):.2f} on {invoice_no}. Enter the correct amount or record it without linking to an invoice.','error'); return _back()
                if purpose and purpose!=invoice_no: notes=(f'Purpose: {purpose}. '+notes).strip()
                purpose=invoice['invoice_no']
            receipt=SCHOOL_CODE+'-R-'+datetime.now().strftime('%Y%m%d%H%M%S')+'-'+secrets.token_hex(2).upper()
            cur=conn.execute('INSERT INTO fees(receipt_no,student_id,amount,payment_date,payment_method,purpose,received_by,notes) VALUES(?,?,?,?,?,?,?,?)',(receipt,student_id,amount,payment_date,payment_method,purpose,current_user()['full_name'],notes))
            conn.commit(); audit('create','fee',cur.lastrowid,receipt)
            if f.get('sms_receipt')=='yes':
                sent_ok=_send_receipt_sms(s,amount,receipt)
                flash('Payment recorded. Receipt SMS sent to the guardian.' if sent_ok else 'Payment recorded, but the receipt SMS could not be sent.','success' if sent_ok else 'warning')
            else: flash('Payment recorded and receipt generated.','success')
            return redirect(url_for('receipt',fee_id=cur.lastrowid))
    return render_template('fee_form.html', student=s, invoices=_open_invoices(conn,student_id), today=date.today().isoformat(), form=request.form if request.method=='POST' else None)

@app.route('/receipts/<int:fee_id>')
@roles_required('Administrator','Accountant','Proprietor','Headteacher')
def receipt(fee_id):
    row=db().execute('SELECT f.*,s.admission_no,s.first_name,s.last_name,c.name class_name FROM fees f JOIN students s ON s.id=f.student_id LEFT JOIN classes c ON c.id=s.class_id WHERE f.id=?',(fee_id,)).fetchone()
    if not row: abort(404)
    return render_template('receipt.html', fee=row)

@app.route('/reports')
@roles_required('Administrator','Proprietor','Headteacher','Admissions Officer')
def reports():
    conn=db()
    rows=[dict(r) for r in conn.execute("SELECT c.name class_name,COUNT(s.id) total,COALESCE(SUM(CASE WHEN s.gender='Male' THEN 1 ELSE 0 END),0) male,COALESCE(SUM(CASE WHEN s.gender='Female' THEN 1 ELSE 0 END),0) female FROM classes c LEFT JOIN students s ON s.class_id=c.id AND s.status='Active' GROUP BY c.id ORDER BY c.id").fetchall()]
    extra=conn.execute("SELECT COUNT(*) total,COALESCE(SUM(CASE WHEN gender='Male' THEN 1 ELSE 0 END),0) male,COALESCE(SUM(CASE WHEN gender='Female' THEN 1 ELSE 0 END),0) female FROM students WHERE status='Active' AND (class_id IS NULL OR class_id NOT IN (SELECT id FROM classes))").fetchone()
    if extra['total']: rows.append({'class_name':'Unassigned','total':extra['total'],'male':extra['male'],'female':extra['female']})
    for r in rows: r['other']=r['total']-r['male']-r['female']
    totals=conn.execute("SELECT COUNT(*) n FROM students WHERE status='Active'").fetchone()['n']
    return render_template('reports.html', rows=rows, totals=totals)

@app.route('/invoices')
@roles_required('Administrator','Accountant','Proprietor','Headteacher')
def invoices():
    q=request.args.get('q','').strip()
    rows=db().execute('''SELECT i.*,s.admission_no,s.first_name,s.last_name,c.name class_name,
      COALESCE((SELECT SUM(f.amount) FROM fees f WHERE f.student_id=i.student_id AND f.purpose=i.invoice_no),0) paid
      FROM fee_invoices i JOIN students s ON s.id=i.student_id LEFT JOIN classes c ON c.id=s.class_id
      WHERE s.first_name||' '||s.last_name LIKE ? OR s.admission_no LIKE ? OR i.invoice_no LIKE ?
      ORDER BY i.due_date DESC,i.id DESC LIMIT 500''',(f'%{q}%',f'%{q}%',f'%{q}%')).fetchall()
    rows=[dict(r, balance=max(0,float(r['amount'])-float(r['discount'])-float(r['paid']))) for r in rows]
    return render_template('invoices.html',invoices=rows,q=q,can_manage=current_user()['role'] in {'Administrator','Accountant'})

@app.route('/invoices/<int:invoice_id>/print')
@roles_required('Administrator','Accountant','Proprietor','Headteacher')
def invoice_doc(invoice_id):
    conn=db()
    inv=conn.execute('''SELECT i.*,s.admission_no,s.first_name,s.last_name,s.guardian_name,c.name class_name FROM fee_invoices i
      JOIN students s ON s.id=i.student_id LEFT JOIN classes c ON c.id=s.class_id WHERE i.id=?''',(invoice_id,)).fetchone()
    if not inv: abort(404)
    pays=conn.execute('SELECT * FROM fees WHERE student_id=? AND purpose=? ORDER BY payment_date,id',(inv['student_id'],inv['invoice_no'])).fetchall()
    paid=round(sum(float(x['amount']) for x in pays),2); net=round(float(inv['amount'])-float(inv['discount']),2)
    return render_template('invoice_doc.html',inv=inv,pays=pays,paid=paid,net=net,balance=round(max(0.0,net-paid),2),issued=date.today().isoformat())

@app.route('/invoices/new',methods=['GET','POST'])
@roles_required('Administrator','Accountant')
def invoice_new():
    conn=db()
    if request.method=='POST':
        f=request.form; student=f.get('student_id',''); year=f.get('academic_year','').strip(); term=f.get('term',''); desc=f.get('description','').strip(); due=f.get('due_date','')
        try: amount=round(float(f.get('amount','')),2); discount=round(float(f.get('discount','0') or 0),2); date.fromisoformat(due)
        except (ValueError,TypeError): amount=-1; discount=-1
        valid_terms={'Term 1','Term 2','Term 3'}
        if not student.isdigit() or not conn.execute("SELECT 1 FROM students WHERE id=? AND status='Active'",(int(student),)).fetchone(): flash('Select an active student.','error')
        elif not year or term not in valid_terms or not desc or len(desc)>200: flash('Enter an academic year, valid term and description.','error')
        elif amount<0 or discount<0 or discount>amount: flash('Amount and discount must be valid, and discount cannot exceed amount.','error')
        elif not due: flash('Enter a due date.','error')
        else:
            inv=SCHOOL_CODE+'-INV-'+datetime.now().strftime('%Y%m%d')+'-'+secrets.token_hex(3).upper()
            cur=conn.execute('INSERT INTO fee_invoices(invoice_no,student_id,academic_year,term,description,amount,discount,due_date,created_by) VALUES(?,?,?,?,?,?,?,?,?)',(inv,int(student),year,term,desc,amount,discount,due,current_user()['id']))
            conn.commit(); audit('create','invoice',cur.lastrowid,inv); flash('Fee invoice created. Record payments using the exact invoice number as payment purpose to apply them to this invoice.','success'); return redirect(url_for('invoices'))
    students=conn.execute("SELECT id,admission_no,first_name,last_name FROM students WHERE status='Active' ORDER BY last_name,first_name").fetchall()
    return render_template('invoice_form.html',students=students,today=date.today().isoformat())

@app.route('/reports/attendance')
@roles_required('Administrator','Proprietor','Headteacher','Class Teacher','Subject Teacher','Teacher')
def attendance_report():
    user=current_user(); class_filter=request.args.get('class_name','').strip(); start_date=request.args.get('start_date','').strip(); end_date=request.args.get('end_date','').strip()
    _sc=class_scope(user)
    if _sc is not None:
        if not _sc: abort(403)
        if class_filter and class_filter not in _sc: abort(403)
        if not class_filter and len(_sc)==1: class_filter=_sc[0]
    for value in (start_date,end_date):
        if value:
            try: date.fromisoformat(value)
            except ValueError: abort(400)
    if start_date and end_date and start_date>end_date: abort(400)
    students=db().execute("SELECT s.id,s.admission_no,s.first_name,s.last_name,s.photo_path,c.name class_name FROM students s LEFT JOIN classes c ON c.id=s.class_id WHERE s.status='Active' "+('AND c.name=? ' if class_filter else (f'AND c.name IN {_in(_sc)} ' if _sc else ''))+'ORDER BY c.id,s.last_name,s.first_name',([class_filter] if class_filter else (list(_sc) if _sc else []))).fetchall()
    results=[]
    for student in students:
        rows=db().execute("SELECT payload_json FROM school_records WHERE module_key='attendance' AND student_id=?",(student['id'],)).fetchall()
        counts={'Present':0,'Late':0,'Absent':0,'Authorised absence':0}
        for row in rows:
            try: p=json.loads(row['payload_json'])
            except (ValueError,TypeError): continue
            event=p.get('event_date','')
            if start_date and event<start_date: continue
            if end_date and event>end_date: continue
            status=p.get('attendance_status')
            if status in counts: counts[status]+=1
        total=sum(counts.values())
        if total:
            attended=counts['Present']+counts['Late']
            results.append({'student':student,'counts':counts,'total':total,'attended':attended,'percentage':attended/total*100})
    return render_template('attendance_report.html',rows=results,classes=[c for c in db().execute('SELECT name FROM classes WHERE active=1 ORDER BY id').fetchall() if _sc is None or c['name'] in _sc],class_filter=class_filter,start_date=start_date,end_date=end_date)

def _report_extras(student_id, year, term, terms):
    """Attendance for the term, outstanding fees and the next term's opening date, for a printed report card."""
    start=end=None
    for t in terms:
        pl=t['payload']
        if pl.get('academic_year')==year and pl.get('term')==term: start,end=_parse_date(pl.get('start_date')),_parse_date(pl.get('end_date'))
    att={'present':0,'late':0,'absent':0,'authorised':0}
    for r in db().execute("SELECT payload_json,event_date FROM school_records WHERE module_key='attendance' AND student_id=?",(student_id,)).fetchall():
        d=_parse_date(r['event_date'])
        if start and end and (not d or d<start or d>end): continue
        try: st=str(json.loads(r['payload_json']).get('attendance_status',''))
        except (ValueError,TypeError): continue
        if st=='Present': att['present']+=1
        elif st=='Late': att['late']+=1
        elif st.startswith('Authorised'): att['authorised']+=1
        elif st=='Absent': att['absent']+=1
    owing=db().execute('''SELECT COALESCE(SUM(MAX(0,i.amount-i.discount-COALESCE((SELECT SUM(f.amount) FROM fees f WHERE f.student_id=i.student_id AND f.purpose=i.invoice_no),0))),0) FROM fee_invoices i WHERE i.student_id=?''',(student_id,)).fetchone()[0]
    nxt=''
    if end:
        later=sorted((_parse_date(t['payload'].get('start_date')),t['payload'].get('term',''),t['payload'].get('academic_year','')) for t in terms if _parse_date(t['payload'].get('start_date')) and _parse_date(t['payload'].get('start_date'))>end)
        if later: nxt=later[0][0].isoformat()
    return {'attendance':att,'attendance_total':sum(att.values()),'fees_owing':round(float(owing),2),'next_term':nxt}

@app.route('/reports/report-cards')
@roles_required('Administrator','Proprietor','Headteacher','Class Teacher','Subject Teacher','Teacher')
def report_cards():
    user=current_user(); class_filter=request.args.get('class_name','').strip(); year=request.args.get('academic_year','').strip(); term=request.args.get('term','').strip()
    _sc=class_scope(user)
    if _sc is not None:
        if not _sc: abort(403)
        if class_filter and class_filter not in _sc: abort(403)
        if not class_filter and len(_sc)==1: class_filter=_sc[0]
    if term and term not in {'Term 1','Term 2','Term 3'}: abort(400)
    if 'academic_year' not in request.args and 'term' not in request.args:
        _cur=_current_term()
        if _cur: year,term=_cur
    _scale=_grade_scale()
    students=db().execute("SELECT s.id,s.admission_no,s.first_name,s.last_name,c.name class_name FROM students s LEFT JOIN classes c ON c.id=s.class_id WHERE s.status='Active' "+('AND c.name=? ' if class_filter else (f'AND c.name IN {_in(_sc)} ' if _sc else ''))+'ORDER BY c.id,s.last_name,s.first_name',([class_filter] if class_filter else (list(_sc) if _sc else []))).fetchall()
    cards=[]
    for student in students:
        records=db().execute("SELECT payload_json FROM school_records WHERE module_key='assessments' AND student_id=? ORDER BY event_date,id",(student['id'],)).fetchall()
        subjects={}
        for row in records:
            try: p=json.loads(row['payload_json'])
            except (ValueError,TypeError): continue
            if year and p.get('academic_year')!=year: continue
            if term and p.get('term')!=term: continue
            try: score=float(p.get('score',0)); maximum=float(p.get('maximum_score',0))
            except (TypeError,ValueError): continue
            if maximum<=0: continue
            name=p.get('subject_name','Unspecified subject')
            subjects.setdefault(name,[]).append((score/maximum*100,p.get('teacher_comment','')))
        if subjects:
            subject_rows=[]
            for name,vals in sorted(subjects.items()):
                avg=sum(v[0] for v in vals)/len(vals)
                grade,remark=_grade_for(avg,_scale)
                subject_rows.append({'name':name,'average':avg,'grade':grade,'remark':remark,'comment':next((v[1] for v in reversed(vals) if v[1]),'')})
            _avg=sum(x['average'] for x in subject_rows)/len(subject_rows); _g,_r=_grade_for(_avg,_scale)
            cards.append({'student':student,'subjects':subject_rows,'average':_avg,'grade':_g,'remark':_r})
    for _name in {c['student']['class_name'] for c in cards}:
        _group=sorted([c for c in cards if c['student']['class_name']==_name],key=lambda c:-c['average'])
        for _i,_c in enumerate(_group):
            _c['position']=1+sum(1 for o in _group if o['average']>_c['average']); _c['of']=len(_group)
    _terms=_records('terms')
    for _c in cards: _c.update(_report_extras(_c['student']['id'],year,term,_terms))
    classes=[c for c in db().execute('SELECT name FROM classes WHERE active=1 ORDER BY id').fetchall() if _sc is None or c['name'] in _sc]
    return render_template('report_cards.html',cards=cards,classes=classes,class_filter=class_filter,year=year,term=term,generated=date.today().isoformat(),grade_note=_scale_note(_scale))

@app.route('/export/students.csv')
@login_required
def export_students():
    u=current_user()
    if u['role'] not in STUDENT_ACCESS_ROLES: abort(403)
    q=request.args.get('q','').strip(); selected_student=request.args.get('student_id',''); class_id=request.args.get('class_id',''); status=request.args.get('status',''); gender=request.args.get('gender','')
    sql='SELECT s.admission_no,s.first_name,s.last_name,s.dob,s.gender,s.admission_date,c.name class_name,s.status,s.guardian_name,s.guardian_phone FROM students s LEFT JOIN classes c ON c.id=s.class_id WHERE 1=1'; args=[]
    if selected_student.isdigit(): sql+=' AND s.id=?'; args.append(int(selected_student))
    if q: sql+=' AND (s.first_name||\' \'||s.last_name LIKE ? OR s.admission_no LIKE ?)'; args += [f'%{q}%']*2
    if class_id.isdigit(): sql+=' AND s.class_id=?'; args.append(int(class_id))
    if status: sql+=' AND s.status=?'; args.append(status)
    if gender: sql+=' AND s.gender=?'; args.append(gender)
    _sc=class_scope(u)
    if _sc is not None:
        if not _sc: abort(403)
        sql+=f' AND c.name IN {_in(_sc)}'; args+=_sc
    sql+=' ORDER BY s.last_name,s.first_name'
    rows=db().execute(sql,args).fetchall()
    out=io.StringIO(); writer=csv.writer(out); writer.writerow(['Admission Number','First Name','Last Name','Date of Birth','Gender','Admission Date','Class','Status','Guardian','Guardian Phone'])
    for r in rows:
        safe = []
        for value in list(r):
            if isinstance(value, str) and value[:1] in ('=', '+', '-', '@', '\t', '\r'):
                value = "'" + value
            safe.append(value)
        writer.writerow(safe)
    response=make_response('\ufeff'+out.getvalue()); response.headers['Content-Type']='text/csv; charset=utf-8'; response.headers['Content-Disposition']='attachment; filename=kings_gate_students.csv'; audit('export','students',None,f'{len(rows)} records'); return response

@app.route('/fees/new')
@roles_required('Administrator','Accountant')
def fee_student_select():
    q=request.args.get('q','').strip()
    rows=db().execute('''SELECT id,admission_no,first_name,last_name FROM students
      WHERE status='Active' AND (first_name||' '||last_name LIKE ? OR admission_no LIKE ?)
      ORDER BY last_name,first_name LIMIT 100''',(f'%{q}%',f'%{q}%')).fetchall()
    return render_template('fee_student_select.html', students=rows, q=q)

@app.route('/fees')
@roles_required('Administrator','Accountant','Proprietor','Headteacher')
def fees_directory():
    q=request.args.get('q','').strip()
    rows=db().execute('''SELECT f.*,s.admission_no,s.first_name,s.last_name,c.name class_name
      FROM fees f JOIN students s ON s.id=f.student_id LEFT JOIN classes c ON c.id=s.class_id
      WHERE s.first_name||' '||s.last_name LIKE ? OR s.admission_no LIKE ? OR f.receipt_no LIKE ?
      ORDER BY f.payment_date DESC,f.id DESC LIMIT 500''',(f'%{q}%',f'%{q}%',f'%{q}%')).fetchall()
    total=db().execute('SELECT COALESCE(SUM(amount),0) FROM fees').fetchone()[0]
    match=db().execute('''SELECT COALESCE(SUM(f.amount),0) amt,COUNT(*) n FROM fees f JOIN students s ON s.id=f.student_id
      WHERE s.first_name||' '||s.last_name LIKE ? OR s.admission_no LIKE ? OR f.receipt_no LIKE ?''',(f'%{q}%',f'%{q}%',f'%{q}%')).fetchone()
    return render_template('fees.html', fees=rows, q=q, total=total, match_total=match['amt'], match_count=match['n'], can_record=current_user()['role'] in {'Administrator','Accountant'})

@app.route('/export/students.xlsx')
@roles_required(*STUDENT_ACCESS_ROLES)
def export_students_xlsx():
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    u=current_user(); q=request.args.get('q','').strip(); selected_student=request.args.get('student_id',''); class_id=request.args.get('class_id',''); status=request.args.get('status',''); gender=request.args.get('gender','')
    sql='SELECT s.admission_no,s.first_name,s.last_name,s.dob,s.gender,s.admission_date,c.name class_name,s.status,s.guardian_name,s.guardian_phone FROM students s LEFT JOIN classes c ON c.id=s.class_id WHERE 1=1'; args=[]
    if selected_student.isdigit(): sql+=' AND s.id=?'; args.append(int(selected_student))
    if q: sql+=' AND (s.first_name||\' \'||s.last_name LIKE ? OR s.admission_no LIKE ?)'; args += [f'%{q}%']*2
    if class_id.isdigit(): sql+=' AND s.class_id=?'; args.append(int(class_id))
    if status: sql+=' AND s.status=?'; args.append(status)
    if gender: sql+=' AND s.gender=?'; args.append(gender)
    _sc=class_scope(u)
    if _sc is not None:
        if not _sc: abort(403)
        sql+=f' AND c.name IN {_in(_sc)}'; args+=_sc
    sql+=' ORDER BY s.last_name,s.first_name'; rows=db().execute(sql,args).fetchall()
    wb=Workbook(); ws=wb.active; ws.title='Student records'
    ws.append(['Admission Number','First Name','Last Name','Date of Birth','Gender','Admission Date','Class','Status','Guardian','Guardian Phone'])
    for cell in ws[1]: cell.font=Font(bold=True,color='FFFFFF'); cell.fill=PatternFill('solid',fgColor='50106E'); cell.alignment=Alignment(horizontal='center')
    for row in rows: ws.append([row[k] for k in ['admission_no','first_name','last_name','dob','gender','admission_date','class_name','status','guardian_name','guardian_phone']])
    ws.freeze_panes='A2'; ws.auto_filter.ref=ws.dimensions
    for col in ws.columns:
        letter=col[0].column_letter; ws.column_dimensions[letter].width=min(max(max(len(str(c.value or '')) for c in col)+2,14),32)
    out=io.BytesIO(); wb.save(out); out.seek(0); audit('export','students',None,f'XLSX {len(rows)} records')
    return send_file(out,as_attachment=True,download_name='kings_gate_students.xlsx',mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

@app.route('/export/students.pdf')
@roles_required(*STUDENT_ACCESS_ROLES)
def export_students_pdf():
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import landscape, A4
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet
    u=current_user(); sql='SELECT s.admission_no,s.first_name||\' \'||s.last_name full_name,c.name class_name,s.gender,s.admission_date,s.status FROM students s LEFT JOIN classes c ON c.id=s.class_id WHERE 1=1'; args=[]
    q=request.args.get('q','').strip(); selected_student=request.args.get('student_id',''); class_id=request.args.get('class_id',''); status=request.args.get('status',''); gender=request.args.get('gender','')
    if selected_student.isdigit(): sql+=' AND s.id=?'; args.append(int(selected_student))
    if q: sql+=' AND (s.first_name||\' \'||s.last_name LIKE ? OR s.admission_no LIKE ?)'; args += [f'%{q}%']*2
    if class_id.isdigit(): sql+=' AND s.class_id=?'; args.append(int(class_id))
    if status: sql+=' AND s.status=?'; args.append(status)
    if gender: sql+=' AND s.gender=?'; args.append(gender)
    _sc=class_scope(u)
    if _sc is not None:
        if not _sc: abort(403)
        sql+=f' AND c.name IN {_in(_sc)}'; args+=_sc
    sql+=' ORDER BY s.last_name,s.first_name'; rows=db().execute(sql,args).fetchall()
    out=io.BytesIO(); doc=SimpleDocTemplate(out,pagesize=landscape(A4),rightMargin=24,leftMargin=24,topMargin=24,bottomMargin=24); styles=getSampleStyleSheet()
    story=[Paragraph('Fr. Joseph Connolly SVD Memorial School',styles['Title']),Paragraph('Student directory report. Faith • Knowledge • Service.',styles['Normal']),Spacer(1,12)]
    data=[['Admission Number','Student Name','Class','Gender','Admission Date','Status']]
    data += [[str(r[k] or '') for k in ['admission_no','full_name','class_name','gender','admission_date','status']] for r in rows]
    table=Table(data,repeatRows=1,colWidths=[125,180,100,70,100,75]); table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#50106e')),('TEXTCOLOR',(0,0),(-1,0),colors.white),('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),('GRID',(0,0),(-1,-1),0.35,colors.HexColor('#dddddd')),('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#f6f2fa')]),('FONTSIZE',(0,0),(-1,-1),8),('VALIGN',(0,0),(-1,-1),'TOP')]))
    story.append(table); doc.build(story); out.seek(0); audit('export','students',None,f'PDF {len(rows)} records')
    return send_file(out,as_attachment=True,download_name='kings_gate_students.pdf',mimetype='application/pdf')

IMPORT_COLUMNS = ['Admission Number','First Name','Last Name','Admission Date','Date of Birth','Gender','Class','Nationality','Residential Address','Guardian Name','Guardian Phone','Guardian Email','Guardian Occupation','Guardian Address','Emergency Name','Emergency Phone','Status']

@app.route('/import', methods=['GET','POST'])
@roles_required('Administrator','Headteacher','Admissions Officer')
def import_students():
    if request.method == 'GET':
        return render_template('import.html', columns=IMPORT_COLUMNS)
    action=request.form.get('action','preview')
    if action == 'confirm':
        token=session.get('student_import_token'); conn=db(); imported=0
        batch=conn.execute('SELECT * FROM import_batches WHERE token=? AND user_id=?',(token,current_user()['id'])).fetchone() if token else None
        if not batch or time.time()-batch['created_at']>1800:
            if batch: conn.execute('DELETE FROM import_batches WHERE token=?',(token,)); conn.commit()
            flash('Import preview expired. Upload the file again.', 'error'); return redirect(url_for('import_students'))
        rows=json.loads(batch['rows_json']); errors=json.loads(batch['errors_json'])
        try:
            conn.execute('BEGIN IMMEDIATE')
            for row in rows:
                if conn.execute('SELECT 1 FROM students WHERE admission_no=?',(row['admission_no'],)).fetchone():
                    errors.append(f"{row['admission_no']}: admission number already exists."); continue
                cls=conn.execute('SELECT id FROM classes WHERE name=? AND active=1',(row['class_name'],)).fetchone() if row['class_name'] else None
                cur=conn.execute('''INSERT INTO students(admission_no,first_name,last_name,dob,gender,nationality,address,admission_date,class_id,guardian_name,guardian_phone,guardian_email,guardian_occupation,guardian_address,emergency_name,emergency_phone,status)
                  VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(row['admission_no'],row['first_name'],row['last_name'],row['dob'] or None,row['gender'] or None,row['nationality'] or 'Ghanaian',row['address'],row['admission_date'],cls['id'] if cls else None,row['guardian_name'],row['guardian_phone'],row['guardian_email'],row['guardian_occupation'],row['guardian_address'],row['emergency_name'],row['emergency_phone'],row['status']))
                conn.execute('INSERT INTO enrolment_history(student_id,class_name,academic_year,term,status) VALUES(?,?,?,?,?)',(cur.lastrowid,row['class_name'],str(date.today().year),'Current',row['status'])); imported+=1
            conn.execute('DELETE FROM import_batches WHERE token=?',(token,)); conn.commit(); session.pop('student_import_token',None); audit('import','students',None,f'{imported} records imported')
        except Exception:
            conn.rollback(); raise
        flash(f'Import complete. {imported} records saved. {len(errors)} rows skipped.', 'success' if imported else 'warning')
        for err in errors[:8]: flash(err,'warning')
        return redirect(url_for('students'))
    upload=request.files.get('file')
    if not upload or not upload.filename or not upload.filename.lower().endswith(('.xlsx','.csv')):
        flash('Upload an .xlsx or .csv file.', 'error'); return redirect(url_for('import_students'))
    try:
        if upload.filename.lower().endswith('.xlsx'):
            from openpyxl import load_workbook
            wb=load_workbook(upload,read_only=True,data_only=True); ws=wb.active; raw=list(ws.iter_rows(values_only=True)); wb.close()
        else:
            raw=list(csv.reader(io.TextIOWrapper(upload.stream,encoding='utf-8-sig',newline='')))
        if not raw: raise ValueError('The uploaded file is empty.')
        if len(raw)>501: raise ValueError('Maximum import size is 500 student rows.')
        def norm(x): return re.sub(r'[^a-z0-9]+','',str(x or '').lower())
        header_map={norm(h):i for i,h in enumerate(raw[0])}
        aliases={'admissionnumber':['admissionnumber','admissionno'],'firstname':['firstname'],'lastname':['lastname','surname'],'admissiondate':['admissiondate'],'dateofbirth':['dateofbirth','dob'],'gender':['gender'],'class':['class','classname'],'nationality':['nationality'],'address':['residentialaddress','address'],'guardianname':['guardianname'],'guardianphone':['guardianphone'],'guardianemail':['guardianemail'],'guardianoccupation':['guardianoccupation'],'guardianaddress':['guardianaddress'],'emergencyname':['emergencyname'],'emergencyphone':['emergencyphone'],'status':['status','enrolmentstatus']}
        mapped={k:next((header_map[a] for a in opts if a in header_map),None) for k,opts in aliases.items()}
        for required in ('firstname','lastname','admissiondate'):
            if mapped[required] is None: raise ValueError('Required columns are First Name, Last Name and Admission Date. Use the downloadable template.')
        known_classes={r['name'] for r in db().execute('SELECT name FROM classes WHERE active=1').fetchall()}; seen=set(); valid=[]; errors=[]
        def val(cells,key):
            idx=mapped.get(key)
            if idx is None or idx>=len(cells) or cells[idx] is None: return ''
            v=cells[idx]
            if isinstance(v,datetime): return v.date().isoformat()
            if isinstance(v,date): return v.isoformat()
            return str(v).strip()
        for line,cells in enumerate(raw[1:],2):
            if not any(str(v or '').strip() for v in cells): continue
            first,last=val(cells,'firstname'),val(cells,'lastname'); adm=val(cells,'admissionnumber'); adm_date=val(cells,'admissiondate')
            if not adm:
                year=date.today().year; n=1
                while f'{SCHOOL_CODE}-{year}-{n:04d}' in seen or db().execute('SELECT 1 FROM students WHERE admission_no=?',(f'{SCHOOL_CODE}-{year}-{n:04d}',)).fetchone(): n+=1
                adm=f'{SCHOOL_CODE}-{year}-{n:04d}'
            if not first or not last or not adm_date: errors.append(f'Row {line}: first name, last name and admission date are required.'); continue
            try: date.fromisoformat(adm_date[:10]); adm_date=adm_date[:10]
            except ValueError: errors.append(f'Row {line}: invalid admission date. Use YYYY-MM-DD.'); continue
            dob=val(cells,'dateofbirth')
            if dob:
                try: date.fromisoformat(dob[:10]); dob=dob[:10]
                except ValueError: errors.append(f'Row {line}: invalid date of birth.'); continue
            gender=val(cells,'gender')
            if gender and gender not in {'Male','Female','Other'}: errors.append(f'Row {line}: gender must be Male, Female or Other.'); continue
            cls=val(cells,'class')
            if cls and cls not in known_classes: errors.append(f'Row {line}: unknown class {cls}.'); continue
            status=val(cells,'status') or 'Active'
            if status not in {'Active','Transferred','Withdrawn','Graduated'}: errors.append(f'Row {line}: invalid status.'); continue
            if adm in seen or db().execute('SELECT 1 FROM students WHERE admission_no=?',(adm,)).fetchone(): errors.append(f'Row {line}: duplicate admission number {adm}.'); continue
            seen.add(adm); valid.append({'admission_no':adm[:80],'first_name':first[:100],'last_name':last[:100],'admission_date':adm_date,'dob':dob,'gender':gender,'class_name':cls,'nationality':val(cells,'nationality') or 'Ghanaian','address':val(cells,'address')[:500],'guardian_name':val(cells,'guardianname')[:150],'guardian_phone':val(cells,'guardianphone')[:50],'guardian_email':val(cells,'guardianemail')[:150],'guardian_occupation':val(cells,'guardianoccupation')[:150],'guardian_address':val(cells,'guardianaddress')[:500],'emergency_name':val(cells,'emergencyname')[:150],'emergency_phone':val(cells,'emergencyphone')[:50],'status':status})
        token=secrets.token_urlsafe(24); conn=db()
        conn.execute('DELETE FROM import_batches WHERE created_at<?',(time.time()-1800,))
        conn.execute('INSERT INTO import_batches(token,user_id,rows_json,errors_json,created_at) VALUES(?,?,?,?,?)',(token,current_user()['id'],json.dumps(valid),json.dumps(errors),time.time())); conn.commit()
        session['student_import_token']=token
        return render_template('import_preview.html',rows=valid,errors=errors)
    except Exception as exc:
        flash(f'Could not read import file: {exc}', 'error'); return redirect(url_for('import_students'))

@app.route('/import/template.xlsx')
@roles_required('Administrator','Headteacher','Admissions Officer')
def import_template():
    from openpyxl import Workbook
    wb=Workbook(); ws=wb.active; ws.title='Student import'; ws.append(IMPORT_COLUMNS); ws.freeze_panes='A2'; ws.auto_filter.ref=ws.dimensions
    out=io.BytesIO(); wb.save(out); out.seek(0)
    return send_file(out,as_attachment=True,download_name='kings_gate_student_import_template.xlsx',mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

@app.route('/users', methods=['GET','POST'])
@roles_required('Administrator')
def users():
    conn=db()
    if request.method=='POST':
        f=request.form; username=f.get('username','').strip(); password=f.get('password',''); name=f.get('full_name','').strip(); role=f.get('role',''); assigned=normalise_assigned(role,f.get('assigned_class'))
        subjects_json,subjects_err=clean_subjects(role,f.getlist('subjects_taught'))
        linked_student=f.get('student_id','').strip(); linked_children=[x for x in request.form.getlist('child_ids') if x.isdigit()]
        if not username or not password or len(password)<12 or not name or role not in ASSIGNABLE_ROLES:
            flash('Provide a name, username, supported role, and password of at least 12 characters.','error')
        elif assigned is False:
            flash('That class choice is only for Subject Teachers, and must use JHS 1, JHS 2 and JHS 3.','error')
        elif subjects_err:
            flash(subjects_err,'error')
        elif role in {'Parent/Guardian','Student'} and not linked_student.isdigit():
            flash('Parent and student accounts must be linked to one student record.','error')
        elif linked_children and role=='Student':
            flash('Student accounts cannot have children linked.','error')
        elif role not in {'Parent/Guardian','Student'} and linked_student:
            flash('Only parent and student accounts are linked to a student record.','error')
        elif linked_student and not conn.execute('SELECT 1 FROM students WHERE id=?',(int(linked_student),)).fetchone():
            flash('Choose an existing student record.','error')
        elif any(not conn.execute('SELECT 1 FROM students WHERE id=?',(int(sid),)).fetchone() for sid in linked_children):
            flash('One or more selected children do not exist.','error')
        else:
            try:
                cur=conn.execute('INSERT INTO users(username,password_hash,full_name,role,assigned_class,student_id,must_change_password) VALUES(?,?,?,?,?,?,1)',(username,generate_password_hash(password),name,role,assigned if role not in {'Parent/Guardian','Student'} else None,int(linked_student) if linked_student else None))
                conn.execute('UPDATE users SET subjects_taught=? WHERE id=?',(subjects_json,cur.lastrowid))
                if role=='Parent/Guardian' or role in FAMILY_ROLES:
                    child_ids=set(int(x) for x in linked_children)
                    if linked_student: child_ids.add(int(linked_student))
                    for child_id in child_ids:
                        conn.execute('INSERT OR IGNORE INTO parent_children(user_id,student_id) VALUES(?,?)',(cur.lastrowid,child_id))
                conn.commit(); audit('create','user',cur.lastrowid,username); flash('User account created. The user must change the temporary password at first sign-in. Parent accounts are linked to all selected children.','success')
            except sqlite3.IntegrityError: flash('Username already exists.','error')
        return redirect(url_for('users'))
    all_students=conn.execute('SELECT id,admission_no,first_name,last_name FROM students ORDER BY last_name,first_name').fetchall()
    user_rows=conn.execute('SELECT u.*,s.admission_no linked_admission_no,s.first_name linked_first_name,s.last_name linked_last_name FROM users u LEFT JOIN students s ON s.id=u.student_id ORDER BY u.id DESC').fetchall()
    parent_child_map={row['id']:[x['student_id'] for x in conn.execute('SELECT student_id FROM parent_children WHERE user_id=?',(row['id'],)).fetchall()] for row in user_rows}
    return render_template('users.html', users=user_rows, roles=ASSIGNABLE_ROLES, classes=conn.execute('SELECT * FROM classes WHERE active=1 ORDER BY id').fetchall(), students=all_students,parent_child_map=parent_child_map,subject_choices=subject_catalogue(),st_choices=[(st_value(c),st_label(list(c))) for c in SUBJECT_TEACHER_CHOICES])

@app.route('/users/<int:user_id>/children',methods=['POST'])
@roles_required('Administrator')
def user_children(user_id):
    conn=db(); user=conn.execute("SELECT id,role FROM users WHERE id=?",(user_id,)).fetchone()
    if not user or user['role']!='Parent/Guardian': abort(404)
    ids=request.form.getlist('child_ids'); valid=[]
    for value in ids:
        if not value.isdigit() or not conn.execute('SELECT 1 FROM students WHERE id=?',(int(value),)).fetchone():
            flash('Invalid child selection. No links were changed.','error'); return redirect(url_for('users'))
        valid.append(int(value))
    if not valid:
        flash('Select at least one child for a parent account.','error'); return redirect(url_for('users'))
    conn.execute('DELETE FROM parent_children WHERE user_id=?',(user_id,))
    conn.executemany('INSERT INTO parent_children(user_id,student_id) VALUES(?,?)',[(user_id,x) for x in sorted(set(valid))])
    conn.execute('UPDATE users SET student_id=? WHERE id=?',(valid[0],user_id)); conn.commit(); audit('update','parent_children',user_id,f'Linked {len(set(valid))} student records')
    flash('Parent child links updated.','success'); return redirect(url_for('users'))

def _active_admin_count(conn, excluding=None):
    q="SELECT COUNT(*) FROM users WHERE role='Administrator' AND active=1"; a=[]
    if excluding is not None: q+=' AND id<>?'; a.append(excluding)
    return conn.execute(q,a).fetchone()[0]

def _release_user_refs(conn, uid):
    """Detach a user from records that point at them so the account can be deleted. Returns the tables that still need the user (blockers)."""
    blockers=[]
    tables=[r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()]
    for t in tables:
        notnull={r[1]:r[3] for r in conn.execute(f'PRAGMA table_info("{t}")').fetchall()}
        for fk in conn.execute(f'PRAGMA foreign_key_list("{t}")').fetchall():
            if fk[2]!='users' or str(fk[6]).upper()=='CASCADE': continue
            col=fk[3]
            if t=='import_batches': conn.execute('DELETE FROM import_batches WHERE user_id=?',(uid,))
            elif notnull.get(col): 
                if conn.execute(f'SELECT 1 FROM "{t}" WHERE "{col}"=? LIMIT 1',(uid,)).fetchone(): blockers.append(t)
            else: conn.execute(f'UPDATE "{t}" SET "{col}"=NULL WHERE "{col}"=?',(uid,))
    return blockers

@app.route('/users/<int:user_id>/edit', methods=['GET','POST'])
@roles_required('Administrator')
def user_edit(user_id):
    conn=db(); u=conn.execute('SELECT * FROM users WHERE id=?',(user_id,)).fetchone()
    if not u: abort(404)
    me=current_user()['id']==user_id
    if request.method=='POST':
        f=request.form; username=f.get('username','').strip(); name=f.get('full_name','').strip(); role=f.get('role','') if not me else u['role']
        assigned=normalise_assigned(role,f.get('assigned_class')); linked=f.get('student_id','').strip(); password=f.get('password','') if not me else ''
        kids=sorted({int(x) for x in f.getlist('child_ids') if x.isdigit()})
        sj,sj_err=clean_subjects(role,f.getlist('subjects_taught'),keep=user_subjects(u))
        portal=role in {'Parent/Guardian','Student'}; err=None
        if not username or not name or role not in ASSIGNABLE_ROLES: err='Provide a name, a username and a supported role.'
        elif assigned is False: err='That class choice is only for Subject Teachers, and must use JHS 1, JHS 2 and JHS 3.'
        elif password and len(password)<12: err='A new temporary password must be at least 12 characters.'
        elif portal and not linked.isdigit(): err='Parent and student accounts must be linked to one student record.'
        elif not portal and linked: err='Only parent and student accounts are linked to a student record.'
        elif linked and not conn.execute('SELECT 1 FROM students WHERE id=?',(int(linked),)).fetchone(): err='Choose an existing student record.'
        elif sj_err: err=sj_err
        elif kids and role=='Student': err='Student accounts cannot have children linked.'
        elif any(not conn.execute('SELECT 1 FROM students WHERE id=?',(k,)).fetchone() for k in kids): err='One or more selected children do not exist.'
        elif u['role']=='Administrator' and role!='Administrator' and u['active'] and _active_admin_count(conn,user_id)==0: err='This is the only active Administrator, so the role cannot be changed.'
        if err: flash(err,'error'); return redirect(url_for('user_edit',user_id=user_id))
        try:
            conn.execute('UPDATE users SET username=?,full_name=?,role=?,assigned_class=?,student_id=? WHERE id=?',(username,name,role,None if portal else assigned,int(linked) if portal else None,user_id))
            conn.execute('UPDATE users SET subjects_taught=? WHERE id=?',(sj,user_id))
            before={r[0] for r in conn.execute('SELECT student_id FROM parent_children WHERE user_id=?',(user_id,)).fetchall()}
            if role=='Student': after=set()
            else:
                after=set(kids)
                if role=='Parent/Guardian': after.add(int(linked))
            conn.execute('DELETE FROM parent_children WHERE user_id=?',(user_id,))
            conn.executemany('INSERT INTO parent_children(user_id,student_id) VALUES(?,?)',[(user_id,k) for k in sorted(after)])
            changes=[x for x,(a,b) in {'name':(u['full_name'],name),'username':(u['username'],username),'role':(u['role'],role),'class':(u['assigned_class'] or '',assigned or ''),'subjects':(u['subjects_taught'] or '',sj or '')}.items() if a!=b]
            if after!=before: changes.append('children linked: '+str(len(after)))
            if password:
                conn.execute('UPDATE users SET password_hash=?,must_change_password=1 WHERE id=?',(generate_password_hash(password),user_id)); changes.append('password reset')
            conn.commit(); audit('update','user',user_id,u['username']+': '+(', '.join(changes) or 'no changes')); flash('User account updated.'+(' The user must change the temporary password at next sign-in.' if password else ''),'success')
        except sqlite3.IntegrityError:
            conn.rollback(); flash('Username already exists.','error'); return redirect(url_for('user_edit',user_id=user_id))
        return redirect(url_for('users'))
    classes=conn.execute('SELECT * FROM classes WHERE active=1 ORDER BY id').fetchall()
    students=conn.execute('SELECT id,admission_no,first_name,last_name FROM students ORDER BY last_name,first_name').fetchall()
    st=[(st_value(c),st_label(list(c))) for c in SUBJECT_TEACHER_CHOICES]
    mine={r[0] for r in conn.execute('SELECT student_id FROM parent_children WHERE user_id=?',(user_id,)).fetchall()}
    _cur=u['assigned_class'] or ''
    if _cur.startswith(ST_PREFIX) and ',' not in _cur: _cur=_cur[len(ST_PREFIX):]   # a single JHS class is the plain class option
    return render_template('user_edit.html',u=u,me=me,mine=mine,cur_class=_cur,subject_choices=sorted(set(subject_catalogue())|set(user_subjects(u)),key=str.casefold),mine_subjects=user_subjects(u),roles=ASSIGNABLE_ROLES,classes=classes,students=students,st_choices=st)

@app.route('/users/<int:user_id>/delete', methods=['POST'])
@roles_required('Administrator')
def user_delete(user_id):
    conn=db(); u=conn.execute('SELECT * FROM users WHERE id=?',(user_id,)).fetchone()
    if not u: abort(404)
    if user_id==current_user()['id']: flash('You cannot delete your own account.','error')
    elif not request.form.get('confirm'): flash('Tick the box to confirm the deletion.','error'); return redirect(url_for('user_edit',user_id=user_id))
    elif u['role']=='Administrator' and u['active'] and _active_admin_count(conn,user_id)==0: flash('This is the only active Administrator and cannot be deleted.','error')
    else:
        blockers=_release_user_refs(conn,user_id)
        if blockers:
            conn.rollback(); flash('This account has records that must keep its name ('+', '.join(sorted(set(blockers)))+'). Suspend the account instead of deleting it.','error'); return redirect(url_for('user_edit',user_id=user_id))
        conn.execute('DELETE FROM users WHERE id=?',(user_id,)); conn.commit(); audit('delete','user',user_id,u['username']+' ('+u['role']+')'); flash('User account deleted.','success')
    return redirect(url_for('users'))

@app.route('/users/<int:user_id>/toggle', methods=['POST'])
@roles_required('Administrator')
def user_toggle(user_id):
    if user_id == current_user()['id']: flash('You cannot deactivate your own account.','error')
    else:
        u=db().execute('SELECT * FROM users WHERE id=?',(user_id,)).fetchone()
        if u: db().execute('UPDATE users SET active=? WHERE id=?',(0 if u['active'] else 1,user_id)); db().commit(); audit('change_status','user',user_id,u['username']); flash('User account status updated.','success')
    return redirect(url_for('users'))

@app.route('/portal')
@login_required
def portal():
    user=current_user(); conn=db()
    if user['role'] not in FAMILY_ROLES|{'Parent/Guardian','Student'}: abort(403)
    if user['role']=='Student':
        if not user['student_id']: abort(403)
        linked_ids=[user['student_id']]
    else:
        linked_ids=[r['student_id'] for r in conn.execute('SELECT student_id FROM parent_children WHERE user_id=? ORDER BY student_id',(user['id'],)).fetchall()]
        if not linked_ids and user['student_id']:
            linked_ids=[user['student_id']]
    if not linked_ids: abort(403)
    selected=request.args.get('student_id','')
    if selected:
        if not selected.isdigit() or int(selected) not in linked_ids: abort(403)
        student_id=int(selected)
    else:
        student_id=linked_ids[0]
    student=conn.execute('SELECT s.*,c.name class_name FROM students s LEFT JOIN classes c ON c.id=s.class_id WHERE s.id=?',(student_id,)).fetchone()
    if not student: abort(403)
    children=conn.execute('SELECT s.id,s.admission_no,s.first_name,s.last_name,c.name class_name FROM students s LEFT JOIN classes c ON c.id=s.class_id WHERE s.id IN (%s) ORDER BY s.last_name,s.first_name' % ','.join('?' for _ in linked_ids),linked_ids).fetchall()
    payments=conn.execute('SELECT * FROM fees WHERE student_id=? ORDER BY payment_date DESC,id DESC LIMIT 20',(student_id,)).fetchall()
    invoices=conn.execute('''SELECT i.*, COALESCE((SELECT SUM(f.amount) FROM fees f WHERE f.student_id=i.student_id AND f.purpose=i.invoice_no),0) paid FROM fee_invoices i WHERE i.student_id=? ORDER BY i.due_date DESC''',(student_id,)).fetchall()
    attendance=[]; results=[]
    for key,bucket in (('attendance',attendance),('assessments',results)):
        for row in conn.execute("SELECT * FROM school_records WHERE student_id=? AND module_key=? ORDER BY COALESCE(event_date,created_at) DESC,id DESC LIMIT 50",(student_id,key)).fetchall():
            try: payload=json.loads(row['payload_json'])
            except (ValueError,TypeError): payload={}
            item=dict(row); item['payload']=payload; bucket.append(item)
    timetable=conn.execute("SELECT * FROM school_records WHERE module_key='timetable' AND class_name=? ORDER BY id",(student['class_name'] or '',)).fetchall()
    lessons=[]
    for row in timetable:
        try: payload=json.loads(row['payload_json'])
        except (ValueError,TypeError): payload={}
        item=dict(row); item['payload']=payload; lessons.append(item)
    momo=conn.execute('SELECT * FROM momo_payments WHERE student_id=? ORDER BY id DESC LIMIT 10',(student_id,)).fetchall()
    if user['role'] in FAMILY_ROLES: audit('view','child_portal',student_id,user['username']+' viewed own child')
    return render_template('portal.html',momo=momo,momo_names=INT.NETWORK_NAMES,student=student,children=children,payments=payments,invoices=invoices,attendance=attendance,results=results,lessons=lessons,portal_role='Student' if user['role']=='Student' else 'Parent/Guardian')

@app.route('/change-password', methods=['GET','POST'])
@login_required
def change_password():
    if request.method == 'POST':
        old = request.form.get('current_password','')
        new = request.form.get('new_password','')
        confirm = request.form.get('confirm_password','')
        user = current_user()
        if not check_password_hash(user['password_hash'], old):
            flash('Current password is incorrect.', 'error')
        elif len(new) < 12 or new.lower() == new or not any(ch.isdigit() for ch in new):
            flash('Use at least 12 characters, including an uppercase letter and a number.', 'error')
        elif new != confirm:
            flash('The new passwords do not match.', 'error')
        else:
            db().execute('UPDATE users SET password_hash=?, must_change_password=0 WHERE id=?', (generate_password_hash(new), user['id']))
            db().commit(); audit('change_password','user',user['id'],'Password changed by account holder')
            session.clear(); flash('Password changed. Sign in again with your new password.', 'success')
            return redirect(url_for('login'))
    return render_template('change_password.html')

@app.route('/admin/backup')
@roles_required('Administrator')
def download_backup():
    data=_dump_sql().encode('utf-8')
    # Ship a portable SQL backup rather than relying on SQLite's newer serialize API.
    audit('backup','database',None,'Administrator downloaded a SQL database backup')
    return send_file(io.BytesIO(data),as_attachment=True,download_name=f'fr_joseph_connolly_backup_{date.today().isoformat()}.sql',mimetype='application/sql')

ALLOWED_DOCUMENT_EXTENSIONS={'pdf','png','jpg','jpeg','docx','xlsx','csv','txt'}
_SIGNATURES={'pdf':(b'%PDF-',),'png':(b'\x89PNG\r\n\x1a\n',),'jpg':(b'\xff\xd8\xff',),'jpeg':(b'\xff\xd8\xff',),'docx':(b'PK\x03\x04',),'xlsx':(b'PK\x03\x04',)}
def _content_matches_extension(path,ext):
    """Reject files whose real content does not match the file type they claim to be."""
    with open(path,'rb') as fh: head=fh.read(16)
    if ext in _SIGNATURES: return any(head.startswith(sig) for sig in _SIGNATURES[ext])
    return b'\x00' not in head and b'MZ'!=head[:2]  # csv and txt must be plain text, not programs
def document_upload_dir():
    path=os.environ.get('SCHOOL_UPLOAD_DIR',os.path.join(BASE_DIR,'private_uploads'))
    os.makedirs(path,mode=0o700,exist_ok=True)
    try: os.chmod(path,0o700)
    except OSError: pass
    return path

@app.route('/documents/files',methods=['GET','POST'])
@roles_required('Administrator','Headteacher','Admissions Officer')
def document_files():
    conn=db()
    if request.method=='POST':
        upload=request.files.get('file'); category=request.form.get('category','').strip(); student_value=request.form.get('student_id','').strip()
        allowed_categories={'Student','Staff','School','Finance','Policy','Other'}
        if not upload or not upload.filename:
            flash('Choose a document to upload.','error'); return redirect(url_for('document_files'))
        original=secure_filename(upload.filename)
        ext=original.rsplit('.',1)[-1].lower() if '.' in original else ''
        if not original or ext not in ALLOWED_DOCUMENT_EXTENSIONS:
            flash('Allowed file types: PDF, PNG, JPG, DOCX, XLSX, CSV and TXT.','error'); return redirect(url_for('document_files'))
        if category not in allowed_categories:
            flash('Choose a valid document category.','error'); return redirect(url_for('document_files'))
        student_id=None
        if student_value:
            if not student_value.isdigit() or not conn.execute('SELECT 1 FROM students WHERE id=?',(int(student_value),)).fetchone():
                flash('Choose a valid linked student.','error'); return redirect(url_for('document_files'))
            student_id=int(student_value)
        stored=f'{uuid.uuid4().hex}.{ext}'; path=os.path.join(document_upload_dir(),stored)
        try:
            upload.save(path); size=os.path.getsize(path)
            if size<=0 or size>8*1024*1024:
                os.remove(path); flash('File must be between 1 byte and 8 MB.','error'); return redirect(url_for('document_files'))
            if not _content_matches_extension(path,ext):
                os.remove(path); flash('The file content does not match its type. Upload a genuine PDF, image, Word, Excel, CSV or text file.','error'); return redirect(url_for('document_files'))
            mime=mimetypes.guess_type(original)[0] or 'application/octet-stream'
            cur=conn.execute('INSERT INTO document_files(original_name,stored_name,mime_type,size_bytes,category,student_id,uploaded_by) VALUES(?,?,?,?,?,?,?)',(original,stored,mime,size,category,student_id,current_user()['id']))
            conn.commit(); audit('upload','document',cur.lastrowid,f'{original} ({size} bytes)')
            flash('Document uploaded to private storage.','success')
        except Exception:
            if os.path.exists(path): os.remove(path)
            raise
        return redirect(url_for('document_files'))
    rows=conn.execute('SELECT d.*,u.full_name uploader,s.admission_no,s.first_name,s.last_name FROM document_files d JOIN users u ON u.id=d.uploaded_by LEFT JOIN students s ON s.id=d.student_id ORDER BY d.id DESC LIMIT 300').fetchall()
    students=conn.execute('SELECT id,admission_no,first_name,last_name FROM students ORDER BY last_name,first_name').fetchall()
    return render_template('document_files.html',files=rows,students=students)

@app.route('/documents/files/<int:file_id>')
@roles_required('Administrator','Headteacher','Admissions Officer')
def document_download(file_id):
    row=db().execute('SELECT * FROM document_files WHERE id=?',(file_id,)).fetchone()
    if not row: abort(404)
    if row['category']=='Finance' and current_user()['role']!='Administrator': abort(403)
    path=os.path.join(document_upload_dir(),row['stored_name'])
    if not os.path.isfile(path): abort(404)
    audit('download','document',file_id,row['original_name'])
    return send_file(path,as_attachment=True,download_name=row['original_name'],mimetype='application/octet-stream',conditional=True)

@app.route('/audit')
@roles_required('Administrator')
def audit_page():
    rows=db().execute('SELECT a.*,u.username FROM audit_log a LEFT JOIN users u ON u.id=a.user_id ORDER BY a.id DESC LIMIT 250').fetchall()
    return render_template('audit.html', rows=rows)


# Integrated operational registers. Each register stores validated, searchable records in the
# same database as students, staff accounts, fees, and audit events. External services are
# intentionally marked as configuration-dependent and are not simulated.
MODULES = {
 'staff': {'label':'Staff & HR','roles':{'Administrator','Proprietor','Headteacher'},'description':'Staff profiles, employment, qualifications, responsibilities and leave records. Payroll calculations require a separately configured payroll policy.','fields':[
  ('full_name','Full name','text',True),('staff_number','Staff number','text',False),('position','Position','text',True),('department','Department','text',False),('phone','Phone','text',False),('email','Email','text',False),('qualification','Qualifications','text',False),('employment_date','Employment date','date',False),('line_manager','Line manager','text',False),('employment_status','Employment status','select:Active|On leave|Suspended|Separated',True)]},
 'subjects': {'label':'Subjects & Teaching','roles':{'Administrator','Headteacher'},'description':'Subject catalogue and class allocation records.','fields':[
  ('subject_name','Subject name','text',True),('subject_code','Subject code','text',False),('class_name','Class','class',True),('teacher_name','Assigned teacher','text',False),('academic_year','Academic year','text',True),('term','Term','select:Term 1|Term 2|Term 3',True)]},
 'attendance': {'label':'Student Attendance','roles':{'Administrator','Headteacher','Class Teacher','Subject Teacher','Teacher'},'description':'Record attendance by date and class. Staff assigned to a class are restricted to that class.','fields':[
  ('student_id','Student','student',True),('class_name','Class','class',True),('event_date','Attendance date','date',True),('attendance_status','Attendance status','select:Present|Absent|Late|Authorised absence',True),('notes','Notes','textarea',False)]},
 'staff-attendance': {'label':'Staff Attendance','roles':{'Administrator','Headteacher'},'description':'Daily staff attendance and lateness register.','fields':[
  ('staff_name','Staff member','text',True),('event_date','Date','date',True),('attendance_status','Status','select:Present|Absent|Late|Authorised absence',True),('minutes_late','Minutes late','number',False),('notes','Notes','textarea',False)]},
 'assessments': {'label':'Assessments & Results','roles':{'Administrator','Headteacher','Class Teacher','Subject Teacher','Teacher'},'description':'Record subject assessment marks. Grading scales and report-card aggregation must be configured and verified before issuing official results.','fields':[
  ('student_id','Student','student',True),('class_name','Class','class',True),('subject_name','Subject','text',True),('assessment_type','Assessment type','select:Classwork|Homework|Quiz|Project|Examination',True),('assessment_name','Assessment name','text',True),('event_date','Assessment date','date',True),('academic_year','Academic year','text',True),('term','Term','select:Term 1|Term 2|Term 3',True),('score','Score earned','number',True),('maximum_score','Maximum score','number',True),('teacher_comment','Teacher comment','textarea',False)]},
 'timetable': {'label':'Timetable','roles':{'Administrator','Headteacher','Class Teacher','Subject Teacher','Teacher'},'description':'Lesson and activity schedule register. Check teacher, room and class conflicts before publishing.','fields':[
  ('class_name','Class','class',True),('day','Day','select:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday',True),('start_time','Start time (HH:MM)','text',True),('end_time','End time (HH:MM)','text',True),('subject_name','Subject or activity','text',True),('teacher_name','Teacher','text',False),('room','Room','text',False),('academic_year','Academic year','text',True),('term','Term','select:Term 1|Term 2|Term 3',True)]},
 'admissions': {'label':'Admissions Applications','roles':{'Administrator','Headteacher','Admissions Officer'},'description':'Track applicants, application decisions and conversion into student records.','fields':[
  ('applicant_name','Applicant full name','text',True),('date_of_birth','Date of birth','date',False),('requested_class','Requested class','class',True),('guardian_name','Parent or guardian','text',True),('guardian_phone','Guardian phone','text',True),('application_date','Application date','date',True),('application_status','Application status','select:Received|Under review|Accepted|Waitlisted|Rejected|Enrolled',True),('decision_notes','Decision notes','textarea',False)]},
 'calendar': {'label':'School Calendar','roles':{'Administrator','Proprietor','Headteacher','Admissions Officer','Class Teacher','Subject Teacher','Teacher','Accountant','Librarian','Storekeeper'},'description':'School events, term dates, meetings, holidays and examinations.','fields':[
  ('event_name','Event name','text',True),('event_type','Event type','select:Term date|Examination|Holiday|PTA meeting|Staff meeting|School event|Extracurricular',True),('event_date','Date','date',True),('end_date','End date','date',False),('location','Location','text',False),('details','Details','textarea',False)]},
 'announcements': {'label':'Announcements','roles':{'Administrator','Proprietor','Headteacher'},'description':'In-app school announcements. SMS and email delivery require configured provider credentials.','fields':[
  ('announcement_title','Title','text',True),('audience','Audience','select:All staff|Teachers|Parents|Students|Specific class',True),('class_name','Class, if applicable','class',False),('publish_date','Publish date','date',True),('message','Message','textarea',True),('announcement_status','Status','select:Draft|Published|Archived',True)]},
 'library': {'label':'Library','roles':{'Administrator','Headteacher','Librarian'},'description':'Book catalogue and issue/return tracking register.','fields':[
  ('book_title','Book title','text',True),('book_code','Book ID / ISBN','text',False),('author','Author','text',False),('category','Category','text',False),('transaction_type','Record type','select:Book registered|Book issued|Book returned|Lost|Damaged',True),('borrower_name','Borrower name','text',False),('borrower_admission_no','Student admission number','text',False),('event_date','Transaction date','date',True),('due_date','Due date','date',False)]},
 'inventory': {'label':'Inventory & Stores','roles':{'Administrator','Proprietor','Headteacher','Storekeeper'},'description':'Stock and school asset register.','fields':[
  ('item_name','Item name','text',True),('item_code','Asset / stock code','text',False),('category','Category','text',True),('quantity','Quantity','number',True),('minimum_stock','Low-stock alert level','number',False),('unit','Unit','text',False),('transaction_type','Transaction','select:Stock in|Stock out|Allocated|Damaged|Missing|Stocktake',True),('location','Location / department','text',False),('event_date','Transaction date','date',True),('supplier','Supplier','text',False),('notes','Notes','textarea',False)]},
 'finance': {'label':'Income & Expenditure','roles':{'Administrator','Proprietor','Accountant'},'description':'Record non-fee income and expenditure. This is a register, not a reconciled general ledger or statutory financial statement.','fields':[
  ('transaction_type','Transaction type','select:Income|Expenditure',True),('category','Category','text',True),('description','Description','text',True),('amount_cedis','Amount (GHS)','number',True),('event_date','Transaction date','date',True),('payment_method','Payment method','select:Cash|Bank transfer|MTN MoMo|Telecel Cash|AT Money|Other',True),('reference','Reference','text',False),('notes','Notes','textarea',False)]},
 'procurement': {'label':'Procurement & Suppliers','roles':{'Administrator','Proprietor','Accountant','Headteacher'},'description':'Track purchase requests and supplier orders. Supplier payments remain in the financial register.','fields':[
  ('supplier_name','Supplier name','text',True),('request_title','Item or service','text',True),('requested_by','Requested by','text',True),('request_date','Request date','date',True),('amount_cedis','Estimated amount (GHS)','number',False),('approval_status','Approval status','select:Requested|Approved|Rejected|Ordered|Received|Cancelled',True),('purchase_order','Purchase order reference','text',False),('notes','Notes','textarea',False)]},
 'transport': {'label':'Transport','roles':{'Administrator','Proprietor','Headteacher'},'description':'Vehicle, route, driver and student transport assignment register.','fields':[
  ('vehicle_registration','Vehicle registration','text',True),('vehicle_type','Vehicle type','text',False),('driver_name','Driver','text',False),('route_name','Route','text',True),('stop_name','Stop','text',False),('student_id','Student, if assigned','student',False),('event_date','Effective date','date',True),('transport_status','Status','select:Active|Maintenance|Inactive',True),('notes','Notes','textarea',False)]},
 'boarding': {'label':'Boarding & Dormitory','roles':{'Administrator','Proprietor','Headteacher'},'description':'Optional boarding register. Use only if the school operates boarding facilities.','fields':[
  ('student_id','Student','student',True),('dormitory','Dormitory','text',True),('room','Room','text',True),('bed','Bed','text',False),('event_date','Allocation date','date',True),('boarding_status','Status','select:Allocated|Moved|Checked out',True),('notes','Notes','textarea',False)]},
 'welfare': {'label':'Student Welfare & Safeguarding','roles':{'Administrator','Headteacher'},'description':'Restricted welfare register. Enter only necessary information. Access is limited to the designated safeguarding roles.','fields':[
  ('student_id','Student','student',True),('event_date','Incident date','date',True),('case_type','Case type','select:Welfare|Discipline|Safeguarding|Referral',True),('priority','Priority','select:Low|Medium|High|Urgent',True),('summary','Restricted summary','textarea',True),('follow_up','Follow-up action','textarea',False),('case_status','Case status','select:Open|Under review|Referred|Closed',True)]},
 'health': {'label':'School Health Register','roles':{'Administrator','Headteacher'},'description':'Restricted basic health and clinic visit register. Store only necessary health information and restrict access.','fields':[
  ('student_id','Student','student',True),('event_date','Visit date','date',True),('visit_reason','Reason for visit','text',True),('action_taken','Action taken','textarea',False),('guardian_contacted','Guardian contacted','select:Yes|No|Not required',True),('referral','Referral','text',False)]},
 'documents': {'label':'Document Register','roles':{'Administrator','Headteacher','Admissions Officer'},'description':'Register document metadata and storage references. Use the private document upload register for file storage.','fields':[
  ('document_title','Document title','text',True),('document_category','Category','select:Student|Staff|School|Finance|Policy|Other',True),('related_person','Related student or staff','text',False),('document_reference','Secure storage reference','text',False),('event_date','Document date','date',False),('access_level','Access level','select:Restricted|Staff only|Management',True),('notes','Notes','textarea',False)]},
}
MODULES['staff']['roles'].update({'Administrator'})
for _k in ('attendance','assessments','timetable'): MODULES[_k]['class_scoped']=True
# Records module route and helpers
def _module_allowed(key):
    cfg = MODULES.get(key)
    if not cfg: abort(404)
    role = current_user()['role']
    if role not in cfg['roles']:
        abort(403)
    if role in TEACHER_ROLES and key in {'attendance','assessments','timetable'}:
        if not class_scope(current_user()): abort(403)
    return cfg

def _module_rows(key):
    _module_allowed(key)
    user = current_user()
    sql = 'SELECT r.*,s.admission_no,s.first_name,s.last_name FROM school_records r LEFT JOIN students s ON s.id=r.student_id WHERE r.module_key=?'
    args = [key]
    if user['role'] in TEACHER_ROLES and key in {'attendance','assessments','timetable'}:
        _sc=class_scope(user); sql += f' AND r.class_name IN {_in(_sc)}'; args += _sc
        _ss=subject_scope(user) if key=='assessments' else None
        if _ss: sql += f" AND json_extract(r.payload_json,'$.subject_name') IN {_in(_ss)}"; args += _ss
    if key in {'welfare','health'} and user['role'] not in {'Administrator','Headteacher'}:
        abort(403)
    # Staff directory lookup must include every staff record so older staff
    # members remain searchable and selectable, even after the register grows
    # beyond the 500-row display cap used by other operational registers.
    if key == 'staff':
        sql += ' ORDER BY COALESCE(r.event_date,r.created_at) DESC,r.id DESC'
    else:
        sql += ' ORDER BY COALESCE(r.event_date,r.created_at) DESC,r.id DESC LIMIT 500'
    return db().execute(sql,args).fetchall()

def _field_definitions(cfg):
    result=[]
    _u=current_user(); _sc=class_scope(_u) if _u and cfg.get('class_scoped') else None
    for name,label,kind,required in cfg['fields']:
        options=[]
        if cfg is MODULES.get('assessments') and name=='subject_name' and _u and subject_scope(_u):
            options=list(subject_scope(_u)); kind='select'
        elif kind.startswith('select:'):
            options=kind.split(':',1)[1].split('|')
            kind='select'
        elif kind=='class':
            options=[r['name'] for r in db().execute('SELECT name FROM classes WHERE active=1 ORDER BY id').fetchall() if _sc is None or r['name'] in _sc]
            kind='select'
        elif kind=='student':
            students=[x for x in db().execute("SELECT s.id,s.admission_no,s.first_name,s.last_name,c.name class_name FROM students s LEFT JOIN classes c ON c.id=s.class_id WHERE s.status='Active' ORDER BY s.last_name,s.first_name").fetchall() if _sc is None or x['class_name'] in _sc]
            options=[{'value':str(s['id']),'label':f"{s['admission_no']} · {s['first_name']} {s['last_name']}"} for s in students]
            kind='student'
        result.append({'name':name,'label':label,'kind':kind,'required':required,'options':options})
    return result

def _save_module_record(key, record_id=None):
    cfg = _module_allowed(key)
    f=request.form
    payload={}
    for name,label,kind,required in cfg['fields']:
        value=f.get(name,'').strip()
        if required and not value:
            raise ValueError(f'{label} is required.')
        if kind=='date' and value:
            try: date.fromisoformat(value)
            except ValueError: raise ValueError(f'{label} must be a valid date.')
        if kind.startswith('select:') and value and value not in kind.split(':',1)[1].split('|'):
            raise ValueError(f'Choose a valid option for {label}.')
        if kind in {'number'} and value:
            try:
                number=float(value)
                if not math.isfinite(number) or number < 0: raise ValueError()
                payload[name]=number
            except ValueError:
                raise ValueError(f'{label} must be a non-negative number.')
        else:
            payload[name]=value
    if key=='staff':
        prior={}
        if record_id:
            oldrow=db().execute("SELECT payload_json FROM school_records WHERE id=? AND module_key='staff'",(record_id,)).fetchone()
            if oldrow:
                try: prior=json.loads(oldrow['payload_json'])
                except (ValueError,TypeError): prior={}
        try: payload['passport_photo_path']=_save_passport_photo(request.files.get('passport_photo'),'staff',prior.get('passport_photo_path'))
        except ValueError as exc: raise ValueError(str(exc))
    if key=='assessments':
        _ss=subject_scope(current_user())
        if _ss and payload.get('subject_name') not in _ss: raise ValueError('You can enter results only for your own subjects: '+', '.join(_ss)+'.')
    if key=='assessments':
        try:
            score=float(payload.get('score',0)); maximum=float(payload.get('maximum_score',0))
            if maximum <= 0: raise ValueError('Maximum score must be greater than zero.')
            if score > maximum: raise ValueError('Score earned must not exceed the maximum score.')
        except (TypeError, ValueError) as exc:
            if str(exc) in {'Maximum score must be greater than zero.','Score earned must not exceed the maximum score.'}: raise
            raise ValueError('Enter valid assessment scores.')
    if key=='timetable':
        start=payload.get('start_time',''); end=payload.get('end_time','')
        time_pattern=r'([01]\d|2[0-3]):[0-5]\d'
        if not re.fullmatch(time_pattern,start) or not re.fullmatch(time_pattern,end) or start>=end:
            raise ValueError('Enter valid 24-hour times, with the end after the start.')
        existing=db().execute("SELECT id,class_name,payload_json FROM school_records WHERE module_key='timetable' AND id<>COALESCE(?,0)",(record_id,)).fetchall()
        for item in existing:
            try: old=json.loads(item['payload_json'])
            except (ValueError,TypeError): continue
            same_period=(old.get('day')==payload.get('day') and old.get('term')==payload.get('term') and old.get('academic_year')==payload.get('academic_year'))
            overlaps=start < old.get('end_time','') and end > old.get('start_time','')
            if same_period and overlaps and item['class_name']==payload.get('class_name'):
                raise ValueError('This class already has a timetable entry during that time.')
            if same_period and overlaps and payload.get('teacher_name') and old.get('teacher_name','').strip().casefold()==payload.get('teacher_name','').strip().casefold():
                raise ValueError('This teacher is already assigned to an overlapping lesson.')
            if same_period and overlaps and payload.get('room') and old.get('room','').strip().casefold()==payload.get('room','').strip().casefold():
                raise ValueError('This room is already booked for an overlapping lesson.')
    _v3_validate(key,payload,record_id)
    title_key=next((x[0] for x in cfg['fields'] if x[0] in {'full_name','subject_name','event_name','announcement_title','book_title','item_name','description','applicant_name','request_title','route_name','vehicle_registration','document_title','assessment_name','staff_name'}),None)
    title=str(_v3_title(key,payload) or payload.get(title_key) or cfg['label'])[:200]
    student_id=None
    if payload.get('student_id'):
        try: student_id=int(payload['student_id'])
        except (ValueError,TypeError): raise ValueError('Choose a valid student.')
        found=db().execute("SELECT id FROM students WHERE id=? AND status='Active'",(student_id,)).fetchone()
        if not found: raise ValueError('The selected student is not active or does not exist.')
    if key=='attendance' and student_id and payload.get('event_date'):
        existing=db().execute("SELECT id,payload_json FROM school_records WHERE module_key='attendance' AND student_id=? AND id<>COALESCE(?,0)",(student_id,record_id)).fetchall()
        for item in existing:
            try: old=json.loads(item['payload_json'])
            except (ValueError,TypeError): continue
            if old.get('event_date')==payload.get('event_date'):
                raise ValueError('Attendance has already been recorded for this student on this date.')
    class_name=payload.get('class_name') or payload.get('requested_class')
    if key in {'attendance','assessments'} and student_id:
        row=db().execute('SELECT c.name FROM students s LEFT JOIN classes c ON c.id=s.class_id WHERE s.id=?',(student_id,)).fetchone()
        if not row or row['name'] != class_name:
            raise ValueError('The selected student must belong to the selected class.')
    if current_user()['role'] in TEACHER_ROLES and key in {'attendance','assessments','timetable'}:
        _sc=class_scope(current_user())
        if class_name not in _sc:
            raise ValueError('Your account is limited to its own classes.')
        if student_id:
            row=db().execute('SELECT c.name FROM students s LEFT JOIN classes c ON c.id=s.class_id WHERE s.id=?',(student_id,)).fetchone()
            if not row or row['name'] not in _sc:
                raise ValueError('The selected student is outside your classes.')
    event_date=payload.get('event_date') or payload.get('application_date') or payload.get('publish_date') or payload.get('request_date')
    amount=payload.get('amount_cedis')
    status=payload.get('attendance_status') or payload.get('application_status') or payload.get('announcement_status') or payload.get('approval_status') or payload.get('employment_status') or payload.get('boarding_status') or payload.get('transport_status') or payload.get('case_status') or payload.get('transaction_type') or payload.get('leave_status') or payload.get('payroll_status') or payload.get('refund_status') or payload.get('scholarship_status') or payload.get('term_status') or 'Recorded'
    old_status=None
    if record_id:
        old=db().execute('SELECT id,status FROM school_records WHERE id=? AND module_key=?',(record_id,key)).fetchone()
        if not old: abort(404)
        old_status=old['status']
        db().execute('UPDATE school_records SET title=?,payload_json=?,student_id=?,class_name=?,event_date=?,amount_cedis=?,status=?,updated_by=?,updated_at=CURRENT_TIMESTAMP WHERE id=? AND module_key=?',
          (title,json.dumps(payload,ensure_ascii=False),student_id,class_name,event_date,amount,status,current_user()['id'],record_id,key))
        audit('update',key,record_id,f"Updated {cfg['label']} record")
    else:
        cur=db().execute('INSERT INTO school_records(module_key,title,payload_json,student_id,class_name,event_date,amount_cedis,status,created_by,updated_by) VALUES(?,?,?,?,?,?,?,?,?,?)',
          (key,title,json.dumps(payload,ensure_ascii=False),student_id,class_name,event_date,amount,status,current_user()['id'],current_user()['id']))
        record_id=cur.lastrowid
        audit('create',key,record_id,f"Created {cfg['label']} record")
    db().commit()
    if key=='admissions': _record_admission_history(record_id,status,old_status)
    return record_id

@app.route('/modules/<key>')
@login_required
def module_list(key):
    cfg=_module_allowed(key)
    rows=_module_rows(key)
    search=request.args.get('q','').strip()
    selected_record=request.args.get('record_id','').strip()
    staff_choices=[]
    if key=='staff':
        for choice in rows:
            try: choice_payload=json.loads(choice['payload_json'])
            except (ValueError,TypeError): choice_payload={}
            staff_choices.append({'id':choice['id'],'full_name':choice_payload.get('full_name',choice['title']),'staff_number':choice_payload.get('staff_number','')})
    if key=='staff':
        filtered=[]
        for row in rows:
            try: payload=json.loads(row['payload_json'])
            except (ValueError,TypeError): payload={}
            haystack=' '.join(str(payload.get(k,'')) for k in ('full_name','staff_number','position','department'))+' '+str(row['id'])
            if search and search.casefold() not in haystack.casefold(): continue
            if selected_record.isdigit() and row['id']!=int(selected_record): continue
            filtered.append(row)
        rows=filtered
    unpacked=[]
    for row in rows:
        item=dict(row)
        try: item['payload']=json.loads(item['payload_json'])
        except (ValueError,TypeError): item['payload']={}
        unpacked.append(item)
    inventory_summary=[]
    if key=='inventory':
        ledger=db().execute("SELECT id,title,payload_json,created_at FROM school_records WHERE module_key='inventory' ORDER BY COALESCE(event_date,created_at),id").fetchall()
        balances={}
        for entry in ledger:
            try: p=json.loads(entry['payload_json'])
            except (ValueError,TypeError): continue
            name=(p.get('item_code') or p.get('item_name') or entry['title']).strip().casefold()
            if not name: continue
            item=balances.setdefault(name,{'name':p.get('item_name') or entry['title'],'code':p.get('item_code',''),'unit':p.get('unit','units'),'quantity':0.0,'minimum':float(p.get('minimum_stock') or 0),'category':p.get('category',''),'negative':False})
            try: qty=float(p.get('quantity',0) or 0)
            except (ValueError,TypeError): qty=0
            movement=p.get('transaction_type')
            if movement=='Stocktake': item['quantity']=qty
            elif movement=='Stock in': item['quantity']+=qty
            elif movement in {'Stock out','Allocated','Damaged','Missing'}: item['quantity']-=qty
            if p.get('minimum_stock') not in ('',None):
                try: item['minimum']=float(p['minimum_stock'])
                except (ValueError,TypeError): pass
            item['category']=p.get('category',item['category']); item['unit']=p.get('unit') or item['unit']
        inventory_summary=sorted([dict(v,quantity=round(v['quantity'],2),low=v['quantity']<=v['minimum'],negative=v['quantity']<0) for v in balances.values()],key=lambda x:x['name'].casefold())
    return render_template('module_list.html',cfg=cfg,key=key,records=unpacked,inventory_summary=inventory_summary,search=search,selected_record=selected_record,staff_choices=staff_choices)

@app.route('/modules/<key>/new',methods=['GET','POST'])
@login_required
def module_new(key):
    cfg=_module_allowed(key)
    fields=_field_definitions(cfg)
    if request.method=='POST':
        try:
            _save_module_record(key)
            flash(f"{cfg['label']} record saved.",'success')
            return redirect(url_for('module_list',key=key))
        except ValueError as exc:
            flash(str(exc),'error')
    return render_template('module_form.html',cfg=cfg,key=key,fields=fields,record=request.form.to_dict() if request.method=='POST' else None,record_id=None)

@app.route('/modules/admissions/<int:record_id>/convert',methods=['POST'])
@roles_required('Administrator','Headteacher','Admissions Officer')
def admission_convert(record_id):
    conn=db(); row=conn.execute("SELECT * FROM school_records WHERE id=? AND module_key='admissions'",(record_id,)).fetchone()
    if not row: abort(404)
    try: payload=json.loads(row['payload_json'])
    except (ValueError,TypeError): payload={}
    if payload.get('application_status') not in {'Accepted','Enrolled'}:
        flash('Only accepted applicants can be enrolled. Update the application decision first.','error'); return redirect(url_for('module_list',key='admissions'))
    name=payload.get('applicant_name','').strip().split()
    if len(name)<2:
        flash('Applicant needs a first and last name before conversion.','error'); return redirect(url_for('module_edit',key='admissions',record_id=record_id))
    existing=conn.execute('SELECT id FROM students WHERE lower(first_name)=lower(?) AND lower(last_name)=lower(?) AND COALESCE(dob,\'\')=COALESCE(?,\'\') LIMIT 1',(name[0],name[-1],payload.get('date_of_birth') or None)).fetchone()
    if existing:
        flash('A matching student record already exists. Review the student directory before enrolling this applicant.','error'); return redirect(url_for('module_list',key='admissions'))
    class_row=conn.execute('SELECT id FROM classes WHERE name=? AND active=1',(payload.get('requested_class'),)).fetchone()
    if not class_row:
        flash('The requested class is no longer active. Update the application class first.','error'); return redirect(url_for('module_edit',key='admissions',record_id=record_id))
    admission_no=make_admission_no()
    cur=conn.execute('INSERT INTO students(admission_no,first_name,last_name,dob,admission_date,class_id,guardian_name,guardian_phone,status) VALUES(?,?,?,?,?,?,?,?,?)',(admission_no,name[0],' '.join(name[1:]),payload.get('date_of_birth') or None,date.today().isoformat(),class_row['id'],payload.get('guardian_name',''),payload.get('guardian_phone',''),'Active'))
    conn.execute('INSERT INTO enrolment_history(student_id,class_name,academic_year,term,status) VALUES(?,?,?,?,?)',(cur.lastrowid,payload.get('requested_class'),str(date.today().year),'Current','Active'))
    payload['application_status']='Enrolled'; payload['converted_student_id']=cur.lastrowid; payload['converted_admission_no']=admission_no
    conn.execute("UPDATE school_records SET payload_json=?,status='Enrolled',updated_by=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(json.dumps(payload,ensure_ascii=False),current_user()['id'],record_id)); conn.commit()
    audit('convert','admission',record_id,f'Created student {admission_no} from applicant')
    flash(f'Applicant enrolled successfully. Admission number: {admission_no}.','success'); return redirect(url_for('student_detail',student_id=cur.lastrowid))

@app.route('/modules/<key>/<int:record_id>/edit',methods=['GET','POST'])
@login_required
def module_edit(key,record_id):
    cfg=_module_allowed(key)
    row=db().execute('SELECT * FROM school_records WHERE id=? AND module_key=?',(record_id,key)).fetchone()
    if not row: abort(404)
    if current_user()['role'] in TEACHER_ROLES and key in {'attendance','assessments','timetable'} and row['class_name'] not in class_scope(current_user()):
        abort(403)
    if key=='assessments' and subject_scope(current_user()):
        try: _p=json.loads(row['payload_json'])
        except (ValueError,TypeError): _p={}
        if _p.get('subject_name') not in subject_scope(current_user()): abort(403)
    if request.method=='POST':
        try:
            _save_module_record(key,record_id)
            flash(f"{cfg['label']} record updated.",'success')
            return redirect(url_for('module_list',key=key))
        except ValueError as exc:
            flash(str(exc),'error')
    try: payload=json.loads(row['payload_json'])
    except (ValueError,TypeError): payload={}
    if request.method=='POST': payload={**payload,**request.form.to_dict()}
    return render_template('module_form.html',cfg=cfg,key=key,fields=_field_definitions(cfg),record=payload,record_id=record_id)

@app.route('/modules/<key>/export.csv')
@login_required
def module_export(key):
    cfg=_module_allowed(key)
    rows=_module_rows(key)
    output=io.StringIO()
    writer=csv.writer(output)
    writer.writerow(['Record ID','Title','Date','Status','Student Admission No','Student Name','Details'])
    for r in rows:
        writer.writerow([r['id'],_csv_safe(r['title']),r['event_date'] or '',_csv_safe(r['status'] or ''),r['admission_no'] or '',_csv_safe((r['first_name'] or '')+' '+(r['last_name'] or '')),_csv_safe(r['payload_json'])])
    response=make_response('\ufeff'+output.getvalue())
    response.headers['Content-Type']='text/csv; charset=utf-8'
    response.headers['Content-Disposition']=f'attachment; filename="{key}-records.csv"'
    audit('export',key,None,f"Exported {cfg['label']} CSV")
    return response

# ======================================================================================================
# Version 3 additions: staff leave and payroll, fee structures / arrears / refunds / cashbook,
# academic terms, configurable grading and transcripts, library overdue, absence alerts,
# printable timetable, admission letters and approval history, and backup restore.
# ======================================================================================================
ANNUAL_LEAVE_DAYS = float(os.environ.get('LEAVE_ANNUAL_DAYS', '15'))          # confirm against school/GES policy
SSNIT_EMPLOYEE_RATE = float(os.environ.get('SSNIT_EMPLOYEE_RATE', '5.5'))      # percent of basic salary
SSNIT_EMPLOYER_RATE = float(os.environ.get('SSNIT_EMPLOYER_RATE', '13'))       # percent of basic salary
LIBRARY_FINE_PER_DAY = float(os.environ.get('LIBRARY_FINE_PER_DAY', '0.50'))   # GHS per overdue day
DEFAULT_GRADE_SCALE = [(80.0,'A','Excellent'),(70.0,'B','Very good'),(60.0,'C','Good'),(50.0,'D','Satisfactory'),(40.0,'E','Pass'),(0.0,'F','Fail')]
FINANCE_VIEW_ROLES = ('Administrator','Accountant','Proprietor')
LEADERSHIP_ROLES = ('Administrator','Proprietor','Headteacher')

MODULES['leave'] = {'label':'Staff Leave','roles':{'Administrator','Headteacher'},
  'description':'Leave requests and decisions. Working days are counted Monday to Friday. The yearly annual-leave entitlement is set by LEAVE_ANNUAL_DAYS (default 15); confirm it against the school policy.',
  'fields':[('staff_name','Staff member','text',True),('leave_type','Leave type','select:Annual|Sick|Maternity|Paternity|Compassionate|Study|Unpaid',True),
  ('start_date','First day of leave','date',True),('end_date','Last day of leave','date',True),('leave_status','Decision','select:Pending|Approved|Rejected|Cancelled',True),('notes','Reason or notes','textarea',False)]}
MODULES['payroll'] = {'label':'Payroll','roles':{'Administrator','Proprietor','Accountant'},
  'description':'Monthly pay records. The employee SSNIT contribution is worked out from basic salary at the rate set by SSNIT_EMPLOYEE_RATE (default 5.5%). Enter income tax (PAYE) as calculated by the school accountant. Confirm all rates with the Ghana Revenue Authority and SSNIT before paying staff.',
  'fields':[('staff_name','Staff member','text',True),('pay_month','Pay month (YYYY-MM)','text',True),('basic_salary','Basic salary (GHS)','number',True),('allowances','Allowances (GHS)','number',False),
  ('income_tax','Income tax / PAYE (GHS)','number',False),('other_deductions','Other deductions (GHS)','number',False),('payroll_status','Status','select:Draft|Approved|Paid',True),('notes','Notes','textarea',False)]}
MODULES['fee-structure'] = {'label':'Fee Structures','roles':{'Administrator','Proprietor','Accountant'},
  'description':'Set the fee items for each class, term and year. Use "Generate invoices" to create one invoice per student from these items.',
  'fields':[('class_name','Class','class',True),('academic_year','Academic year','text',True),('term','Term','select:Term 1|Term 2|Term 3',True),('item_name','Fee item (for example Tuition)','text',True),('amount_cedis','Amount (GHS)','number',True),('due_date','Due date','date',False)]}
MODULES['scholarships'] = {'label':'Scholarships & Discounts','roles':{'Administrator','Proprietor','Headteacher','Accountant'},
  'description':'Discounts applied automatically when invoices are generated for the student.',
  'fields':[('student_id','Student','student',True),('academic_year','Academic year','text',True),('term','Applies to','select:All terms|Term 1|Term 2|Term 3',True),('discount_type','Discount type','select:Percentage|Fixed amount',True),
  ('discount_value','Discount value (% or GHS)','number',True),('reason','Reason','text',True),('scholarship_status','Status','select:Active|Ended',True)]}
MODULES['refunds'] = {'label':'Refunds','roles':{'Administrator','Proprietor','Accountant'},
  'description':'Refunds of fees paid. A refund cannot be more than the student has paid. Paid refunds appear in the cashbook as money out.',
  'fields':[('student_id','Student','student',True),('amount_cedis','Refund amount (GHS)','number',True),('event_date','Refund date','date',True),('refund_reason','Reason','text',True),
  ('refund_method','Method','select:Cash|Bank transfer|MTN MoMo|Telecel Cash|AT Money|Cheque',True),('refund_status','Status','select:Pending|Approved|Paid|Rejected',True)]}
MODULES['terms'] = {'label':'Academic Terms','roles':{'Administrator','Headteacher'},
  'description':'Academic years and terms. The term marked Current is used as the default on report cards.',
  'fields':[('academic_year','Academic year (for example 2026/2027)','text',True),('term','Term','select:Term 1|Term 2|Term 3',True),('start_date','Start date','date',True),('end_date','End date','date',True),('term_status','Status','select:Upcoming|Current|Closed',True)]}
MODULES['grading'] = {'label':'Grading Scale','roles':{'Administrator','Headteacher'},
  'description':'The grading scale used on report cards and transcripts. Add one record per grade. If none are added, the default bands are used (A 80, B 70, C 60, D 50, E 40, F below 40).',
  'fields':[('grade','Grade (for example A)','text',True),('min_percent','Lowest percentage for this grade','number',True),('remark','Remark (for example Excellent)','text',False)]}

# -- helpers ---------------------------------------------------------------------------------------------
def _num(v, default=0.0):
    try:
        x = float(v)
        return x if math.isfinite(x) else default
    except (TypeError, ValueError):
        return default

def _payload_of(row):
    try: return json.loads(row['payload_json'])
    except (ValueError, TypeError): return {}

def _records(key, where='', args=()):
    out = []
    for r in db().execute('SELECT * FROM school_records WHERE module_key=? ' + where + ' ORDER BY id', (key,) + tuple(args)).fetchall():
        d = dict(r); d['payload'] = _payload_of(r); out.append(d)
    return out

def _working_days(start, end):
    days, d = 0.0, start
    while d <= end:
        if d.weekday() < 5: days += 1
        d += timedelta(days=1)
    return days

def _parse_date(value, default=None):
    try: return date.fromisoformat(value)
    except (TypeError, ValueError): return default

def _same_name(a, b): return str(a or '').strip().casefold() == str(b or '').strip().casefold()

def _annual_leave_used(staff_name, year, exclude_id=0):
    used = 0.0
    for r in _records('leave'):
        p = r['payload']
        if r['id'] == exclude_id or not _same_name(p.get('staff_name'), staff_name): continue
        if p.get('leave_type') == 'Annual' and p.get('leave_status') in ('Pending', 'Approved') and str(p.get('start_date', ''))[:4] == str(year):
            used += _num(p.get('days'))
    return used

def _grade_scale():
    scale = []
    for r in _records('grading'):
        p = r['payload']
        if p.get('grade'): scale.append((_num(p.get('min_percent')), str(p['grade']), str(p.get('remark', ''))))
    return sorted(scale, reverse=True) or list(DEFAULT_GRADE_SCALE)

def _grade_for(avg, scale):
    for minimum, grade, remark in scale:
        if avg >= minimum: return grade, remark
    return scale[-1][1], scale[-1][2]

def _scale_note(scale):
    custom = bool(_records('grading'))
    text = ', '.join(f"{g} {m:g}+" for m, g, _ in scale)
    return (f'Grading scale set by the school: {text}.' if custom else f'Default grade bands: {text}. Add the school-approved scale under Grading Scale before issuing official reports.')

def _current_term():
    for r in _records('terms'):
        if r['payload'].get('term_status') == 'Current': return r['payload'].get('academic_year', ''), r['payload'].get('term', '')
    return None

def _student_marks(student_id, year='', term=''):
    """Subject averages (percent) for one student, filtered by year and term."""
    subjects = {}
    for row in db().execute("SELECT payload_json FROM school_records WHERE module_key='assessments' AND student_id=? ORDER BY event_date,id", (student_id,)).fetchall():
        p = _payload_of(row)
        if year and p.get('academic_year') != year: continue
        if term and p.get('term') != term: continue
        score, maximum = _num(p.get('score')), _num(p.get('maximum_score'))
        if maximum <= 0: continue
        subjects.setdefault(p.get('subject_name', 'Unspecified subject'), []).append((score / maximum * 100, p.get('teacher_comment', '')))
    return subjects

# -- validation hook used by the generic register saver ---------------------------------------------------
def _v3_validate(key, payload, record_id):
    rid = record_id or 0
    if key == 'leave':
        start, end = _parse_date(payload['start_date']), _parse_date(payload['end_date'])
        if end < start: raise ValueError('The last day of leave must not be before the first day.')
        if (end - start).days > 366: raise ValueError('Leave cannot be longer than one year.')
        days = _working_days(start, end)
        if days <= 0: raise ValueError('The selected dates contain no working days (Monday to Friday).')
        payload['days'] = days; payload['event_date'] = payload['start_date']
        active = payload['leave_status'] in ('Pending', 'Approved')
        for r in _records('leave'):
            p = r['payload']
            if r['id'] == rid or not _same_name(p.get('staff_name'), payload['staff_name']) or p.get('leave_status') not in ('Pending', 'Approved') or not active: continue
            if start <= _parse_date(p.get('end_date'), start) and end >= _parse_date(p.get('start_date'), end):
                raise ValueError('This staff member already has leave that overlaps these dates.')
        if payload['leave_type'] == 'Annual' and active:
            used = _annual_leave_used(payload['staff_name'], start.year, rid)
            if used + days > ANNUAL_LEAVE_DAYS + 1e-9:
                raise ValueError(f'This would use {used + days:g} annual leave days in {start.year}, which is more than the entitlement of {ANNUAL_LEAVE_DAYS:g}.')
    elif key == 'payroll':
        month = payload['pay_month']
        if not re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])', month): raise ValueError('Pay month must look like 2026-11.')
        for r in _records('payroll'):
            if r['id'] != rid and _same_name(r['payload'].get('staff_name'), payload['staff_name']) and r['payload'].get('pay_month') == month:
                raise ValueError('A payroll record for this staff member and month already exists.')
        basic, allowances = _num(payload.get('basic_salary')), _num(payload.get('allowances'))
        tax, other = _num(payload.get('income_tax')), _num(payload.get('other_deductions'))
        if basic <= 0: raise ValueError('Basic salary must be greater than zero.')
        gross = basic + allowances
        ssnit = round(basic * SSNIT_EMPLOYEE_RATE / 100, 2)
        deductions = round(ssnit + tax + other, 2)
        if deductions > gross: raise ValueError('Total deductions are more than gross pay.')
        payload.update(gross_pay=round(gross, 2), ssnit_employee=ssnit, ssnit_employer=round(basic * SSNIT_EMPLOYER_RATE / 100, 2),
                       ssnit_rate=SSNIT_EMPLOYEE_RATE, total_deductions=deductions, net_pay=round(gross - deductions, 2),
                       amount_cedis=round(gross - deductions, 2), event_date=month + '-01')
    elif key == 'fee-structure':
        if _num(payload.get('amount_cedis')) <= 0: raise ValueError('The fee amount must be greater than zero.')
        for r in _records('fee-structure'):
            p = r['payload']
            if r['id'] != rid and p.get('class_name') == payload['class_name'] and p.get('academic_year') == payload['academic_year'] and p.get('term') == payload['term'] and _same_name(p.get('item_name'), payload['item_name']):
                raise ValueError('This fee item already exists for that class, year and term.')
        if payload.get('due_date'): payload['event_date'] = payload['due_date']
    elif key == 'scholarships':
        value = _num(payload.get('discount_value'))
        if value <= 0: raise ValueError('The discount must be greater than zero.')
        if payload['discount_type'] == 'Percentage' and value > 100: raise ValueError('A percentage discount cannot be more than 100.')
        payload['event_date'] = date.today().isoformat()
    elif key == 'refunds':
        amount = _num(payload.get('amount_cedis'))
        if amount <= 0: raise ValueError('The refund must be greater than zero.')
        if payload['refund_status'] in ('Approved', 'Paid'):
            sid = int(payload['student_id'])
            paid = db().execute('SELECT COALESCE(SUM(amount),0) FROM fees WHERE student_id=?', (sid,)).fetchone()[0]
            refunded = sum(_num(r['payload'].get('amount_cedis')) for r in _records('refunds') if r['id'] != rid and r['student_id'] == sid and r['payload'].get('refund_status') in ('Approved', 'Paid'))
            if amount + refunded > paid + 0.004:
                raise ValueError(f'This refund is more than the student has paid (paid GH₵ {paid:.2f}, already refunded GH₵ {refunded:.2f}).')
    elif key == 'terms':
        start, end = _parse_date(payload['start_date']), _parse_date(payload['end_date'])
        if end <= start: raise ValueError('The end date must be after the start date.')
        for r in _records('terms'):
            p = r['payload']
            if r['id'] == rid: continue
            if p.get('academic_year') == payload['academic_year'] and p.get('term') == payload['term']: raise ValueError('That term already exists for this academic year.')
            if payload['term_status'] == 'Current' and p.get('term_status') == 'Current': raise ValueError('Another term is already marked Current. Mark it Closed first.')
        payload['event_date'] = payload['start_date']
    elif key == 'grading':
        value = _num(payload.get('min_percent'), -1)
        if value < 0 or value > 100: raise ValueError('The lowest percentage must be between 0 and 100.')
        for r in _records('grading'):
            p = r['payload']
            if r['id'] == rid: continue
            if _same_name(p.get('grade'), payload['grade']): raise ValueError('That grade already exists.')
            if abs(_num(p.get('min_percent')) - value) < 1e-9: raise ValueError('Another grade already starts at that percentage.')

def _v3_title(key, p):
    return {'leave': lambda: f"{p.get('staff_name','')} · {p.get('leave_type','')} leave",
            'payroll': lambda: f"{p.get('staff_name','')} · {p.get('pay_month','')}",
            'fee-structure': lambda: f"{p.get('item_name','')} · {p.get('class_name','')} {p.get('term','')}",
            'scholarships': lambda: f"Scholarship · {p.get('discount_value','')}{'%' if p.get('discount_type')=='Percentage' else ' GHS'}",
            'refunds': lambda: f"Refund · GH₵ {_num(p.get('amount_cedis')):.2f}",
            'terms': lambda: f"{p.get('academic_year','')} · {p.get('term','')}",
            'grading': lambda: f"Grade {p.get('grade','')} (from {_num(p.get('min_percent')):g}%)"}.get(key, lambda: None)()

# -- staff leave balances --------------------------------------------------------------------------------
@app.route('/staff/leave-balances')
@roles_required('Administrator','Headteacher')
def leave_balances():
    year = request.args.get('year', str(date.today().year)).strip()
    if not re.fullmatch(r'\d{4}', year): abort(400)
    names = {}
    for r in _records('staff'): names[r['payload'].get('full_name', r['title']).strip().casefold()] = r['payload'].get('full_name', r['title'])
    leave = _records('leave')
    for r in leave: names.setdefault(str(r['payload'].get('staff_name', '')).strip().casefold(), r['payload'].get('staff_name', ''))
    rows = []
    for key_, name in sorted(names.items()):
        if not key_: continue
        taken = {}; pending = 0.0
        for r in leave:
            p = r['payload']
            if not _same_name(p.get('staff_name'), name) or str(p.get('start_date', ''))[:4] != year: continue
            if p.get('leave_status') == 'Approved': taken[p.get('leave_type')] = taken.get(p.get('leave_type'), 0) + _num(p.get('days'))
            elif p.get('leave_status') == 'Pending': pending += _num(p.get('days'))
        annual = taken.get('Annual', 0.0)
        rows.append({'name': name, 'entitlement': ANNUAL_LEAVE_DAYS, 'annual': annual, 'pending': pending, 'remaining': ANNUAL_LEAVE_DAYS - annual,
                     'sick': taken.get('Sick', 0.0), 'other': sum(v for k, v in taken.items() if k not in ('Annual', 'Sick'))})
    return render_template('leave_balances.html', rows=rows, year=year)

# -- payroll ---------------------------------------------------------------------------------------------
@app.route('/payroll/summary')
@roles_required(*FINANCE_VIEW_ROLES)
def payroll_summary():
    month = request.args.get('month', date.today().strftime('%Y-%m')).strip()
    if not re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])', month): abort(400)
    rows = [r for r in _records('payroll') if r['payload'].get('pay_month') == month]
    keys = ('basic_salary', 'allowances', 'gross_pay', 'ssnit_employee', 'income_tax', 'other_deductions', 'net_pay', 'ssnit_employer')
    totals = {k: round(sum(_num(r['payload'].get(k)) for r in rows), 2) for k in keys}
    return render_template('payroll_summary.html', rows=rows, month=month, totals=totals)

@app.route('/payroll/<int:record_id>/payslip')
@roles_required(*FINANCE_VIEW_ROLES)
def payslip(record_id):
    row = db().execute("SELECT * FROM school_records WHERE id=? AND module_key='payroll'", (record_id,)).fetchone()
    if not row: abort(404)
    audit('view', 'payroll', record_id, 'Opened payslip')
    return render_template('payslip.html', p=_payload_of(row), record=row)

# -- fee generation, arrears, cashbook -------------------------------------------------------------------
def _scholarship_discount(student_id, year, term, total):
    discount = 0.0
    for r in _records('scholarships'):
        p = r['payload']
        if r['student_id'] != student_id or p.get('scholarship_status') != 'Active' or p.get('academic_year') != year or p.get('term') not in ('All terms', term): continue
        value = _num(p.get('discount_value'))
        discount += total * value / 100 if p.get('discount_type') == 'Percentage' else value
    return round(min(discount, total), 2)

@app.route('/fees/generate', methods=['GET', 'POST'])
@roles_required('Administrator','Accountant')
def fees_generate():
    conn = db(); classes = conn.execute('SELECT name FROM classes WHERE active=1 ORDER BY id').fetchall()
    result = None
    if request.method == 'POST':
        class_name, year, term = request.form.get('class_name', ''), request.form.get('academic_year', '').strip(), request.form.get('term', '')
        due = request.form.get('due_date', '').strip()
        items = [r for r in _records('fee-structure') if r['payload'].get('class_name') == class_name and r['payload'].get('academic_year') == year and r['payload'].get('term') == term]
        if not conn.execute('SELECT 1 FROM classes WHERE name=?', (class_name,)).fetchone() or not year or term not in ('Term 1', 'Term 2', 'Term 3'):
            flash('Choose a class, academic year and term.', 'error')
        elif not items:
            flash('No fee items are set for that class, year and term. Add them under Fee Structures first.', 'error')
        elif due and not _parse_date(due):
            flash('Enter a valid due date.', 'error')
        else:
            total = round(sum(_num(i['payload'].get('amount_cedis')) for i in items), 2)
            due_date = due or next((i['payload'].get('due_date') for i in items if i['payload'].get('due_date')), '') or date.today().isoformat()
            desc = ('Term fees: ' + ', '.join(i['payload'].get('item_name', '') for i in items))[:200]
            made = skipped = 0
            for s in conn.execute("SELECT s.id FROM students s JOIN classes c ON c.id=s.class_id WHERE s.status='Active' AND c.name=? ORDER BY s.id", (class_name,)).fetchall():
                if conn.execute("SELECT 1 FROM fee_invoices WHERE student_id=? AND academic_year=? AND term=? AND description LIKE 'Term fees:%'", (s['id'], year, term)).fetchone():
                    skipped += 1; continue
                discount = _scholarship_discount(s['id'], year, term, total)
                inv = SCHOOL_CODE + '-INV-' + datetime.now().strftime('%Y%m%d') + '-' + secrets.token_hex(3).upper()
                conn.execute('INSERT INTO fee_invoices(invoice_no,student_id,academic_year,term,description,amount,discount,due_date,created_by) VALUES(?,?,?,?,?,?,?,?,?)',
                             (inv, s['id'], year, term, desc, total, discount, due_date, current_user()['id']))
                made += 1
            conn.commit(); audit('generate', 'invoice', None, f'{class_name} {year} {term}: {made} created, {skipped} skipped')
            result = {'made': made, 'skipped': skipped, 'total': total, 'class_name': class_name}
            flash(f'{made} invoice(s) created for {class_name} ({total:.2f} each before discounts). {skipped} student(s) already had term fees and were skipped.', 'success')
    return render_template('fees_generate.html', classes=classes, result=result, form=request.form)

def _arrears_data(class_name='', year='', term='', only_owing=True):
    conn = db(); today = date.today().isoformat()
    sql = "SELECT s.id,s.admission_no,s.first_name,s.last_name,c.name class_name,s.guardian_name,s.guardian_phone FROM students s LEFT JOIN classes c ON c.id=s.class_id WHERE s.status='Active'"
    args = []
    if class_name: sql += ' AND c.name=?'; args.append(class_name)
    students = conn.execute(sql + ' ORDER BY c.id,s.last_name,s.first_name', args).fetchall()
    refunds = {}
    for r in _records('refunds'):
        if r['payload'].get('refund_status') in ('Approved', 'Paid'): refunds[r['student_id']] = refunds.get(r['student_id'], 0) + _num(r['payload'].get('amount_cedis'))
    inv_sql = '''SELECT i.*,COALESCE((SELECT SUM(f.amount) FROM fees f WHERE f.student_id=i.student_id AND f.purpose=i.invoice_no),0) paid FROM fee_invoices i WHERE 1=1'''
    inv_args = []
    if year: inv_sql += ' AND i.academic_year=?'; inv_args.append(year)
    if term: inv_sql += ' AND i.term=?'; inv_args.append(term)
    by_student = {}
    for i in conn.execute(inv_sql, inv_args).fetchall(): by_student.setdefault(i['student_id'], []).append(i)
    rows = []
    for s in students:
        invs = by_student.get(s['id'], [])
        if not invs: continue
        billed = sum(float(i['amount']) for i in invs); discount = sum(float(i['discount']) for i in invs); paid = sum(float(i['paid']) for i in invs)
        balance = sum(max(0.0, float(i['amount']) - float(i['discount']) - float(i['paid'])) for i in invs)
        overdue = sum(max(0.0, float(i['amount']) - float(i['discount']) - float(i['paid'])) for i in invs if i['due_date'] < today)
        if only_owing and balance <= 0.004: continue
        rows.append({'student': s, 'billed': round(billed, 2), 'discount': round(discount, 2), 'paid': round(paid, 2), 'balance': round(balance, 2), 'overdue': round(overdue, 2), 'refunded': round(refunds.get(s['id'], 0), 2), 'invoices': len(invs)})
    totals = {k: round(sum(r[k] for r in rows), 2) for k in ('billed', 'discount', 'paid', 'balance', 'overdue', 'refunded')}
    return rows, totals

def _arrears_args():
    class_name, year, term = request.args.get('class_name', '').strip(), request.args.get('academic_year', '').strip(), request.args.get('term', '').strip()
    if term and term not in ('Term 1', 'Term 2', 'Term 3'): abort(400)
    return class_name, year, term, request.args.get('show', 'owing') != 'all'

@app.route('/fees/arrears')
@roles_required('Administrator','Accountant','Proprietor','Headteacher')
def fees_arrears():
    class_name, year, term, only_owing = _arrears_args()
    rows, totals = _arrears_data(class_name, year, term, only_owing)
    return render_template('arrears.html', rows=rows, totals=totals, class_name=class_name, year=year, term=term, only_owing=only_owing,
                           classes=db().execute('SELECT name FROM classes WHERE active=1 ORDER BY id').fetchall())

@app.route('/fees/arrears.csv')
@roles_required('Administrator','Accountant','Proprietor','Headteacher')
def fees_arrears_csv():
    class_name, year, term, only_owing = _arrears_args()
    rows, totals = _arrears_data(class_name, year, term, only_owing)
    out = io.StringIO(); w = csv.writer(out)
    w.writerow(['Admission number', 'Student', 'Class', 'Guardian', 'Guardian phone', 'Billed', 'Discount', 'Paid', 'Outstanding', 'Overdue', 'Refunded'])
    for r in rows:
        s = r['student']
        w.writerow([_csv_safe(x) for x in [s['admission_no'], f"{s['first_name']} {s['last_name']}", s['class_name'] or '', s['guardian_name'] or '', s['guardian_phone'] or '']] + [f"{r[k]:.2f}" for k in ('billed', 'discount', 'paid', 'balance', 'overdue', 'refunded')])
    w.writerow(['Total', '', '', '', ''] + [f"{totals[k]:.2f}" for k in ('billed', 'discount', 'paid', 'balance', 'overdue', 'refunded')])
    audit('export', 'arrears', None, 'Exported fee arrears CSV')
    resp = make_response(out.getvalue()); resp.headers['Content-Type'] = 'text/csv; charset=utf-8'
    resp.headers['Content-Disposition'] = f'attachment; filename=fee_arrears_{date.today().isoformat()}.csv'
    return resp

def _csv_safe(v):
    v = str(v)
    return "'" + v if v[:1] in ('=', '+', '-', '@', '\t', '\r') else v

@app.route('/fees/cashbook')
@roles_required(*FINANCE_VIEW_ROLES)
def cashbook():
    today = date.today()
    start = request.args.get('start_date', today.replace(day=1).isoformat()).strip(); end = request.args.get('end_date', today.isoformat()).strip()
    if not _parse_date(start) or not _parse_date(end) or start > end: abort(400)
    entries = []
    for f in db().execute('SELECT f.*,s.first_name,s.last_name FROM fees f JOIN students s ON s.id=f.student_id').fetchall():
        entries.append((f['payment_date'], 'Fee receipt', f"{f['receipt_no']} · {f['first_name']} {f['last_name']} · {f['purpose']}", float(f['amount']), 0.0))
    for r in _records('finance'):
        p = r['payload']; amt = _num(p.get('amount_cedis'))
        entries.append((r['event_date'] or '', p.get('transaction_type', ''), f"{p.get('category','')} · {p.get('description','')}", amt if p.get('transaction_type') == 'Income' else 0.0, amt if p.get('transaction_type') == 'Expenditure' else 0.0))
    names = {s['id']: f"{s['first_name']} {s['last_name']}" for s in db().execute('SELECT id,first_name,last_name FROM students').fetchall()}
    for r in _records('refunds'):
        if r['payload'].get('refund_status') == 'Paid':
            entries.append((r['event_date'] or '', 'Refund', f"Refund to {names.get(r['student_id'], 'student')} · {r['payload'].get('refund_reason','')}", 0.0, _num(r['payload'].get('amount_cedis'))))
    entries.sort(key=lambda e: e[0])
    opening = round(sum(e[3] - e[4] for e in entries if e[0] < start), 2)
    balance, rows = opening, []
    for e in entries:
        if start <= e[0] <= end:
            balance = round(balance + e[3] - e[4], 2); rows.append({'date': e[0], 'kind': e[1], 'text': e[2], 'money_in': e[3], 'money_out': e[4], 'balance': balance})
    totals = {'in': round(sum(r['money_in'] for r in rows), 2), 'out': round(sum(r['money_out'] for r in rows), 2)}
    return render_template('cashbook.html', rows=rows, opening=opening, closing=balance, totals=totals, start=start, end=end)

# -- transcripts -----------------------------------------------------------------------------------------
@app.route('/students/<int:student_id>/transcript')
@roles_required('Administrator','Proprietor','Headteacher','Class Teacher','Subject Teacher','Teacher')
def transcript(student_id):
    s = db().execute('SELECT s.*,c.name class_name FROM students s LEFT JOIN classes c ON c.id=s.class_id WHERE s.id=?', (student_id,)).fetchone()
    if not s: abort(404)
    sc = class_scope(current_user())
    if sc is not None and s['class_name'] not in sc: abort(403)
    scale = _grade_scale(); periods = {}
    for row in db().execute("SELECT payload_json FROM school_records WHERE module_key='assessments' AND student_id=?", (student_id,)).fetchall():
        p = _payload_of(row); periods.setdefault((p.get('academic_year', ''), p.get('term', '')), None)
    terms = []
    for (year, term) in sorted(periods):
        marks = _student_marks(student_id, year, term)
        if not marks: continue
        subj = []
        for name, vals in sorted(marks.items()):
            avg = sum(v[0] for v in vals) / len(vals); grade, remark = _grade_for(avg, scale)
            subj.append({'name': name, 'average': avg, 'grade': grade, 'remark': remark})
        overall = sum(x['average'] for x in subj) / len(subj)
        terms.append({'year': year, 'term': term, 'subjects': subj, 'average': overall, 'grade': _grade_for(overall, scale)[0]})
    audit('view', 'transcript', student_id, 'Opened transcript')
    return render_template('transcript.html', student=s, terms=terms, scale=scale, scale_note=_scale_note(scale), generated=date.today().isoformat())

# -- library overdue -------------------------------------------------------------------------------------
def _open_loans():
    recs = sorted(_records('library'), key=lambda r: (r['event_date'] or '', r['id']))
    loans = []; today = date.today()
    for r in recs:
        p = r['payload']; kind = p.get('transaction_type')
        book = (p.get('book_code') or p.get('book_title', '')).strip().casefold()
        who = (p.get('borrower_admission_no') or p.get('borrower_name', '')).strip().casefold()
        if kind == 'Book issued':
            loans.append({'record': r, 'book': book, 'who': who})
        elif kind in ('Book returned', 'Lost'):
            for i, loan in enumerate(loans):
                if loan['book'] == book and (not who or loan['who'] == who):
                    del loans[i]; break
    out = []
    for loan in loans:
        p = loan['record']['payload']; due = _parse_date(p.get('due_date'))
        days = (today - due).days if due and due < today else 0
        out.append({'id': loan['record']['id'], 'title': p.get('book_title', ''), 'code': p.get('book_code', ''), 'borrower': p.get('borrower_name', ''), 'admission_no': p.get('borrower_admission_no', ''),
                    'issued': loan['record']['event_date'] or '', 'due': p.get('due_date', ''), 'days_overdue': days, 'fine': round(days * LIBRARY_FINE_PER_DAY, 2)})
    return sorted(out, key=lambda x: (-x['days_overdue'], x['due']))

@app.route('/library/overdue')
@roles_required('Administrator','Headteacher','Librarian')
def library_overdue():
    loans = _open_loans()
    return render_template('overdue.html', loans=loans, overdue=[x for x in loans if x['days_overdue']], fine_rate=LIBRARY_FINE_PER_DAY)

@app.route('/library/overdue/<int:record_id>/notice')
@roles_required('Administrator','Headteacher','Librarian')
def overdue_notice(record_id):
    loan = next((x for x in _open_loans() if x['id'] == record_id and x['days_overdue']), None)
    if not loan: abort(404)
    return render_template('overdue_notice.html', loan=loan, fine_rate=LIBRARY_FINE_PER_DAY, today=date.today().isoformat())

# -- absence alerts --------------------------------------------------------------------------------------
@app.route('/reports/absence-alerts')
@roles_required('Administrator','Proprietor','Headteacher','Class Teacher','Subject Teacher','Teacher')
def absence_alerts():
    try: days = int(request.args.get('days', '14')); minimum = int(request.args.get('minimum', '3'))
    except ValueError: abort(400)
    if not 1 <= days <= 120 or not 1 <= minimum <= 60: abort(400)
    sc = class_scope(current_user())
    if sc is not None and not sc: abort(403)
    since = (date.today() - timedelta(days=days)).isoformat(); counts = {}
    for r in db().execute("SELECT student_id,class_name,event_date,payload_json FROM school_records WHERE module_key='attendance' AND event_date>=? AND student_id IS NOT NULL", (since,)).fetchall():
        if _payload_of(r).get('attendance_status') != 'Absent': continue
        if sc is not None and r['class_name'] not in sc: continue
        counts.setdefault(r['student_id'], []).append(r['event_date'])
    rows = []
    for sid, dates in counts.items():
        if len(dates) < minimum: continue
        s = db().execute("SELECT s.*,c.name class_name FROM students s LEFT JOIN classes c ON c.id=s.class_id WHERE s.id=? AND s.status='Active'", (sid,)).fetchone()
        if s: rows.append({'student': s, 'count': len(dates), 'last': max(dates), 'dates': sorted(dates)})
    rows.sort(key=lambda x: (-x['count'], x['student']['last_name']))
    return render_template('absence_alerts.html', rows=rows, days=days, minimum=minimum, since=since)

# -- printable timetable ---------------------------------------------------------------------------------
@app.route('/timetable/print')
@roles_required('Administrator','Headteacher','Class Teacher','Subject Teacher','Teacher')
def timetable_print():
    sc = class_scope(current_user())
    if sc is not None and not sc: abort(403)
    class_name = request.args.get('class_name', '').strip(); year = request.args.get('academic_year', '').strip(); term = request.args.get('term', '').strip()
    if class_name and sc is not None and class_name not in sc: abort(403)
    classes = [c['name'] for c in db().execute('SELECT name FROM classes WHERE active=1 ORDER BY id').fetchall() if sc is None or c['name'] in sc]
    grid = None; slots = []
    if class_name:
        cells = {}
        for r in _records('timetable'):
            p = r['payload']
            if r['class_name'] != class_name or (year and p.get('academic_year') != year) or (term and p.get('term') != term): continue
            slot = (p.get('start_time', ''), p.get('end_time', '')); cells.setdefault((slot, p.get('day')), []).append(p)
        slots = sorted({k[0] for k in cells})
        grid = [{'slot': sl, 'cells': [cells.get((sl, d), []) for d in ('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday')]} for sl in slots]
    return render_template('timetable_print.html', classes=classes, class_name=class_name, year=year, term=term, grid=grid,
                           days=['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'])

# -- admissions: approval history and offer letter -------------------------------------------------------
def _record_admission_history(record_id, status, old_status):
    if status == old_status: return
    note = (db().execute("SELECT payload_json FROM school_records WHERE id=?", (record_id,)).fetchone() or {'payload_json': '{}'})['payload_json']
    db().execute('INSERT INTO admission_history(record_id,status,previous_status,changed_by,notes) VALUES(?,?,?,?,?)',
                 (record_id, status, old_status, current_user()['id'], _payload_of({'payload_json': note}).get('decision_notes', '')))
    db().commit()

def _admission_row(record_id):
    row = db().execute("SELECT * FROM school_records WHERE id=? AND module_key='admissions'", (record_id,)).fetchone()
    if not row: abort(404)
    return row

@app.route('/modules/admissions/<int:record_id>/history')
@roles_required('Administrator','Headteacher','Admissions Officer')
def admission_history(record_id):
    row = _admission_row(record_id)
    history = db().execute('SELECT h.*,u.full_name FROM admission_history h LEFT JOIN users u ON u.id=h.changed_by WHERE h.record_id=? ORDER BY h.id', (record_id,)).fetchall()
    return render_template('admission_history.html', record=row, p=_payload_of(row), history=history)

@app.route('/modules/admissions/<int:record_id>/letter')
@roles_required('Administrator','Headteacher','Admissions Officer')
def admission_letter(record_id):
    row = _admission_row(record_id); p = _payload_of(row)
    if row['status'] not in ('Accepted', 'Enrolled'): flash('An offer letter can only be printed for an accepted or enrolled applicant.', 'error'); return redirect(url_for('module_list', key='admissions'))
    audit('view', 'admissions', record_id, 'Opened admission letter')
    return render_template('admission_letter.html', record=row, p=p, today=date.today().isoformat())

# -- backup restore --------------------------------------------------------------------------------------
def _dump_sql():
    source = sqlite3.connect(DB_PATH, timeout=15); target = sqlite3.connect(':memory:')
    try:
        source.backup(target)
        return '\n'.join(target.iterdump())
    finally:
        source.close(); target.close()

RESTORE_REQUIRED_TABLES = {'users', 'students', 'classes', 'fees', 'school_records', 'audit_log'}

@app.route('/admin/restore', methods=['GET', 'POST'])
@roles_required('Administrator')
def restore_backup():
    if request.method == 'POST':
        upload = request.files.get('backup_file')
        if request.form.get('confirm', '').strip() != 'RESTORE':
            flash('Type RESTORE in the confirmation box.', 'error'); return redirect(url_for('restore_backup'))
        if not upload or not upload.filename.lower().endswith('.sql'):
            flash('Choose a .sql backup file downloaded from this system.', 'error'); return redirect(url_for('restore_backup'))
        raw = upload.read(40 * 1024 * 1024 + 1)
        if len(raw) > 40 * 1024 * 1024: flash('The backup file is too large.', 'error'); return redirect(url_for('restore_backup'))
        try: text = raw.decode('utf-8')
        except UnicodeDecodeError: flash('That file is not a valid backup.', 'error'); return redirect(url_for('restore_backup'))
        temp = sqlite3.connect(':memory:')
        def authorizer(action, arg1, arg2, dbname, source):
            if action in (sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH): return sqlite3.SQLITE_DENY
            if action == sqlite3.SQLITE_PRAGMA and str(arg1).lower() != 'foreign_keys': return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        try:
            temp.set_authorizer(authorizer); temp.executescript(text); temp.set_authorizer(None)
            tables = {r[0] for r in temp.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
            if not RESTORE_REQUIRED_TABLES <= tables: raise ValueError('The file is missing school tables.')
            if temp.execute("SELECT COUNT(*) FROM users WHERE role='Administrator' AND active=1").fetchone()[0] < 1: raise ValueError('The backup has no active Administrator account.')
            if temp.execute('PRAGMA integrity_check').fetchone()[0] != 'ok': raise ValueError('The backup failed an integrity check.')
        except (sqlite3.Error, ValueError) as exc:
            temp.close(); flash(f'The file was not restored because it is not a valid school backup ({exc}). Nothing was changed.', 'error'); return redirect(url_for('restore_backup'))
        # Keep a safety copy of the current data before replacing it.
        safety_dir = os.path.join(document_upload_dir(), '_backups'); os.makedirs(safety_dir, exist_ok=True)
        safety = os.path.join(safety_dir, f"before_restore_{datetime.now().strftime('%Y%m%d_%H%M%S')}.sql")
        with open(safety, 'w', encoding='utf-8') as fh: fh.write(_dump_sql())
        destination = sqlite3.connect(DB_PATH, timeout=30)
        try: temp.backup(destination)
        finally: destination.close(); temp.close()
        init_db()
        try: audit('restore', 'database', None, f'Database restored from {upload.filename}. Safety copy: {os.path.basename(safety)}')
        except sqlite3.Error: pass
        session.clear()
        flash('The backup was restored. Please sign in again. A safety copy of the previous data was kept on the server.', 'success')
        return redirect(url_for('login'))
    return render_template('restore.html')

# ======================================================================================================
# Version 4 additions: SMS (Arkesel), email (SMTP) and mobile money (Paystack). All switched off until
# the school adds the settings described in integrations.py and INTEGRATIONS_SETUP.md.
# ======================================================================================================

MAX_MESSAGE_RECIPIENTS = 500
COMMS_ROLES = ('Administrator', 'Headteacher', 'Proprietor')
PLACEHOLDERS = ('student', 'guardian', 'class', 'balance', 'school')
MOMO_PENDING = ('Initiating', 'Pending', 'OTP needed')


@app.context_processor
def _integration_flags():
    s = INT.status()
    return {'sms_ready': s['sms']['ready'], 'email_ready': s['email']['ready'], 'momo_ready': s['momo']['ready']}


def _log_message(channel, recipient, subject, body, ok, ref='', error='', student_id=None):
    u = current_user()
    db().execute('INSERT INTO message_log(channel,recipient,subject,body,status,provider_ref,error,student_id,sent_by) VALUES(?,?,?,?,?,?,?,?,?)',
                 (channel, recipient, (subject or '')[:200], body[:1000], 'Sent' if ok else 'Failed', ref, (error or '')[:300], student_id, u['id'] if u else None))


def _fill(template, values):
    """Replace {student}, {guardian}, {class}, {balance} and {school}. Anything else is left exactly as typed."""
    return re.sub(r'\{(' + '|'.join(PLACEHOLDERS) + r')\}', lambda m: str(values.get(m.group(1), '')), template)


def _audience_groups(audience, class_name='', student_id=None):
    """People to contact, one entry per phone number (a parent with several children gets one message)."""
    conn = db(); entries = []
    if audience == 'staff':
        for r in _records('staff'):
            p = r['payload']
            if p.get('employment_status') in ('Separated', 'Suspended'): continue
            entries.append({'name': p.get('full_name', r['title']), 'phone': INT.normalize_phone(p.get('phone')), 'email': p.get('email', '') if INT.valid_email(p.get('email')) else '',
                            'students': [], 'classes': [], 'balance': 0.0, 'student_id': None, 'key': f"staff-{r['id']}"})
    else:
        sql = "SELECT s.id,s.first_name,s.last_name,s.guardian_name,s.guardian_phone,s.guardian_email,c.name class_name FROM students s LEFT JOIN classes c ON c.id=s.class_id WHERE s.status='Active'"
        args = []
        if audience == 'class': sql += ' AND c.name=?'; args.append(class_name)
        elif audience == 'student': sql += ' AND s.id=?'; args.append(student_id)
        students = conn.execute(sql + ' ORDER BY s.last_name,s.first_name', args).fetchall()
        owing = {}
        if audience == 'owing':
            rows, _ = _arrears_data(class_name, '', '', True)
            owing = {r['student']['id']: r['balance'] for r in rows}
            students = [s for s in students if s['id'] in owing]
        for s in students:
            entries.append({'name': s['guardian_name'] or 'Parent/Guardian', 'phone': INT.normalize_phone(s['guardian_phone']), 'email': s['guardian_email'] if INT.valid_email(s['guardian_email']) else '',
                            'students': [f"{s['first_name']} {s['last_name']}"], 'classes': [s['class_name'] or ''], 'balance': owing.get(s['id'], 0.0), 'student_id': s['id'],
                            'key': ('p' + INT.normalize_phone(s['guardian_phone'])) if INT.normalize_phone(s['guardian_phone']) else f"s-{s['id']}"})
    groups = {}
    for e in entries:
        g = groups.setdefault(e['key'], dict(e, students=[], classes=[], balance=0.0))
        g['students'] += e['students']; g['classes'] += [c for c in e['classes'] if c and c not in g['classes']]; g['balance'] += e['balance']
        g['email'] = g['email'] or e['email']
    return list(groups.values())


def _group_values(g):
    return {'student': ' and '.join(g['students']), 'guardian': g['name'], 'class': ', '.join(g['classes']), 'balance': f"GHS {g['balance']:.2f}" if g['balance'] else '', 'school': 'Fr. Joseph Connolly SVD Memorial School'}


def _deliver(channel, targets, subject, template):
    """targets: groups. Sends and logs. Returns counts."""
    sent = failed = 0
    if channel in ('sms', 'both'):
        pairs = [(g['phone'], _fill(template, _group_values(g))) for g in targets if g['phone']]
        owners = [g for g in targets if g['phone']]
        if pairs:
            for person, (number, text), res in zip(owners, pairs, INT.send_sms(pairs)):
                _log_message('sms', number, '', text, res['ok'], res['ref'], res['error'], person.get('student_id'))
                sent += res['ok']; failed += (not res['ok'])
    if channel in ('email', 'both'):
        for person in targets:
            if not person['email']: continue
            text = _fill(template, _group_values(person)); subj = _fill(subject, _group_values(person))
            try: INT.send_email(person['email'], subj, text); _log_message('email', person['email'], subj, text, True, '', '', person.get('student_id')); sent += 1
            except INT.IntegrationError as exc: _log_message('email', person['email'], subj, text, False, '', str(exc), person.get('student_id')); failed += 1
    db().commit()
    return sent, failed


@app.route('/communications', methods=['GET', 'POST'])
@roles_required(*COMMS_ROLES)
def communications():
    conn = db()
    classes = [c['name'] for c in conn.execute('SELECT name FROM classes WHERE active=1 ORDER BY id').fetchall()]
    students = conn.execute("SELECT id,admission_no,first_name,last_name FROM students WHERE status='Active' ORDER BY last_name,first_name").fetchall()
    form = {'audience': 'class', 'channel': 'sms', 'class_name': '', 'student_id': '', 'subject': '', 'message': ''}
    preview = result = None
    if request.method == 'GET' and request.args.get('announcement', '').isdigit():
        row = conn.execute("SELECT * FROM school_records WHERE id=? AND module_key='announcements'", (int(request.args['announcement']),)).fetchone()
        if row:
            p = _payload_of(row); aud = p.get('audience', '')
            form.update(subject=p.get('announcement_title', ''), message=f"{p.get('announcement_title', '')}: {p.get('message', '')}"[:600],
                        audience='staff' if aud in ('All staff', 'Teachers') else 'class' if aud == 'Specific class' and p.get('class_name') else 'all', class_name=p.get('class_name', ''))
    if request.method == 'POST':
        form = {k: request.form.get(k, '').strip() for k in ('audience', 'channel', 'class_name', 'student_id', 'subject', 'message')}
        error = None
        if form['audience'] not in ('all', 'class', 'owing', 'student', 'staff'): error = 'Choose who should receive the message.'
        elif form['channel'] not in ('sms', 'email', 'both'): error = 'Choose how to send the message.'
        elif not form['message'] or len(form['message']) > 600: error = 'Write a message of up to 600 characters.'
        elif form['channel'] in ('email', 'both') and not form['subject']: error = 'Add an email subject.'
        elif form['channel'] in ('sms', 'both') and not INT.status()['sms']['ready']: error = 'SMS is not switched on yet. See Integrations.'
        elif form['channel'] in ('email', 'both') and not INT.status()['email']['ready']: error = 'Email is not switched on yet. See Integrations.'
        elif form['audience'] == 'class' and form['class_name'] not in classes: error = 'Choose a class.'
        elif form['audience'] == 'owing' and form['class_name'] and form['class_name'] not in classes: error = 'Choose a valid class.'
        elif form['audience'] == 'student' and not form['student_id'].isdigit(): error = 'Choose a student.'
        if error: flash(error, 'error')
        else:
            groups = _audience_groups(form['audience'], form['class_name'], int(form['student_id']) if form['student_id'].isdigit() else None)
            sms_t = [g for g in groups if g['phone']] if form['channel'] in ('sms', 'both') else []
            mail_t = [g for g in groups if g['email']] if form['channel'] in ('email', 'both') else []
            targets = [g for g in groups if (g in sms_t) or (g in mail_t)]
            sample = _fill(form['message'], _group_values(targets[0])) if targets else ''
            preview = {'people': len(groups), 'sms': len(sms_t), 'email': len(mail_t), 'skipped': len(groups) - len(targets), 'sample': sample, 'segments': INT.sms_segments(sample) if sample else 0}
            if len(targets) > MAX_MESSAGE_RECIPIENTS: flash(f'That is {len(targets)} people. Send to {MAX_MESSAGE_RECIPIENTS} or fewer at a time (choose one class).', 'error')
            elif request.form.get('action') == 'send':
                if request.form.get('confirm') != 'yes': flash('Tick the box to confirm you have checked the preview.', 'error')
                elif not targets: flash('Nobody in this group has a valid phone number or email address.', 'error')
                else:
                    sent, failed = _deliver(form['channel'], targets, form['subject'], form['message'])
                    audit('send', 'message', None, f"{form['channel']} to {form['audience']}: {sent} sent, {failed} failed")
                    result = {'sent': sent, 'failed': failed}
                    flash(f'{sent} message(s) sent, {failed} failed.', 'success' if not failed else 'warning')
    return render_template('communications.html', form=form, classes=classes, students=students, preview=preview, result=result, max_recipients=MAX_MESSAGE_RECIPIENTS)


@app.route('/communications/log')
@roles_required('Administrator', 'Headteacher')
def message_log_page():
    status_filter = request.args.get('status', '')
    sql = 'SELECT m.*,u.full_name sender FROM message_log m LEFT JOIN users u ON u.id=m.sent_by'
    args = []
    if status_filter in ('Sent', 'Failed'): sql += ' WHERE m.status=?'; args.append(status_filter)
    rows = db().execute(sql + ' ORDER BY m.id DESC LIMIT 300', args).fetchall()
    return render_template('message_log.html', rows=rows, status_filter=status_filter)


@app.route('/reports/absence-alerts/<int:student_id>/sms', methods=['POST'])
@roles_required('Administrator', 'Proprietor', 'Headteacher', 'Class Teacher', 'Subject Teacher', 'Teacher')
def absence_sms(student_id):
    s = db().execute("SELECT s.*,c.name class_name FROM students s LEFT JOIN classes c ON c.id=s.class_id WHERE s.id=? AND s.status='Active'", (student_id,)).fetchone()
    if not s: abort(404)
    sc = class_scope(current_user())
    if sc is not None and s['class_name'] not in sc: abort(403)
    back = redirect(_safe_back(url_for('absence_alerts')))
    phone = INT.normalize_phone(s['guardian_phone'])
    last = request.form.get('last', '')
    if not INT.status()['sms']['ready']: flash('SMS is not switched on yet.', 'error')
    elif not phone: flash('This student has no valid guardian phone number.', 'error')
    else:
        text = f"Dear {s['guardian_name'] or 'Parent/Guardian'}, {s['first_name']} {s['last_name']} has been absent from school" + (f" (last on {last})" if _parse_date(last) else '') + ". Please contact the school office. - Fr. Joseph Connolly SVD Memorial School"
        res = INT.send_sms([(phone, text)])[0]
        _log_message('sms', phone, '', text, res['ok'], res['ref'], res['error'], student_id); db().commit()
        audit('send', 'message', student_id, 'Absence SMS ' + ('sent' if res['ok'] else 'failed'))
        flash('Message sent to the guardian.' if res['ok'] else f"The message was not sent: {res['error']}", 'success' if res['ok'] else 'error')
    return back


def _safe_back(default):
    """Go back to the page the user came from, but only when it is on this same site."""
    ref = request.referrer or ''
    parts = urlparse(ref)
    if parts.netloc == request.host and parts.path.startswith('/'):
        return parts.path + ('?' + parts.query if parts.query else '')
    return default


def _send_receipt_sms(student, amount, receipt_no):
    """Best effort: a failed SMS must never undo a recorded payment."""
    try:
        phone = INT.normalize_phone(student['guardian_phone'])
        if not phone or not INT.status()['sms']['ready']: return False
        text = f"Fr. Joseph Connolly SVD Memorial School: we received GHS {amount:.2f} for {student['first_name']} {student['last_name']}. Receipt {receipt_no}. Thank you."
        res = INT.send_sms([(phone, text)])[0]
        _log_message('sms', phone, '', text, res['ok'], res['ref'], res['error'], student['id']); db().commit()
        return res['ok']
    except Exception:
        app.logger.exception('Receipt SMS failed')
        return False


# -- integrations status and test sends ------------------------------------------------------------------
@app.route('/admin/integrations')
@roles_required('Administrator')
def integrations_page():
    return render_template('integrations.html', st=INT.status(), bk=INT.backup_email_status(), bk_state=backup_mail_state(), webhook_url=request.url_root.rstrip('/') + '/webhooks/paystack')


@app.route('/admin/integrations/send-backup', methods=['POST'])
@roles_required('Administrator')
def integrations_send_backup():
    auto_backup(force=True)
    latest = sorted(f for f in os.listdir(backup_dir()) if re.fullmatch(r'school_\d{4}-\d{2}-\d{2}\.db', f))
    if not latest: flash('The backup could not be made. See the server log.', 'error')
    else:
        ok, msg = email_backup_file(os.path.join(backup_dir(), latest[-1]))
        audit('backup_email', 'database', None, 'Sent' if ok else 'Failed: ' + msg[:150])
        flash(msg, 'success' if ok else 'error')
    return redirect(url_for('integrations_page'))


@app.route('/admin/integrations/test-sms', methods=['POST'])
@roles_required('Administrator')
def integrations_test_sms():
    phone = INT.normalize_phone(request.form.get('phone', ''))
    if not phone: flash('Enter a valid Ghana mobile number, for example 0244123456.', 'error')
    else:
        try:
            text = 'Test message from the Fr. Joseph Connolly SVD Memorial School system.'
            res = INT.send_sms([(phone, text)])[0]
            _log_message('sms', phone, '', text, res['ok'], res['ref'], res['error']); db().commit()
            flash('Test SMS accepted by the provider.' if res['ok'] else f"The provider refused it: {res['error']}", 'success' if res['ok'] else 'error')
        except INT.IntegrationError as exc: flash(str(exc), 'error')
    return redirect(url_for('integrations_page'))


@app.route('/admin/integrations/test-email', methods=['POST'])
@roles_required('Administrator')
def integrations_test_email():
    to = request.form.get('email', '').strip()
    try:
        INT.send_email(to, 'Test email from the school system', 'This is a test message from the Fr. Joseph Connolly SVD Memorial School system.')
        _log_message('email', to, 'Test email', 'Test message', True); db().commit(); flash('Test email sent.', 'success')
    except INT.IntegrationError as exc:
        _log_message('email', to, 'Test email', 'Test message', False, '', str(exc)); db().commit(); flash(str(exc), 'error')
    return redirect(url_for('integrations_page'))


# -- mobile money ----------------------------------------------------------------------------------------
def _portal_linked_ids(user):
    conn = db()
    if user['role'] == 'Student': return [user['student_id']] if user['student_id'] else []
    ids = [r['student_id'] for r in conn.execute('SELECT student_id FROM parent_children WHERE user_id=?', (user['id'],)).fetchall()]
    return ids or ([user['student_id']] if user['student_id'] else [])


def _invoice_balance(conn, student_id, invoice_no):
    inv = conn.execute('''SELECT i.*,COALESCE((SELECT SUM(f.amount) FROM fees f WHERE f.student_id=i.student_id AND f.purpose=i.invoice_no),0) paid
                          FROM fee_invoices i WHERE i.invoice_no=? AND i.student_id=?''', (invoice_no, student_id)).fetchone()
    return (inv, round(max(0.0, float(inv['amount']) - float(inv['discount']) - float(inv['paid'])), 2)) if inv else (None, 0.0)


@app.route('/portal/pay', methods=['POST'])
@login_required
def portal_pay():
    user = current_user(); conn = db()
    sid_raw = request.form.get('student_id', '')
    if not sid_raw.isdigit() or int(sid_raw) not in _portal_linked_ids(user): abort(403)
    sid = int(sid_raw); back = redirect(url_for('portal', student_id=sid))
    if not INT.status()['momo']['ready']: flash('Paying by mobile money is not available yet. Please pay at the school office.', 'error'); return back
    inv, balance = _invoice_balance(conn, sid, request.form.get('invoice_no', ''))
    try: amount = round(float(request.form.get('amount', '')), 2)
    except ValueError: amount = 0
    phone = INT.normalize_phone(request.form.get('phone', ''))
    network = request.form.get('network', '') or INT.network_of(phone)
    student = conn.execute('SELECT * FROM students WHERE id=?', (sid,)).fetchone()
    email = student['guardian_email'] if INT.valid_email(student['guardian_email']) else os.environ.get('MOMO_FALLBACK_EMAIL', '').strip()
    if not inv: flash('Choose one of the invoices shown.', 'error')
    elif balance <= 0: flash('That invoice is already paid.', 'error')
    elif not math.isfinite(amount) or amount <= 0 or amount > balance + 0.004: flash(f'Enter an amount between GH₵ 0.01 and the balance of GH₵ {balance:.2f}.', 'error')
    elif not phone: flash('Enter a valid Ghana mobile money number, for example 0244123456.', 'error')
    elif network not in INT.NETWORK_NAMES: flash('Choose the mobile money network for this number.', 'error')
    elif not INT.valid_email(email): flash('The school has no email address on file for payments. Please pay at the school office.', 'error')
    elif conn.execute("SELECT 1 FROM momo_payments WHERE invoice_no=? AND status IN ('Initiating','Pending','OTP needed') AND created_at>=datetime('now','-15 minutes')", (inv['invoice_no'],)).fetchone():
        flash('A payment for this invoice is already waiting for approval on a phone. Approve it, or wait 15 minutes before trying again.', 'warning')
    else:
        ref = SCHOOL_CODE + '-MM-' + secrets.token_hex(6).upper()
        cur = conn.execute('INSERT INTO momo_payments(reference,student_id,invoice_no,amount,phone,network,status,provider,initiated_by) VALUES(?,?,?,?,?,?,?,?,?)',
                           (ref, sid, inv['invoice_no'], amount, phone, network, 'Initiating', 'paystack', user['id'])); conn.commit()
        try:
            res = INT.momo_charge(ref, amount, phone, email, network)
        except INT.IntegrationError as exc:
            conn.execute("UPDATE momo_payments SET status='Failed',message=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (str(exc)[:300], cur.lastrowid)); conn.commit()
            audit('momo_request', 'momo_payment', cur.lastrowid, 'Request failed'); flash(f'The payment could not be started: {exc}', 'error'); return back
        state = {'pending': 'Pending', 'otp': 'OTP needed', 'success': 'Pending', 'failed': 'Failed'}[res['status']]
        conn.execute('UPDATE momo_payments SET status=?,message=?,updated_at=CURRENT_TIMESTAMP WHERE id=?', (state, res['message'], cur.lastrowid)); conn.commit()
        audit('momo_request', 'momo_payment', cur.lastrowid, f'GHS {amount:.2f} on {inv["invoice_no"]}')
        if res['status'] == 'failed': flash('The payment was declined. Please try again or pay at the school office.', 'error')
        else: flash(res['message'] or 'Check your phone and approve the payment request. Your receipt appears here once the payment is confirmed.', 'success')
    return back


def _momo_settle(reference, amount_pesewas, currency):
    """Record a confirmed mobile money payment exactly once. Returns 'recorded', 'already', 'mismatch' or 'unknown'."""
    conn = db(); row = conn.execute('SELECT * FROM momo_payments WHERE reference=?', (reference,)).fetchone()
    if not row: return 'unknown'
    if row['status'] == 'Success': return 'already'
    if currency != 'GHS' or int(amount_pesewas) != int(round(float(row['amount']) * 100)):
        conn.execute("UPDATE momo_payments SET status='Mismatch',message=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (f'Provider reported {amount_pesewas} pesewas in {currency}; expected {int(round(float(row["amount"]) * 100))}.', row['id'])); conn.commit()
        audit('momo_mismatch', 'momo_payment', row['id'], 'Amount or currency did not match. Not recorded.'); return 'mismatch'
    if conn.execute("UPDATE momo_payments SET status='Success',updated_at=CURRENT_TIMESTAMP WHERE id=? AND status<>'Success'", (row['id'],)).rowcount != 1:
        conn.rollback(); return 'already'
    _, balance = _invoice_balance(conn, row['student_id'], row['invoice_no'])
    amount = round(float(row['amount']), 2)
    linked = amount <= balance + 0.004
    purpose = row['invoice_no'] if linked else f"Mobile money {reference}"
    note = f"Mobile money ({INT.NETWORK_NAMES.get(row['network'], 'mobile money')}) via Paystack, reference {reference}." + ('' if linked else f" Invoice {row['invoice_no']} was already paid or reduced, so this payment is not linked to it: please review.")
    receipt = SCHOOL_CODE + '-R-' + datetime.now().strftime('%Y%m%d%H%M%S') + '-' + secrets.token_hex(2).upper()
    cur = conn.execute('INSERT INTO fees(receipt_no,student_id,amount,payment_date,payment_method,purpose,received_by,notes) VALUES(?,?,?,?,?,?,?,?)',
                       (receipt, row['student_id'], amount, date.today().isoformat(), 'Mobile Money', purpose, 'Mobile money (Paystack)', note))
    conn.execute('UPDATE momo_payments SET fee_id=? WHERE id=?', (cur.lastrowid, row['id'])); conn.commit()
    audit('momo_received', 'fee', cur.lastrowid, f'{receipt} for {reference}')
    student = conn.execute('SELECT * FROM students WHERE id=?', (row['student_id'],)).fetchone()
    _send_receipt_sms(student, amount, receipt)
    return 'recorded'


def _momo_check(row):
    """Ask the provider about a pending payment and update it. Returns a short state word."""
    v = INT.momo_verify(row['reference'])
    if v['status'] == 'success': return _momo_settle(row['reference'], v['amount_pesewas'], v['currency'])
    if v['status'] in ('failed', 'abandoned', 'reversed'):
        db().execute("UPDATE momo_payments SET status='Failed',message=?,updated_at=CURRENT_TIMESTAMP WHERE id=? AND status<>'Success'", (f"Provider status: {v['status']}", row['id'])); db().commit()
        return 'failed'
    return 'waiting'


@app.route('/webhooks/paystack', methods=['POST'])
def paystack_webhook():
    raw = request.get_data()
    if not INT.webhook_signature_ok(raw, request.headers.get('X-Paystack-Signature', '')): abort(401)
    try: event = json.loads(raw)
    except ValueError: abort(400)
    data = (event or {}).get('data') or {}; reference = str(data.get('reference', ''))
    if event.get('event') == 'charge.success' and reference:
        _momo_settle(reference, data.get('amount') or 0, str(data.get('currency', '')))
    elif event.get('event') == 'charge.failed' and reference:
        db().execute("UPDATE momo_payments SET status='Failed',message=?,updated_at=CURRENT_TIMESTAMP WHERE reference=? AND status<>'Success'", (str(data.get('gateway_response', 'Payment failed'))[:300], reference)); db().commit()
    return {'ok': True}, 200


@app.route('/portal/pay/<int:payment_id>/check', methods=['POST'])
@login_required
def portal_pay_check(payment_id):
    row = db().execute('SELECT * FROM momo_payments WHERE id=?', (payment_id,)).fetchone()
    if not row or row['student_id'] not in _portal_linked_ids(current_user()): abort(404)
    try:
        state = _momo_check(row) if row['status'] in MOMO_PENDING else 'done'
        flash({'recorded': 'Payment confirmed. Your receipt is in the list below.', 'already': 'This payment is already recorded.', 'failed': 'The payment did not go through.',
               'waiting': 'Still waiting for approval on the phone.', 'done': 'This payment is already finished.', 'mismatch': 'The amount did not match. Please contact the school office.', 'unknown': 'Payment not found.'}[state], 'success' if state in ('recorded', 'already') else 'warning')
    except INT.IntegrationError as exc: flash(str(exc), 'error')
    return redirect(url_for('portal', student_id=row['student_id']))


@app.route('/fees/mobile-money')
@roles_required('Administrator', 'Accountant', 'Proprietor', 'Headteacher')
def momo_payments_page():
    rows = db().execute('''SELECT m.*,s.first_name,s.last_name,s.admission_no,f.receipt_no FROM momo_payments m JOIN students s ON s.id=m.student_id
                           LEFT JOIN fees f ON f.id=m.fee_id ORDER BY m.id DESC LIMIT 300''').fetchall()
    return render_template('momo_payments.html', rows=rows, can_verify=current_user()['role'] in ('Administrator', 'Accountant'), pending_states=MOMO_PENDING, names=INT.NETWORK_NAMES)


@app.route('/fees/mobile-money/<int:payment_id>/verify', methods=['POST'])
@roles_required('Administrator', 'Accountant')
def momo_verify_now(payment_id):
    row = db().execute('SELECT * FROM momo_payments WHERE id=?', (payment_id,)).fetchone()
    if not row: abort(404)
    try:
        state = _momo_check(row) if row['status'] in MOMO_PENDING else 'done'
        flash({'recorded': 'Payment confirmed and recorded.', 'already': 'Already recorded.', 'failed': 'The payment failed or was abandoned.', 'waiting': 'Still waiting for the payer to approve.', 'done': 'Nothing to check.', 'mismatch': 'Amount mismatch: not recorded. Contact the provider.', 'unknown': 'Not found.'}[state], 'success' if state in ('recorded', 'already') else 'warning')
    except INT.IntegrationError as exc: flash(str(exc), 'error')
    return redirect(url_for('momo_payments_page'))

CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
       "font-src 'self' https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; form-action 'self'; "
       "frame-ancestors 'none'; base-uri 'self'; object-src 'none'")


@app.after_request
def security_headers(response):
    response.headers.setdefault('X-Content-Type-Options','nosniff')
    response.headers.setdefault('X-Frame-Options','DENY')
    response.headers.setdefault('Referrer-Policy','strict-origin-when-cross-origin')
    response.headers.setdefault('Permissions-Policy','camera=(self), microphone=(), geolocation=()')
    response.headers.setdefault('Content-Security-Policy', CSP)
    response.headers.setdefault('Cross-Origin-Opener-Policy','same-origin')
    response.headers.setdefault('Cross-Origin-Resource-Policy','same-origin')
    if app.config['SESSION_COOKIE_SECURE']:
        response.headers.setdefault('Strict-Transport-Security','max-age=31536000; includeSubDomains')
    if session.get('user_id') or request.endpoint == 'login':
        response.headers['Cache-Control']='no-store, private'
    return response


# ---- automatic safety copies -------------------------------------------------------------------------
BACKUP_KEEP = 14
_last_backup_check = 0.0


def backup_dir():
    path = os.environ.get('SCHOOL_BACKUP_DIR') or os.path.join(os.path.dirname(os.path.abspath(DB_PATH)), 'backups')
    os.makedirs(path, mode=0o700, exist_ok=True)
    try: os.chmod(path, 0o700)
    except OSError: pass
    return path


def auto_backup(force=False):
    """One consistent copy of the database per day, newest 14 kept. Returns the file name or None."""
    global _last_backup_check
    if os.environ.get('SCHOOL_AUTO_BACKUP', '1') == '0' and not force: return None
    if not os.path.exists(DB_PATH): return None
    _last_backup_check = time.time()
    folder = backup_dir(); target = os.path.join(folder, f"school_{date.today().isoformat()}.db")
    if os.path.exists(target) and not force: return None
    temp = target + '.partial'
    src = sqlite3.connect(DB_PATH, timeout=30)
    try:
        dst = sqlite3.connect(temp)
        try: src.backup(dst)
        finally: dst.close()
        os.replace(temp, target); os.chmod(target, 0o600)
    except (sqlite3.Error, OSError):
        app.logger.exception('Automatic backup failed')
        try: os.remove(temp)
        except OSError: pass
        return None
    finally: src.close()
    for old in sorted(f for f in os.listdir(folder) if re.fullmatch(r'school_\d{4}-\d{2}-\d{2}\.db', f))[:-BACKUP_KEEP]:
        try: os.remove(os.path.join(folder, old))
        except OSError: pass
    return os.path.basename(target)



# ---- encrypted backup by e-mail --------------------------------------------------------------------------
BACKUP_MAX_MAIL_BYTES = 20 * 1024 * 1024
_mail_lock = threading.Lock()


def _backup_mail_state_path(): return os.path.join(backup_dir(), 'email_state.json')


def backup_mail_state():
    try:
        with open(_backup_mail_state_path(), encoding='utf-8') as fh: return json.load(fh)
    except (OSError, ValueError): return {}


def _save_backup_mail_state(**changes):
    state = backup_mail_state(); state.update(changes)
    with open(_backup_mail_state_path(), 'w', encoding='utf-8') as fh: json.dump(state, fh)


def _encrypted_zip(path, password):
    """AES-256 password-protected zip of one backup file (opens in 7-Zip, WinZip, macOS Archive Utility 3rd-party tools)."""
    buf = _io.BytesIO()
    with pyzipper.AESZipFile(buf, 'w', compression=pyzipper.ZIP_DEFLATED, encryption=pyzipper.WZ_AES) as zf:
        zf.setpassword(password.encode('utf-8')); zf.setencryption(pyzipper.WZ_AES, nbits=256)
        with open(path, 'rb') as src: zf.writestr(os.path.basename(path), src.read())
    return buf.getvalue()


def email_backup_file(path):
    """E-mail one backup, encrypted. Returns (ok, message). The password is never logged or sent."""
    st = INT.backup_email_status()
    if not st['ready']: return False, 'Backup e-mail is not set up: ' + ', '.join(st['missing'])
    data = _encrypted_zip(path, os.environ['BACKUP_ZIP_PASSWORD'].strip())
    if len(data) > BACKUP_MAX_MAIL_BYTES:
        msg = 'The backup is larger than the 20 MB e-mail limit, so it was not e-mailed. Download it from the Administrator menu instead.'
        _save_backup_mail_state(last_error=msg, last_error_at=datetime.now().isoformat(timespec='seconds')); return False, msg
    day = os.path.basename(path)[7:17]
    try:
        INT.send_email(st['to'], f'School database backup {day}',
                       'The attached file is today\'s encrypted backup of the school database.\n\nIt is a password-protected zip (AES-256). Open it with 7-Zip or WinZip using the backup password set by the system administrator. '
                       'Keep it private: it contains student and guardian records. Do not forward it.',
                       (os.path.basename(path)[:-3] + '.zip', data, 'application/zip'))
    except INT.IntegrationError as exc:
        _save_backup_mail_state(last_error=str(exc), last_error_at=datetime.now().isoformat(timespec='seconds')); return False, str(exc)
    _save_backup_mail_state(last_sent_file=os.path.basename(path), last_sent_at=datetime.now().isoformat(timespec='seconds'), last_error='')
    return True, 'Encrypted backup e-mailed.'


def email_pending_backup():
    """Send the newest daily backup if it has not been e-mailed yet. Safe to call often."""
    if not os.environ.get('BACKUP_EMAIL_TO', '').strip() or not _mail_lock.acquire(blocking=False): return
    try:
        files = sorted(f for f in os.listdir(backup_dir()) if re.fullmatch(r'school_\d{4}-\d{2}-\d{2}\.db', f))
        if files and backup_mail_state().get('last_sent_file') != files[-1]:
            ok, msg = email_backup_file(os.path.join(backup_dir(), files[-1]))
            if not ok: app.logger.error('Backup e-mail not sent: %s', msg)
    except Exception:
        app.logger.exception('Backup e-mail failed')
    finally: _mail_lock.release()


@app.before_request
def _daily_backup():
    if time.time() - _last_backup_check > 3600 and request.endpoint not in ('static', 'health_check'):
        try:
            auto_backup()
            threading.Thread(target=email_pending_backup, daemon=True).start()
        except Exception: app.logger.exception('Backup check failed')


def startup_checks():
    """Quick structural check of the database when the program starts. Problems are logged loudly."""
    try:
        conn = sqlite3.connect(DB_PATH, timeout=30)
        try:
            result = conn.execute('PRAGMA quick_check').fetchone()[0]
        finally: conn.close()
        if result != 'ok': app.logger.error('DATABASE CHECK FAILED: %s. Restore the latest file in the backups folder.', result)
    except sqlite3.Error:
        app.logger.exception('Database check could not run')


@app.get('/healthz')
def health_check():
    # Lightweight platform health check; do not disclose database details.
    try:
        db().execute('SELECT 1').fetchone()
        return {'status': 'ok'}, 200
    except Exception:
        app.logger.exception('Health check failed')
        return {'status': 'unavailable'}, 503

@app.errorhandler(403)
def forbidden(_): return render_template('error.html', code=403, message='Your account does not have permission to view this page.'),403
@app.errorhandler(404)
def missing(_): return render_template('error.html', code=404, message='The requested record or page was not found.'),404
@app.errorhandler(400)
def bad_request(e): return render_template('error.html', code=400, message=getattr(e, 'description', None) or 'The request could not be understood. Go back and try again.'),400
@app.errorhandler(405)
def wrong_method(_): return render_template('error.html', code=405, message='That action is not allowed on this page.'),405
@app.errorhandler(413)
def too_large(_): return render_template('error.html', code=413, message='The file is too large. Documents may be up to 8 MB and photographs up to 5 MB.'),413
@app.errorhandler(Exception)
def unexpected(e):
    if isinstance(e, HTTPException): return e
    app.logger.exception('Unhandled error on %s %s', request.method, request.path)
    try: db().rollback()
    except Exception: pass
    return render_template('error.html', code=500, message='Something went wrong on our side. Nothing was lost; please try again, and tell the administrator if it keeps happening.'),500

init_db()
startup_checks()
if __name__ == '__main__':
    app.run(debug=os.environ.get('FLASK_DEBUG') == '1', host=os.environ.get('HOST', '127.0.0.1'), port=int(os.environ.get('PORT','5000')))
