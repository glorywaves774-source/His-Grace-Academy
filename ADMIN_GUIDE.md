# Administrator guide

## Initial setup
1. Install Python 3.10 or newer and the requirements in requirements.txt.
2. Set a unique random SECRET_KEY in the environment. In production, set APP_ENV=production and use HTTPS with COOKIE_SECURE=1.
3. Run the application locally and sign in with the initial account shown in README.md.
4. Change the initial password immediately.
5. Create named staff accounts from User access. Assign only the role required for each person's duties. Set an assigned class for class teachers. Subject teachers automatically work in JHS 1, JHS 2 and JHS 3, so they need no assigned class.
6. Confirm the school class list and inspect the school branding.
7. Create synthetic test records before importing any real data.

## Backups
The Administrator can download a SQL dump from Database backup. Store it securely, restrict access and test restoration into a separate database. This is a manual backup function. It does not provide scheduled or off-site encrypted backup.

## Security administration
- Do not share staff accounts.
- Suspend accounts promptly when staff leave.
- Review the audit log.
- Use a long random SECRET_KEY and never publish it.
- Keep the database and backups outside public web directories.
- Do not expose Flask's development server to the public internet.
- Use a production WSGI server, HTTPS reverse proxy, restricted filesystem permissions, monitoring and encrypted off-site backups before launch.
- Do not enable parent/student accounts until verified record linking and portal isolation are implemented.
- Do not connect payment or messaging providers without official credentials and end-to-end testing.

## Before school launch
Run `pytest -q`, resolve every test failure, and test all roles by trying both allowed and forbidden actions. Verify exports, backups and restoration. Ask school leadership to approve data protection, retention, safeguarding and financial procedures. Complete the outstanding items in FEATURE_STATUS.md before relying on the system for official results, balances, sensitive records or external notifications.

## Version 3 quick guide
- **Charge fees for a term:** Fee structures (add the items for a class, year and term) then Generate invoices. Add Scholarships first if a student has a discount. Record payments against the invoice number; Fee arrears shows who owes.
- **Pay staff:** Payroll, add one record per person per month (SSNIT is worked out for you; enter PAYE yourself), then open the payslip. Check the rates in your settings against current Ghana rules.
- **Staff leave:** Staff leave to record a request and decision; Leave balances shows days used and remaining.
- **Terms and grading:** Academic terms (mark one Current) and Grading scale (one record per grade) before printing report cards.
- **Restore a backup:** download a backup first, then Restore backup. The current data is saved as a safety copy on the server before it is replaced, and everyone is signed out.
