"""Installable-app (PWA) tests: manifest, icons, service worker privacy rules, and unchanged security."""
import json
import struct
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_v3 import A, PW, setup_module, teardown_module  # noqa: F401
from werkzeug.security import generate_password_hash

ROOT = Path(__file__).resolve().parents[1]


def png_size(path):
    data = path.read_bytes()
    assert data[:8] == b'\x89PNG\r\n\x1a\n'
    return struct.unpack('>II', data[16:24])


def test_manifest_is_valid():
    r = A.app.test_client().get('/manifest.webmanifest')
    assert r.status_code == 200
    assert r.mimetype == 'application/manifest+json'
    m = json.loads(r.data)
    assert m['display'] == 'standalone' and m['start_url'] == '/' and m['scope'] == '/'
    assert m['name'] and m['short_name'] and len(m['short_name']) <= 14
    assert m['theme_color'].startswith('#') and m['background_color'].startswith('#')
    assert {i['purpose'] for i in m['icons']} == {'any', 'maskable'}


def test_icons_exist_with_declared_sizes():
    m = json.loads(A.app.test_client().get('/manifest.webmanifest').data)
    for icon in m['icons']:
        w, h = icon['sizes'].split('x')
        assert png_size(ROOT / icon['src'].lstrip('/')) == (int(w), int(h))
    assert png_size(ROOT / 'static/icons/apple-touch-icon.png') == (180, 180)


def test_service_worker_headers_and_privacy():
    r = A.app.test_client().get('/sw.js')
    assert r.status_code == 200
    assert 'javascript' in r.mimetype
    assert r.headers['Service-Worker-Allowed'] == '/'
    assert 'no-cache' in r.headers['Cache-Control']
    body = r.get_data(as_text=True)
    assert "startsWith('/static/')" in body and "request.mode === 'navigate'" in body
    # only public files may be pre-cached
    for risky in ('/students', '/fees', '/staff', '/dashboard', '/api'):
        assert risky not in body


def test_offline_page_is_public():
    r = A.app.test_client().get('/offline')
    assert r.status_code == 200 and b'offline' in r.data.lower()


def test_login_page_links_the_manifest_and_has_no_inline_script():
    r = A.app.test_client().get('/login')
    html = r.get_data(as_text=True)
    assert 'rel="manifest"' in html and 'apple-touch-icon' in html
    import re
    assert not re.search(r'<script(?![^>]*\bsrc=)[^>]*>', html)
    assert "script-src 'self'" in r.headers['Content-Security-Policy']


def test_pwa_files_reachable_while_password_change_is_forced():
    with A.app.app_context():
        c = A.db()
        c.execute('INSERT OR IGNORE INTO users(username,password_hash,full_name,role,active,must_change_password) VALUES(?,?,?,?,1,1)',
                  ('pwa_forced', generate_password_hash(PW), 'Forced', 'Administrator'))
        c.commit()
    cl = A.app.test_client()
    assert cl.post('/login', data={'username': 'pwa_forced', 'password': PW}).status_code == 302
    for path in ('/manifest.webmanifest', '/sw.js', '/offline'):
        assert cl.get(path).status_code == 200, path
    assert cl.get('/').status_code == 302  # records are still locked behind the password change


def test_signed_in_pages_remain_uncacheable():
    with A.app.app_context():
        c = A.db()
        c.execute('INSERT OR IGNORE INTO users(username,password_hash,full_name,role,active,must_change_password) VALUES(?,?,?,?,1,0)',
                  ('pwa_admin', generate_password_hash(PW), 'Admin', 'Administrator'))
        c.commit()
    cl = A.app.test_client()
    assert cl.post('/login', data={'username': 'pwa_admin', 'password': PW}).status_code == 302
    r = cl.get('/', follow_redirects=True)
    assert r.status_code == 200 and 'no-store' in r.headers['Cache-Control']


def test_install_prompt_code_avoids_innerhtml():
    js = (ROOT / 'static/app.js').read_text()
    block = js[js.index('Installable app'):]
    assert 'innerHTML' not in block and 'serviceWorker' in block and 'beforeinstallprompt' in block
