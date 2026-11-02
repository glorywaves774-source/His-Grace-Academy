# Feature status against the master prompt

Status meanings: **Implemented foundation** means a basic database-backed workflow exists. It does not mean the entire specification is complete. **Outstanding** means the required complete workflow is not present or has not been verified.

| Prompt area | Status | Notes |
|---|---|---|
| 1. Student management | Partial | Registration, admission number, profile, guardian contacts, class/status, search, filters and exports. Private document uploads are now available. Photos, promotion/transfer workflows and full history screens remain outstanding. |
| 2. Staff and HR | Partial | Staff register with employment details. Attendance workflow is a register. Leave requests with balances and payroll with payslips are implemented (version 3). Appraisals, workload and statutory tax tables are incomplete. |
| 3. Class and subject management | Partial | Class list and subject allocation register. Full academic-year enrolment, streams and promotion workflow are incomplete. |
| 4. Attendance | Partial | Student and staff attendance entries with duplicate-date validation. Attendance summary percentages by student and date range are now available. An on-screen absence-alert list is available (version 3). Parent notifications and richer term reports remain outstanding. |
| 5. Examinations and report cards | Partial | Assessment score register with score validation. A basic report-card summary now aggregates assessment percentages by subject and applies default grade bands. Configurable grading scale, class positions, academic terms and printable transcripts are implemented (version 3). Weighting, official report layout and an approval workflow remain outstanding. |
| 6. Fees and finance | Partial | Payment receipts, fee invoices, discounts and calculated invoice balances are implemented. Payments link to invoices by invoice number. Fee structures, invoice generation, scholarships, refunds, arrears and a cashbook are implemented (version 3). Reconciliation, budgets and financial statements remain outstanding. |
| 7. Timetable | Partial | Class lesson register and same-class overlap validation. Teacher and room overlap checks are now included for matching year and term. Printable timetable views are implemented (version 3). Comprehensive timetable acceptance tests remain outstanding. |
| 8. Parent portal | Partial | Parent accounts support multiple school-managed child links. The read-only portal shows the selected linked child’s attendance, results, fee invoices/payments and class timetable. Messaging, announcements in the portal and full runtime isolation tests remain outstanding. |
| 9. Student portal | Partial | Administrator can link a student account to a student record. Read-only portal is scoped to that student’s attendance, results, fee payments and class timetable. Assignments, announcements and full runtime isolation tests remain outstanding. |
| 10. Communication | Partial | Announcement register plus SMS (Arkesel) and email (SMTP) sending with a message log. Built and tested with simulated providers; needs the school's accounts to go live. |
| 11. Library | Partial | Book/issue/return register. Open loans, an overdue list with fines and printable overdue notices are implemented (version 3). Inventory counts and loan reminders are incomplete. |
| 12. Inventory and stores | Partial | Stock/asset register. A stock movement ledger now calculates balances from Stock in, Stock out, Allocated, Damaged, Missing and Stocktake entries, with low-stock and negative-stock alerts. Physical stock verification and full procurement integration remain outstanding. |
| 13. Admissions | Partial | Applicant register and status choices plus conversion of accepted applicants into student records with duplicate-match checks. Approval history and printable offer letters are implemented (version 3). A document checklist and broader duplicate matching remain incomplete. |
| 14. Dashboard analytics | Partial | Student totals, status, gender, per-class enrolment and 12-month admission trend are database-driven and reconcile with each other (tested). Fee balances, attendance, results, staff, inventory and year comparisons are not on the dashboard yet. |
| 15. Accounts and RBAC | Partial | Core server-side roles and class restrictions. Parent/student roles now have a linked-record portal and no access to administration routes. Granular configurable permissions and full runtime isolation tests remain outstanding. |
| 16. Calendar | Partial | Event register. Reminder delivery and term calendar automation are incomplete. |
| 17. Transport | Partial | Vehicle/route/assignment register. Route management, maintenance and fee automation are incomplete. |
| 18. Boarding | Partial | Optional dormitory allocation register. Occupancy, meal, incident and attendance workflows are incomplete. |
| 19. Welfare and safeguarding | Partial | Restricted register for Administrator and Headteacher. Case workflow, secure sensitive storage and independent review are outstanding. |
| 20. School health | Partial | Restricted clinic register. Detailed health workflows and privacy review are outstanding. |
| 21. Procurement | Partial | Supplier and purchase request register. Purchase orders, goods received, approvals linked to inventory/finance are incomplete. |
| 22. Document management | Partial | Document register plus private upload and authorised download for PDF, image, Office, CSV and text files, with size/type checks. Encryption at rest, retention policy, antivirus scanning and finer-grained category permissions remain outstanding. |
| 23. Reports | Partial | Student exports, register CSV exports and a basic academic report-card summary. Transcripts, arrears and cashbook are implemented (version 3). Financial statements and complete role-scoped analytics remain incomplete. |
| 24. Security and data protection | Partial | Password hashing, CSRF checks, session controls, role checks, audit log and SQL backup. A restore screen with validation and a safety copy is implemented and tested (version 3). Production security review, encrypted off-site backup and retention controls are outstanding. |
| 25. Settings | Partial | Default school identity and class setup. Full settings interface is incomplete. |
| 26. Ghana-specific requirements | Partial | GHS labels, basic school classes, printable HTML receipt. SMS, email and mobile money (Paystack) are built but off until configured; USSD is not included. |
| 27. Architecture and deployment | Partial | Flask/SQLite local app and setup instructions. Production hosting and disaster recovery are not verified. |
| 28. User interface | Partial | Responsive branded pages and module forms. Full accessibility and cross-device QA are outstanding. |
| 29. Testing and QA | Partial | 36 automated tests pass (`pytest -q`), covering the core flows and all version 3 additions. Browser testing on real devices, independent security review and school acceptance testing are still needed before real use. |

Do not use real student, health, safeguarding or financial records until the outstanding security and workflow work has been completed and verified. Parent/Guardian accounts support multiple linked children. This updated workflow has not yet been runtime-tested.

## Passport photographs (added in this update)
- Student photo upload on new and existing student records: implemented in source.
- Staff photo upload on new and existing staff records: implemented in source.
- Supported formats: JPEG, PNG, WebP. Maximum file size: 5 MB.
- Private storage uses SCHOOL_UPLOAD_DIR and therefore the configured persistent Render disk.
- Access to student photographs is restricted by role and parent/student record linkage. Staff photographs are restricted to Administrator, Proprietor and Headteacher roles.
- Runtime upload and browser display tests remain pending because the current build environment lacks Flask and package network access.


## Diagnostic update (2026-10-30)
- Fixed private passport-photo URL resolution for both student and staff records. Stored paths include `passport_photos/`; the private route now safely normalizes this prefix before resolving files.
- Restricted student photograph delivery by role and assigned class. Parent and student accounts remain limited to linked records. Finance-only accounts no longer receive student photo access.
- Passport uploads now decode and validate the image using Pillow, apply EXIF orientation, normalize to JPEG, resize to a maximum 1600px edge, and enforce the 5 MB input limit.
- Added automated integration tests for student and staff photo upload and retrieval. These tests require the Flask dependencies and remain unexecuted in this build environment.

### Passport photograph access update
- Accountant: permitted to view student and staff passport photographs through authenticated private-photo routes.
- Existing parent/student/teacher access boundaries remain in force.
- Runtime permission tests must be run in the deployment environment before production use.

## Version 9 update
Student directory lookup now supports typed name/admission-number search and direct dropdown selection. Staff & HR lookup now supports typed name/staff-number/record-ID search and direct dropdown selection. Syntax and template parsing checks passed. Full authenticated browser and role-permission tests remain outstanding.

## Version 10 record lookup scan
- Staff directory search and dropdown options now query the full staff register. The previous shared 500-record cap could hide older staff from search and selection.
- Regression tests added for student search and selection and staff lookup beyond 500 records.
- These regression tests have not executed in this environment because Flask and Werkzeug are unavailable.
