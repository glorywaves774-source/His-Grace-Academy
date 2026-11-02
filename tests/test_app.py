"""Smoke and security tests for Fr. Joseph Connolly SVD Memorial School Management System.
Run with: pytest -q
"""
import os
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DB_FILE = tempfile.mktemp(prefix='kings_gate_test_', suffix='.sqlite3')
os.environ['SCHOOL_DB'] = DB_FILE
os.environ['SECRET_KEY'] = 'test-only-secret-key-not-for-deployment'

import app as school_app

client = school_app.app.test_client()


def login_initial_admin():
    return client.post('/login', data={'username': 'admin', 'password': 'ChangeMe123!'}, follow_redirects=True)


def csrf():
    with client.session_transaction() as sess:
        return sess.get('csrf')


def change_initial_password():
    token = csrf()
    return client.post('/change-password', data={
        '_csrf': token,
        'current_password': 'ChangeMe123!',
        'new_password': 'SchoolSecure2026!',
        'confirm_password': 'SchoolSecure2026!'
    }, follow_redirects=True)


def test_00_initial_admin_is_forced_to_change_password():
    response = login_initial_admin()
    assert response.status_code == 200
    assert b'Change your sign-in password' in response.data or b'Update your sign-in password' in response.data
    response = change_initial_password()
    assert response.status_code == 200
    assert b'Sign in to your account' in response.data


def test_10_admin_pages_render_after_password_rotation():
    response = client.post('/login', data={'username': 'admin', 'password': 'SchoolSecure2026!'}, follow_redirects=True)
    assert response.status_code == 200
    for path in ['/dashboard', '/students', '/classes', '/reports', '/fees', '/import', '/users', '/audit']:
        result = client.get(path)
        assert result.status_code == 200, (path, result.status_code, result.data[:300])


def test_20_student_creation_and_exports():
    if not csrf():
        client.post('/login', data={'username': 'admin', 'password': 'SchoolSecure2026!'}, follow_redirects=True)
    token = csrf()
    with school_app.app.app_context():
        class_id = school_app.db().execute("SELECT id FROM classes WHERE name='Primary 1'").fetchone()['id']
    response = client.post('/students/new', data={
        '_csrf': token, 'admission_no': 'KGI-TEST-0001', 'first_name': 'Ama', 'last_name': 'Mensah',
        'admission_date': '2026-10-29', 'dob': '2018-03-04', 'gender': 'Female', 'class_id': str(class_id),
        'guardian_name': 'Kofi Mensah', 'guardian_phone': '0244000000', 'status': 'Active'
    }, follow_redirects=True)
    assert response.status_code == 200
    assert b'Ama Mensah' in response.data
    assert client.get('/export/students.csv').status_code == 200
    assert client.get('/export/students.xlsx').status_code == 200
    assert client.get('/export/students.pdf').status_code == 200


def test_30_unauthenticated_post_is_rejected():
    client.post('/logout', data={'_csrf': 'invalid'}, follow_redirects=True)
    with client.session_transaction() as sess:
        sess.clear()
    response = client.post('/students/new', data={'first_name': 'No', 'last_name': 'Access'})
    assert response.status_code in (302, 400)


def teardown_module():
    try:
        Path(DB_FILE).unlink(missing_ok=True)
    except OSError:
        pass


def test_40_module_routes_are_database_backed_and_role_protected():
    client.post('/login', data={'username': 'admin', 'password': 'SchoolSecure2026!'}, follow_redirects=True)
    response = client.get('/modules/attendance')
    assert response.status_code == 200
    token = csrf()
    with school_app.app.app_context():
        sid = school_app.db().execute("SELECT id FROM students WHERE admission_no='KGI-TEST-0001'").fetchone()['id']
    response = client.post('/modules/attendance/new', data={
        '_csrf': token, 'student_id': str(sid), 'class_name': 'Primary 1',
        'event_date': '2026-10-29', 'attendance_status': 'Present', 'notes': 'test'
    }, follow_redirects=True)
    assert response.status_code == 200
    assert b'Attendance record saved' in response.data
    with school_app.app.app_context():
        row = school_app.db().execute("SELECT COUNT(*) FROM school_records WHERE module_key='attendance'").fetchone()[0]
        assert row == 1
    # A non-admin role must not access a restricted welfare register. Use a separate
    # teacher account and client; never demote the shared admin account, because later
    # tests sign in as admin.
    teacher_client = school_app.app.test_client()
    with school_app.app.app_context():
        conn = school_app.db()
        conn.execute("INSERT OR IGNORE INTO users(username,password_hash,full_name,role,assigned_class,active,must_change_password) VALUES(?,?,?,?,?,1,0)",
                     ('class_teacher_40', school_app.generate_password_hash('TeacherSecure2026!'), 'Class Teacher', 'Class Teacher', 'Primary 1'))
        conn.commit()
    teacher_client.post('/login', data={'username': 'class_teacher_40', 'password': 'TeacherSecure2026!'}, follow_redirects=True)
    assert teacher_client.get('/modules/welfare').status_code == 403
    assert teacher_client.get('/modules/attendance').status_code == 200


def test_50_parent_portal_is_linked_to_one_student_only():
    # Use a separate client so this test does not depend on the admin session.
    portal_client = school_app.app.test_client()
    with school_app.app.app_context():
        conn = school_app.db()
        first = conn.execute("SELECT id FROM students WHERE admission_no='KGI-TEST-0001'").fetchone()
        if not first:
            class_id = conn.execute("SELECT id FROM classes WHERE name='Primary 1'").fetchone()['id']
            cur = conn.execute("INSERT INTO students(admission_no,first_name,last_name,admission_date,class_id) VALUES(?,?,?,?,?)", ('KGI-PORTAL-0001','Ama','Linked','2026-10-29',class_id))
            first_id = cur.lastrowid
        else:
            first_id = first['id']
        conn.execute("INSERT OR IGNORE INTO users(username,password_hash,full_name,role,student_id,active,must_change_password) VALUES(?,?,?,?,?,1,0)",
                     ('portal_parent', school_app.generate_password_hash('PortalSecure2026!'), 'Test Parent', 'Parent/Guardian', first_id))
        conn.commit()
    response = portal_client.post('/login', data={'username':'portal_parent','password':'PortalSecure2026!'}, follow_redirects=False)
    assert response.status_code == 302
    assert response.headers['Location'].endswith('/portal')
    page = portal_client.get('/portal')
    assert page.status_code == 200
    assert b'Ama' in page.data
    assert portal_client.get('/students').status_code == 403
    assert portal_client.get('/modules/health').status_code == 403


def test_60_parent_account_can_link_multiple_children_without_cross_access():
    parent_client = school_app.app.test_client()
    with school_app.app.app_context():
        conn = school_app.db()
        class_id = conn.execute("SELECT id FROM classes WHERE name='Primary 1'").fetchone()['id']
        one = conn.execute("SELECT id FROM students WHERE admission_no='KGI-PORTAL-0001'").fetchone()
        one_id = one['id'] if one else conn.execute("INSERT INTO students(admission_no,first_name,last_name,admission_date,class_id) VALUES(?,?,?,?,?)", ('KGI-PORTAL-0001','Ama','Linked','2026-10-29',class_id)).lastrowid
        two = conn.execute("SELECT id FROM students WHERE admission_no='KGI-PORTAL-0002'").fetchone()
        two_id = two['id'] if two else conn.execute("INSERT INTO students(admission_no,first_name,last_name,admission_date,class_id) VALUES(?,?,?,?,?)", ('KGI-PORTAL-0002','Kojo','Linked','2026-10-29',class_id)).lastrowid
        conn.execute("INSERT OR IGNORE INTO users(username,password_hash,full_name,role,student_id,active,must_change_password) VALUES(?,?,?,?,?,1,0)", ('multi_parent', school_app.generate_password_hash('ParentSecure2026!'), 'Multi Parent', 'Parent/Guardian', one_id))
        parent_id = conn.execute("SELECT id FROM users WHERE username='multi_parent'").fetchone()['id']
        conn.execute('INSERT OR IGNORE INTO parent_children(user_id,student_id) VALUES(?,?)', (parent_id, one_id))
        conn.execute('INSERT OR IGNORE INTO parent_children(user_id,student_id) VALUES(?,?)', (parent_id, two_id))
        conn.commit()
    parent_client.post('/login', data={'username':'multi_parent','password':'ParentSecure2026!'}, follow_redirects=True)
    page = parent_client.get('/portal')
    assert page.status_code == 200
    assert b'Ama' in page.data or b'Kojo' in page.data
    assert parent_client.get(f'/portal?student_id={two_id}').status_code == 200
    assert parent_client.get('/students').status_code == 403
    with school_app.app.app_context():
        outsider = school_app.db().execute("SELECT id FROM students WHERE admission_no='KGI-TEST-0001'").fetchone()
        outsider_id = outsider['id']
    assert parent_client.get(f'/portal?student_id={outsider_id}').status_code == 403


def test_70_invoice_pages_are_protected_and_render_for_finance_user():
    finance_client = school_app.app.test_client()
    with school_app.app.app_context():
        conn = school_app.db()
        conn.execute("INSERT OR IGNORE INTO users(username,password_hash,full_name,role,active,must_change_password) VALUES(?,?,?,?,1,0)", ('invoice_accountant', school_app.generate_password_hash('FinanceSecure2026!'), 'Finance User', 'Accountant'))
        conn.commit()
    assert finance_client.get('/invoices').status_code in (302, 401)
    finance_client.post('/login', data={'username':'invoice_accountant','password':'FinanceSecure2026!'}, follow_redirects=True)
    assert finance_client.get('/invoices').status_code == 200
    assert finance_client.get('/reports/report-cards').status_code == 403


def test_80_invoice_payment_link_and_balance_calculation():
    finance_client = school_app.app.test_client()
    with school_app.app.app_context():
        conn = school_app.db()
        conn.execute("INSERT OR IGNORE INTO users(username,password_hash,full_name,role,active,must_change_password) VALUES(?,?,?,?,1,0)", ('billing_accountant', school_app.generate_password_hash('BillingSecure2026!'), 'Billing User', 'Accountant'))
        student = conn.execute("SELECT id FROM students WHERE admission_no='KGI-TEST-0001'").fetchone()
        if not student:
            class_id = conn.execute("SELECT id FROM classes WHERE name='Primary 1'").fetchone()['id']
            student_id = conn.execute("INSERT INTO students(admission_no,first_name,last_name,admission_date,class_id) VALUES(?,?,?,?,?)", ('KGI-BILL-0001','Esi','Test','2026-10-29',class_id)).lastrowid
        else:
            student_id = student['id']
        conn.commit()
    finance_client.post('/login', data={'username':'billing_accountant','password':'BillingSecure2026!'}, follow_redirects=True)
    token = None
    with finance_client.session_transaction() as sess:
        token = sess.get('csrf')
    response = finance_client.post('/invoices/new', data={
        '_csrf': token, 'student_id': str(student_id), 'academic_year': '2026/2027', 'term': 'Term 1',
        'description': 'Test tuition invoice', 'amount': '100.00', 'discount': '10.00', 'due_date': '2026-11-30'
    }, follow_redirects=True)
    assert response.status_code == 200
    with school_app.app.app_context():
        invoice = school_app.db().execute("SELECT * FROM fee_invoices WHERE student_id=? AND description='Test tuition invoice' ORDER BY id DESC LIMIT 1", (student_id,)).fetchone()
    assert invoice is not None
    response = finance_client.post(f'/fees/new/{student_id}', data={
        '_csrf': token, 'amount': '25.00', 'payment_date': '2026-10-29', 'payment_method': 'Cash',
        'purpose': 'Test tuition invoice', 'invoice_no': invoice['invoice_no'], 'notes': ''
    }, follow_redirects=True)
    assert response.status_code == 200
    with school_app.app.app_context():
        paid = school_app.db().execute('SELECT COALESCE(SUM(amount),0) FROM fees WHERE student_id=? AND purpose=?', (student_id, invoice['invoice_no'])).fetchone()[0]
        assert paid == 25.0
        assert round(invoice['amount'] - invoice['discount'] - paid, 2) == 65.0


def test_90_student_passport_photo_upload_and_private_retrieval():
    from io import BytesIO
    from PIL import Image
    client.post('/login', data={'username': 'admin', 'password': 'SchoolSecure2026!'}, follow_redirects=True)
    token = csrf()
    image = BytesIO()
    Image.new('RGB', (120, 160), 'navy').save(image, format='PNG')
    image.seek(0)
    response = client.post('/students/new', data={
        '_csrf': token, 'admission_no': 'KGI-PHOTO-STU-001', 'first_name': 'Photo', 'last_name': 'Student',
        'admission_date': '2026-10-30', 'status': 'Active', 'passport_photo': (image, 'student.png')
    }, content_type='multipart/form-data', follow_redirects=True)
    assert response.status_code == 200
    with school_app.app.app_context():
        student = school_app.db().execute("SELECT id,photo_path FROM students WHERE admission_no='KGI-PHOTO-STU-001'").fetchone()
        assert student and student['photo_path'].startswith('passport_photos/students/')
    photo = client.get('/private/passport/' + student['photo_path'])
    assert photo.status_code == 200
    assert photo.mimetype == 'image/jpeg'


def test_91_staff_passport_photo_upload_and_private_retrieval():
    from io import BytesIO
    from PIL import Image
    client.post('/login', data={'username': 'admin', 'password': 'SchoolSecure2026!'}, follow_redirects=True)
    token = csrf()
    image = BytesIO()
    Image.new('RGB', (120, 160), 'darkgreen').save(image, format='PNG')
    image.seek(0)
    response = client.post('/modules/staff/new', data={
        '_csrf': token, 'full_name': 'Photo Staff', 'position': 'Teacher', 'employment_status': 'Active',
        'passport_photo': (image, 'staff.png')
    }, content_type='multipart/form-data', follow_redirects=True)
    assert response.status_code == 200
    with school_app.app.app_context():
        row = school_app.db().execute("SELECT payload_json FROM school_records WHERE module_key='staff' ORDER BY id DESC LIMIT 1").fetchone()
        payload = __import__('json').loads(row['payload_json'])
        assert payload['passport_photo_path'].startswith('passport_photos/staff/')
    photo = client.get('/private/passport/' + payload['passport_photo_path'])
    assert photo.status_code == 200
    assert photo.mimetype == 'image/jpeg'


def test_92_student_directory_search_and_dropdown_selection():
    client.post('/login', data={'username': 'admin', 'password': 'SchoolSecure2026!'}, follow_redirects=True)
    response = client.get('/students?q=KGI-TEST-0001')
    assert response.status_code == 200
    assert b'Ama Mensah' in response.data
    with school_app.app.app_context():
        student = school_app.db().execute("SELECT id FROM students WHERE admission_no='KGI-TEST-0001'").fetchone()
        assert student
    response = client.get(f'/students?student_id={student["id"]}')
    assert response.status_code == 200
    assert b'Ama Mensah' in response.data


def test_93_staff_directory_search_includes_records_beyond_500():
    client.post('/login', data={'username': 'admin', 'password': 'SchoolSecure2026!'}, follow_redirects=True)
    with school_app.app.app_context():
        conn = school_app.db()
        conn.execute("INSERT INTO school_records(module_key,title,payload_json,status,created_by,updated_by) VALUES('staff','Older Searchable Staff','{\"full_name\":\"Older Searchable Staff\",\"staff_number\":\"KGI-STAFF-OLD-001\"}','Active',1,1)")
        for i in range(505):
            conn.execute("INSERT INTO school_records(module_key,title,payload_json,status,created_by,updated_by) VALUES('staff',?,?, 'Active',1,1)", (f'Bulk Staff {i:03d}', __import__('json').dumps({'full_name': f'Bulk Staff {i:03d}', 'staff_number': f'KGI-BULK-{i:03d}'})))
        conn.commit()
    response = client.get('/modules/staff?q=KGI-STAFF-OLD-001')
    assert response.status_code == 200
    assert b'Older Searchable Staff' in response.data
    response = client.get('/modules/staff?record_id=1')
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Regression tests added in version 12
# ---------------------------------------------------------------------------
import json
from datetime import date


def admin_client():
    c = school_app.app.test_client()
    c.post('/login', data={'username': 'admin', 'password': 'SchoolSecure2026!'}, follow_redirects=True)
    return c


def _token(c):
    with c.session_transaction() as sess:
        return sess.get('csrf')


def test_94_admin_account_is_still_an_administrator():
    # Guards against any test demoting the shared admin account again.
    with school_app.app.app_context():
        assert school_app.db().execute("SELECT role FROM users WHERE username='admin'").fetchone()['role'] == 'Administrator'


def test_95_dashboard_numbers_match_the_database():
    with school_app.app.app_context():
        conn = school_app.db()
        p2 = conn.execute("SELECT id FROM classes WHERE name='Primary 2'").fetchone()['id']
        today = date.today().isoformat()
        rows = [('KGI-DASH-1', 'Dash', 'One', 'Male', p2, 'Active'), ('KGI-DASH-2', 'Dash', 'Two', 'Female', p2, 'Active'),
                ('KGI-DASH-3', 'Dash', 'Three', 'Other', p2, 'Active'), ('KGI-DASH-4', 'Dash', 'Four', None, None, 'Active'),
                ('KGI-DASH-5', 'Dash', 'Five', 'Male', p2, 'Withdrawn')]
        for adm, f, l, g, cid, st in rows:
            conn.execute('INSERT INTO students(admission_no,first_name,last_name,gender,admission_date,class_id,status) VALUES(?,?,?,?,?,?,?)', (adm, f, l, g, today, cid, st))
        conn.commit()
        total = conn.execute('SELECT COUNT(*) FROM students').fetchone()[0]
        active = conn.execute("SELECT COUNT(*) FROM students WHERE status='Active'").fetchone()[0]
        p2_active = conn.execute("SELECT COUNT(*) FROM students WHERE status='Active' AND class_id=?", (p2,)).fetchone()[0]
    captured = {}
    original = school_app.render_template
    def spy(name, **ctx):
        captured.update(ctx); return original(name, **ctx)
    school_app.render_template = spy
    try:
        response = admin_client().get('/dashboard')
    finally:
        school_app.render_template = original
    assert response.status_code == 200
    assert captured['total'] == total and captured['active'] == active
    # The class bar for Primary 2 must count the active students (it previously always showed 0).
    assert {r['name']: r['n'] for r in captured['class_rows']}['Primary 2'] == p2_active >= 3
    # Charts reconcile: classes (+ Unassigned) add up to Active; genders add up to Active.
    assert sum(r['n'] for r in captured['class_rows']) == active
    assert sum(captured['genders'].values()) == active
    assert captured['genders']['Other'] >= 1
    # 12 consecutive months, including empty ones, ending with the current month.
    assert len(captured['month_rows']) == 12 and captured['month_rows'][-1]['key'] == date.today().strftime('%Y-%m')
    assert captured['new_this_month'] == captured['month_rows'][-1]['n'] >= 5


def test_96_classes_and_reports_pages_count_active_students():
    c = admin_client()
    with school_app.app.app_context():
        expected = school_app.db().execute("SELECT COUNT(*) FROM students s JOIN classes c ON c.id=s.class_id WHERE c.name='Primary 2' AND s.status='Active'").fetchone()[0]
    assert expected >= 3
    page = c.get('/classes').data.decode()
    row = page[page.index('Primary 2</b>'):]
    assert f'<td>{expected}</td>' in row[:300]
    report = c.get('/reports')
    assert report.status_code == 200 and b'Unassigned' in report.data


def test_97_librarian_and_storekeeper_land_on_a_page_they_can_open():
    with school_app.app.app_context():
        conn = school_app.db()
        for name, role in (('lib_user', 'Librarian'), ('store_user', 'Storekeeper')):
            conn.execute("INSERT OR IGNORE INTO users(username,password_hash,full_name,role,active,must_change_password) VALUES(?,?,?,?,1,0)",
                         (name, school_app.generate_password_hash('RoleSecure2026!'), name, role))
        conn.commit()
    for name in ('lib_user', 'store_user'):
        c = school_app.app.test_client()
        c.post('/login', data={'username': name, 'password': 'RoleSecure2026!'})
        landing = c.get('/', follow_redirects=True)
        assert landing.status_code == 200, (name, landing.status_code)
        assert b'Dashboard overview' not in landing.data


def test_98_enrolling_an_accepted_applicant_creates_a_student():
    c = admin_client(); token = _token(c)
    response = c.post('/modules/admissions/new', data={'_csrf': token, 'applicant_name': 'Efua Applicant', 'date_of_birth': '2019-05-04',
        'requested_class': 'Primary 1', 'guardian_name': 'Parent One', 'guardian_phone': '0244000111',
        'application_date': date.today().isoformat(), 'application_status': 'Accepted'}, follow_redirects=True)
    assert b'record saved' in response.data
    with school_app.app.app_context():
        rid = school_app.db().execute("SELECT id FROM school_records WHERE module_key='admissions' ORDER BY id DESC LIMIT 1").fetchone()['id']
    response = c.post(f'/modules/admissions/{rid}/convert', data={'_csrf': token}, follow_redirects=True)
    assert response.status_code == 200 and b'Applicant enrolled successfully' in response.data
    with school_app.app.app_context():
        assert school_app.db().execute("SELECT 1 FROM students WHERE first_name='Efua' AND last_name='Applicant'").fetchone()


def test_99_payment_cannot_exceed_invoice_balance_and_form_keeps_input():
    c = admin_client(); token = _token(c)
    with school_app.app.app_context():
        conn = school_app.db()
        sid = conn.execute("SELECT id FROM students WHERE admission_no='KGI-DASH-1'").fetchone()['id']
        conn.execute("INSERT INTO fee_invoices(invoice_no,student_id,academic_year,term,description,amount,discount,due_date) VALUES('KGI-INV-OVER',?,'2026/2027','Term 1','Tuition',100,0,'2026-12-01')", (sid,))
        conn.commit()
    response = c.post(f'/fees/new/{sid}', data={'_csrf': token, 'amount': '150', 'payment_date': date.today().isoformat(),
        'payment_method': 'Cash', 'purpose': 'Tuition', 'invoice_no': 'KGI-INV-OVER'}, follow_redirects=True)
    assert b'more than the outstanding balance' in response.data and b'value="150"' in response.data
    with school_app.app.app_context():
        assert school_app.db().execute("SELECT COUNT(*) FROM fees WHERE student_id=?", (sid,)).fetchone()[0] == 0
    ok = c.post(f'/fees/new/{sid}', data={'_csrf': token, 'amount': '100', 'payment_date': date.today().isoformat(),
        'payment_method': 'Cash', 'purpose': 'Tuition', 'invoice_no': 'KGI-INV-OVER'}, follow_redirects=True)
    assert b'Payment recorded' in ok.data
    page = c.get('/invoices?q=KGI-INV-OVER').data.decode()
    assert 'GH₵ 0.00' in page


def test_100_exports_respect_the_selected_student():
    c = admin_client()
    with school_app.app.app_context():
        sid = school_app.db().execute("SELECT id FROM students WHERE admission_no='KGI-DASH-2'").fetchone()['id']
    body = c.get(f'/export/students.csv?student_id={sid}').data.decode('utf-8-sig')
    assert 'KGI-DASH-2' in body and 'KGI-DASH-1' not in body


def test_101_student_form_keeps_input_after_a_validation_error():
    c = admin_client(); token = _token(c)
    response = c.post('/students/new', data={'_csrf': token, 'admission_no': 'KGI-KEEP-1', 'first_name': 'Keepme', 'last_name': 'Please',
        'admission_date': 'not-a-date', 'guardian_name': 'Typed Guardian'}, follow_redirects=True)
    assert b'Enter a valid admission date' in response.data
    assert b'value="Keepme"' in response.data and b'Typed Guardian' in response.data


def test_102_login_page_shows_the_whole_crest_and_layout_styles_exist():
    page = school_app.app.test_client().get('/login').data.decode()
    assert 'school-crest.png' in page and 'school-poster' not in page and 'Memorial School<' in page
    assert 'Memorial School<br>International School' not in page
    css = (Path(__file__).resolve().parents[1] / 'static' / 'style.css').read_text(encoding='utf-8')
    for selector in ('.filter-bar', '.narrow', '.login-crest'):
        assert selector in css


def test_103_dashboard_attendance_and_fees_are_accurate_and_capped_at_today():
    from datetime import date, timedelta
    today = date.today()
    with school_app.app.app_context():
        conn = school_app.db()
        sid = conn.execute("SELECT id FROM students WHERE status='Active' LIMIT 1").fetchone()['id']
        for n, (d, amt) in enumerate([(today, 40), (today.replace(day=1), 10), (today + timedelta(days=3), 999)]):
            conn.execute("INSERT INTO fees(receipt_no,student_id,amount,payment_date,payment_method,purpose,received_by) VALUES(?,?,?,?,?,?,?)",
                         (f'FJC-T103-{n}', sid, amt, d.isoformat(), 'Cash', 'Test', 'Test'))
        for status in ('Present', 'Late', 'Absent'):
            payload = json.dumps({'student_id': str(sid), 'class_name': 'Primary 1', 'event_date': today.isoformat(), 'attendance_status': status})
            conn.execute("INSERT INTO school_records(module_key,title,payload_json,student_id,class_name,event_date,status) VALUES('attendance','Student Attendance',?,?,?,?,?)",
                         (payload, sid, 'Primary 1', today.isoformat(), status))
        conn.commit()
        expected = conn.execute("SELECT COALESCE(SUM(amount),0) FROM fees WHERE payment_date>=? AND payment_date<=?", (today.replace(day=1).isoformat(), today.isoformat())).fetchone()[0]
    captured = {}
    original = school_app.render_template
    def spy(name, **ctx):
        captured.update(ctx); return original(name, **ctx)
    school_app.render_template = spy
    try:
        page = admin_client().get('/dashboard')
    finally:
        school_app.render_template = original
    assert page.status_code == 200
    assert captured['fees_month'] == expected and 999 not in (captured['fees_month'],) and captured['fees_month'] >= 50
    assert captured['attendance_today'] >= 3 and captured['present_today'] >= 2
    assert b'Fees collected' in page.data


def test_104_teacher_dashboard_hides_fees_and_scopes_attendance():
    with school_app.app.app_context():
        conn = school_app.db()
        conn.execute("INSERT OR IGNORE INTO users(username,password_hash,full_name,role,assigned_class,active,must_change_password) VALUES(?,?,?,?,?,1,0)",
                     ('class_teacher_40', school_app.generate_password_hash('TeacherSecure2026!'), 'Class Teacher', 'Class Teacher', 'Primary 1'))
        conn.commit()
    c = school_app.app.test_client()
    c.post('/login', data={'username': 'class_teacher_40', 'password': 'TeacherSecure2026!'})
    captured = {}
    original = school_app.render_template
    def spy(name, **ctx):
        captured.update(ctx); return original(name, **ctx)
    school_app.render_template = spy
    try:
        page = c.get('/dashboard')
    finally:
        school_app.render_template = original
    assert page.status_code == 200
    assert captured['show_fees'] is False and captured['fees_month'] is None and b'Fees collected' not in page.data
    assert captured['attendance_today'] >= 3
    with school_app.app.app_context():
        conn = school_app.db()
        conn.execute("INSERT INTO school_records(module_key,title,payload_json,class_name,event_date,status) VALUES('attendance','Student Attendance','{}','Primary 6',date('now'),'Present')")
        conn.commit()
    captured.clear(); school_app.render_template = spy
    try:
        c.get('/dashboard')
    finally:
        school_app.render_template = original
    with school_app.app.app_context():
        conn = school_app.db()
        own = conn.execute("SELECT COUNT(*) FROM school_records WHERE module_key='attendance' AND event_date=date('now') AND class_name='Primary 1'").fetchone()[0]
        everyone = conn.execute("SELECT COUNT(*) FROM school_records WHERE module_key='attendance' AND event_date=date('now')").fetchone()[0]
    assert own < everyone, 'test data must include another class'
    assert captured['attendance_today'] == own


def test_105_generated_numbers_use_the_school_code_not_another_schools_initials():
    with school_app.app.app_context():
        assert school_app.SCHOOL_CODE == 'FJC'
        assert school_app.make_admission_no().startswith('FJC-')
    c = admin_client()
    assert b'value="FJC-' in c.get('/students/new').data


def test_106_assets_are_light_and_free_of_other_school_branding():
    root = Path(__file__).resolve().parents[1]
    for name in ('school-crest.png', 'school-crest-small.png'):
        assert (root / 'static' / name).stat().st_size < 300_000
    for p in list((root / 'templates').glob('*.html')) + [root / 'static' / 'style.css', root / 'app.py']:
        text = p.read_text(encoding='utf-8')
        assert 'Kings Gate' not in text and 'KGI-' not in text and 'KINGS GATE' not in text, p.name
    assert not (root / 'static' / 'school-poster.jpg').exists()
