# Online deployment guide (Render)

This project includes a Render Blueprint in `render.yaml`. It configures a Python web service, HTTPS cookies, a health check, a generated Flask secret, and a persistent disk for the SQLite database and private document uploads.

## Before you start

- Create a GitHub account and a private repository for the school system.
- Create a Render account and connect the repository.
- The included `starter` service and persistent disk are paid resources. Check Render's current pricing before confirming deployment.
- Do not put real student records into the system until the acceptance and security tests in `SECURITY_CHECKLIST.md` are complete.

## Deploy

1. Extract the ZIP on your computer.
2. Create a **private** GitHub repository and upload the project files. Do not upload `school.db`, `.env`, student documents, backups, or real student data.
3. In Render, choose **New > Blueprint** and connect the private repository containing `render.yaml`.
4. Review the service and persistent disk plan and create the resources.
5. When prompted for `ADMIN_INITIAL_PASSWORD`, enter a unique password of at least 16 characters. Save it in a password manager. This is only used when the database has no user accounts. It is not printed in logs.
6. Wait for the deployment and confirm the service health check passes at `/healthz`.
7. Open the HTTPS service URL and sign in with the configured initial admin username and password. Change the password immediately if the app prompts you to do so.
8. Create named accounts with the least privileges needed. Test each role using synthetic data before adding school records.

## Persistence and backups

The database and private uploads are stored under `/var/data` on the persistent disk. Do not remove the disk when redeploying. A persistent disk is not a backup. Configure and test separate encrypted off-site backups before production use. Periodically restore a backup into a separate test instance.

## Domain

After acceptance testing, add the school's domain in Render's custom-domain settings and follow its DNS/HTTPS instructions. Do not share the admin URL or credentials publicly.

## Known limitations

- This deployment recipe keeps SQLite on a persistent disk. It is appropriate for a controlled pilot or small deployment after testing, but it is not a substitute for a reviewed multi-user production architecture or managed PostgreSQL migration for higher concurrency.
- Render's persistent disk is a paid feature. A free ephemeral filesystem must not be used for the school database or uploads.
- External SMS, email and mobile-money services are not active until real provider accounts, credentials, and end-to-end tests are configured.
- Deployment configuration does not prove application workflows or permissions are secure. Run the complete automated test suite and school acceptance checklist before using real student, health, safeguarding, or financial records.

## Install as an app

Once the site is online with HTTPS, staff and parents can install it on their phones and computers. See `INSTALL_AS_APP.md`.
