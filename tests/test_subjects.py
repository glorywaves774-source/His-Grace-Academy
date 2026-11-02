"""Subjects taught: recorded on a Subject Teacher's account and enforced when entering results."""
import json
import re
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_v3 import A, PW, setup_module, teardown_module, add_user, add_student, Agent  # noqa: F401


def prepare():
    with A.app.app_context():
        c = A.db()
        have = {json.loads(r['payload_json']).get('subject_name') for r in c.execute("SELECT payload_json FROM school_records WHERE module_key='subjects'")}
        for n in ('Mathematics', 'Integrated Science', 'Computing'):
            if n not in have:
                c.execute("INSERT INTO school_records(module_key,title,payload_json,status) VALUES('subjects',?,?,'Recorded')", (n, json.dumps({'subject_name': n, 'class_name': 'JHS 1', 'academic_year': '2030/2031', 'term': 'Term 1'})))
        c.commit()


def set_subjects(name, subjects):
    with A.app.app_context():
        c = A.db(); c.execute('UPDATE users SET subjects_taught=? WHERE username=?', (json.dumps(subjects) if subjects else None, name)); c.commit()


def result(student_id, subject, **extra):
    d = {'student_id': str(student_id), 'class_name': 'JHS 1', 'subject_name': subject, 'assessment_type': 'Quiz', 'assessment_name': 'Test ' + subject,
         'event_date': '2030-10-05', 'academic_year': '2030/2031', 'term': 'Term 1', 'score': '40', 'maximum_score': '50'}
    d.update(extra); return d


def test_subjects_saved_shown_and_validated_on_user_forms():
    prepare(); add_user('sj_admin', 'Administrator'); ad = Agent('sj_admin'); tok = ad.token()
    r = ad.c.post('/users', data={'_csrf': tok, 'full_name': 'Sj One', 'username': 'sj_one', 'password': 'LongPassword2026!', 'role': 'Subject Teacher', 'assigned_class': 'ST:JHS 1,JHS 2', 'subjects_taught': ['Mathematics', 'Computing']})
    assert r.status_code == 302
    with A.app.app_context():
        row = A.db().execute("SELECT subjects_taught FROM users WHERE username='sj_one'").fetchone()
    assert json.loads(row['subjects_taught']) == ['Mathematics', 'Computing']
    page = ad.get('/users').get_data(as_text=True)
    assert 'Subjects: Mathematics, Computing' in page
    bad = ad.c.post('/users', data={'_csrf': tok, 'full_name': 'x', 'username': 'sj_bad', 'password': 'LongPassword2026!', 'role': 'Subject Teacher', 'subjects_taught': ['Basket Weaving']}, follow_redirects=True)
    assert b'Choose subjects from the school subject list' in bad.data
    # other roles never keep subjects
    ad.c.post('/users', data={'_csrf': tok, 'full_name': 'ct', 'username': 'sj_ct', 'password': 'LongPassword2026!', 'role': 'Class Teacher', 'assigned_class': 'JHS 1', 'subjects_taught': ['Mathematics']})
    with A.app.app_context():
        assert A.db().execute("SELECT subjects_taught FROM users WHERE username='sj_ct'").fetchone()[0] is None
    # edit page preselects, and editing changes them
    with A.app.app_context(): uid = A.db().execute("SELECT id FROM users WHERE username='sj_one'").fetchone()['id']
    ed = ad.get(f'/users/{uid}/edit').get_data(as_text=True)
    assert re.search(r'<option selected>Mathematics</option>', ed) and re.search(r'<option selected>Computing</option>', ed)
    ad.c.post(f'/users/{uid}/edit', data={'_csrf': tok, 'full_name': 'Sj One', 'username': 'sj_one', 'role': 'Subject Teacher', 'assigned_class': 'ST:JHS 1,JHS 2', 'subjects_taught': ['Integrated Science']})
    with A.app.app_context():
        assert json.loads(A.db().execute("SELECT subjects_taught FROM users WHERE id=?", (uid,)).fetchone()[0]) == ['Integrated Science']


def test_teacher_can_enter_and_see_only_own_subjects():
    prepare(); s = add_student('SJ1', 'Kofi', 'Subjone', 'JHS 1')
    add_user('sj_admin2', 'Administrator'); ad = Agent('sj_admin2'); atok = ad.token()
    assert ad.c.post('/modules/assessments/new', data=dict(result(s, 'Integrated Science'), _csrf=atok)).status_code == 302
    add_user('sj_math', 'Subject Teacher'); set_subjects('sj_math', ['Mathematics'])
    t = Agent('sj_math'); tok = t.token()
    form = t.get('/modules/assessments/new').get_data(as_text=True)
    sel = re.search(r'<select[^>]*name="subject_name".*?</select>', form, re.S).group(0)
    assert 'value="Mathematics"' in sel and 'Integrated Science' not in sel and 'Computing' not in sel
    assert t.c.post('/modules/assessments/new', data=dict(result(s, 'Mathematics'), _csrf=tok)).status_code == 302
    r = t.c.post('/modules/assessments/new', data=dict(result(s, 'Integrated Science', assessment_name='Sneaky'), _csrf=tok), follow_redirects=True)
    assert b'only for your own subjects' in r.data
    listing = t.get('/modules/assessments').get_data(as_text=True)
    assert 'Mathematics' in listing and 'Integrated Science' not in listing
    with A.app.app_context():
        sci = A.db().execute("SELECT id FROM school_records WHERE module_key='assessments' AND title LIKE '%Integrated Science%' LIMIT 1").fetchone()
    assert sci is not None and t.get(f'/modules/assessments/{sci["id"]}/edit').status_code == 403
    assert 'Integrated Science' in ad.get('/modules/assessments').get_data(as_text=True)   # administrators still see everything


def test_no_subjects_set_and_other_roles_unchanged():
    prepare(); s = add_student('SJ2', 'Esi', 'Subjtwo', 'JHS 1')
    add_user('sj_free', 'Subject Teacher'); t = Agent('sj_free'); tok = t.token()
    assert 'name="subject_name"' in t.get('/modules/assessments/new').get_data(as_text=True)
    assert t.c.post('/modules/assessments/new', data=dict(result(s, 'Any Typed Subject'), _csrf=tok)).status_code == 302
    add_user('sj_ctch', 'Class Teacher')
    with A.app.app_context():
        c = A.db(); c.execute("UPDATE users SET assigned_class='JHS 1', subjects_taught=? WHERE username='sj_ctch'", (json.dumps(['Mathematics']),)); c.commit()
    ct = Agent('sj_ctch'); ctok = ct.token()
    assert ct.c.post('/modules/assessments/new', data=dict(result(s, 'Anything Else', assessment_name='CT entry'), _csrf=ctok)).status_code == 302


def test_starter_list_used_until_register_has_subjects():
    with A.app.app_context():
        c = A.db(); saved = c.execute("SELECT * FROM school_records WHERE module_key='subjects'").fetchall(); c.execute("DELETE FROM school_records WHERE module_key='subjects'"); c.commit()
        assert A.subject_catalogue() == A.STARTER_SUBJECTS
        for r in saved: c.execute('INSERT INTO school_records(id,module_key,title,payload_json,status) VALUES(?,?,?,?,?)', (r['id'], r['module_key'], r['title'], r['payload_json'], r['status']))
        c.commit()


def test_edit_page_keeps_a_single_class_subject_teacher_on_that_class():
    prepare(); add_user('sj_admin3', 'Administrator'); ad = Agent('sj_admin3'); tok = ad.token()
    add_user('sj_single', 'Subject Teacher')
    with A.app.app_context():
        c = A.db(); c.execute("UPDATE users SET assigned_class='ST:JHS 2' WHERE username='sj_single'"); uid = c.execute("SELECT id FROM users WHERE username='sj_single'").fetchone()['id']; c.commit()
    page = ad.get(f'/users/{uid}/edit').get_data(as_text=True)
    assert re.search(r'<option selected>JHS 2</option>', page)
    ad.c.post(f'/users/{uid}/edit', data={'_csrf': tok, 'full_name': 'sj_single', 'username': 'sj_single', 'role': 'Subject Teacher', 'assigned_class': 'JHS 2'})
    with A.app.app_context():
        assert A.db().execute("SELECT assigned_class FROM users WHERE id=?", (uid,)).fetchone()[0] == 'ST:JHS 2'
