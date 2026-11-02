# Security and release checklist

The following controls exist in the current code: password hashing, CSRF token checks on POST requests, a per-username sign-in lockout, HTTP-only and SameSite session cookies, optional Secure cookies, password rotation for new accounts, role decorators on protected routes, class scoping for class/subject teachers, no-store cache headers on authenticated responses, basic audit logging, and a database uniqueness constraint on admission numbers.

These controls are not a substitute for independent security review. Before real student data is entered:

- Install dependencies and run `pytest -q` in a clean environment.
- Test direct URL access for every role, including disabled and suspended users.
- Verify reverse proxy HTTPS settings and set `COOKIE_SECURE=1`.
- Set `APP_ENV=production` and a persistent random `SECRET_KEY`.
- Confirm the database file and backup downloads are protected by OS permissions.
- Configure encrypted off-site backups and test a restore to a separate database.
- Verify every report/export includes only the permitted records and fields for the signed-in role.
- Complete parent/child and student/account linking before creating parent or student portal accounts.
- Complete privacy, data-retention, safeguarding, and operational sign-off with school leadership.

## Version 5 hardening (built in and tested)

- Strict Content-Security-Policy (no inline scripts), HSTS when cookies are Secure, clickjacking and MIME-sniffing protection, cross-origin isolation headers.
- Production start-up refuses a missing or short `SECRET_KEY` (32+ characters) and refuses debug mode. Secure cookies are on by default in production.
- Constant-time sign-in (no hint whether a username exists); changing a password signs out every older session for that account.
- Friendly error pages for 400/403/404/405/413/500; internal details are logged, never shown. One failing request cannot stop the service.
- Uploaded documents must really be the type they claim (a program renamed to .pdf is refused); photographs are re-encoded and size-limited; decompression bombs refused.
- Exported spreadsheets neutralise formulas typed into text fields.
- The database runs in WAL mode, is structurally checked at start-up, and an automatic consistent copy is made once a day (newest 14 kept) in the `backups` folder (set `SCHOOL_BACKUP_DIR`, ideally on the same persistent disk). Keep an off-site copy too: download the backup from the Administrator menu regularly.
- Dependencies were audited with pip-audit / npm audit and had no known vulnerabilities on the build date. Re-run them before every release.
- Backups e-mailed off the server are always AES-256 encrypted; with no `BACKUP_ZIP_PASSWORD` nothing is sent. The passphrase is kept only in the server settings.
