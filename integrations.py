"""Connections to outside services: SMS (Arkesel), email (SMTP) and mobile money (Paystack).

Everything here is OFF until the school sets the matching environment settings. Secrets are read
from the environment only and are never written to the database, the audit log or the message log.
All web calls go through http_request(), so tests (and any future provider) can replace it.

SMS        SMS_PROVIDER=arkesel  ARKESEL_API_KEY  SMS_SENDER_ID (up to 11 letters/digits, registered with Arkesel)
Email      SMTP_HOST SMTP_PORT SMTP_USER SMTP_PASSWORD SMTP_FROM SMTP_SECURITY=starttls|ssl|none
Mobile     MOMO_PROVIDER=paystack  PAYSTACK_SECRET_KEY  MOMO_FALLBACK_EMAIL (used when a guardian has no email)
"""
import hashlib
import hmac
import json
import os
import re
import smtplib
import ssl
import urllib.error
import urllib.request
from email.message import EmailMessage


class IntegrationError(Exception):
    """A provider refused or failed. The message is safe to show to staff."""


class NotConfigured(IntegrationError):
    """The service has not been switched on."""


def _env(name, default=''):
    return os.environ.get(name, default).strip()


# ----------------------------------------------------------------------------- phone numbers
GHANA_MOBILE_CODES = {'20', '23', '24', '25', '26', '27', '28', '50', '53', '54', '55', '56', '57', '58', '59'}
NETWORK_BY_CODE = {'24': 'mtn', '25': 'mtn', '53': 'mtn', '54': 'mtn', '55': 'mtn', '59': 'mtn',
                   '20': 'vod', '50': 'vod',
                   '26': 'atl', '27': 'atl', '56': 'atl', '57': 'atl'}
NETWORK_NAMES = {'mtn': 'MTN MoMo', 'vod': 'Telecel Cash', 'atl': 'AT Money'}


def normalize_phone(raw):
    """Return a Ghana mobile number as 233XXXXXXXXX, or None when it is not a valid mobile number."""
    digits = re.sub(r'[\s\-().]', '', str(raw or ''))
    if digits.startswith('+'): digits = digits[1:]
    if digits.startswith('00'): digits = digits[2:]
    if digits.startswith('233') and len(digits) == 12: pass
    elif digits.startswith('0') and len(digits) == 10: digits = '233' + digits[1:]
    elif len(digits) == 9: digits = '233' + digits
    else: return None
    if not digits.isdigit() or digits[3:5] not in GHANA_MOBILE_CODES: return None
    return digits


def local_phone(msisdn):
    return '0' + msisdn[3:]


def network_of(msisdn):
    return NETWORK_BY_CODE.get(msisdn[3:5]) if msisdn else None


def valid_email(address):
    address = str(address or '').strip()
    return bool(re.fullmatch(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(\.[A-Za-z0-9\-]+)+", address)) and len(address) <= 254


def sms_segments(text):
    """Rough number of SMS parts. Plain text is 160 characters (153 when joined); other characters use 70 (67)."""
    n = len(text)
    plain = all(ord(c) < 128 for c in text)
    single, multi = (160, 153) if plain else (70, 67)
    return 1 if n <= single else -(-n // multi)


# ----------------------------------------------------------------------------- web calls
def http_request(method, url, headers=None, body=None, timeout=20):
    """Send one web request and return (status_code, parsed_json_or_text). Replaced in tests."""
    data = json.dumps(body).encode('utf-8') if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=dict(headers or {}))
    if data is not None: req.add_header('Content-Type', 'application/json')
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw, status = resp.read().decode('utf-8', 'replace'), resp.status
    except urllib.error.HTTPError as exc:
        raw, status = exc.read().decode('utf-8', 'replace'), exc.code
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise IntegrationError('Could not reach the provider. Check the internet connection and try again.') from exc
    try: return status, json.loads(raw)
    except ValueError: return status, raw


# ----------------------------------------------------------------------------- status
def status():
    """What is switched on and what is still missing. Never returns secret values."""
    sms_missing = [n for n, v in (('SMS_PROVIDER=arkesel', _env('SMS_PROVIDER').lower() == 'arkesel'), ('ARKESEL_API_KEY', _env('ARKESEL_API_KEY')), ('SMS_SENDER_ID', _env('SMS_SENDER_ID'))) if not v]
    mail_missing = [n for n in ('SMTP_HOST', 'SMTP_USER', 'SMTP_PASSWORD') if not _env(n)]
    momo_missing = [n for n, v in (('MOMO_PROVIDER=paystack', _env('MOMO_PROVIDER').lower() == 'paystack'), ('PAYSTACK_SECRET_KEY', _env('PAYSTACK_SECRET_KEY'))) if not v]
    return {'sms': {'ready': not sms_missing, 'missing': sms_missing, 'provider': 'Arkesel', 'sender': _env('SMS_SENDER_ID')},
            'email': {'ready': not mail_missing, 'missing': mail_missing, 'provider': 'SMTP', 'host': _env('SMTP_HOST'), 'from': _env('SMTP_FROM') or _env('SMTP_USER')},
            'momo': {'ready': not momo_missing, 'missing': momo_missing, 'provider': 'Paystack', 'fallback_email': bool(_env('MOMO_FALLBACK_EMAIL'))}}


# ----------------------------------------------------------------------------- SMS (Arkesel)
ARKESEL_URL = 'https://sms.arkesel.com/api/v2/sms/send'


def send_sms(pairs):
    """pairs: list of (msisdn, message). Identical messages are sent together.
    Returns a list of dicts {recipient, ok, ref, error} in the same order."""
    if not status()['sms']['ready']: raise NotConfigured('SMS is not switched on. Add the Arkesel settings first.')
    results = [None] * len(pairs)
    groups = {}
    for i, (number, message) in enumerate(pairs): groups.setdefault(message, []).append((i, number))
    for message, members in groups.items():
        for start in range(0, len(members), 100):
            chunk = members[start:start + 100]
            body = {'sender': _env('SMS_SENDER_ID')[:11], 'message': message, 'recipients': [n for _, n in chunk]}
            try:
                code, data = http_request('POST', ARKESEL_URL, {'api-key': _env('ARKESEL_API_KEY')}, body)
                ok = code == 200 and isinstance(data, dict) and str(data.get('status', '')).lower() == 'success'
                error = '' if ok else (str(data.get('message', ''))[:200] if isinstance(data, dict) else f'Provider answered {code}')
                refs = {str(d.get('recipient')): str(d.get('id', '')) for d in (data.get('data') or []) if isinstance(d, dict)} if ok and isinstance(data, dict) and isinstance(data.get('data'), list) else {}
            except IntegrationError as exc:
                ok, error, refs = False, str(exc), {}
            for i, number in chunk:
                results[i] = {'recipient': number, 'ok': ok, 'ref': refs.get(number, ''), 'error': error or ('' if ok else 'Not sent')}
    return results


# ----------------------------------------------------------------------------- email (SMTP)
def send_email(to, subject, text, attachment=None):
    """attachment: optional (filename, bytes, mime_type)."""
    if not status()['email']['ready']: raise NotConfigured('Email is not switched on. Add the SMTP settings first.')
    if not valid_email(to): raise IntegrationError('That email address is not valid.')
    sender = _env('SMTP_FROM') or _env('SMTP_USER')
    msg = EmailMessage()
    msg['From'], msg['To'], msg['Subject'] = sender, to, re.sub(r'[\r\n]+', ' ', subject)[:200]
    msg.set_content(text)
    if attachment:
        name, data, mime = attachment
        maintype, _, subtype = mime.partition('/')
        msg.add_attachment(data, maintype=maintype, subtype=subtype or 'octet-stream', filename=name)
    host, port, security = _env('SMTP_HOST'), int(_env('SMTP_PORT', '587') or 587), (_env('SMTP_SECURITY', 'starttls') or 'starttls').lower()
    try:
        if security == 'ssl':
            smtp = smtplib.SMTP_SSL(host, port, timeout=20, context=ssl.create_default_context())
        else:
            smtp = smtplib.SMTP(host, port, timeout=20)
        with smtp:
            if security == 'starttls': smtp.starttls(context=ssl.create_default_context())
            smtp.login(_env('SMTP_USER'), _env('SMTP_PASSWORD'))
            smtp.send_message(msg)
    except (smtplib.SMTPException, OSError) as exc:
        raise IntegrationError(f'The email was not sent ({type(exc).__name__}). Check the SMTP settings.') from exc
    return True


def backup_email_status():
    """Settings for e-mailing the daily encrypted backup. Never returns the password."""
    to = _env('BACKUP_EMAIL_TO')
    missing = []
    if not valid_email(to): missing.append('BACKUP_EMAIL_TO')
    if len(_env('BACKUP_ZIP_PASSWORD')) < 12: missing.append('BACKUP_ZIP_PASSWORD (at least 12 characters)')
    missing += [n for n in status()['email']['missing']]
    return {'ready': not missing, 'missing': missing, 'to': to}


# ----------------------------------------------------------------------------- mobile money (Paystack)
PAYSTACK = 'https://api.paystack.co'


def _paystack_headers():
    if not status()['momo']['ready']: raise NotConfigured('Mobile money is not switched on. Add the Paystack settings first.')
    return {'Authorization': 'Bearer ' + _env('PAYSTACK_SECRET_KEY')}


def momo_charge(reference, amount_cedis, msisdn, email, network=None):
    """Ask the payer's phone to approve a payment. Returns {status, message}.
    status is 'pending' (approve on the phone), 'otp' (provider wants a code), 'success' or 'failed'."""
    network = network or network_of(msisdn)
    if network not in NETWORK_NAMES: raise IntegrationError('Choose the mobile money network for this number.')
    body = {'email': email, 'amount': int(round(float(amount_cedis) * 100)), 'currency': 'GHS', 'reference': reference,
            'mobile_money': {'phone': local_phone(msisdn), 'provider': network}}
    code, data = http_request('POST', PAYSTACK + '/charge', _paystack_headers(), body)
    if not isinstance(data, dict) or not data.get('status'):
        raise IntegrationError((str(data.get('message', ''))[:200] if isinstance(data, dict) else f'The provider answered {code}.') or 'The payment request was refused.')
    info = data.get('data') or {}
    state = str(info.get('status', '')).lower()
    mapped = {'pay_offline': 'pending', 'pending': 'pending', 'send_otp': 'otp', 'success': 'success', 'failed': 'failed'}.get(state, 'pending')
    return {'status': mapped, 'message': str(info.get('display_text') or data.get('message') or '')[:300]}


def momo_verify(reference):
    """Ask the provider what happened to a payment. Returns {status, amount_pesewas, currency}."""
    code, data = http_request('GET', PAYSTACK + '/transaction/verify/' + urllib.request.quote(reference, safe=''), _paystack_headers())
    if not isinstance(data, dict) or not data.get('status'):
        raise IntegrationError('The provider could not confirm this payment yet.')
    info = data.get('data') or {}
    return {'status': str(info.get('status', '')).lower(), 'amount_pesewas': int(info.get('amount') or 0), 'currency': str(info.get('currency', ''))}


def webhook_signature_ok(raw_body, header_value):
    key = _env('PAYSTACK_SECRET_KEY')
    if not key or not header_value: return False
    expected = hmac.new(key.encode('utf-8'), raw_body, hashlib.sha512).hexdigest()
    return hmac.compare_digest(expected, str(header_value).strip().lower())
