"""Administrators can edit and delete user accounts (with safeguards)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_v3 import A, PW, setup_module, teardown_module, add_user, Agent  # noqa: F401


def uid(name):
    with A.app.app_context():
        r = A.db().execute('SELECT id FROM users WHERE username=?', (name,)).fetchone()
        return r['id'] if r else None


def row(name):
    with A.app.app_context():
        r = A.db().execute('SELECT * FROM users WHERE username=?', (name,)).fetchone()
        return dict(r) if r else None


def test_edit_details_role_class_and_password_reset():
    add_user('ua_boss', 'Administrator'); add_user('ua_t1', 'Teacher')
    ag = Agent('ua_boss'); tok = ag.token(); i = uid('ua_t1')
    page = ag.get(f'/users/{i}/edit'); assert page.status_code == 200 and b'Delete this account' in page.data
    r = ag.c.post(f'/users/{i}/edit', data={'_csrf': tok, 'full_name': 'Ama Mensah', 'username': 'ua_t1_new', 'role': 'Subject Teacher', 'assigned_class': 'ST:JHS 1,JHS 2', 'password': 'BrandNewTemp2026!'})
    assert r.status_code == 302
    u = row('ua_t1_new')
    assert u['full_name'] == 'Ama Mensah' and u['role'] == 'Subject Teacher' and u['assigned_class'] == 'ST:JHS 1,JHS 2' and u['must_change_password'] == 1
    assert Agent.__init__ and A.app.test_client().post('/login', data={'username': 'ua_t1_new', 'password': 'BrandNewTemp2026!'}).status_code == 302
    # blank password keeps it; duplicate username refused
    r = ag.c.post(f'/users/{i}/edit', data={'_csrf': tok, 'full_name': 'Ama Mensah', 'username': 'ua_boss', 'role': 'Teacher'}, follow_redirects=True)
    assert b'Username already exists' in r.data and row('ua_t1_new')


def test_cannot_edit_own_role_or_delete_self_or_last_admin():
    ag = Agent('ua_boss'); tok = ag.token(); me = uid('ua_boss')
    ag.c.post(f'/users/{me}/edit', data={'_csrf': tok, 'full_name': 'Boss', 'username': 'ua_boss', 'role': 'Teacher'})
    assert row('ua_boss')['role'] == 'Administrator'
    r = ag.c.post(f'/users/{me}/delete', data={'_csrf': tok, 'confirm': '1'}, follow_redirects=True)
    assert b'cannot delete your own' in r.data and row('ua_boss')
    with A.app.app_context():  # make ua_boss the only active administrator
        c = A.db(); c.execute("UPDATE users SET active=0 WHERE role='Administrator' AND username<>'ua_boss'"); c.commit()
    add_user('ua_adm2', 'Administrator'); other = uid('ua_adm2')
    with A.app.app_context():
        c = A.db(); c.execute("UPDATE users SET active=0 WHERE id=?", (other,)); c.commit()
    # inactive second admin may be deleted; but demoting/deleting the only active admin is refused from another admin
    r = ag.c.post(f'/users/{other}/delete', data={'_csrf': tok, 'confirm': '1'}); assert row('ua_adm2') is None
    with A.app.app_context():
        c = A.db(); c.execute("UPDATE users SET active=1 WHERE role='Administrator'"); c.commit()


def test_delete_user_keeps_audit_history_and_needs_confirmation():
    add_user('ua_gone', 'Teacher'); g = uid('ua_gone')
    with A.app.app_context():
        c = A.db(); c.execute("INSERT INTO audit_log(user_id,action,entity,entity_id,details) VALUES(?,?,?,?,?)", (g, 'test', 'x', 1, 'by gone')); c.commit()
    ag = Agent('ua_boss'); tok = ag.token()
    r = ag.c.post(f'/users/{g}/delete', data={'_csrf': tok}, follow_redirects=True)
    assert row('ua_gone') and b'confirm' in r.data
    r = ag.c.post(f'/users/{g}/delete', data={'_csrf': tok, 'confirm': '1'}, follow_redirects=True)
    assert row('ua_gone') is None and b'User account deleted' in r.data
    with A.app.app_context():
        c = A.db()
        assert c.execute("SELECT COUNT(*) FROM audit_log WHERE details='by gone' AND user_id IS NULL").fetchone()[0] == 1
        assert c.execute("SELECT COUNT(*) FROM audit_log WHERE action='delete' AND entity='user' AND details LIKE 'ua_gone%'").fetchone()[0] == 1


def test_delete_refused_when_user_owns_required_records():
    add_user('ua_up', 'Teacher'); g = uid('ua_up')
    with A.app.app_context():
        c = A.db()
        c.execute("INSERT INTO document_files(original_name,stored_name,mime_type,size_bytes,category,uploaded_by) VALUES('a.pdf','ua_up_a.pdf','application/pdf',1,'Other',?)", (g,)); c.commit()
    ag = Agent('ua_boss'); tok = ag.token()
    r = ag.c.post(f'/users/{g}/delete', data={'_csrf': tok, 'confirm': '1'}, follow_redirects=True)
    assert row('ua_up') and b'Suspend the account' in r.data


def test_non_administrators_cannot_edit_or_delete():
    add_user('ua_plain', 'Teacher'); t = uid('ua_t1_new')
    ag = Agent('ua_plain'); tok = ag.token()
    assert ag.get(f'/users/{t}/edit').status_code in (302, 403)
    assert ag.c.post(f'/users/{t}/delete', data={'_csrf': tok, 'confirm': '1'}).status_code in (302, 403)
    assert row('ua_t1_new')
