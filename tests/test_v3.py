"""Tests for the version 3 additions: leave, payroll, fee structures/arrears/refunds/cashbook,
terms, grading and transcripts, library overdue, absence alerts, timetable print, admission
letters/history, subject-teacher access to JHS 1-3, the Users page fix and backup restore."""
import io
import os
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault('SCHOOL_DB', tempfile.mktemp(prefix='fjc_test_', suffix='.sqlite3'))
os.environ.setdefault('SECRET_KEY', 'test-only-secret-key-not-for-deployment')
import app as A
from werkzeug.security import generate_password_hash

def setup_module():
    # test_app.py removes the shared database when it finishes, so make sure a fresh one exists.
    A.init_db()


def teardown_module():
    Path(A.DB_PATH).unlink(missing_ok=True)


PW = 'TeacherSecure2026!'
TODAY = date.today()


def add_user(username, role, assigned=None, student_id=None):
    with A.app.app_context():
        c = A.db()
        c.execute('INSERT OR IGNORE INTO users(username,password_hash,full_name,role,assigned_class,student_id,active,must_change_password) VALUES(?,?,?,?,?,?,1,0)',
                  (username, generate_password_hash(PW), username, role, assigned, student_id))
        c.commit()
        return c.execute('SELECT id FROM users WHERE username=?', (username,)).fetchone()['id']


def add_student(adm, first, last, cls):
    with A.app.app_context():
        c = A.db()
        cid = c.execute('SELECT id FROM classes WHERE name=?', (cls,)).fetchone()['id']
        c.execute('INSERT OR IGNORE INTO students(admission_no,first_name,last_name,admission_date,class_id,status,guardian_name,guardian_phone) VALUES(?,?,?,?,?,?,?,?)',
                  (adm, first, last, TODAY.isoformat(), cid, 'Active', 'Guardian ' + last, '0244000000'))
        c.commit()
        return c.execute('SELECT id FROM students WHERE admission_no=?', (adm,)).fetchone()['id']


class Agent:
    def __init__(self, username, password=PW):
        self.c = A.app.test_client()
        r = self.c.post('/login', data={'username': username, 'password': password})
        assert r.status_code == 302, (username, r.status_code)

    def token(self):
        self.c.get('/change-password')
        with self.c.session_transaction() as s:
            return s.get('csrf')

    def get(self, path, **kw): return self.c.get(path, **kw)

    def post(self, path, data=None, **kw):
        data = dict(data or {}); data['_csrf'] = self.token()
        return self.c.post(path, data=data, **kw)

    def module(self, key, **fields): return self.post(f'/modules/{key}/new', fields)


def admin():
    add_user('v3_admin', 'Administrator')
    return Agent('v3_admin')


def flashes_ok(resp): return resp.status_code == 302


# ---------------------------------------------------------------------------------------------------
def test_01_users_page_loads_when_parent_accounts_exist():
    sid = add_student('V3-P-1', 'Pa', 'Rent', 'Primary 1')
    a = admin()
    with A.app.app_context():
        c = A.db()
        c.execute('INSERT OR IGNORE INTO users(username,password_hash,full_name,role,student_id,active,must_change_password) VALUES(?,?,?,?,?,1,0)', ('v3_parent', generate_password_hash(PW), 'Parent One', 'Parent/Guardian', sid))
        uid = c.execute("SELECT id FROM users WHERE username='v3_parent'").fetchone()['id']
        c.execute('INSERT OR IGNORE INTO parent_children(user_id,student_id) VALUES(?,?)', (uid, sid)); c.commit()
    r = a.get('/users')
    assert r.status_code == 200 and b'Parent One' in r.data


def test_02_subject_teachers_work_in_jhs_only():
    j1 = add_student('V3-J1', 'Kojo', 'One', 'JHS 1'); j3 = add_student('V3-J3', 'Efua', 'Three', 'JHS 3'); p3 = add_student('V3-P3', 'Pim', 'Nine', 'Primary 3')
    add_user('v3_subject', 'Subject Teacher')
    t = Agent('v3_subject')
    listing = t.get('/students').data.decode()
    assert 'V3-J1' in listing and 'V3-J3' in listing and 'V3-P3' not in listing
    assert t.get(f'/students/{j1}').status_code == 200 and t.get(f'/students/{j3}').status_code == 200
    assert t.get(f'/students/{p3}').status_code == 403
    assert t.get('/dashboard').status_code == 200
    base = dict(subject_name='Science', assessment_type='Quiz', assessment_name='Q1', event_date=TODAY.isoformat(), academic_year='2026/2027', term='Term 1', score='18', maximum_score='20')
    assert t.module('assessments', student_id=str(j1), class_name='JHS 1', **base).status_code == 302
    assert t.module('assessments', student_id=str(j3), class_name='JHS 3', **base).status_code == 302
    assert b'limited to its own classes' in t.module('assessments', student_id=str(p3), class_name='Primary 3', **base).data
    form = t.get('/modules/assessments/new').data.decode()
    assert 'JHS 2' in form and 'Kojo' in form
    assert 'V3-P3' not in form and 'Pim Nine' not in form
    assert t.get('/reports/report-cards').status_code == 200
    assert t.get('/reports/attendance?class_name=JHS+2').status_code == 200
    assert t.get('/reports/attendance?class_name=Primary+3').status_code == 403
    assert 'Pim Nine' not in t.get('/reports/report-cards').data.decode()
    add_user('v3_class', 'Class Teacher', 'Primary 1')
    assert Agent('v3_class').get(f'/students/{j1}').status_code == 403


def test_03_staff_leave_rules_and_balances():
    a = admin()
    mon = TODAY + timedelta(days=(7 - TODAY.weekday()) % 7 + 7)       # a future Monday
    fri = mon + timedelta(days=4)
    ok = a.module('leave', staff_name='Mr Leave Test', leave_type='Annual', start_date=mon.isoformat(), end_date=fri.isoformat(), leave_status='Approved')
    assert ok.status_code == 302
    assert b'overlaps' in a.module('leave', staff_name='mr leave test', leave_type='Sick', start_date=mon.isoformat(), end_date=mon.isoformat(), leave_status='Pending').data
    assert b'not be before' in a.module('leave', staff_name='Mr Leave Test', leave_type='Sick', start_date=fri.isoformat(), end_date=mon.isoformat(), leave_status='Pending').data
    later = mon + timedelta(days=28)
    too_long = a.module('leave', staff_name='Mr Leave Test', leave_type='Annual', start_date=later.isoformat(), end_date=(later + timedelta(days=24)).isoformat(), leave_status='Approved')
    if later.year == mon.year: assert b'more than the entitlement' in too_long.data
    page = a.get(f'/staff/leave-balances?year={mon.year}').data.decode()
    assert 'Mr Leave Test' in page
    assert a.get('/staff/leave-balances?year=abc').status_code == 400


def test_04_payroll_calculation_payslip_and_access():
    a = admin(); month = TODAY.strftime('%Y-%m')
    r = a.module('payroll', staff_name='Ms Pay Test', pay_month=month, basic_salary='1000', allowances='200', income_tax='50', other_deductions='10', payroll_status='Approved')
    assert r.status_code == 302
    with A.app.app_context():
        row = A.db().execute("SELECT id,payload_json FROM school_records WHERE module_key='payroll' AND title LIKE 'Ms Pay Test%'").fetchone()
        p = A._payload_of(row)
    assert p['gross_pay'] == 1200 and p['ssnit_employee'] == 55 and p['total_deductions'] == 115 and p['net_pay'] == 1085 and p['ssnit_employer'] == 130
    assert b'already exists' in a.module('payroll', staff_name='ms pay test', pay_month=month, basic_salary='1000', payroll_status='Draft').data
    assert b'must look like' in a.module('payroll', staff_name='X', pay_month='2026-13', basic_salary='1', payroll_status='Draft').data
    assert b'more than gross' in a.module('payroll', staff_name='Ms Big Tax', pay_month=month, basic_salary='100', income_tax='500', payroll_status='Draft').data
    slip = a.get(f"/payroll/{row['id']}/payslip").data.decode()
    assert '1,085.00' in slip and 'Ms Pay Test' in slip
    assert 'Ms Pay Test' in a.get(f'/payroll/summary?month={month}').data.decode()
    add_user('v3_acct', 'Accountant'); add_user('v3_head', 'Headteacher')
    assert Agent('v3_acct').get(f"/payroll/{row['id']}/payslip").status_code == 200
    assert Agent('v3_head').get(f"/payroll/{row['id']}/payslip").status_code == 403
    assert Agent('v3_head').get('/modules/payroll').status_code == 403


def test_05_fee_structure_scholarship_arrears_refund_cashbook():
    s1 = add_student('V3-F1', 'Ama', 'Fee', 'Primary 5'); s2 = add_student('V3-F2', 'Kofi', 'Fee', 'Primary 5')
    a = admin()
    for item, amt in (('Tuition', '500'), ('PTA levy', '100')):
        assert a.module('fee-structure', class_name='Primary 5', academic_year='2026/2027', term='Term 1', item_name=item, amount_cedis=amt).status_code == 302
    assert b'already exists' in a.module('fee-structure', class_name='Primary 5', academic_year='2026/2027', term='Term 1', item_name='tuition', amount_cedis='1').data
    assert a.module('scholarships', student_id=str(s1), academic_year='2026/2027', term='All terms', discount_type='Percentage', discount_value='10', reason='Merit', scholarship_status='Active').status_code == 302
    assert b'more than 100' in a.module('scholarships', student_id=str(s1), academic_year='2026/2027', term='All terms', discount_type='Percentage', discount_value='150', reason='x', scholarship_status='Active').data
    gen = dict(class_name='Primary 5', academic_year='2026/2027', term='Term 1', due_date=(TODAY - timedelta(days=3)).isoformat())
    assert a.post('/fees/generate', gen).status_code == 200
    with A.app.app_context():
        inv = A.db().execute('SELECT * FROM fee_invoices WHERE student_id=?', (s1,)).fetchone(); inv2 = A.db().execute('SELECT * FROM fee_invoices WHERE student_id=?', (s2,)).fetchone()
    assert inv['amount'] == 600 and inv['discount'] == 60 and inv2['amount'] == 600 and inv2['discount'] == 0
    a.post('/fees/generate', gen)
    with A.app.app_context():
        assert A.db().execute('SELECT COUNT(*) n FROM fee_invoices WHERE student_id=?', (s1,)).fetchone()['n'] == 1     # not duplicated
    # a payment against the invoice
    pay = a.post(f'/fees/new/{s1}', dict(amount='100', payment_date=TODAY.isoformat(), payment_method='Cash', purpose=inv['invoice_no'], invoice_no=inv['invoice_no']))
    assert pay.status_code == 302
    page = a.get('/fees/arrears?class_name=Primary+5&academic_year=2026/2027&term=Term+1').data.decode()
    assert '440.00' in page and '600.00' in page          # s1: 600-60-100 outstanding; s2 owes 600
    assert 'V3-F1' in page and 'V3-F2' in page
    csv_text = a.get('/fees/arrears.csv?class_name=Primary+5').data.decode()
    assert 'V3-F1' in csv_text and 'Total' in csv_text
    # refunds
    assert b'more than the student has paid' in a.module('refunds', student_id=str(s1), amount_cedis='500', event_date=TODAY.isoformat(), refund_reason='Error', refund_method='Cash', refund_status='Paid').data
    assert a.module('refunds', student_id=str(s1), amount_cedis='30', event_date=TODAY.isoformat(), refund_reason='Overcharge', refund_method='Cash', refund_status='Paid').status_code == 302
    book = a.get(f'/fees/cashbook?start_date={TODAY.isoformat()}&end_date={TODAY.isoformat()}').data.decode()
    assert 'Fee receipt' in book and 'Refund' in book and 'Closing balance' in book
    assert a.get('/fees/cashbook?start_date=2026-12-01&end_date=2026-01-01').status_code == 400
    assert Agent('v3_head').get('/fees/arrears').status_code == 200
    assert Agent('v3_head').get('/fees/cashbook').status_code == 403
    assert b'No fee items' in a.post('/fees/generate', dict(class_name='JHS 1', academic_year='2030/2031', term='Term 1')).data


def test_06_terms_grading_report_cards_and_transcript():
    sid = add_student('V3-G1', 'Grace', 'Grade', 'Primary 6')
    a = admin()
    base = dict(student_id=str(sid), class_name='Primary 6', subject_name='Maths', assessment_type='Examination', assessment_name='End term', event_date=TODAY.isoformat(), academic_year='2030/2031', term='Term 2', score='85', maximum_score='100')
    assert a.module('assessments', **base).status_code == 302
    card = a.get('/reports/report-cards?class_name=Primary+6&academic_year=2030/2031&term=Term+2').data.decode()
    assert '>A<' in card or '<td>A</td>' in card                       # default scale
    assert a.module('grading', grade='HD', min_percent='75', remark='Highest distinction').status_code == 302
    assert b'already exists' in a.module('grading', grade='hd', min_percent='10').data
    assert b'already starts' in a.module('grading', grade='X', min_percent='75').data
    assert b'between 0 and 100' in a.module('grading', grade='Y', min_percent='120').data
    assert a.module('grading', grade='LOW', min_percent='0', remark='Needs support').status_code == 302
    card = a.get('/reports/report-cards?class_name=Primary+6&academic_year=2030/2031&term=Term+2').data.decode()
    assert 'HD' in card and 'Highest distinction' in card and 'Grading scale set by the school' in card and 'Position in class' in card and '1 of' in card
    # terms
    assert a.module('terms', academic_year='2030/2031', term='Term 2', start_date='2031-01-05', end_date='2031-04-10', term_status='Current').status_code == 302
    assert b'already marked Current' in a.module('terms', academic_year='2030/2031', term='Term 3', start_date='2031-05-01', end_date='2031-07-30', term_status='Current').data
    assert b'end date must be after' in a.module('terms', academic_year='2031/2032', term='Term 1', start_date='2031-09-10', end_date='2031-09-01', term_status='Upcoming').data
    default_card = a.get('/reports/report-cards?class_name=Primary+6').data.decode()
    assert '2030/2031' in default_card and 'Term 2' in default_card      # current term is the default
    tr = a.get(f'/students/{sid}/transcript').data.decode()
    assert 'ACADEMIC TRANSCRIPT' in tr and 'Maths' in tr and 'HD' in tr
    assert Agent('v3_class').get(f'/students/{sid}/transcript').status_code == 403
    assert a.get('/students/999999/transcript').status_code == 404


def test_07_library_overdue_and_notice():
    a = admin()
    issued = (TODAY - timedelta(days=20)).isoformat(); due = (TODAY - timedelta(days=10)).isoformat()
    for code, title in (('B-1', 'Atlas'), ('B-2', 'Dictionary')):
        assert a.module('library', book_title=title, book_code=code, transaction_type='Book issued', borrower_name='Kwesi', borrower_admission_no='V3-L1', event_date=issued, due_date=due).status_code == 302
    page = a.get('/library/overdue').data.decode()
    assert 'Atlas' in page and 'Dictionary' in page and '5.00' in page            # 10 days x 0.50
    assert a.module('library', book_title='Atlas', book_code='B-1', transaction_type='Book returned', borrower_name='Kwesi', borrower_admission_no='V3-L1', event_date=TODAY.isoformat()).status_code == 302
    page = a.get('/library/overdue').data.decode()
    assert 'Atlas' not in page and 'Dictionary' in page
    with A.app.app_context():
        rid = A.db().execute("SELECT id FROM school_records WHERE module_key='library' AND title='Dictionary'").fetchone()['id']
    assert 'OVERDUE BOOK NOTICE' in a.get(f'/library/overdue/{rid}/notice').data.decode()
    add_user('v3_lib', 'Librarian'); assert Agent('v3_lib').get('/library/overdue').status_code == 200
    add_user('v3_store', 'Storekeeper'); assert Agent('v3_store').get('/library/overdue').status_code == 403


def test_08_absence_alerts_and_timetable_print():
    sid = add_student('V3-A1', 'Abu', 'Sent', 'JHS 2'); other = add_student('V3-A2', 'Ama', 'Here', 'JHS 2'); prim = add_student('V3-A3', 'Pri', 'Mary', 'Primary 2')
    t = Agent('v3_subject')
    for i in range(3):
        d = (TODAY - timedelta(days=i)).isoformat()
        assert t.module('attendance', student_id=str(sid), class_name='JHS 2', event_date=d, attendance_status='Absent').status_code == 302
    a = admin()
    for i in range(3):
        a.module('attendance', student_id=str(prim), class_name='Primary 2', event_date=(TODAY - timedelta(days=i)).isoformat(), attendance_status='Absent')
    a.module('attendance', student_id=str(other), class_name='JHS 2', event_date=TODAY.isoformat(), attendance_status='Absent')
    page = t.get('/reports/absence-alerts?days=14&minimum=3').data.decode()
    assert 'V3-A1' in page and 'V3-A2' not in page and 'V3-A3' not in page      # at the alert level; teacher sees JHS only
    assert 'V3-A3' in a.get('/reports/absence-alerts?days=14&minimum=3').data.decode()
    assert a.get('/reports/absence-alerts?days=0').status_code == 400
    # printable timetable
    lesson = dict(class_name='JHS 2', day='Monday', start_time='08:00', end_time='08:40', subject_name='Integrated Science', teacher_name='Mr Kofi', room='R9', academic_year='2026/2027', term='Term 1')
    assert t.module('timetable', **lesson).status_code == 302
    grid = t.get('/timetable/print?class_name=JHS+2').data.decode()
    assert 'Integrated Science' in grid and 'Mr Kofi' in grid and '08:00' in grid
    assert t.get('/timetable/print?class_name=Primary+2').status_code == 403


def test_09_admission_history_and_letter():
    a = admin()
    base = dict(applicant_name='Naa Applicant', requested_class='Primary 2', guardian_name='Mr Applicant', guardian_phone='0200000000', application_date=TODAY.isoformat(), application_status='Received')
    assert a.module('admissions', **base).status_code == 302
    with A.app.app_context():
        rid = A.db().execute("SELECT id FROM school_records WHERE module_key='admissions' AND title='Naa Applicant'").fetchone()['id']
    assert a.get(f'/modules/admissions/{rid}/letter', follow_redirects=True).data.decode().count('OFFER OF ADMISSION') == 0
    for status in ('Under review', 'Accepted'):
        assert a.post(f'/modules/admissions/{rid}/edit', dict(base, application_status=status, decision_notes=f'moved to {status}')).status_code == 302
    page = a.get(f'/modules/admissions/{rid}/history').data.decode()
    assert 'Received' in page and 'Under review' in page and 'Accepted' in page and 'moved to Accepted' in page
    letter = a.get(f'/modules/admissions/{rid}/letter').data.decode()
    assert 'OFFER OF ADMISSION' in letter and 'Naa Applicant' in letter and 'Primary 2' in letter
    assert Agent('v3_subject').get(f'/modules/admissions/{rid}/letter').status_code == 403


def test_10_backup_restore_round_trip_and_safeguards():
    a = admin()
    backup = a.get('/admin/backup'); assert backup.status_code == 200 and b'CREATE TABLE' in backup.data
    assert 'fr_joseph_connolly_backup_' in backup.headers['Content-Disposition']
    add_student('V3-RESTORE-ME', 'Temp', 'Student', 'Primary 4')
    # wrong confirmation, wrong type, garbage, non-admin
    assert b'RESTORE in the confirmation' in a.post('/admin/restore', {'confirm': 'no', 'backup_file': (io.BytesIO(backup.data), 'b.sql')}, content_type='multipart/form-data', follow_redirects=True).data
    assert b'valid school backup' in a.post('/admin/restore', {'confirm': 'RESTORE', 'backup_file': (io.BytesIO(b'this is not sql at all;'), 'bad.sql')}, content_type='multipart/form-data', follow_redirects=True).data
    assert b'valid school backup' in a.post('/admin/restore', {'confirm': 'RESTORE', 'backup_file': (io.BytesIO(b"ATTACH DATABASE '/tmp/x.db' AS x;"), 'evil.sql')}, content_type='multipart/form-data', follow_redirects=True).data
    with A.app.app_context(): assert A.db().execute("SELECT COUNT(*) n FROM students WHERE admission_no='V3-RESTORE-ME'").fetchone()['n'] == 1     # untouched
    assert Agent('v3_head').get('/admin/restore').status_code == 403
    res = a.post('/admin/restore', {'confirm': 'RESTORE', 'backup_file': (io.BytesIO(backup.data), 'good.sql')}, content_type='multipart/form-data')
    assert res.status_code == 302 and '/login' in res.headers['Location']
    with A.app.app_context():
        assert A.db().execute("SELECT COUNT(*) n FROM students WHERE admission_no='V3-RESTORE-ME'").fetchone()['n'] == 0    # rolled back to the backup
        assert A.db().execute("SELECT COUNT(*) n FROM users WHERE username='v3_admin'").fetchone()['n'] == 1
        assert A.db().execute("SELECT COUNT(*) n FROM audit_log WHERE action='restore'").fetchone()['n'] >= 1
    safety = Path(A.document_upload_dir()) / '_backups'
    assert safety.is_dir() and any(safety.glob('before_restore_*.sql'))
    assert Agent('v3_admin').get('/dashboard').status_code == 200
