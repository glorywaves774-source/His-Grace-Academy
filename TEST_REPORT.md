# His Grace Academy run

59 automated tests pass (`pip install -r requirements-dev.txt` then `pytest -q`). Live SMS, e-mail and mobile-money providers are untested.

# Test report

## Version 3 (current)
Run with `pytest -q`. Result: **36 tests, 58 passed, 0 failed.**

New tests cover: the Users page with parent accounts; subject teachers in JHS 1-3 only (students, records, forms, reports); leave rules and balances; payroll arithmetic, payslips and access; fee structures, scholarships, invoice generation, arrears, refunds and the cashbook; grading, terms, report cards and transcripts; library overdue and notices; absence alerts and the printable timetable; admission history and letters; backup restore, including refusal of wrong confirmations, invalid files and non-administrators.

Pages were also opened in a real browser and checked by eye. Not tested: real deployment, real devices, SMS/email/mobile-money integrations, an independent security review.

Earlier sections below describe previous versions and are kept for history; where they say tests were not run, that is superseded by this section.

---

# Test report

Date prepared: 2026-10-29

## Checks completed during packaging
- Python source compilation completed without syntax errors.
- The source requirements document was reviewed and mapped in FEATURE_STATUS.md.
- Database-backed module routes, field validation and class-scoped register rules were added.
- Test cases cover initial password rotation, core pages, student creation/exports, unauthenticated access, module record persistence and restricted-register access.

## Checks not completed
- The Flask runtime suite was not executed. Flask is not installed in the build environment, and package installation failed because network name resolution was unavailable.
- Browser rendering, mobile/tablet layout, end-to-end financial calculations, cross-role access testing, backup restoration, external integrations and production deployment were not verified.
- Static compilation does not prove that every route, template, database workflow or security control works at runtime.

## Required next steps
In an environment with package installation available:
1. Create and activate a clean virtual environment.
2. Run `pip install -r requirements.txt`.
3. Run `pytest -q` and resolve every failure.
4. Test every role against permitted and forbidden routes, including direct URLs and exports.
5. Test timetable overlaps, duplicate attendance, score validation and record edits.
6. Verify SQL backup restoration into a clean database.
7. Conduct browser testing on desktop, tablet and mobile.
8. Conduct independent security and school staff acceptance reviews using synthetic data.

No production-readiness claim is made by this report.


## Audit update, 2026-10-29

- `python -m py_compile app.py tests/test_app.py`: passed.
- Jinja template parsing: passed for all 21 HTML templates.
- Automated runtime tests: not executed successfully. Flask and Werkzeug are missing from the environment and package installation failed because the package index could not be reached.
- Added a parent portal smoke test for linked-student access and blocked administration routes. This test is written but not runtime-verified.
- Production readiness remains unverified. Install dependencies in a network-enabled environment, run `pytest -q`, and complete the deployment security checklist before entering real records.


## Follow-up audit update, 2026-10-29

Implemented in source after the prior package:
- Fee invoice creation with discount validation and computed outstanding balance, plus invoice-linked payment recording.
- Multi-child parent accounts with school-managed child links and portal selection scoped to linked student IDs.
- Academic report-card summary grouped by subject, academic year and term, with default percentage bands. These bands are not school-approved until management confirms them.
- Admissions conversion for accepted applicants with a duplicate check and creation of enrolment history.
- Private document upload and authorised download routes with extension checks, an 8 MB request limit and storage outside the public static directory.
- Timetable conflict checks for class, teacher and room within the same day, term and academic year.
- Added automated tests for multi-child isolation and invoice payment/balance behavior.

Static verification after these changes:
- Python compilation passed for app.py and tests/test_app.py.
- Jinja parsing passed for all 26 HTML templates.
- Extracted database creation SQL executed successfully in an isolated SQLite database and required tables were present.

Runtime pytest, browser acceptance tests and penetration/security tests remain unverified because Flask and Werkzeug are unavailable in this build environment and package downloads are blocked. Do not use this release with real school records until these tests pass in a properly provisioned environment.

## Passport photo verification checklist
Static checks performed for this update:
- Python source compiles successfully with `python -m py_compile app.py`.
- Jinja parsing succeeds for all templates.
- Student creation and editing forms use multipart form encoding and include a passport photo field.
- Staff creation and editing forms use multipart form encoding and include a passport photo field.
- Image upload validates JPEG, PNG and WebP file signatures and enforces a 5 MB size limit.
- Image files are stored beneath SCHOOL_UPLOAD_DIR/private_uploads/passport_photos, not under public static assets.
- Image delivery requires login and checks the matching student/parent link or management role.
Not yet verified: live upload through Flask, file decoding by browsers, image persistence after Render restart, and end-to-end role tests. Run these in the deployed staging service before entering real records.


## Diagnostic pass: 2026-10-30
Static checks completed: Python compilation for `app.py` and `tests/test_app.py`; Jinja parsing for all 26 HTML templates; ZIP integrity check. Added integration tests for student and staff passport photo upload/retrieval. Full Flask test execution was not possible in this environment because Flask and Werkzeug are not installed and package repository access is unavailable. Therefore database-backed request tests, login/role tests, file upload round trips and deployment smoke tests remain unverified. Do not treat this build as production-approved until these tests pass in the deployment environment.

## Version 10 scan results
- `python -m py_compile app.py tests/test_app.py`: passed.
- Jinja parsing: all 26 HTML templates passed.
- Template `url_for` endpoint reference scan: no missing endpoints found.
- ZIP integrity: passed.
- `pytest -q`: blocked during collection by `ModuleNotFoundError: No module named 'flask'`. No application tests executed.
- Static review found that staff lookup inherited a 500-record limit. Updated the staff directory query to include all staff records and added regression tests for older records.
- Live HTTP, database migration, authentication, role isolation, image upload/display, and Render persistence remain unverified. Install requirements and run the complete test suite in a staging environment before production use.


## Version 2 run (His Grace Academy, executed with Flask 3.1 / Python 3)
- `pytest -q`: 26 passed.
- Crawled every reachable page as Administrator (309 URLs): no 4xx/5xx responses.
- CSV import preview and confirm, XLSX/PDF/CSV exports and register CSV export: working.
- Screenshots reviewed at desktop and phone widths for login, dashboard, receipt, students, invoices and forms.
- Still not verified: other roles through a browser, Render deployment and persistence, restore from backup, penetration testing.
