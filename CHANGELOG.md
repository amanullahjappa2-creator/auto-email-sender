# Changelog

All notable changes to MailFlow Studio will be documented in this file.

## Unreleased

Future changes will be listed here.

## v1.0.0 - 2026-11-01

- Added per-recipient `{{name}}` and `{{email}}` template personalization.
- Added per-account suppression lists that skip opted-out recipients.
- Added Docker Compose deployment with web, scheduler, and PostgreSQL services.
- Added Ruff linting and pip-audit dependency checks to CI.
- Raised the measured CI coverage floor to 65% with delivery and scheduler tests.
- Added deployment-friendly app health monitoring via `/healthz`.
- Improved repository documentation and contribution processes.
- Added public security reporting guidance and issue templates.
- Added a lightweight health-check script for validating app readiness in local and hosted deployments.
- Documented the roadmap for future MailFlow Studio improvements and reliability work.
