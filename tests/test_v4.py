"""Version 4: SMS (Arkesel), email (SMTP) and mobile money (Paystack). A fake transport replaces the
network, so these tests never contact a provider."""
import hashlib, hmac, json
import integrations as INT
from test_v3 import A, Agent, Path, TODAY, add_student, add_user, admin  # noqa: F401

KEY = 'sk_test_fake_secret'
SENT = []


def setup_module():
    A.init_db()


def teardown_module():
    Path(A.DB_PATH).unlink(missing_ok=True)


def configure(monkeypatch, sms=True, mail=True, momo=True):
    for k in ('SMS_PROVIDER','ARKESEL_API_KEY','SMS_SENDER_ID','SMTP_HOST','SMTP_USER','SMTP_PASSWORD','MOMO_PROVIDER','PAYSTACK_SECRET_KEY','MOMO_FALLBACK_EMAIL'):
        monkeypatch.delenv(k, raising=False)
    if sms: monkeypatch.setenv('SMS_PROVIDER','arkesel'); monkeypatch.setenv('ARKESEL_API_KEY','ark-secret'); monkeypatch.setenv('SMS_SENDER_ID','HISGRACE')
    if mail: monkeypatch.setenv('SMTP_HOST','smtp.example.org'); monkeypatch.setenv('SMTP_USER','u@example.org'); monkeypatch.setenv('SMTP_PASSWORD','pw')
    if momo: monkeypatch.setenv('MOMO_PROVIDER','paystack'); monkeypatch.setenv('PAYSTACK_SECRET_KEY',KEY); monkeypatch.setenv('MOMO_FALLBACK_EMAIL','school@example.org')
    SENT.clear()
    state = {'verify': {'status': 'pending', 'amount': 0, 'currency': 'GHS'}}

    def fake(method, url, headers=None, body=None, timeout=20):
        SENT.append((method, url, headers, body))
        if 'arkesel' in url:
            return 200, {'status': 'success', 'data': [{'recipient': n, 'id': 'm' + n} for n in body['recipients']]}
        if url.endswith('/charge'):
            return 200, {'status': True, 'data': {'status': 'pay_offline', 'display_text': 'Approve on your phone'}}
        if '/transaction/verify/' in url:
            v = state['verify']
            return 200, {'status': True, 'data': {'status': v['status'], 'amount': v['amount'], 'currency': v['currency']}}
        return 404, {}
    monkeypatch.setattr(INT, 'http_request', fake)
    return state


class FakeSMTP:
    sent = []
    def __init__(self, *a, **k): pass
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def starttls(self, **k): pass
    def login(self, u, p): pass
    def send_message(self, m): FakeSMTP.sent.append(m)


def test_phone_helpers():
    assert INT.normalize_phone('0244 123 456') == '233244123456'
    assert INT.normalize_phone('+233201234567') == '233201234567'
    assert INT.normalize_phone('12345') is None and INT.normalize_phone('0100000000') is None
    assert INT.network_of('233244123456') == 'mtn' and INT.network_of('233201234567') == 'vod' and INT.network_of('233271234567') == 'atl'


def test_off_by_default_and_status_hides_secrets(monkeypatch):
    configure(monkeypatch, False, False, False)
    st = INT.status()
    assert not st['sms']['ready'] and not st['email']['ready'] and not st['momo']['ready']
    a = admin(); assert a.get('/communications').status_code == 200
    configure(monkeypatch)
    page = a.get('/admin/integrations').get_data(as_text=True)
    assert 'ark-secret' not in page and KEY not in page and 'HISGRACE' in page and '/webhooks/paystack' in page


def test_roles_for_new_pages(monkeypatch):
    configure(monkeypatch)
    add_user('v4_teacher', 'Class Teacher', 'JHS 1'); t = Agent('v4_teacher')
    for p in ('/communications', '/communications/log', '/admin/integrations', '/fees/mobile-money'): assert t.get(p).status_code == 403, p
    add_user('v4_acc', 'Accountant'); ac = Agent('v4_acc')
    assert ac.get('/fees/mobile-money').status_code == 200 and ac.get('/communications').status_code == 403


def test_send_sms_to_class_dedupes_parents(monkeypatch):
    configure(monkeypatch)
    a = admin()
    with A.app.app_context():
        c = A.db()
        for n, (adm, f) in enumerate((('V4-001', 'Ama'), ('V4-002', 'Kofi'))):
            add_student(adm, f, 'Mensah', 'JHS 2')
        c.execute("UPDATE students SET guardian_phone='0244777888' WHERE admission_no IN ('V4-001','V4-002')"); c.commit()
    r = a.post('/communications', {'audience': 'class', 'class_name': 'JHS 2', 'channel': 'sms', 'message': 'Hello {guardian}, {student} in {class}.', 'action': 'preview'})
    assert b'with a valid phone' in r.data
    r = a.post('/communications', {'audience': 'class', 'class_name': 'JHS 2', 'channel': 'sms', 'message': 'Hello {guardian}, {student} in {class}.', 'action': 'send'})
    assert not SENT  # not confirmed
    r = a.post('/communications', {'audience': 'class', 'class_name': 'JHS 2', 'channel': 'sms', 'message': 'Hello {guardian}, {student} in {class}.', 'action': 'send', 'confirm': 'yes'})
    assert SENT and SENT[0][1].endswith('/sms/send') and SENT[0][2]['api-key'] == 'ark-secret'
    mine = [b for b in SENT if '233244777888' in b[3]['recipients']]
    assert len(mine) == 1 and mine[0][3]['recipients'].count('233244777888') == 1 and 'Ama Mensah and Kofi Mensah' in mine[0][3]['message']
    log = a.get('/communications/log').get_data(as_text=True)
    assert '233244777888' in log and 'ark-secret' not in log


def test_send_email_and_failure_logged(monkeypatch):
    configure(monkeypatch)
    monkeypatch.setattr(INT.smtplib, 'SMTP', FakeSMTP); FakeSMTP.sent.clear()
    a = admin()
    with A.app.app_context():
        add_student('V4-010', 'Esi', 'Boateng', 'JHS 3'); c = A.db()
        c.execute("UPDATE students SET guardian_email='parent@example.org' WHERE admission_no='V4-010'"); c.commit()
    sid10 = None
    with A.app.app_context(): sid10 = A.db().execute("SELECT id FROM students WHERE admission_no='V4-010'").fetchone()['id']
    a.post('/communications', {'audience': 'student', 'student_id': sid10, 'channel': 'email', 'subject': 'Hi {student}', 'message': 'Note for {guardian}', 'action': 'send', 'confirm': 'yes'})
    assert len(FakeSMTP.sent) == 1 and FakeSMTP.sent[0]['To'] == 'parent@example.org'
    assert FakeSMTP.sent[0]['Subject'] == 'Hi Esi Boateng'
    class Boom(FakeSMTP):
        def login(self, u, p): raise INT.smtplib.SMTPAuthenticationError(535, b'no')
    monkeypatch.setattr(INT.smtplib, 'SMTP', Boom)
    a.post('/communications', {'audience': 'student', 'student_id': sid10, 'channel': 'email', 'subject': 'x', 'message': 'y', 'action': 'send', 'confirm': 'yes'})
    assert 'Failed' in a.get('/communications/log?status=Failed').get_data(as_text=True)


def test_blocked_when_channel_not_configured(monkeypatch):
    configure(monkeypatch, sms=False)
    a = admin()
    r = a.post('/communications', {'audience': 'staff', 'channel': 'sms', 'message': 'x', 'action': 'send', 'confirm': 'yes'})
    assert b'SMS is not switched on' in r.data and not SENT


def test_receipt_sms_does_not_block_payment(monkeypatch):
    configure(monkeypatch)
    a = admin()
    sid = add_student('V4-020', 'Yaw', 'Asare', 'JHS 1')
    r = a.post(f'/fees/new/{sid}', {'amount': '50', 'payment_date': TODAY.isoformat(), 'payment_method': 'Cash', 'purpose': 'Tuition', 'sms_receipt': 'yes'})
    assert r.status_code == 302 and SENT and 'Receipt' in SENT[-1][3]['message']
    def boom(*a, **k): raise INT.IntegrationError('down')
    monkeypatch.setattr(INT, 'http_request', boom)
    r = a.post(f'/fees/new/{sid}', {'amount': '5', 'payment_date': TODAY.isoformat(), 'payment_method': 'Cash', 'purpose': 'Tuition', 'sms_receipt': 'yes'})
    assert r.status_code == 302
    with A.app.app_context(): assert A.db().execute('SELECT COUNT(*) n FROM fees WHERE student_id=?', (sid,)).fetchone()['n'] == 2


def make_invoice(sid, amount=200.0):
    with A.app.app_context():
        c = A.db(); inv = f'INV-V4-{sid}-{secrets_hex()}'
        c.execute('INSERT INTO fee_invoices(invoice_no,student_id,academic_year,term,description,amount,discount,due_date,created_by) VALUES(?,?,?,?,?,?,?,?,?)',
                  (inv, sid, '2026/2027', 'Term 1', 'Tuition', amount, 0, TODAY.isoformat(), 1)); c.commit()
        return inv


def secrets_hex():
    import secrets; return secrets.token_hex(3)


def parent_for(sid, name):
    uid = add_user(name, 'Parent/Guardian', student_id=sid)
    with A.app.app_context():
        A.db().execute('INSERT OR IGNORE INTO parent_children(user_id,student_id) VALUES(?,?)', (uid, sid)); A.db().commit()
    return Agent(name)


def test_momo_full_flow_webhook_idempotent(monkeypatch):
    configure(monkeypatch)
    sid = add_student('V4-030', 'Abena', 'Owusu', 'JHS 1'); inv = make_invoice(sid, 200)
    p = parent_for(sid, 'v4_parent1')
    r = p.post('/portal/pay', {'student_id': sid, 'invoice_no': inv, 'amount': '80', 'phone': '0244123456'}, follow_redirects=True)
    assert b'Approve on your phone' in r.data
    charge = [s for s in SENT if s[1].endswith('/charge')][-1]
    assert charge[3]['amount'] == 8000 and charge[3]['currency'] == 'GHS' and charge[3]['mobile_money'] == {'phone': '0244123456', 'provider': 'mtn'}
    ref = charge[3]['reference']
    # second request while one is waiting is refused
    r = p.post('/portal/pay', {'student_id': sid, 'invoice_no': inv, 'amount': '10', 'phone': '0244123456'}, follow_redirects=True)
    assert b'already waiting' in r.data
    body = json.dumps({'event': 'charge.success', 'data': {'reference': ref, 'amount': 8000, 'currency': 'GHS'}}).encode()
    c = A.app.test_client()
    assert c.post('/webhooks/paystack', data=body, headers={'X-Paystack-Signature': 'bad'}).status_code == 401
    sig = hmac.new(KEY.encode(), body, hashlib.sha512).hexdigest()
    for _ in range(2):  # delivered twice
        assert c.post('/webhooks/paystack', data=body, headers={'X-Paystack-Signature': sig}).status_code == 200
    with A.app.app_context():
        rows = A.db().execute("SELECT * FROM fees WHERE student_id=? AND payment_method='Mobile Money'", (sid,)).fetchall()
        assert len(rows) == 1 and rows[0]['amount'] == 80 and rows[0]['purpose'] == inv
    page = p.get(f'/portal?student_id={sid}').get_data(as_text=True)
    assert 'Success' in page


def test_momo_amount_mismatch_not_recorded(monkeypatch):
    configure(monkeypatch)
    sid = add_student('V4-040', 'Kojo', 'Ntim', 'JHS 1'); inv = make_invoice(sid, 100)
    p = parent_for(sid, 'v4_parent2')
    p.post('/portal/pay', {'student_id': sid, 'invoice_no': inv, 'amount': '60', 'phone': '0551234567'})
    ref = [s for s in SENT if s[1].endswith('/charge')][-1][3]['reference']
    body = json.dumps({'event': 'charge.success', 'data': {'reference': ref, 'amount': 100, 'currency': 'GHS'}}).encode()
    sig = hmac.new(KEY.encode(), body, hashlib.sha512).hexdigest()
    A.app.test_client().post('/webhooks/paystack', data=body, headers={'X-Paystack-Signature': sig})
    with A.app.app_context():
        assert A.db().execute("SELECT COUNT(*) n FROM fees WHERE student_id=?", (sid,)).fetchone()['n'] == 0
        assert A.db().execute('SELECT status FROM momo_payments WHERE reference=?', (ref,)).fetchone()['status'] == 'Mismatch'


def test_momo_check_status_verifies_with_provider(monkeypatch):
    state = configure(monkeypatch)
    sid = add_student('V4-050', 'Efua', 'Tetteh', 'JHS 2'); inv = make_invoice(sid, 150)
    p = parent_for(sid, 'v4_parent3')
    p.post('/portal/pay', {'student_id': sid, 'invoice_no': inv, 'amount': '150', 'phone': '0201234567'})
    with A.app.app_context(): mid = A.db().execute('SELECT id FROM momo_payments WHERE student_id=?', (sid,)).fetchone()['id']
    r = p.post(f'/portal/pay/{mid}/check', follow_redirects=True); assert b'Still waiting' in r.data
    state['verify'] = {'status': 'success', 'amount': 15000, 'currency': 'GHS'}
    r = p.post(f'/portal/pay/{mid}/check', follow_redirects=True); assert b'Payment confirmed' in r.data
    with A.app.app_context(): assert A.db().execute("SELECT COUNT(*) n FROM fees WHERE student_id=? AND payment_method='Mobile Money'", (sid,)).fetchone()['n'] == 1


def test_momo_guards(monkeypatch):
    configure(monkeypatch)
    s1 = add_student('V4-060', 'A', 'One', 'JHS 1'); s2 = add_student('V4-061', 'B', 'Two', 'JHS 1')
    inv2 = make_invoice(s2, 100); inv1 = make_invoice(s1, 100)
    p = parent_for(s1, 'v4_parent4')
    assert p.post('/portal/pay', {'student_id': s2, 'invoice_no': inv2, 'amount': '10', 'phone': '0244123456'}).status_code == 403
    for data, msg in (({'invoice_no': inv2, 'amount': '10'}, b'Choose one of the invoices'), ({'invoice_no': inv1, 'amount': '500'}, b'Enter an amount'),
                      ({'invoice_no': inv1, 'amount': '10', 'phone': '123'}, b'valid Ghana mobile')):
        d = {'student_id': s1, 'phone': '0244123456'}; d.update(data)
        assert msg in p.post('/portal/pay', d, follow_redirects=True).data
    assert not [s for s in SENT if s[1].endswith('/charge')]
    # a teacher cannot use the portal pay route
    add_user('v4_t2', 'Class Teacher', 'JHS 1')
    assert Agent('v4_t2').post('/portal/pay', {'student_id': s1}).status_code == 403


def test_absence_sms_respects_class_scope(monkeypatch):
    configure(monkeypatch)
    s = add_student('V4-070', 'Z', 'Zed', 'JHS 3')
    add_user('v4_t3', 'Class Teacher', 'JHS 1'); t = Agent('v4_t3')
    assert t.post(f'/reports/absence-alerts/{s}/sms', {}).status_code == 403
    assert admin().post(f'/reports/absence-alerts/{s}/sms', {'last': TODAY.isoformat()}).status_code == 302 and SENT
