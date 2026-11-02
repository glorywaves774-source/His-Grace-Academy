# Version 1.15 - His Grace Academy branding clean-up

- Removed leftovers from other schools found by a scan of every file and every page:
  - The browser/app theme colour was Fr. Joseph Connolly's brown (#6B352A); it is now His Grace Academy's brown (#5e3b29), on the page and in the installable app.
  - Student exports were named `kings_gate_*` and their Excel header and PDF table headings used Kings Gate purple. Files are now `his_grace_*` with brown headings.
  - Purple tints inherited from the Kings Gate styles (button and card shadows, focus rings, borders, grey text, the 3D tooltip) are now warm brown/grey tones.
  - The README referred to a `kings_gate_school` folder; fixed. The PDF subtitle no longer ends with "!." .
- No other school's name, crest, phone number or admission prefix appears on any of the 107 pages checked.

# Version 1.14 - 3D view polish after a full scan

- Full scan of the system (static analysis, a crawl of 100+ pages, unassigned-student and fee cases, a real-browser check): no errors found.
- 3D class view: long class names are shortened on the floor labels instead of overlapping, and the camera leaves more room at the front so the last class label is never cut off.

# Version 1.13 - 3D dashboard view

- The **Dashboard** has a new **3D class view**: drag to rotate, scroll or pinch to zoom, hover or tap a column for the exact numbers, and use **Reset view** to go back. It shows active boys and girls in each class.
- Leadership roles (Administrator, Proprietor, Headteacher) also get a **Fees** tab: billed, paid and outstanding per class. Teachers and other roles never see fee figures, and class-limited teachers see only their own classes.
- **Table** switches to the same numbers as a plain table. The table is also shown automatically when the device cannot draw 3D, and it is always present when JavaScript is off. The existing charts and cards are unchanged.
- Built with three.js, bundled into one file served by the system itself (`dashboard3d.js`); no internet connection or outside service is needed and the security policy is unchanged. It respects the "reduce motion" setting and pauses when the page is hidden.

# Version 1.12 - fix: edit page for single-class Subject Teachers

- Fixed: on the **Edit user** page, a Subject Teacher assigned to one JHS class showed "Not class restricted", so saving without changing the class would have given them all three JHS classes. The page now shows and keeps the assigned class. Affects versions that had the Edit page.
- The User access list is now shown first at full width, so classes and subjects are readable; the create form is below it.

# Version 1.11 - subjects taught by Subject Teachers

- On **User access** (create and Edit), a Subject Teacher now has **Subjects taught**: choose one or more subjects. They are saved on the account and shown in the users list.
- The subject list comes from **Subjects & Teaching**. Until that register has subjects, a standard JHS starter list is offered (English Language, Mathematics, Integrated Science, Social Studies, Religious & Moral Education, Computing, French, Ghanaian Language, Creative Arts & Design, Career Technology).
- When entering **Assessments and results**, a Subject Teacher's Subject box offers only their subjects, and the system refuses any other. They see and can edit only their own subjects' results. Administrators and the Headteacher still see everything.
- Subject Teachers with no subjects chosen, and every account created before this version, keep today's behaviour (any subject). Class Teachers and Teachers are not restricted. **Department** in the staff register is unchanged.

# Version 1.10 - printable invoice and one-page report cards

- **Fee invoice:** every invoice now has a **Print** link. The printed invoice has the school letterhead, bill-to details, due date, fee description, discount, payments received (with receipt numbers), balance to pay, payment instructions, and signature and stamp areas.
- **Report card:** each pupil gets one A4 page with the school letterhead, pupil details, position in class, subject table with grade and remark, overall average and grade, attendance, school fees outstanding, next-term opening date (when set under Academic terms), lines for the class teacher's and headteacher's remarks, and signature and stamp areas.
- **Printing:** **Print all** gives one page per pupil. **Print this pupil** prints only that pupil's page.
- The invoice list now fits the screen, with the class and year/term shown under the pupil and invoice.
- Notes: the next-term date and term-based attendance need the Academic terms register (not in the Node edition, which counts all recorded attendance and leaves the next-term date to write in). Confirm marks and the grading scale before issuing official reports.

# Version 1.9 - staff who are also parents

- A staff member (Proprietor, Headteacher, Accountant, Admissions Officer, teachers, Librarian, Storekeeper, or Administrator) can now have children at the school linked to the **same account**. The Administrator sets this under **Children at the school** when creating a user or on the user's **Edit** page.
- A linked person gets a **My children** page in the menu showing only their own children's results, attendance, fees and receipts. Their staff role and class limits do not change, and the link never gives them extra access to other pupils.
- Role changes between staff roles keep the links; changing to a Student account clears them. Deleting a user removes the links, never the child.
- Linking, unlinking and each view of a child's page by staff are written to the audit log.

# Version 1.8 - administrators can edit and delete users

- **User access** now has an **Edit** link on every account. The Administrator can change the full name, username, role, assigned class(es) and linked student, and can set a new temporary password (the person must change it at next sign-in).
- The Administrator can **delete** an account from its edit page, after ticking a confirmation box. Records the person created stay, without their name, and the audit log keeps who was deleted.
- Safeguards: you cannot delete your own account or change your own role; the only active Administrator cannot be demoted or deleted; a username must stay unique; if an account owns records that must keep it (for example uploaded documents), deletion is refused and you are told to suspend it instead.
- Only Administrators can edit or delete users. Every edit and deletion is written to the audit log.

# Version 1.7 - subject teachers in one, two or three JHS classes

- On **User access**, the class list now also offers, for Subject Teachers: JHS 1 & JHS 2, JHS 2 & JHS 3, JHS 1 & JHS 3, and JHS 1, JHS 2 & JHS 3. A Subject Teacher sees and edits only the classes chosen.
- A Subject Teacher with no class chosen, and every account created before this version, keeps access to all three JHS classes. Choosing the class list entry for a new Subject Teacher defaults to all three.
- The choice is only accepted for the Subject Teacher role. Class Teachers and other roles work as before.
- The users list shows the classes, for example "JHS 1 & JHS 2".

# Version 1.6 - take passport photos with the camera

- Student and staff photo forms now have a **Take photo with camera** button. Capture, retake or cancel; the picture is attached like a normal upload and is checked and stored the same way (JPEG/PNG/WebP, 5 MB limit, private storage).
- The camera works only on a secure connection (https, or localhost on the same computer) and only for this site; the microphone and location stay blocked. If the camera is missing or permission is refused, a message appears and file upload still works.
- Nothing else changed.

# Version 1.5 - install as an app

- The system can now be installed on phones, tablets and computers from the online address (home-screen icon, own window). See `INSTALL_AS_APP.md`.
- Each school has its own app name, colours and icon.
- Only public files (colours, icons, scripts) are kept on the device. Student, fee and staff pages are never stored; signing in, security and backups are unchanged.
- Shows a friendly offline page when there is no internet.

# Version 1.3 - easier to read

- All small text is larger (nothing below 12 px; most labels, tables, menus and badges are one size bigger).
- The crest is bigger in the menu and on receipts, letters and payslips so its lettering can be read.
- Status badge and footer text have stronger contrast; the student search box is no longer squeezed.

# Version 1.2 - school colours

- Design now uses the school's colours: brown, white and wine. Wine (taken from the crest) marks the main buttons; the sidebar, headings and charts are brown on white. The crest background was changed from navy to brown to match; the shield is unchanged.

# Version 1 - His Grace Academy, Saboba

First release for His Grace Academy, built on the hardened Fr. Joseph Connolly system (all 59 tests pass).

- School crest, navy / maroon / gold colours and name throughout: sidebar, login, receipts, letters, transcripts, payslips, PDF exports, SMS text.
- Students, attendance, assessments and report cards with a configurable grading scale, transcripts, timetable.
- Fees: structures, invoice generation, scholarships, refunds, arrears, cashbook, receipts.
- Staff: HR records, leave with balances, payroll with SSNIT and payslips.
- Library, inventory, health, admissions with history and offer letters, announcements, document storage.
- Subject Teachers can work in JHS 1, JHS 2 and JHS 3; class teachers are limited to their own class.
- SMS (Arkesel), e-mail (SMTP) and mobile money (Paystack) are built in but switched off until configured (INTEGRATIONS_SETUP.md). Tested with simulated providers only.
- Security: strict browser protections, CSRF, sign-in lockout, audit log, encrypted daily backup by e-mail (optional), automatic daily backup copies.
- Admission, receipt and invoice numbers start with HGA (change with SCHOOL_CODE).
