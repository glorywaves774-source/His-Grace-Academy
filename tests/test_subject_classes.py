"""Subject teachers can be assigned one, two or all three JHS classes from the user form."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_v3 import A, PW, setup_module, teardown_module  # noqa: F401


def scope(role, assigned):
    return A.class_scope({'role': role, 'assigned_class': assigned})


def test_choices_grant_exactly_the_chosen_classes():
    assert scope('Subject Teacher', A.st_value(['JHS 1'])) == ['JHS 1']
    assert scope('Subject Teacher', A.st_value(['JHS 2', 'JHS 3'])) == ['JHS 2', 'JHS 3']
    assert scope('Subject Teacher', A.st_value(['JHS 1', 'JHS 3'])) == ['JHS 1', 'JHS 3']
    assert scope('Subject Teacher', A.st_value(['JHS 1', 'JHS 2', 'JHS 3'])) == ['JHS 1', 'JHS 2', 'JHS 3']


def test_existing_subject_teachers_and_other_roles_unchanged():
    assert scope('Subject Teacher', None) == ['JHS 1', 'JHS 2', 'JHS 3']
    assert scope('Subject Teacher', 'JHS 2') == ['JHS 2', 'JHS 1', 'JHS 3']  # legacy plain value keeps all three
    assert scope('Class Teacher', 'Primary 4') == ['Primary 4']
    assert scope('Teacher', None) == []
    assert scope('Administrator', None) is None


def test_normalise_rules():
    n = A.normalise_assigned
    assert n('Subject Teacher', '') is None
    assert n('Subject Teacher', 'JHS 2') == 'ST:JHS 2'
    assert n('Subject Teacher', 'ST:JHS 3,JHS 1') == 'ST:JHS 1,JHS 3'
    assert n('Subject Teacher', 'ST:JHS 1,Primary 1') is False
    assert n('Class Teacher', 'ST:JHS 1,JHS 2') is False
    assert n('Class Teacher', 'Primary 4') == 'Primary 4'


def test_user_form_creates_subject_teacher_with_two_classes_and_shows_them():
    c = A.app.test_client()
    # sign in as the seeded teacher-capable admin from test_v3 helpers
    from test_v3 import add_user, Agent
    add_user('st_admin', 'Administrator')
    ag = Agent('st_admin')
    tok = ag.token()
    for name, val in (('st_two', 'ST:JHS 1,JHS 2'), ('st_all', 'ST:JHS 1,JHS 2,JHS 3'), ('st_one', 'JHS 3')):
        r = ag.c.post('/users', data={'_csrf': tok, 'full_name': name, 'username': name, 'password': 'LongPassword2026!', 'role': 'Subject Teacher', 'assigned_class': val})
        assert r.status_code == 302
    bad = ag.c.post('/users', data={'_csrf': tok, 'full_name': 'x', 'username': 'bad_ct', 'password': 'LongPassword2026!', 'role': 'Class Teacher', 'assigned_class': 'ST:JHS 1,JHS 2'}, follow_redirects=True)
    assert b'only for Subject Teachers' in bad.data
    with A.app.app_context():
        rows = {r['username']: r['assigned_class'] for r in A.db().execute("SELECT username,assigned_class FROM users WHERE username IN ('st_two','st_all','st_one','bad_ct')")}
    assert rows == {'st_two': 'ST:JHS 1,JHS 2', 'st_all': 'ST:JHS 1,JHS 2,JHS 3', 'st_one': 'ST:JHS 3'}
    page = ag.get('/users').get_data(as_text=True)
    assert 'JHS 1 &amp; JHS 2' in page and 'JHS 1, JHS 2 &amp; JHS 3' in page
    assert 'value="ST:JHS 1,JHS 3"' in page


def test_students_list_limited_to_chosen_classes():
    from test_v3 import add_user, add_student, Agent
    add_student('STX1', 'Jone', 'Aone', 'JHS 1'); add_student('STX2', 'Jtwo', 'Atwo', 'JHS 2'); add_student('STX3', 'Jthree', 'Athree', 'JHS 3')
    with A.app.app_context():
        c = A.db()
        c.execute("INSERT OR IGNORE INTO users(username,password_hash,full_name,role,assigned_class,active,must_change_password) VALUES('st_j12',?,'ST J12','Subject Teacher','ST:JHS 1,JHS 2',1,0)", (A.generate_password_hash(PW),))
        c.commit()
    page = Agent('st_j12').get('/students').get_data(as_text=True)
    assert 'STX1' in page and 'STX2' in page and 'STX3' not in page
