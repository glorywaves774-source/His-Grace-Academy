# Setting up SMS, email and mobile money

Everything is OFF until you add the settings below to the server's environment (or `.env`). Restart the app afterwards.
Open **Integrations** (Administrator menu) to see what is ready and to send a test. Keys are never shown in the app and never stored in the database.

## 1. SMS (Arkesel)
1. Create an Arkesel account and copy the **API key** (v2).
2. Register a **sender name** of up to 11 letters/digits (e.g. `FJCSCHOOL`) and wait for approval.
3. Set `SMS_PROVIDER=arkesel`, `ARKESEL_API_KEY`, `SMS_SENDER_ID`.
4. Integrations → send a test SMS to your own phone.

## 2. Email (SMTP)
Set `SMTP_HOST`, `SMTP_PORT` (587 with `SMTP_SECURITY=starttls`, or 465 with `ssl`), `SMTP_USER`, `SMTP_PASSWORD`, optionally `SMTP_FROM`. For Gmail use an app password. Send a test from Integrations.

## 3. Mobile money (Paystack)
1. Create a Paystack Ghana account with mobile money enabled. Start with the **test** secret key.
2. Set `MOMO_PROVIDER=paystack`, `PAYSTACK_SECRET_KEY`, and `MOMO_FALLBACK_EMAIL` (Paystack needs an email; this is used when a guardian has none).
3. In the Paystack dashboard (Settings → API Keys & Webhooks) set the webhook URL to `https://YOUR-DOMAIN/webhooks/paystack`. The page under Integrations shows the exact address. The site must be on HTTPS and reachable from the internet.
4. Make a small test payment from a parent account, then switch to the live key.

How a payment works: a parent picks an unpaid invoice in the portal and enters their mobile money number. Paystack asks them to approve on the phone. When it succeeds, Paystack calls the webhook (or someone presses *Check status* / *Verify now*), the system confirms the amount (GHS, exact pesewas) and records a normal receipt once, even if notified twice. A mismatch is never recorded; it shows as *Mismatch* under Fees → Mobile money.

## 4. Daily backup by e-mail (encrypted)
Once SMTP (section 2) works, add two settings:
- `BACKUP_EMAIL_TO=glorywaves774@gmail.com`
- `BACKUP_ZIP_PASSWORD=` a long passphrase (12+ characters). **Write it down somewhere safe: without it the backups cannot be opened, and it is not stored anywhere in the system.**

Each day the system makes its backup and e-mails it as an AES-256 password-protected zip. Unencrypted backups are never e-mailed: without the password setting, nothing is sent. Open the zip with 7-Zip or WinZip. Integrations -> "Backup by e-mail" shows the last send and any problem, and "Send a backup now" tests it. Backups over 20 MB cannot be e-mailed (Gmail's limit); the page then tells you to download one manually.

Gmail as the sender: set `SMTP_HOST=smtp.gmail.com`, `SMTP_PORT=587`, `SMTP_USER` to the Gmail address and `SMTP_PASSWORD` to a Gmail **app password** (Google Account -> Security -> 2-Step Verification -> App passwords), not the normal password.

## Using messages
- **Send messages**: pick the audience (a class, all guardians, guardians with unpaid fees, one student, or staff), preview, tick the confirmation and send. Up to 500 people at a time; a parent with several children gets one message. Placeholders: `{student} {guardian} {class} {balance} {school}`.
- **Announcements** have a "Send as SMS/email" link. **Absence alerts** have an "SMS guardian" button. **Record payment** has a "send receipt SMS" tick box (a failed SMS never blocks the payment).
- **Message log** (Administrator, Headteacher) lists every message and any provider error.

## Not yet proven
These connections were tested only with simulated providers. Before relying on them, try each with the school's own accounts (test SMS, test email, a small test payment).
