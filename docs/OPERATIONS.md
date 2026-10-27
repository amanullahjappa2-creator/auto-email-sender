# MailFlow Operations Guide

## Daily checks

- Confirm the app process is running and reachable on `/healthz`.
- Check that the scheduler is active when scheduled emails are in use.
- Ensure `.env` credentials remain private and unchanged.

## Maintenance

- Review recent email delivery logs after sending batches.
- Rotate secrets if access is suspected to be compromised.
- Keep the system time and timezone aligned with the configured `APP_TIMEZONE` value.

## Recovery

If the app stops responding, restart the web process and verify the database is reachable. If the scheduler stalls, restart the worker and inspect the most recent scheduled jobs.
