# Fr. Joseph Connolly SVD Memorial School Management System

Official name: Fr. Joseph Connolly SVD Memorial School  
Slogan: Faith • Knowledge • Service  
Location reference: Saboba, Northern Region, Ghana  
Currency: Ghana cedi (GHS)

This repository contains a Flask application backed by SQLite. It uses a shared database for student records, fee receipts, accounts, audit events, and the integrated operational registers. It is a staged implementation. Do not treat it as a production-ready release until the test and deployment checklist passes.

## Run locally on Windows

1. Install Python 3.10 or newer.
2. Extract this ZIP.
3. Open PowerShell in the `kings_gate_school` folder.
4. Run:

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
$env:SECRET_KEY = (python -c "import secrets; print(secrets.token_hex(32))")
python app.py
```

Open `http://127.0.0.1:5000`.

macOS/Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
export SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"
python app.py
```

The SQLite database defaults to `school.db` inside the project. Set `SCHOOL_DB` to a full path outside the source directory for deployments. The built-in Flask server is for local testing only.

## Online deployment

For an online deployment with a persistent database and private document storage, follow `DEPLOY_ONLINE.md`. The included `render.yaml` configures a Render web service with a persistent disk, HTTPS cookies, generated secret key, health check, and a required initial administrator password. The persistent disk is a paid feature. Do not use a free ephemeral filesystem for school records. The service has not been deployed or runtime-tested from this environment.

## Initial local account

Username: `admin`  
Temporary password: `ChangeMe123!`

The account must change its password on first login. Change it immediately and never deploy the default credentials. The app requires `SECRET_KEY` when `APP_ENV=production`. Enable secure cookies behind HTTPS with `COOKIE_SECURE=1`.

## Current operational features

- Login with password hashing, account lockout, session expiry, CSRF checks on POST, security headers and forced initial password rotation.
- Server-side role checks and class-scoped access for class/subject teachers on supported registers.
- Student registration, unique admission number generation, guardian/emergency details, class assignment, profile viewing/editing, search and filters.
- Classes: Daycare, KG 1, KG 2, Primary 1 to 6, and JHS 1 to 3.
- Database-derived student dashboard summaries, class/gender/status charts and recent records.
- Student directory CSV, XLSX and PDF exports. CSV formula prefixes are protected.
- CSV/XLSX import with preview, row validation, duplicate checks and confirmation.
- User creation/suspension and forced temporary password changes.
- Payment receipt entries with unique receipt numbers and printable HTML receipts. Fee invoices, discounts, invoice-linked payments and outstanding balance calculations are now included. Payments apply to an invoice when the invoice number is selected at payment entry.
- Administrator SQL backup download.
- Parent accounts support multiple linked children, with portal child selection checked against the school-managed relationship table.
- Basic report-card summaries aggregate assessment percentages by subject and support class, year and term filters. Default grade bands must be approved by school management before official use.
- Private document upload and authorised download for selected file types, stored outside the public static directory.
- Timetable conflict checks cover class, teacher and room overlaps within the same day, term and academic year.
- Inventory stock movement calculations support stock-in, stock-out, allocation, damage, missing and stocktake transactions, with low-stock and negative-balance warnings.
- Attendance summary report calculates student attendance percentages over a selected date range.
- Audit log for important actions.
- Shared database registers for staff/HR, subjects, student attendance, staff attendance, assessments, timetable, admissions applications, school calendar, announcements, library, inventory, income/expenditure, procurement, transport, boarding, restricted welfare, restricted health, and document references. Accepted admissions applications support conversion to a student record with a duplicate check.
- Validation for non-negative amounts/scores, score maximums, date fields, timetable time ranges, class timetable overlaps, duplicate student attendance by date, and assigned-class restrictions.
- CSV export for each operational register.
- Responsive purple, gold and navy branding based on the supplied school materials.

## Verification status

This version was run for the first time: `pytest -q` passes (26 tests) and every page was loaded as Administrator without error. Role-by-role browser testing, deployment, backup restoration and security review remain outstanding; see `TEST_REPORT.md`.

Admission, receipt and invoice numbers start with the school code (default `FJC`). Change it with the `SCHOOL_CODE` environment setting before the first student is registered.

## Version 4: SMS, email and mobile money
See INTEGRATIONS_SETUP.md. Off by default; nothing is sent until the settings are added.

## Version 3 settings

Optional environment settings (defaults in brackets; confirm against school policy before relying on them): `LEAVE_ANNUAL_DAYS` (15), `SSNIT_EMPLOYEE_RATE` (5.5), `SSNIT_EMPLOYER_RATE` (13), `LIBRARY_FINE_PER_DAY` (0.50).

Run the tests with `pytest -q` (36 tests).

## Important outstanding requirements

The master prompt lists 29 areas. This build covers an operational foundation and initial registers, but several requirements remain incomplete:

- Portal runtime acceptance tests and additional self-service features, including announcements, messaging and assignments.
- Fine-grained permission configuration, and a complete role-by-role security test suite.
- Student/staff photo uploads, document encryption at rest, malware scanning, retention controls and full document permission review. Basic private document uploads are now implemented.
- Broader duplicate applicant matching and an admissions document checklist. Offer letters and approval history are implemented.
- Budgets, reconciliation and financial statements. Fee structures, scholarships, refunds, arrears and a cashbook are implemented.
- Official report-card layout, examination timetable and academic-year comparisons. Terms, a configurable grading scale, class positions and transcripts are implemented; confirm the school-approved grading scale.
- Automatic parent notifications. An on-screen absence-alert list is implemented.
- Full runtime validation of room and teacher conflicts on real timetables. Printable timetables are implemented.
- Library inventory counts and loan reminders. Open loans, overdue fines and overdue notices are implemented.
- Physical stock verification, procurement integration and independent stock-ledger acceptance tests. Basic stock movement balances and low-stock alerts are now implemented.
- Payroll tax tables. Payroll, SSNIT shares and payslips are implemented; income tax (PAYE) is entered by hand.
- SMS, email, MTN MoMo, Telecel Cash, AT Money and USSD. These must remain disabled until real provider credentials and end-to-end tests are supplied.
- Safeguarding case-management workflow, retention policy, encrypted sensitive-field storage, and independent privacy/security review.
- Scheduled encrypted off-site backups, production monitoring and disaster-recovery testing. A restore screen is implemented.
- A hosted deployment, domain, TLS certificate, and school acceptance testing.
- Parent/student accounts are supported with school-managed student linking. Verify the new multi-child portal isolation tests before real use.

Refer to `FEATURE_STATUS.md` and `SECURITY_CHECKLIST.md` before using real data.

## Test

```bash
pytest -q
```

## Deployment checklist

1. Set `APP_ENV=production`, a long random `SECRET_KEY`, and HTTPS secure cookies.
2. Use a production WSGI server and HTTPS reverse proxy. Do not expose Flask's development server.
3. Store the database, uploads and backups with restricted file-system permissions.
4. Configure encrypted off-site backups and test restoring them to a clean environment.
5. Create named accounts for staff and rotate all temporary passwords.
6. Test each role with synthetic data, including direct URLs and exports.
7. Verify class-teacher scoping, sensitive welfare/health access, finance access, and audit logging.
8. Run the full automated suite, resolve failures, and conduct a security review.
9. Obtain school approval for privacy, retention, safeguarding, and data migration.
10. Test on actual desktop, tablet and mobile browsers before launch.


### Passport photo support
Student and staff profile forms accept JPEG, PNG and WebP images up to 5 MB. Pillow validates and normalizes images to JPEG, applies EXIF orientation, and limits output dimensions. Files are stored under the configured private upload directory and served only through an authenticated, role-checked route. Ensure `SCHOOL_UPLOAD_DIR` points to persistent private storage in production.

## Install as an app

When hosted online with HTTPS, the system can be installed from the browser as an app. See `INSTALL_AS_APP.md`.
