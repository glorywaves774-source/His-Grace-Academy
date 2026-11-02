"""Printable fee invoice and one-page-per-pupil report cards."""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_v3 import A, PW, setup_module, teardown_module, add_user, add_student, Agent  # noqa: F401


def seed():
    s1 = add_student('DOC1', 'Ama', 'Docone', 'JHS 2'); s2 = add_student('DOC2', 'Kofi', 'Doctwo', 'JHS 2')
    with A.app.app_context():
        c = A.db()
        if c.execute("SELECT 1 FROM fee_invoices WHERE invoice_no='DOC-INV-1'").fetchone(): return s1, s2
        c.execute("INSERT INTO fee_invoices(invoice_no,student_id,academic_year,term,description,amount,discount,due_date) VALUES('DOC-INV-1',?,'2030/2031','Term 1','Tuition and PTA levy',1000,100,'2030-09-30')", (s1,))
        c.execute("INSERT INTO fees(receipt_no,student_id,amount,payment_date,payment_method,purpose,received_by) VALUES('DOC-R-1',?,400,'2030-09-10','Cash','DOC-INV-1','Bursar')", (s1,))
        c.execute("INSERT INTO school_records(module_key,title,payload_json,status) VALUES('terms','t1',?,'Recorded')", (json.dumps({'academic_year': '2030/2031', 'term': 'Term 1', 'term_status': 'Upcoming', 'start_date': '2030-09-01', 'end_date': '2030-12-15'}),))
        c.execute("INSERT INTO school_records(module_key,title,payload_json,status) VALUES('terms','t2',?,'Recorded')", (json.dumps({'academic_year': '2030/2031', 'term': 'Term 2', 'term_status': 'Upcoming', 'start_date': '2031-01-12', 'end_date': '2031-04-01'}),))
        for sid, sc in ((s1, 80), (s2, 60)):
            c.execute("INSERT INTO school_records(module_key,title,payload_json,student_id,class_name,event_date) VALUES('assessments','Mathematics',?,?,'JHS 2','2030-10-05')", (json.dumps({'subject_name': 'Mathematics', 'academic_year': '2030/2031', 'term': 'Term 1', 'score': sc, 'maximum_score': 100, 'teacher_comment': 'Well done'}), sid))
        for i, st in enumerate(['Present', 'Present', 'Late', 'Absent']):
            c.execute("INSERT INTO school_records(module_key,title,payload_json,student_id,class_name,event_date) VALUES('attendance','a',?,?,'JHS 2',?)", (json.dumps({'attendance_status': st}), s1, f'2030-10-0{i+1}'))
        c.execute("INSERT INTO school_records(module_key,title,payload_json,student_id,class_name,event_date) VALUES('attendance','a',?,?,'JHS 2','2031-02-02')", (json.dumps({'attendance_status': 'Absent'}), s1))  # other term: not counted
        c.commit()
    return s1, s2


def test_invoice_document_shows_totals_payments_and_balance():
    s1, _ = seed(); add_user('doc_acct', 'Accountant'); ag = Agent('doc_acct')
    with A.app.app_context(): iid = A.db().execute("SELECT id FROM fee_invoices WHERE invoice_no='DOC-INV-1'").fetchone()['id']
    html = ag.get(f'/invoices/{iid}/print').get_data(as_text=True)
    assert 'FEE INVOICE' in html and 'DOC-INV-1' in html and 'Docone' in html
    assert '1000.00' in html and '-100.00' in html and '900.00' in html and '-400.00' in html and 'GH₵ 500.00' in html
    assert 'DOC-R-1' in html and 'Balance to pay' in html
    assert f'/invoices/{iid}/print' in ag.get('/invoices').get_data(as_text=True)


def test_invoice_document_is_restricted_and_404s():
    add_user('doc_teacher', 'Teacher'); t = Agent('doc_teacher')
    assert t.get('/invoices/1/print').status_code in (302, 403)
    add_user('doc_acct2', 'Accountant'); assert Agent('doc_acct2').get('/invoices/999999/print').status_code == 404


def test_report_cards_one_sheet_per_pupil_with_attendance_fees_and_next_term():
    seed(); add_user('doc_head', 'Headteacher'); ag = Agent('doc_head')
    html = ag.get('/reports/report-cards?class_name=JHS+2&academic_year=2030/2031&term=Term+1').get_data(as_text=True)
    assert html.count('class="doc-sheet report-sheet"') == 2
    assert 'TERMLY REPORT CARD' in html and "Class teacher's remarks" in html and 'data-print-card' in html
    assert '2 present · 1 late · 1 absent' in html          # the February absence belongs to another term
    assert 'GH₵ 500.00' in html                              # outstanding fees for the first pupil
    assert '2031-01-12' in html                              # next term opens
    assert 'Position in class' in html and '1 of 2' in html and '2 of 2' in html
