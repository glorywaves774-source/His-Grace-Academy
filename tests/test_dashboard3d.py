"""3D dashboard view: the scene data matches the database, respects class scope and fee permissions, and needs no CSP change."""
import html
import json
import re
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_v3 import A, PW, TODAY, setup_module, teardown_module, add_user, add_student, Agent  # noqa: F401


def scene_of(page):
    m = re.search(r'data-scene="([^"]*)"', page)
    assert m, 'no 3D panel on the dashboard'
    return json.loads(html.unescape(m.group(1)))


def two_classes():
    with A.app.app_context():
        return [r['name'] for r in A.db().execute('SELECT name FROM classes WHERE active=1 ORDER BY id LIMIT 2')]


def seed():
    c1, c2 = two_classes()
    ids = {}
    for adm, cls, gender in (('D3-1', c1, 'Male'), ('D3-2', c1, 'Female'), ('D3-3', c1, 'Female'), ('D3-4', c2, 'Male')):
        sid = add_student(adm, 'Dee' + adm[-1], 'Three', cls)
        with A.app.app_context():
            c = A.db(); c.execute('UPDATE students SET gender=? WHERE id=?', (gender, sid)); c.commit()
        ids[adm] = sid
    with A.app.app_context():
        c = A.db()
        c.execute("INSERT OR IGNORE INTO fee_invoices(invoice_no,student_id,academic_year,term,description,amount,discount,due_date) VALUES('D3-INV-1',?,'2030/2031','Term 1','School fees',500,50,'2030-12-01')", (ids['D3-1'],))
        c.execute("INSERT OR IGNORE INTO fees(receipt_no,student_id,amount,payment_date,payment_method,purpose,received_by) VALUES('D3-R1',?,200,?, 'Cash','D3-INV-1','tester')", (ids['D3-1'], TODAY.isoformat()))
        c.commit()
    return c1, c2


def test_scene_matches_database_for_leadership():
    c1, c2 = seed(); add_user('d3_admin', 'Administrator')
    page = Agent('d3_admin').c.get('/dashboard').get_data(as_text=True)
    scene = scene_of(page)
    with A.app.app_context():
        active = A.db().execute("SELECT COUNT(*) FROM students WHERE status='Active'").fetchone()[0]
    assert sum(r['total'] for r in scene['enrol']) == active
    assert all(r['boys'] + r['girls'] + r['other'] == r['total'] for r in scene['enrol'])
    row1 = next(r for r in scene['enrol'] if r['name'] == c1)
    assert row1['boys'] >= 1 and row1['girls'] >= 2
    frow = next(r for r in scene['fees'] if r['name'] == c1)
    assert frow['billed'] >= 450 and frow['paid'] >= 200
    assert abs(frow['outstanding'] - (frow['billed'] - frow['paid'])) < 0.01 or frow['outstanding'] >= 250
    assert 'data-d3-mode="fees"' in page and 'data-d3-tablefor="fees"' in page
    assert 'dashboard3d.js' in page and 'data-d3-table' in page   # script tag and the no-JavaScript table


def test_class_scope_and_no_fees_for_teachers():
    c1, c2 = seed(); add_user('d3_teacher', 'Class Teacher', assigned=c1)
    page = Agent('d3_teacher').c.get('/dashboard').get_data(as_text=True)
    scene = scene_of(page)
    assert [r['name'] for r in scene['enrol']] == [c1]
    assert scene['fees'] == []
    assert 'data-d3-mode="fees"' not in page and 'data-d3-tablefor="fees"' not in page
    assert '"billed"' not in html.unescape(re.search(r'data-scene="([^"]*)"', page).group(1))


def test_script_is_self_hosted_and_csp_unchanged():
    add_user('d3_admin2', 'Administrator'); ag = Agent('d3_admin2')
    js = ag.c.get('/static/dashboard3d.js')
    assert js.status_code == 200 and len(js.get_data()) > 100000
    resp = ag.c.get('/dashboard')
    csp = resp.headers['Content-Security-Policy']
    assert "script-src 'self';" in csp and "unsafe-inline" not in csp.split('script-src')[1].split(';')[0] and 'cdn' not in csp
    assert not re.search(r'<script(?![^>]*\bsrc=)[^>]*>', resp.get_data(as_text=True)), 'inline script found'
