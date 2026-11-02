"""Version 5: hardening. Headers, error pages, sessions, uploads, CSV safety, backups and start-up rules."""
import io
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from test_v3 import A, Agent, add_student, add_user, admin  # noqa: F401  (importing sets up the shared test database)
ROOT = Path(__file__).resolve().parents[1]


def setup_module():
    A.init_db()


def teardown_module():
    Path(A.DB_PATH).unlink(missing_ok=True)


def test_security_headers_and_no_inline_scripts():
    r = A.app.test_client().get('/login')
    csp = r.headers['Content-Security-Policy']
    assert "script-src 'self'" in csp and "frame-ancestors 'none'" in csp and "object-src 'none'" in csp
    assert 'unsafe-inline' not in csp.split('style-src')[0]  # scripts must never allow inline code
    assert r.headers['X-Frame-Options'] == 'DENY' and r.headers['X-Content-Type-Options'] == 'nosniff'
    assert 'no-store' in r.headers['Cache-Control']
    for page in (ROOT / 'templates').glob('*.html'):
        text = page.read_text(encoding='utf-8')
        assert not re.search(r'\son(click|change|submit|load|error)=', text), page.name
        assert '<script>' not in text, page.name
    assert (ROOT / 'static' / 'app.js').exists()


def test_friendly_error_pages_and_no_stack_traces(monkeypatch):
    c = A.app.test_client()
    assert b'not allowed' in c.get('/logout').data or c.get('/logout').status_code in (302, 405)
    assert c.get('/no-such-page').status_code == 404
    a = admin()
    monkeypatch.setattr(A, 'class_scope', lambda user: (_ for _ in ()).throw(RuntimeError('secret internal detail')))
    r = a.get('/dashboard')
    assert r.status_code == 500 and b'secret internal detail' not in r.data and b'Traceback' not in r.data and b'Something went wrong' in r.data


def test_changed_password_ends_old_sessions():
    add_user('v5_user', 'Class Teacher', 'JHS 1')
    t = Agent('v5_user')
    assert t.get('/students').status_code == 200
    with A.app.app_context():
        c = A.db(); c.execute("UPDATE users SET password_hash=? WHERE username='v5_user'", (A.generate_password_hash('AnotherSecure2026!'),)); c.commit()
    assert t.get('/students').status_code == 302  # back to sign-in


def test_unknown_user_and_wrong_password_look_identical():
    add_user('v5_real', 'Class Teacher', 'JHS 1')
    c = A.app.test_client()
    a = c.post('/login', data={'username': 'v5_real', 'password': 'wrong'}).get_data(as_text=True)
    b = c.post('/login', data={'username': 'v5_nobody', 'password': 'wrong'}).get_data(as_text=True)
    assert 'Invalid username or password' in a and 'Invalid username or password' in b


def test_back_redirect_stays_on_this_site():
    s = add_student('V5-001', 'Ab', 'Cd', 'JHS 1')
    a = admin()
    a.get('/reports/absence-alerts')  # warm token
    r = a.post(f'/reports/absence-alerts/{s}/sms', {}, headers={'Referer': 'https://evil.example/steal'})
    assert r.status_code == 302 and 'evil.example' not in r.headers['Location']


def test_document_upload_rejects_disguised_files():
    a = admin()
    bad = a.post('/documents/files', {'category': 'School', 'file': (io.BytesIO(b'MZ\x90\x00 not a pdf'), 'report.pdf')}, content_type='multipart/form-data', follow_redirects=True)
    assert b'does not match' in bad.data
    good = a.post('/documents/files', {'category': 'School', 'file': (io.BytesIO(b'%PDF-1.4\n%fake but starts like a pdf'), 'ok.pdf')}, content_type='multipart/form-data', follow_redirects=True)
    assert b'uploaded to private storage' in good.data


def test_csv_export_neutralises_formulas():
    a = admin()
    a.module('announcements', announcement_title="=HYPERLINK(\"http://evil\")", audience='All staff', publish_date=A.date.today().isoformat(), message='x', announcement_status='Draft')
    csv_text = a.get('/modules/announcements/export.csv').get_data(as_text=True)
    assert "'=HYPERLINK" in csv_text and ',=HYPERLINK' not in csv_text


def test_automatic_backup_is_consistent_and_rotates(monkeypatch, tmp_path):
    monkeypatch.setenv('SCHOOL_BACKUP_DIR', str(tmp_path))
    for n in range(1, 21): (tmp_path / f'school_2020-01-{n:02d}.db').write_bytes(b'old')
    name = A.auto_backup(force=True)
    files = sorted(p.name for p in tmp_path.iterdir())
    assert name in files and len(files) <= A.BACKUP_KEEP and 'school_2020-01-01.db' not in files
    import sqlite3
    conn = sqlite3.connect(tmp_path / name)
    try:
        assert conn.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert conn.execute('SELECT COUNT(*) FROM users').fetchone()[0] >= 1
    finally: conn.close()
    assert A.auto_backup() is None  # already have today's copy


def _run_import(env_extra):
    env = {k: v for k, v in os.environ.items() if k not in ('SECRET_KEY', 'APP_ENV', 'FLASK_DEBUG', 'COOKIE_SECURE')}
    env.update(SCHOOL_DB=tempfile.mktemp(suffix='.db'), **env_extra)
    return subprocess.run([sys.executable, '-c', 'import app'], cwd=ROOT, env=env, capture_output=True, text=True)


def test_production_refuses_weak_or_missing_secret_and_debug():
    assert _run_import({'APP_ENV': 'production'}).returncode != 0
    assert _run_import({'APP_ENV': 'production', 'SECRET_KEY': 'short'}).returncode != 0
    assert _run_import({'APP_ENV': 'production', 'SECRET_KEY': 'x' * 40, 'FLASK_DEBUG': '1', 'ADMIN_INITIAL_PASSWORD': 'Unique-Password-2026!'}).returncode != 0
    ok = _run_import({'APP_ENV': 'production', 'SECRET_KEY': 'x' * 40, 'ADMIN_INITIAL_PASSWORD': 'Unique-Password-2026!'})
    assert ok.returncode == 0, ok.stderr[-400:]


def test_backup_is_emailed_encrypted(monkeypatch, tmp_path):
    import io as _io, smtplib, pyzipper
    from integrations import IntegrationError  # noqa: F401
    monkeypatch.setenv('SCHOOL_BACKUP_DIR', str(tmp_path))
    for k, v in dict(BACKUP_EMAIL_TO='owner@example.org', BACKUP_ZIP_PASSWORD='Correct-Horse-Battery-9', SMTP_HOST='smtp.example.org', SMTP_USER='u@example.org', SMTP_PASSWORD='pw').items(): monkeypatch.setenv(k, v)
    sent = []
    class FakeSMTP:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def starttls(self, **k): pass
        def login(self, u, p): pass
        def send_message(self, m): sent.append(m)
    monkeypatch.setattr(A.INT.smtplib, 'SMTP', FakeSMTP)
    A.auto_backup(force=True)
    A.email_pending_backup()
    assert len(sent) == 1 and sent[0]['To'] == 'owner@example.org'
    att = [p for p in sent[0].iter_attachments()][0]
    raw = att.get_payload(decode=True)
    assert b'SQLite format' not in raw  # the data is not readable without the password
    assert 'Correct-Horse' not in sent[0].as_string()
    with pyzipper.AESZipFile(_io.BytesIO(raw)) as zf:
        zf.setpassword(b'Correct-Horse-Battery-9')
        assert zf.read(zf.namelist()[0]).startswith(b'SQLite format')
        zf.setpassword(b'wrong-password-123')
        try: zf.read(zf.namelist()[0]); opened = True
        except RuntimeError: opened = False
        assert not opened
    A.email_pending_backup()
    assert len(sent) == 1  # already sent today


def test_backup_email_needs_password_and_survives_failures(monkeypatch, tmp_path):
    monkeypatch.setenv('SCHOOL_BACKUP_DIR', str(tmp_path))
    for k, v in dict(BACKUP_EMAIL_TO='owner@example.org', SMTP_HOST='h', SMTP_USER='u', SMTP_PASSWORD='p').items(): monkeypatch.setenv(k, v)
    monkeypatch.delenv('BACKUP_ZIP_PASSWORD', raising=False)
    assert not A.INT.backup_email_status()['ready']  # refuses to send unencrypted
    A.auto_backup(force=True)
    ok, msg = A.email_backup_file(str(next(tmp_path.glob('school_*.db'))))
    assert not ok and 'BACKUP_ZIP_PASSWORD' in msg
    monkeypatch.setenv('BACKUP_ZIP_PASSWORD', 'Correct-Horse-Battery-9')
    def boom(*a, **k): raise OSError('network down')
    monkeypatch.setattr(A.INT.smtplib, 'SMTP', boom)
    A.email_pending_backup()  # must not raise
    assert 'The email was not sent' in A.backup_mail_state().get('last_error', '')
    page = admin().get('/admin/integrations').get_data(as_text=True)
    assert 'Backup by e-mail' in page and 'Correct-Horse' not in page
