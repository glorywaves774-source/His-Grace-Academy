"""Staff who are also parents of pupils: one account, plus a My children page."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_v3 import A, PW, setup_module, teardown_module, add_user, add_student, Agent  # noqa: F401


def uid(name):
    with A.app.app_context():
        return A.db().execute('SELECT id FROM users WHERE username=?', (name,)).fetchone()['id']


def kids(name):
    with A.app.app_context():
        return sorted(r[0] for r in A.db().execute('SELECT student_id FROM parent_children WHERE user_id=?', (uid(name),)).fetchall())


def link(admin, name, role, child_ids, **extra):
    tok = admin.token()
    data = {'_csrf': tok, 'full_name': name, 'username': name, 'role': role, 'child_ids': [str(c) for c in child_ids]}
    data.update(extra)
    return admin.c.post(f'/users/{uid(name)}/edit', data=data, follow_redirects=True)


def test_staff_roles_can_be_linked_and_see_only_their_children():
    add_user('fam_admin', 'Administrator'); admin = Agent('fam_admin')
    own = add_student('FAM1', 'Kofi', 'Ownchild', 'Primary 1'); other = add_student('FAM2', 'Esi', 'Otherchild', 'Primary 2')
    for name, role in (('fam_acct', 'Accountant'), ('fam_prop', 'Proprietor'), ('fam_teach', 'Teacher'), ('fam_lib', 'Librarian')):
        add_user(name, role)
        r = link(admin, name, role, [own])
        assert b'User account updated' in r.data, (name, r.data[:200])
        assert kids(name) == [own]
        ag = Agent(name)
        page = ag.get('/portal')
        assert page.status_code == 200 and b'Ownchild' in page.data and b'Otherchild' not in page.data
        assert ag.get(f'/portal?student_id={other}').status_code == 403
        assert b'My children' in ag.get('/change-password').data  # menu link
    with A.app.app_context():
        assert A.db().execute("SELECT COUNT(*) FROM audit_log WHERE action='view' AND entity='child_portal'").fetchone()[0] >= 4


def test_staff_without_children_have_no_portal_and_menu_link():
    add_user('fam_none', 'Accountant'); ag = Agent('fam_none')
    assert ag.get('/portal').status_code == 403
    assert 'My children' not in ag.get('/change-password').get_data(as_text=True)


def test_menu_link_shows_for_linked_staff_and_staff_access_is_unchanged():
    add_user('fam_t2', 'Subject Teacher'); admin = Agent('fam_admin')
    pchild = add_student('FAM3', 'Yaw', 'Primarykid', 'Primary 3')
    link(admin, 'fam_t2', 'Subject Teacher', [pchild], assigned_class='ST:JHS 1')
    ag = Agent('fam_t2')
    assert 'My children' in ag.get('/change-password').get_data(as_text=True)
    assert A.class_scope({'role': 'Subject Teacher', 'assigned_class': 'ST:JHS 1'}) == ['JHS 1']
    students_page = ag.get('/students').get_data(as_text=True)
    assert 'FAM3' not in students_page            # the child is not in a class they teach
    assert ag.get(f'/students/{pchild}').status_code in (403, 404)  # staff access unchanged


def test_role_change_keeps_links_for_family_roles_and_student_role_clears():
    admin = Agent('fam_admin'); c = add_student('FAM4', 'Ama', 'Keep', 'Primary 1')
    add_user('fam_move', 'Teacher'); link(admin, 'fam_move', 'Teacher', [c])
    link(admin, 'fam_move', 'Accountant', [c]); assert kids('fam_move') == [c]
    r = link(admin, 'fam_move', 'Student', [c], student_id=str(c))
    assert b'cannot have children' in r.data and kids('fam_move') == [c]
    link(admin, 'fam_move', 'Student', [], student_id=str(c)); assert kids('fam_move') == []
    link(admin, 'fam_move', 'Teacher', []); assert kids('fam_move') == []


def test_clearing_and_deleting_never_removes_the_child():
    admin = Agent('fam_admin'); c = add_student('FAM5', 'Kwame', 'Safe', 'Primary 1')
    add_user('fam_del', 'Storekeeper'); link(admin, 'fam_del', 'Storekeeper', [c]); assert kids('fam_del') == [c]
    tok = admin.token(); i = uid('fam_del')
    admin.c.post(f'/users/{i}/delete', data={'_csrf': tok, 'confirm': '1'})
    with A.app.app_context():
        assert A.db().execute("SELECT COUNT(*) FROM students WHERE admission_no='FAM5'").fetchone()[0] == 1
        assert A.db().execute('SELECT COUNT(*) FROM parent_children WHERE user_id=?', (i,)).fetchone()[0] == 0


def test_create_user_form_accepts_children_for_staff_and_parent_still_works():
    admin = Agent('fam_admin'); tok = admin.token(); c = add_student('FAM6', 'Efua', 'Form', 'Primary 1')
    r = admin.c.post('/users', data={'_csrf': tok, 'full_name': 'fam_new', 'username': 'fam_new', 'password': 'LongPassword2026!', 'role': 'Headteacher', 'child_ids': [str(c)]})
    assert r.status_code == 302 and kids('fam_new') == [c]
    r = admin.c.post('/users', data={'_csrf': tok, 'full_name': 'fam_par', 'username': 'fam_par', 'password': 'LongPassword2026!', 'role': 'Parent/Guardian', 'student_id': str(c), 'child_ids': [str(c)]})
    assert kids('fam_par') == [c]
