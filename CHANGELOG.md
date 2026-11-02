# Version 5.12 - 3D view polish after a full scan

- Full scan of the system (static analysis, a crawl of all 100+ pages, empty-school and unassigned-student cases, a real-browser check): no errors found.
- 3D class view: long class names are shortened on the floor labels instead of overlapping, and the camera leaves more room at the front so the last class label is never cut off.

# Version 5.11 - 3D dashboard view

- The **Dashboard** has a new **3D class view**: drag to rotate, scroll or pinch to zoom, hover or tap a column for the exact numbers, and use **Reset view** to go back. It shows active boys and girls in each class.
- Leadership roles (Administrator, Proprietor, Headteacher) also get a **Fees** tab: billed, paid and outstanding per class. Teachers and other roles never see fee figures, and class-limited teachers see only their own classes.
- **Table** switches to the same numbers as a plain table. The table is also shown automatically when the device cannot draw 3D, and it is always present when JavaScript is off. The existing charts and cards are unchanged.
- Built with three.js, bundled into one file served by the system itself (`dashboard3d.js`); no internet connection or outside service is needed and the security policy is unchanged. It respects the "reduce motion" setting and pauses when the page is hidden.

# Version 5.10 - fix: edit page for single-class Subject Teachers

- Fixed: on the **Edit user** page, a Subject Teacher assigned to one JHS class showed "Not class restricted", so saving without changing the class would have given them all three JHS classes. The page now shows and keeps the assigned class. Affects versions that had the Edit page.
- The User access list is now shown first at full width, so classes and subjects are readable; the create form is below it.

# Version 5.9 - subjects taught by Subject Teachers

- On **User access** (create and Edit), a Subject Teacher now has **Subjects taught**: choose one or more subjects. They are saved on the account and shown in the users list.
- The subject list comes from **Subjects & Teaching**. Until that register has subjects, a standard JHS starter list is offered (English Language, Mathematics, Integrated Science, Social Studies, Religious & Moral Education, Computing, French, Ghanaian Language, Creative Arts & Design, Career Technology).
- When entering **Assessments and results**, a Subject Teacher's Subject box offers only their subjects, and the system refuses any other. They see and can edit only their own subjects' results. Administrators and the Headteacher still see everything.
- Subject Teachers with no subjects chosen, and every account created before this version, keep today's behaviour (any subject). Class Teachers and Teachers are not restricted. **Department** in the staff register is unchanged.

# Version 5.8 - printable invoice and one-page report cards

- **Fee invoice:** every invoice now has a **Print** link. The printed invoice has the school letterhead, bill-to details, due date, fee description, discount, payments received (with receipt numbers), balance to pay, payment instructions, and signature and stamp areas.
- **Report card:** each pupil gets one A4 page with the school letterhead, pupil details, position in class, subject table with grade and remark, overall average and grade, attendance, school fees outstanding, next-term opening date (when set under Academic terms), lines for the class teacher's and headteacher's remarks, and signature and stamp areas.
- **Printing:** **Print all** gives one page per pupil. **Print this pupil** prints only that pupil's page.
- The invoice list now fits the screen, with the class and year/term shown under the pupil and invoice.
- Notes: the next-term date and term-based attendance need the Academic terms register (not in the Node edition, which counts all recorded attendance and leaves the next-term date to write in). Confirm marks and the grading scale before issuing official reports.

# Version 5.7 - staff who are also parents

- A staff member (Proprietor, Headteacher, Accountant, Admissions Officer, teachers, Librarian, Storekeeper, or Administrator) can now have children at the school linked to the **same account**. The Administrator sets this under **Children at the school** when creating a user or on the user's **Edit** page.
- A linked person gets a **My children** page in the menu showing only their own children's results, attendance, fees and receipts. Their staff role and class limits do not change, and the link never gives them extra access to other pupils.
- Role changes between staff roles keep the links; changing to a Student account clears them. Deleting a user removes the links, never the child.
- Linking, unlinking and each view of a child's page by staff are written to the audit log.

# Version 5.6 - administrators can edit and delete users

- **User access** now has an **Edit** link on every account. The Administrator can change the full name, username, role, assigned class(es) and linked student, and can set a new temporary password (the person must change it at next sign-in).
- The Administrator can **delete** an account from its edit page, after ticking a confirmation box. Records the person created stay, without their name, and the audit log keeps who was deleted.
- Safeguards: you cannot delete your own account or change your own role; the only active Administrator cannot be demoted or deleted; a username must stay unique; if an account owns records that must keep it (for example uploaded documents), deletion is refused and you are told to suspend it instead.
- Only Administrators can edit or delete users. Every edit and deletion is written to the audit log.

# Version 5.5 - subject teachers in one, two or three JHS classes

- On **User access**, the class list now also offers, for Subject Teachers: JHS 1 & JHS 2, JHS 2 & JHS 3, JHS 1 & JHS 3, and JHS 1, JHS 2 & JHS 3. A Subject Teacher sees and edits only the classes chosen.
- A Subject Teacher with no class chosen, and every account created before this version, keeps access to all three JHS classes. Choosing the class list entry for a new Subject Teacher defaults to all three.
- The choice is only accepted for the Subject Teacher role. Class Teachers and other roles work as before.
- The users list shows the classes, for example "JHS 1 & JHS 2".

# Version 5.4 - take passport photos with the camera

- Student and staff photo forms now have a **Take photo with camera** button. Capture, retake or cancel; the picture is attached like a normal upload and is checked and stored the same way (JPEG/PNG/WebP, 5 MB limit, private storage).
- The camera works only on a secure connection (https, or localhost on the same computer) and only for this site; the microphone and location stay blocked. If the camera is missing or permission is refused, a message appears and file upload still works.
- Nothing else changed.

# Version 5.3 - install as an app

- The system can now be installed on phones, tablets and computers from the online address (home-screen icon, own window). See `INSTALL_AS_APP.md`.
- Each school has its own app name, colours and icon.
- Only public files (colours, icons, scripts) are kept on the device. Student, fee and staff pages are never stored; signing in, security and backups are unchanged.
- Shows a friendly offline page when there is no internet.

# Colours update

- The design now uses the school's colours: brown #6B352A and cream-yellow #FFF1A6 (sidebar, buttons, headings, charts and focus highlights). The crest image is unchanged.

# Version 5.1 - daily backup by e-mail

- The daily database backup can be e-mailed (default address glorywaves774@gmail.com) as an AES-256 password-protected zip. Needs `BACKUP_EMAIL_TO`, `BACKUP_ZIP_PASSWORD` and the SMTP settings. Integrations page shows status and has a "Send a backup now" button. Adds the `pyzipper` dependency.

# Version 5 - security and reliability pass

- Dependency fix: Pillow upgraded to 13 (earlier versions had many published vulnerabilities); test tools moved to `requirements-dev.txt`.
- Hardening, backups and error pages as listed under "Version 5 hardening" in SECURITY_CHECKLIST.md.
- Code cleaned: unused imports and variables removed, inline scripts replaced by `static/app.js`, tests tidied.

# Version 4.1 - class list

- Classes are now **Daycare, KG 1, KG 2, Primary 1-6, JHS 1-3**. Existing databases using Creche / Nursery / Kindergarten are renamed automatically, keeping all students, teacher assignments, timetables and fee structures attached. 59 tests pass.

